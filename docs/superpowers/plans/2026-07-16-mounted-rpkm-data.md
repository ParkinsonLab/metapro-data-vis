# Mounted RPKM Data — Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace browser upload with mounted-dataset discovery, on-select dbt pipeline, SSE progress, and FastAPI-only container — while keeping Express/upload mode in dev for cross-check.

**Architecture:** Python `api/datasets/` module owns catalog scan, staleness, async pipeline (subprocess dbt JSON logs → SSE queue). `RUNS_DIR` replaces hardcoded `transform/runs/`. Renderer gains `dataMode` toggle; mounted mode shows Data panel and forces sidecar viz. Container image is FastAPI + static UI only.

**Tech Stack:** FastAPI, uvicorn, watchdog, asyncio SSE, dbt 1.12 + dbt-duckdb, React 19, Vite, Docker (Python base, no Node runtime in container)

**Worktree:** `.worktrees/feature/mounted-rpkm-data/` on branch `feature/mounted-rpkm-data` (from `origin/dev`)

**Design spec:** `docs/superpowers/specs/2026-07-16-mounted-rpkm-data-design.md`

---

## Reference Material

Read before implementing:

- Design spec §2–§9 (paths, discovery, select+SSE, toggles, `names` contract)
- `analytics/transform/scripts/run_pipeline.py` — extend, don't rewrite from scratch
- `analytics/api/filters.py` — `sample_id_from_names`; all `_db_path` helpers in `*_service.py`
- `src/renderer/src/vizBackend.ts` — pattern for `dataMode` toggle
- `src/renderer/src/components/Upload.tsx` — replace in mounted mode only
- `vite.config.ts` — proxy target switch for mounted dev

**Prerequisites:** `build_reference.py` bridges built; `fake_rpkm` fixture available.

---

## File Map

```
analytics/
├── pyproject.toml                          # MODIFY: add watchdog
├── api/
│   ├── config.py                           # CREATE: DATA_ROOT, RUNS_DIR, env helpers
│   ├── datasets/
│   │   ├── __init__.py
│   │   ├── catalog.py                      # CREATE: scan, status, dev fixtures
│   │   ├── identity.py                     # CREATE: sample_id_from_path
│   │   ├── staleness.py                    # CREATE: stat + checksum vs run_context
│   │   ├── pipeline_runner.py              # CREATE: async subprocess, SSE queue
│   │   ├── routes.py                       # CREATE: /api/datasets/*
│   │   └── watcher.py                      # CREATE: watchdog debounced rescan
│   ├── main.py                             # MODIFY: mount datasets router, static UI, lifespan
│   ├── filters.py                          # MODIFY: _db_path uses RUNS_DIR from config
│   ├── *_service.py                        # MODIFY: import shared _db_path
│   └── tests/
│       ├── test_dataset_identity.py        # CREATE
│       ├── test_dataset_catalog.py         # CREATE
│       ├── test_dataset_staleness.py       # CREATE
│       ├── test_dataset_select.py          # CREATE
│       └── test_dataset_sse.py             # CREATE
└── transform/scripts/
    └── run_pipeline.py                     # MODIFY: --runs-dir, checksum in run_context, --log-format json

src/renderer/src/
├── dataMode.ts                             # CREATE: mounted | upload toggle
├── components/
│   ├── DataPanel.tsx                       # CREATE: catalog table, SSE progress
│   └── Upload.tsx                          # MODIFY: only render when dataMode=upload
├── App.tsx                                 # MODIFY: Data vs Upload nav, DataInfoBar path
├── api.ts                                  # MODIFY: dataset channels, mounted-mode base URL
└── store/AppStore.ts                       # MODIFY: active_dataset_path optional field

vite.config.ts                              # MODIFY: env-driven proxy target
package.json                                # MODIFY: dev:mounted script
Dockerfile                                  # MODIFY: Python runtime, uvicorn, no Node CMD
README.md                                   # MODIFY: mount example, local-data, toggles
```

**Not in this PR:** deleting `src/server/` (deferred retire PR).

---

### Task 1: Path configuration

**Files:**
- Create: `analytics/api/config.py`
- Create: `analytics/api/tests/test_config.py`

