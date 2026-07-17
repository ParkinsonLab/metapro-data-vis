# Mounted RPKM Data — Design Spec

> **Status:** Draft (2026-07-16)  
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

SHA-256 of `stress_rpkm_1` (388 MB): ~230 ms. Pipeline duration dominates; live progress via SSE is worthwhile but not blocking.

### 1.3 Locked decisions (brainstorming)

| Decision | Choice |
|---|---|
| Data input | Mounted folders; discover `RPKM_table.tsv` recursively under data root |
| Upload UI | **Remove** — no browser file upload |
| `sample_id` (mounted) | Path relative to `DATA_ROOT`, `/` → `__` (e.g. `/data/proj1/run2/RPKM_table.tsv` → `proj1__run2`) |
| `sample_id` (dev fixtures) | Filename stem (e.g. `test_rpkm_1.tsv` → `test_rpkm_1`) |
| Selection semantics | Select = checksum check → pipeline if stale → activate for viz (no separate Update button) |
| Comparison mode | Out of scope (single select only) |
| Container | Single image; **FastAPI only** (drop Express) |
| Pipeline output | `{RUNS_DIR}/{sample_id}/sample.duckdb` + `run_context.json` |
| Default `RUNS_DIR` | `{DATA_ROOT}/vis/runs` |
| Reference bridges | Baked in image at fixed app path; **never** under data root |
| Discovery | Recursive scan excluding `{DATA_ROOT}/vis/`; **watchdog** + **Refresh** button (no polling in v1) |
| Catalog scan cost | mtime + size only; checksum on select or when mtime/size changed |
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
  proj1/run2/RPKM_table.tsv    # discovered dataset
  vis/runs/
    proj1__run2/
      sample.duckdb
      run_context.json
```

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

**Removed:** Express server (`src/server/index.ts` routes), multer upload, legacy in-memory `add_data` path for viz (legacy Node viz handlers may remain behind `?backend=legacy` until fully retired, or removed in same effort — see §9).

**Static UI:** Vite `dist/` served by FastAPI `StaticFiles` with SPA fallback.

## 4. Sample identity

### 4.1 Mounted datasets

```python
def sample_id_from_path(data_root: Path, rpkm_path: Path) -> str:
    rel = rpkm_path.relative_to(data_root)
    # drop filename RPKM_table.tsv
    parent = rel.parent
    if str(parent) == ".":
        raise ValueError("RPKM_table.tsv at data root is not allowed")
    return str(parent).replace("/", "__")
