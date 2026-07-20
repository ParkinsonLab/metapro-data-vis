# Mounted RPKM Data — Design Spec

> **Status:** Approved (2026-07-16)  
> **Goal:** Replace UI file upload with filesystem-mounted datasets under a configurable data root. FastAPI-only single container discovers `RPKM_table.tsv` files, runs the dbt pipeline on selection when stale, streams build progress via SSE, and activates the dataset for visualization.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — dbt pipeline, `run_pipeline.py`, `run_context.json`
- `docs/superpowers/specs/2026-07-09-inline-rpkm-ingest-design.md` — current ingest graph (`int_rpkm_by_ec_tax+`)
- `docs/superpowers/specs/2026-06-08-electron-to-web-design.md` — web app architecture (Express sidecar superseded here)

**Supersedes (in part):** Upload flow in `Upload.tsx`, Express `/api/data` upload routes, `names`-based sample resolution for the DuckDB backend.

## 1. Context

### 1.1 Problem

Today users upload RPKM TSV files through the browser (`POST /api/data`). The DuckDB viz backend resolves samples by filename stem (`test_rpkm_1.tsv` → `test_rpkm_1`) and expects pre-built `analytics/transform/runs/{sample_id}/sample.duckdb`. The pipeline is invoked manually via CLI, not from the app.

MetaPro users already have output folders on disk. The desired workflow is:

1. Mount one or more host folders into the container under a data root.
2. The app discovers files named `RPKM_table.tsv` (MetaPro's output filename).
3. The user selects a dataset; the app runs dbt if needed and activates it for viz.

Comparison mode (two datasets) is **deferred**.

### 1.2 Measured performance (2026-07-13, local Mac)

| Fixture | TSV size | dbt `build` | `run_pipeline.py` wall | `sample.duckdb` |
|---|---|---|---|---|
| `test_rpkm_1` | 51 MB | 0.7 s | 3.8 s | ~22 MB |
| `stress_rpkm_1` | 388 MB | 2.8 s | 6.3 s | 20 MB |

SHA-256 of `stress_rpkm_1` (388 MB): ~230 ms. Pipeline duration dominates. Select hashes only when mtime/size match (see §5.6).

**SSE rationale:** Stress data completes in ~6 s on a dev Mac, but user machines vary (CPU, disk, Docker overhead, concurrent load). SSE provides live step progress so the UI remains responsive and informative for runs that take minutes. Polling-only would work for happy-path latency but is weaker UX under load.

### 1.3 Locked decisions (brainstorming)

| Decision | Choice |
|---|---|
| Data input | Mounted folders; discover `RPKM_table.tsv` recursively under data root |
| Upload UI | **Remove** — no browser file upload |
| `sample_id` (mounted) | Path relative to `DATA_ROOT`, `/` → `__` (e.g. `/data/proj1/run2/RPKM_table.tsv` → `proj1__run2`) |
| `sample_id` (dev fixtures) | Filename stem (e.g. `test_rpkm_1.tsv` → `test_rpkm_1`) |
| Selection semantics | Select = mtime/size check → pipeline if stale → activate for viz (no separate Update button) |
| Comparison mode | Out of scope (single select only) |
| Container | Single image; **FastAPI only** (no Express in image) |
| Express code (repo) | **Keep during migration**; full delete deferred to a later retire PR |
| Dev data mode | Toggle controls upload UI vs mounted-data UI (see §3.2) |
| Pipeline output | `{RUNS_DIR}/{sample_id}/sample.duckdb` + `run_context.json` |
| Default `RUNS_DIR` | `{DATA_ROOT}/vis/runs` |
| Reference bridges | Baked in image at fixed app path; **never** under data root |
| Discovery | Recursive scan excluding `{DATA_ROOT}/vis/`; **watchdog** + **Refresh** button (no polling in v1) |
| Catalog scan cost | mtime + size only (catalog scan and select use the same rule) |
| Dev data root | `./local-data` (mirrors container layout) |
| Dev fixtures | `ENABLE_DEV_DATASETS=1` lists bundled paths outside data root |
| Pipeline orchestration | Async background job; **SSE** streams dbt progress in v1 |
| dbt → SSE bridge | Subprocess `dbt build --log-format json`; parse stdout lines |

## 2. Path configuration

Paths are **not hardcoded** to `/data`. Environment variables with container-friendly defaults:

| Variable | Container default | Dev default |
|---|---|---|
| `DATA_ROOT` | `/data` | `./local-data` |
| `RUNS_DIR` | `/data/vis/runs` | `./local-data/vis/runs` |
| `REFERENCE_PARQUET_DIR` | `/app/analytics/transform/reference/parquet` | `analytics/transform/reference/parquet` (repo-relative) |
| `ENABLE_DEV_DATASETS` | `0` | `1` (optional in `.env.development`) |

**Invariants:**

- Discovery scans only under `DATA_ROOT`, skipping `{DATA_ROOT}/vis/` entirely.
- `RUNS_DIR` may equal `{DATA_ROOT}/vis/runs` but is independently configurable.
- Deleting `{RUNS_DIR}` or individual `{RUNS_DIR}/{sample_id}/` folders is safe; the app reruns the pipeline on next select.
- Deleting or corrupting reference parquet breaks the app (not recoverable by the user).

**Example dev layout:**

```
local-data/
  proj1/run2/RPKM_table.tsv    # discovered dataset → sample_id proj1__run2
  vis/runs/
    proj1__run2/
      sample.duckdb
      run_context.json
```

**Example mount (host folder → container `/data`):**

```bash
docker run -p 8080:8080 \
  -v /Users/sibyl/Downloads/tutorial_files:/data \
  metapro-viz
```

If MetaPro output is directly in that folder:

| Host path | Container path | `sample_id` |
|---|---|---|
| `tutorial_files/RPKM_table.tsv` | `/data/RPKM_table.tsv` | `_root` |

Nested output is also supported, e.g. `tutorial_files/run1/RPKM_table.tsv` → `/data/run1/RPKM_table.tsv` → `run1`.

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Container (single process: uvicorn)                         │
│                                                              │
│  FastAPI                                                     │
│    GET  /              → StaticFiles (dist/) + SPA fallback  │
│    GET  /api/datasets  → catalog (paths, status)             │
│    POST /api/datasets/refresh → force rescan                 │
│    POST /api/datasets/select  → start pipeline if stale       │
│    GET  /api/datasets/{id}/events → SSE (dbt progress)       │
│    POST /api/viz/*     → existing viz endpoints              │
│                                                              │
│  Background: watchdog on DATA_ROOT (exclude vis/)            │
│  Pipeline: subprocess dbt --log-format json → event queue    │
└──────────────────────────────────────────────────────────────┘

  DATA_ROOT/**/RPKM_table.tsv     user mounts (read)
  RUNS_DIR/{sample_id}/           pipeline output (user-writable)
  REFERENCE_PARQUET_DIR/          image-baked (read-only)
  /app/resources/...              dev fixtures (flag-gated)
```

**Production container:** FastAPI only — no Express binary or Node server in the image.

**Repo / dev (phased):** Do **not** delete `src/server/` in the initial implementation PR. Express remains in the repo for cross-checking until a dedicated retire PR.

**Static UI:** Vite `dist/` served by FastAPI `StaticFiles` with SPA fallback in the container. Dev hot reload is unchanged (see §3.2).

### 3.1 Production vs development

| Surface | Data loading | Viz backend | API process |
|---|---|---|---|
| **Docker container** | Mounted `DATA_ROOT` only | FastAPI + DuckDB | `uvicorn` only |
| **Dev — mounted mode** | Data panel + catalog/SSE | FastAPI + DuckDB (direct or via proxy) | `uvicorn --reload` + Vite |
| **Dev — legacy mode** | Upload UI + `POST /api/data` | Express in-memory and/or `?backend=duckdb` proxy | Express `:3001` + Vite (today) |

### 3.2 Dev toggles and hot reload

Two toggles in dev (container has no toggles — mounted + FastAPI only):

1. **Data mode** (`dataMode`: `mounted` \| `upload`) — Data panel vs Upload UI
2. **Viz backend** (`vizBackend`: `legacy` \| `sidecar`) — Express in-memory viz vs FastAPI DuckDB

#### Toggle viability matrix

| | **viz: sidecar** (DuckDB / FastAPI) | **viz: legacy** (Express in-memory) |
|---|---|---|
| **data: mounted** | **Yes** — primary target. Pipeline → `RUNS_DIR`; viz reads `names[0]` as `sample_id` | **No** — mounted data never enters Express `data{}`. Disable or hide this combo in the UI. |
| **data: upload** | **Yes** — with constraint: `names[0]` must match `runs/{sample_id}/` (see §9.1). Upload does not run the pipeline; use pre-built runs or dev fixtures. | **Yes** — today's default. `names[0]` is the upload label key in Express memory. |

**Conclusion:** toggles are **not fully independent**. When `dataMode=mounted`, force `vizBackend=sidecar` (or auto-switch with a one-line notice). When `dataMode=upload`, both viz modes are valid.

**Mounted mode:** renderer talks to FastAPI for `/api/datasets/*` and viz. Vite proxies `/api` to FastAPI.

**Legacy/upload mode:** renderer uses Upload UI + Express `:3001`; optional `?backend=duckdb` for viz cross-check.

**Hot reload:** Vite HMR (`dev:web`, `:5173`) is independent of the API server. Only the Vite `server.proxy` target changes per data mode. FastAPI supports `--reload` for Python separately.

## 4. Sample identity

### 4.1 Mounted datasets

```python
def sample_id_from_path(data_root: Path, rpkm_path: Path) -> str:
    rel = rpkm_path.relative_to(data_root)
    parent = rel.parent
    if str(parent) == ".":
        # File directly under DATA_ROOT (e.g. /data/RPKM_table.tsv)
        return "_root"
    return str(parent).replace("/", "__")
```

**Root-level files:** A file at `{DATA_ROOT}/RPKM_table.tsv` is allowed with `sample_id = "_root"`. The earlier draft rejected this only because an empty parent path has no natural slug; `_root` is an explicit reserved id.

Display path in UI: **full absolute container path** (e.g. `/data/proj1/run2/RPKM_table.tsv`).

### 4.2 Dev fixtures (`ENABLE_DEV_DATASETS=1`)

Explicit registry (not discovered by scan):

| Path (image) | `sample_id` |
|---|---|
| `/app/resources/example_data/test_rpkm_1.tsv` | `test_rpkm_1` |
| `/app/resources/example_data/test_rpkm_2.tsv` | `test_rpkm_2` |
| `/app/analytics/transform/tests/fixtures/fake_rpkm.tsv` | `fake_rpkm` |
| `/app/analytics/transform/tests/fixtures/bad_rpkm_empty.tsv` | `bad_rpkm_empty` (invalid; preflight fails) |
| `/app/analytics/transform/tests/fixtures/bad_rpkm_empty_mart.tsv` | `bad_rpkm_empty_mart` (invalid; dbt assertion fails) |
| `/app/resources/example_data/stress_rpkm_1.tsv` | `stress_rpkm_1` |
| `/app/resources/example_data/stress_rpkm_2.tsv` | `stress_rpkm_2` |

Dev fixtures use filename stem regardless of whether the file is named `RPKM_table.tsv`. Stress files may be absent from the image unless generated at build time or shipped; listing is conditional on file existence.

Mark `is_dev_fixture: true` in catalog entries.

## 5. Discovery service

### 5.1 Scan algorithm

1. Walk `DATA_ROOT` recursively.
2. Skip any subtree whose path is under `{DATA_ROOT}/vis/`.
3. Collect files named exactly `RPKM_table.tsv`.
4. For each file: compute `sample_id`, `path`, `mtime`, `size`.
5. Merge dev fixtures from registry when flag enabled.
6. Join with run state from `{RUNS_DIR}/{sample_id}/run_context.json` to derive status.

### 5.2 Watcher

- Library: `watchdog` (inotify on Linux).
- Watch `DATA_ROOT`; on debounced event (1–2 s), rerun scan.
- Ignore events under `{DATA_ROOT}/vis/`.
- On Mac Docker Desktop, watcher may miss events; **Refresh** is the escape hatch.

### 5.3 Refresh

`POST /api/datasets/refresh` triggers immediate rescan and returns updated catalog.

### 5.4 Catalog entry schema

```json
{
  "sample_id": "proj1__run2",
  "path": "/data/proj1/run2/RPKM_table.tsv",
  "status": "ready",
  "last_run_at": "2026-07-16T12:00:00Z",
  "last_error": null,
  "is_dev_fixture": false,
  "mtime": 1710000000,
  "size": 53527520
}
```

### 5.5 Status values

| Status | Meaning |
|---|---|
| `discovered` | File found; no successful pipeline run (no DB or no `run_context.json`) |
| `ready` | `sample.duckdb` exists; file mtime/size match `run_context.json` |
| `stale` | File mtime/size differs from `run_context.json` |
| `running` | Pipeline in progress for this `sample_id` |
| `failed` | Last pipeline run failed; `last_error` set |

`rpkm_sha256` is written to `run_context.json` on each pipeline run. Catalog scan uses mtime + size only; select also verifies SHA-256 when mtime/size match (see §5.6, §7.1).

### 5.6 Catalog and select staleness

Catalog scan uses mtime + size only. **Select** is stricter: fresh only when mtime, size, **and** `rpkm_sha256` all match `run_context.json`. Any mtime/size drift triggers a rebuild; when mtime/size match, select hashes the file to catch in-place content changes that left metadata unchanged.

**When catalog shows `stale`:**

| Cause | Example |
|---|---|
| User replaced or edited the TSV | MetaPro re-run wrote new `RPKM_table.tsv` |
| User deleted `vis/runs/{sample_id}/` | DB gone; mtime/size may still match old context if partial delete |
| File mtime/size ≠ `run_context.json` | Includes touch/undo where content is unchanged but metadata drifted |
| Race | File changed after last scan but before select |

**Trade-off:** A touch or editor undo that changes mtime without changing content still triggers a pipeline rerun on select (~seconds). This keeps catalog and select aligned on metadata drift without a separate promotion step.

**Catalog `ready` with changed content (same mtime/size):** possible until select — select computes SHA-256 when mtime/size match and reruns if the hash differs.

**False `ready` in catalog** (file changed after scan): possible until next scan/refresh. Mitigated because **select always re-verifies** with a fresh `stat` and checksum when metadata matches (see §7.1).

**On select:** always `stat` the file fresh; compare mtime/size to `run_context.json`; when they match, compare SHA-256. Do not skip pipeline based on catalog status alone.

## 6. Pipeline staleness and `run_context.json`

Extend `run_context.json` written by `run_pipeline.py`:

```json
{
  "sample_id": "proj1__run2",
  "rpkm_path": "/data/proj1/run2/RPKM_table.tsv",
  "rpkm_mtime": 1710000000,
  "rpkm_size": 53527520,
  "rpkm_sha256": "abc123...",
  "tax_rank": "phylum",
  "pathway_level": "pathway",
  "overall_status": "success",
  "run_at": "2026-07-16T12:00:00Z"
}
```

**Stale if any:**

- `run_context.json` or `sample.duckdb` missing
- `rpkm_mtime` / `rpkm_size` differ from current file
- `rpkm_sha256` differs from current file (computed on select when mtime/size match)

**On select, fresh only when** mtime, size, and `rpkm_sha256` all match. Legacy runs missing `rpkm_sha256` in context rerun on next select.

**On stale/missing select:** delete `{RUNS_DIR}/{sample_id}/` (clean rebuild per existing `_prepare_sample_db` behavior), rerun dbt, replace tables.

## 7. Selection and SSE flow

### 7.1 Select

```
POST /api/datasets/select
{ "sample_id": "proj1__run2" }
```

1. Resolve `rpkm_path` from catalog.
2. **Re-verify staleness** — fresh `stat` + mtime/size compare to `run_context.json`; when mtime/size match, compare SHA-256 (do not trust catalog status alone).
3. If verified `ready` → set `active_sample_id`, return `{ "status": "ready" }`.
4. If `running` for **same** `sample_id` → return `{ "status": "running" }` (idempotent; client may reconnect SSE).
5. If **another** `sample_id` is `running` → **409 Conflict** (v1: single concurrent pipeline).
6. If stale/missing → set status `running`, spawn background pipeline.
7. Return `{ "status": "running", "sample_id": "..." }`.

On success: set `active_sample_id`, status → `ready`. On failure: status → `failed`, populate `last_error`.

**No Update button.** Successful select auto-activates viz.

### 7.2 SSE

```
GET /api/datasets/{sample_id}/events
Accept: text/event-stream
```

Server streams events while pipeline is `running` for that `sample_id`:

```text
event: progress
data: {"step": 1, "total": 23, "name": "int_rpkm_by_ec_tax", "state": "started"}

event: progress
data: {"step": 1, "total": 23, "name": "int_rpkm_by_ec_tax", "state": "finished", "elapsed_s": 1.86}

event: complete
data: {"status": "ready", "sample_id": "proj1__run2"}

event: error
data: {"status": "failed", "message": "..."}
```

**Implementation:**

1. `run_pipeline.py` (or new `pipeline_runner.py`) spawns `dbt build --log-format json ...` with `subprocess.Popen`, stdout line-buffered.
2. Parse each JSON log line; map `NodeStart` / `NodeFinished` / `LogTestResult` to progress events.
3. Push events to a per-`sample_id` `asyncio.Queue`; SSE handler drains the queue.
4. Callback/parser must be **fast** — no blocking I/O in the parse loop.
5. UI opens `EventSource` on select; on `complete`, close stream and refresh viz tabs.
6. If SSE disconnects, UI may fall back to polling catalog status.

### 7.3 Active dataset

Global server state: `active_sample_id: str | null` (mirrors `selected_file_list[0]` in the renderer).

Viz endpoints keep the existing `names` field; mounted mode sends `names: [sample_id]`:

```json
POST /api/viz/overview
{ "names": ["proj1__run2"] }
```

DB path: `{RUNS_DIR}/{sample_id}/sample.duckdb` where `sample_id = sample_id_from_names(names)`.

## 8. UI changes

Replace `Upload.tsx` with a **Data** panel:

| Element | Behavior |
|---|---|
| Dataset table | Full container path, status badge, last-run time |
| Row click | `POST /api/datasets/select` + open SSE |
| Progress | Step bar or log from SSE events while `running` |
| Refresh button | `POST /api/datasets/refresh` — allowed while pipeline runs (see below) |
| Active indicator | Highlight selected row; `DataInfoBar` shows path |
| Removed (mounted mode) | File input, label field, Load Files, Load Test Files, Update, second dropdown |
| Legacy mode (dev) | Upload UI unchanged for cross-check |

Nav label: **Upload → Data** (mounted mode).

### 8.1 Interaction while pipeline is `running`

| Action | UI | Server |
|---|---|---|
| Click **same** row again | Show progress; reconnect SSE if dropped | Idempotent `running` |
| Click **different** row | **Disabled** (greyed out) + tooltip "Pipeline in progress" | 409 if attempted |
| **Refresh** | Enabled — updates file list and badges; does not cancel pipeline | Rescan; preserve `running` state for active job |
| Navigate viz tabs | Disabled or show stale data from prior active sample until new run completes | N/A |

Only one pipeline at a time in v1. The in-progress row shows the SSE progress bar; all other rows are not selectable until complete or failed.

## 9. API and code migration

| Area | Change |
|---|---|
| Express server | **Keep in repo** for dev legacy mode; **omit from container image** |
| FastAPI | Serve static UI (container); add dataset catalog + select + SSE |
| `run_pipeline.py` | `--runs-dir`, `--data-root`; write checksum fields; subprocess JSON logs |
| `analytics/api/filters.py` | `_db_path` → `{RUNS_DIR}/{id}/sample.duckdb` |
| Viz request bodies | **Keep `names`** — `names[0]` is `sample_id` in mounted mode (see §9.1) |
| Renderer `AppStore` | `selected_file_list` unchanged; mounted mode sets `[sample_id]` |
| `vizBackend.ts` / `dataMode` | Viz toggle + data-mode toggle; auto-force sidecar when mounted (see §3.2) |
| Dockerfile | Multi-stage: build frontend; install Python/uv/dbt; `uvicorn api.main:app`; `DATA_ROOT=/data`; no Node server |
| README | Document volume mounts, `local-data` dev setup, dev toggles |

**Express retire:** separate follow-up PR after mounted mode ships and is validated in the container.

### 9.1 Viz `names` contract (unchanged)

**Today there are two uses of `names[0]`** (already inconsistent in label vs filename):

| Source | What `names[0]` is | Legacy Express lookup | DuckDB `sample_id_from_names` |
|---|---|---|---|
| Upload + user label | User-entered `data_name` (e.g. `"my experiment"`) | `data["my experiment"]` | `sample_id = "my experiment"` → `runs/my experiment/` (only if pre-built) |
| Load test / pinned dropdown | Filename (e.g. `test_rpkm_1.tsv`) | `data["test_rpkm_1.tsv"]` | `test_rpkm_1` (`.tsv` stripped) |

So `names` was never strictly "filename" — for upload it is the **dataset key / label**. The DuckDB path already treats `names[0]` as an opaque id (strip `.tsv` if present).

**Mounted mode — keep the same contract:**

- `selected_file_list = [sample_id]` (e.g. `["_root"]`, `["proj1__run2"]`)
- Viz requests continue to send `{ names: selected_file_list, ... }` — **no schema rename**
- `sample_id_from_names(["proj1__run2"])` → `proj1__run2` (unchanged helper)
- UI displays the **full path** in the Data panel / `DataInfoBar`; `names` holds the opaque `sample_id`

No Pydantic or renderer field rename required for mounted mode.

## 10. Error handling

| Condition | Behavior |
|---|---|
| Reference parquet missing at startup | Fail fast with clear log message |
| `RPKM_table.tsv` unreadable | Catalog entry with `failed` or omit + log |
| Pipeline subprocess non-zero exit | `failed` status; SSE `error` event; error banner in UI |
| Concurrent select while running | 409 Conflict |
| Watcher unavailable (platform) | Log warning; rely on Refresh + startup scan |
| User deletes `vis/runs/` | Catalog shows `discovered`/`stale`; select reruns pipeline |

## 11. Testing

| Layer | Tests |
|---|---|
| `sample_id_from_path` | Unit: nested paths, `__` joining, `_root` for data-root file |
| Catalog scan | Temp `DATA_ROOT` tree; assert `vis/` excluded; dev fixtures merged when flag on |
| Staleness | mtime/size on catalog scan; mtime/size + sha256 on select |
| SSE | Integration: mock subprocess JSON lines → SSE events |
| Select flow | End-to-end with `fake_rpkm`; assert `sample.duckdb` created under `RUNS_DIR` |
| Viz | Existing golden tests updated to `sample_id` param |

## 12. Out of scope

- Comparison mode (two datasets / delta viz)
- Polling-based discovery (may add later)
- Deleting Express from the repo (deferred retire PR)
- Upload endpoint removal in legacy dev mode (upload remains for cross-check until retire)
- Multiple concurrent pipeline runs
- Persisting catalog to disk (in-memory + rescan is sufficient for v1)
- Generating `stress_rpkm_*.tsv` at image build time (optional follow-up)

## 13. Acceptance criteria

- [ ] No browser file upload in **mounted** mode UI (legacy upload mode remains in dev until retire PR)
- [ ] `DATA_ROOT` and `RUNS_DIR` configurable; dev defaults to `./local-data`
- [ ] Discovers `RPKM_table.tsv` under `DATA_ROOT`, excludes `vis/`
- [ ] Watcher + Refresh update catalog
- [ ] Select runs pipeline when stale; auto-activates on success
- [ ] SSE streams dbt step progress during pipeline run
- [ ] `run_context.json` includes checksum fields
- [ ] Viz reads `RUNS_DIR` via `sample_id_from_names(names)`; `names` contract unchanged
- [ ] Single-container FastAPI serves UI + API
- [ ] `ENABLE_DEV_DATASETS=1` lists bundled test/stress fixtures
- [ ] Deleting `vis/runs/` does not break the app
- [ ] Reference data outside `DATA_ROOT`; documented as non-user-modifiable