- [ ] **Step 1: Write failing tests for defaults and overrides**

```python
# analytics/api/tests/test_config.py
import os
from api.config import get_settings

def test_defaults(monkeypatch):
    monkeypatch.delenv("DATA_ROOT", raising=False)
    monkeypatch.delenv("RUNS_DIR", raising=False)
    s = get_settings()
    assert s.data_root.name  # Path exists conceptually
    assert s.runs_dir == s.data_root / "vis" / "runs"

def test_runs_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "custom-runs"))
    s = get_settings()
    assert s.runs_dir == tmp_path / "custom-runs"
```

- [ ] **Step 2: Implement `Settings` dataclass**

```python
# analytics/api/config.py
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

@dataclass(frozen=True)
class Settings:
    data_root: Path
    runs_dir: Path
    reference_parquet_dir: Path
    enable_dev_datasets: bool

@lru_cache
def get_settings() -> Settings:
    data_root = Path(os.environ.get("DATA_ROOT", "./local-data")).resolve()
    runs_dir = Path(os.environ.get("RUNS_DIR", str(data_root / "vis" / "runs"))).resolve()
    ref = Path(os.environ.get(
        "REFERENCE_PARQUET_DIR",
        "analytics/transform/reference/parquet",
    )).resolve()
    dev = os.environ.get("ENABLE_DEV_DATASETS", "0") == "1"
    return Settings(data_root=data_root, runs_dir=runs_dir,
                    reference_parquet_dir=ref, enable_dev_datasets=dev)

def db_path(sample_id: str) -> Path:
    return get_settings().runs_dir / sample_id / "sample.duckdb"
```

- [ ] **Step 3: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_config.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/api/config.py analytics/api/tests/test_config.py
git commit -m "feat(api): add DATA_ROOT and RUNS_DIR configuration"
```

---

### Task 2: Sample identity

**Files:**
- Create: `analytics/api/datasets/identity.py`
- Create: `analytics/api/tests/test_dataset_identity.py`

- [ ] **Step 1: Write tests**

Cases: `proj1/run2/RPKM_table.tsv` → `proj1__run2`; `/data/RPKM_table.tsv` → `_root`; dev fixture stem helper.

- [ ] **Step 2: Implement `sample_id_from_path` and `dev_fixture_sample_id`**

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(api): add dataset sample_id derivation"
```

---

### Task 3: Catalog scan and status

**Files:**
- Create: `analytics/api/datasets/catalog.py`
- Create: `analytics/api/tests/test_dataset_catalog.py`

- [ ] **Step 1: Write tests with `tmp_path` tree**

```
tmp/data/proj/RPKM_table.tsv     → discovered
tmp/data/vis/runs/x/sample.duckdb → excluded from discovery
```

- [ ] **Step 2: Implement `scan_datasets(settings) -> list[DatasetEntry]`**

Fields per spec §5.4. Join `run_context.json` for `ready`/`stale`/`discovered`. Dev fixture registry when `enable_dev_datasets`.

- [ ] **Step 3: Implement in-memory `CatalogStore` (thread-safe dict + lock)**

Holds latest scan + `running`/`active_sample_id` state.

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat(api): add RPKM_table.tsv catalog scanner"
```

---

### Task 4: Staleness verification

**Files:**
- Create: `analytics/api/datasets/staleness.py`
- Create: `analytics/api/tests/test_dataset_staleness.py`

- [ ] **Step 1: Tests** — missing context, mtime mismatch, matching mtime/size, sha256 mismatch

- [ ] **Step 2: Implement `verify_staleness(rpkm_path, runs_dir, sample_id) -> StalenessResult`**

Returns `needs_pipeline: bool`, reason enum.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(api): add select-time dataset staleness checks"
```

---

### Task 5: Pipeline runner + run_pipeline extensions

**Files:**
- Modify: `analytics/transform/scripts/run_pipeline.py`
- Create: `analytics/api/datasets/pipeline_runner.py`
- Create: `analytics/api/tests/test_dataset_sse.py`

- [ ] **Step 1: Extend `run_pipeline.py`**

- Add `--runs-dir` (default from env or `transform/runs` for CLI backward compat)
- Write `rpkm_mtime`, `rpkm_size`, `rpkm_sha256` to `run_context.json`
- Add `--log-format json` to dbt subprocess when `--json-logs` flag set