```

Display path in UI: **full absolute container path** (e.g. `/data/proj1/run2/RPKM_table.tsv`).

### 4.2 Dev fixtures (`ENABLE_DEV_DATASETS=1`)

Explicit registry (not discovered by scan):

| Path (image) | `sample_id` |
|---|---|
| `/app/resources/example_data/test_rpkm_1.tsv` | `test_rpkm_1` |
| `/app/resources/example_data/test_rpkm_2.tsv` | `test_rpkm_2` |
| `/app/analytics/transform/tests/fixtures/fake_rpkm.tsv` | `fake_rpkm` |
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
| `ready` | `sample.duckdb` exists; checksum matches current file |
| `stale` | File mtime/size or SHA-256 differs from `run_context.json` |
| `running` | Pipeline in progress for this `sample_id` |
| `failed` | Last pipeline run failed; `last_error` set |

Checksum (`rpkm_sha256`) is computed on select (or when mtime/size changed vs catalog), not on every scan.

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
- `rpkm_sha256` differs (computed when mtime/size changed)

**On stale/missing select:** delete `{RUNS_DIR}/{sample_id}/` (clean rebuild per existing `_prepare_sample_db` behavior), rerun dbt, replace tables.

## 7. Selection and SSE flow

### 7.1 Select

```
POST /api/datasets/select
{ "sample_id": "proj1__run2" }
```

1. Resolve `rpkm_path` from catalog.
2. If status is `ready` → set `active_sample_id`, return `{ "status": "ready" }`.
3. If `running` for same id → return `{ "status": "running" }` (idempotent).
4. If another pipeline is `running` → reject with 409 or queue (v1: **reject** — single concurrent pipeline).
5. Compute checksum if mtime/size changed vs `run_context.json`.
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

Global server state: `active_sample_id: str | null`.

Viz endpoints use `sample_id` directly (replace `names: ["test_rpkm_1.tsv"]`):

```json
POST /api/viz/overview
{ "sample_id": "proj1__run2" }
```

DB path: `{RUNS_DIR}/{sample_id}/sample.duckdb`.

## 8. UI changes

Replace `Upload.tsx` with a **Data** panel:

| Element | Behavior |
|---|---|
| Dataset table | Full container path, status badge, last-run time |
| Row click | `POST /api/datasets/select` + open SSE |
| Progress | Step bar or log from SSE events while `running` |
| Refresh button | `POST /api/datasets/refresh` |
| Active indicator | Highlight selected row; `DataInfoBar` shows path |
| Removed | File input, label field, Load Files, Load Test Files, Update, second dropdown |

Nav label: **Upload → Data**.

Disable row selection while `running` (except show progress on active row).

## 9. API and code migration

| Area | Change |
|---|---|
| Express server | Remove from production path; delete upload routes |
| FastAPI | Serve static UI; add dataset catalog + select + SSE |
| `run_pipeline.py` | `--runs-dir`, `--data-root`; write checksum fields; subprocess JSON logs |
| `analytics/api/filters.py` | `sample_id` param; `_db_path` → `{RUNS_DIR}/{id}/sample.duckdb` |
| Viz services | Accept `sample_id` in request bodies (breaking change for renderer) |
| Renderer `AppStore` | `active_sample_id` replaces `selected_file_list` (length 1) |
| `vizBackend.ts` | Remove `?backend=duckdb` proxy indirection when Express is gone |
| Dockerfile | Multi-stage: build frontend; install Python/uv/dbt; `uvicorn api.main:app`; `DATA_ROOT=/data` |
| README | Document volume mounts, `local-data` dev setup |

**Legacy Node viz:** Remove with Express in the same effort. All viz traffic goes to FastAPI + DuckDB.

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
| `sample_id_from_path` | Unit: nested paths, `__` joining, reject root-level file |
| Catalog scan | Temp `DATA_ROOT` tree; assert `vis/` excluded; dev fixtures merged when flag on |
| Staleness | mtime/size/sha256 mismatch detection |
| SSE | Integration: mock subprocess JSON lines → SSE events |
| Select flow | End-to-end with `fake_rpkm`; assert `sample.duckdb` created under `RUNS_DIR` |
| Viz | Existing golden tests updated to `sample_id` param |

## 12. Out of scope

- Comparison mode (two datasets / delta viz)
- Polling-based discovery (may add later)
- Upload endpoint / browser file ingest
- Multiple concurrent pipeline runs
- Persisting catalog to disk (in-memory + rescan is sufficient for v1)
- Generating `stress_rpkm_*.tsv` at image build time (optional follow-up)

## 13. Acceptance criteria

- [ ] No browser file upload in UI
- [ ] `DATA_ROOT` and `RUNS_DIR` configurable; dev defaults to `./local-data`
- [ ] Discovers `RPKM_table.tsv` under `DATA_ROOT`, excludes `vis/`
- [ ] Watcher + Refresh update catalog
- [ ] Select runs pipeline when stale; auto-activates on success
- [ ] SSE streams dbt step progress during pipeline run
- [ ] `run_context.json` includes checksum fields
- [ ] Viz endpoints use `sample_id`; DB read from `RUNS_DIR`
- [ ] Single-container FastAPI serves UI + API
- [ ] `ENABLE_DEV_DATASETS=1` lists bundled test/stress fixtures
- [ ] Deleting `vis/runs/` does not break the app
- [ ] Reference data outside `DATA_ROOT`; documented as non-user-modifiable