- [ ] **Step 2: Implement `PipelineRunner`**

- `async def run(sample_id, rpkm_path) -> None`
- `subprocess.Popen` with stdout line iterator
- Parse JSON lines → `ProgressEvent` (map `NodeStart`/`NodeFinished`)
- Push to `asyncio.Queue` registered per `sample_id`
- On exit: update catalog status `ready`/`failed`, set `active_sample_id` on success

- [ ] **Step 3: Unit test SSE mapping with fixture JSON log lines**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(api): pipeline runner with dbt JSON log streaming"
```

---

### Task 6: Dataset API routes + SSE

**Files:**
- Create: `analytics/api/datasets/routes.py`
- Modify: `analytics/api/main.py`

- [ ] **Step 1: Routes**

| Method | Path | Handler |
|---|---|---|
| GET | `/api/datasets` | list catalog + `active_sample_id` |
| POST | `/api/datasets/refresh` | rescan |
| POST | `/api/datasets/select` | staleness check, start pipeline |
| GET | `/api/datasets/{sample_id}/events` | SSE stream |

- [ ] **Step 2: Select logic per spec §7.1** — 409 on concurrent pipeline; idempotent same-id `running`

- [ ] **Step 3: SSE via `StreamingResponse`**

```python
async def event_stream(sample_id: str):
    queue = get_queue(sample_id)
    while True:
        event = await queue.get()
        yield f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"
        if event.kind in ("complete", "error"):
            break
```

- [ ] **Step 4: Integration test with `TestClient` + `httpx` async for select + SSE**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(api): dataset catalog, select, and SSE endpoints"
```

---

### Task 7: Wire RUNS_DIR into viz services

**Files:**
- Modify: `analytics/api/filters.py` or replace per-service `_db_path` with `api.config.db_path`
- Modify: all `analytics/api/*_service.py`

- [ ] **Step 1: Replace hardcoded `TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"` with `db_path(sample_id)`**

- [ ] **Step 2: Run existing API golden tests**

```bash
cd analytics && uv run pytest api/tests/ -v
```

Adjust fixture DB paths in tests if they assume `transform/runs/` (use env `RUNS_DIR` in conftest).

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor(api): resolve sample.duckdb from RUNS_DIR"
```

---

### Task 8: Watcher + FastAPI lifespan

**Files:**
- Create: `analytics/api/datasets/watcher.py`
- Modify: `analytics/api/main.py`

- [ ] **Step 1: Debounced watchdog on `DATA_ROOT`, skip `vis/`**

- [ ] **Step 2: `lifespan` context: startup scan + start watcher; shutdown stop watcher**

- [ ] **Step 3: Startup check for reference parquet; log clear error if missing**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(api): filesystem watcher for dataset catalog"
```

---

### Task 9: FastAPI static UI (container path)

**Files:**
- Modify: `analytics/api/main.py`

- [ ] **Step 1: Mount `StaticFiles` on `dist/` when directory exists**

- [ ] **Step 2: SPA fallback route for non-`/api` paths**

- [ ] **Step 3: Manual smoke test**

```bash
npm run build
cd analytics && DATA_ROOT=./local-data uv run uvicorn api.main:app --port 8080
# open http://localhost:8080
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(api): serve Vite build and SPA fallback from FastAPI"
```

---

### Task 10: Renderer — dataMode toggle + Data panel

**Files:**
- Create: `src/renderer/src/dataMode.ts`
- Create: `src/renderer/src/components/DataPanel.tsx`
- Modify: `src/renderer/src/App.tsx`, `src/renderer/src/api.ts`, `src/renderer/src/store/AppStore.ts`

- [ ] **Step 1: `dataMode.ts`** — `mounted` | `upload` in localStorage; `getDataMode()`, `setDataMode()`

- [ ] **Step 2: When `dataMode=mounted`, force `vizBackend=sidecar`**

- [ ] **Step 3: `DataPanel`**

- Fetch `GET /api/datasets` on mount
- Refresh button → `POST /api/datasets/refresh`
- Row click → `POST /api/datasets/select` + `EventSource` for SSE
- On `complete`: `setState({ selected_file_list: [sample_id], active_dataset_path: path })`
- Disable other rows while `running`; show progress from SSE

- [ ] **Step 4: `App.tsx`** — render `DataPanel` or `Upload` based on `dataMode`; nav label "Data" vs "Upload"

- [ ] **Step 5: `DataInfoBar`** — show `active_dataset_path` when set, else `selected_file_list[0]`

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(ui): Data panel with catalog, select, and SSE progress"
```

---

### Task 11: Dev workflow

**Files:**
- Modify: `vite.config.ts`, `package.json`

- [ ] **Step 1: `vite.config.ts` — proxy `/api` to `http://localhost:8080` when `VITE_DATA_MODE=mounted`, else `:3001`**

- [ ] **Step 2: Add scripts**

```json
"dev:fastapi": "cd analytics && DATA_ROOT=../local-data ENABLE_DEV_DATASETS=1 uv run uvicorn api.main:app --port 8080 --reload",
"dev:mounted": "concurrently -n api,web \"npm run dev:fastapi\" \"VITE_DATA_MODE=mounted npm run dev:web\""
```

- [ ] **Step 3: Document in README**

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(dev): add mounted-mode dev scripts and vite proxy"
```

---

### Task 12: Dockerfile (FastAPI-only container)

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Multi-stage**

1. `node:22` — `npm ci && npm run build` → `dist/`
2. `python:3.14` or slim + uv — copy `analytics/`, install deps, `build_reference.py` at build, copy `dist/`, `resources/db/taxonomy.db` if needed for network layout

- [ ] **Step 2: Runtime**

```dockerfile
ENV DATA_ROOT=/data
ENV RUNS_DIR=/data/vis/runs
ENV REFERENCE_PARQUET_DIR=/app/analytics/transform/reference/parquet
EXPOSE 8080
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Smoke test**

```bash
docker build --platform linux/amd64 -t metapro-viz .
docker run --platform linux/amd64 -p 8080:8080 \
  -v /Users/sibyl/Downloads/tutorial_files:/data \
  metapro-viz
```

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(docker): FastAPI-only container with mounted /data support"
```

---

### Task 13: End-to-end verification

- [ ] **Step 1: Place fixture**

```bash
mkdir -p local-data/tutorial
cp analytics/transform/tests/fixtures/fake_rpkm.tsv local-data/tutorial/RPKM_table.tsv
```

- [ ] **Step 2: `npm run dev:mounted`**

- Select `tutorial` dataset (sample_id `tutorial`)
- Confirm SSE progress, viz tabs load

- [ ] **Step 3: Staleness** — touch TSV, refresh shows `stale`, re-select rebuilds

- [ ] **Step 4: Run full test suites**

```bash
cd analytics && uv run pytest -v
npm test
```

- [ ] **Step 5: Update spec status to Approved if not already**

---

## Task Dependency Graph

```
Task 1 (config) ─┬─→ Task 2 (identity) ─→ Task 3 (catalog) ─→ Task 6 (routes)
                 │                              ↑
                 ├─→ Task 4 (staleness) ────────┤
                 └─→ Task 5 (pipeline) ─────────┘
Task 6 ─→ Task 7 (viz RUNS_DIR) ─→ Task 8 (watcher) ─→ Task 9 (static)
Task 10 (UI) depends on Task 6
Task 11 (dev) depends on Task 9 + 10
Task 12 (docker) depends on Task 9
Task 13 (e2e) last
```

---

## Acceptance Checklist (from spec §13)

- [ ] Mounted mode: no upload UI; legacy upload still available via toggle
- [ ] `DATA_ROOT` / `RUNS_DIR` env-configurable; dev `./local-data`
- [ ] Discovers `RPKM_table.tsv`, excludes `vis/`
- [ ] Watcher + Refresh
- [ ] Select + SSE + auto-activate `selected_file_list`
- [ ] Checksum fields in `run_context.json`
- [ ] Viz uses `names[0]` as `sample_id` via `RUNS_DIR`
- [ ] Container: FastAPI only, no Express
- [ ] Dev fixtures behind `ENABLE_DEV_DATASETS`
- [ ] `tutorial_files` mount → `_root` works
