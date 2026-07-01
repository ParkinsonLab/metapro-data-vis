# Overview API via dbt Intermediates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI `POST /api/viz/overview` backed by `int_tax_rollup_resolved`, Express sidecar proxy + shared `fastapi_sidecar_proxy.ts`, renderer `localStorage` toggle (sidecar default), and golden tests on `fake_rpkm` — preserving the existing JSON contract.

**Architecture:** Pin `requested_rank='phylum'` and `pathway_level='superpathway'`; aggregate phylum/superpathway vectors from sample DuckDB; sort phylum counts via `bridge_tax_rollup` reference lookup (kingdom → phylum). Express defaults to legacy when `?backend=duckdb` absent; renderer appends query param for migrated channels unless `localStorage.vizBackend === 'legacy'`.

**Tech Stack:** Python 3.14, FastAPI, DuckDB, pytest, Pydantic; Node 22, Express 5, vitest

**Branch:** `feature/overview-dbt-api`

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-06-29-overview-dbt-api-design.md` — full design (SQL, errors, toggle)
- `analytics/api/chord_service.py` — DuckDB connect pattern, `BRIDGE_TAX_PATH`
- `analytics/api/filters.py` — `sample_id_from_names`
- `analytics/api/envelope.py` — `wrap_handler`
- `analytics/api/tests/test_chord_service.py` — golden test pattern
- `src/server/chord_handler.ts` — current proxy (to refactor)

**Prerequisite:** `analytics/transform/reference/parquet/bridge_tax_rollup.parquet` built; `fake_rpkm` pipeline run once.

---

## File Map

```
analytics/api/
├── schemas.py                    # MODIFY: add Overview* models
├── overview_service.py           # CREATE
├── main.py                       # MODIFY: POST /api/viz/overview
└── tests/
    ├── fixtures/
    │   └── overview_expectations.yaml   # CREATE (via dump script)
    ├── test_overview_service.py  # CREATE
    └── test_main.py              # MODIFY: overview endpoint smoke

analytics/testing/
├── fake_rpkm_fixture.py          # MODIFY: OVERVIEW_YAML + loader
└── dump_fake_rpkm_expectations.py # MODIFY: dump overview goldens

src/server/
├── fastapi_sidecar_proxy.ts      # CREATE
├── chord_handler.ts              # MODIFY: thin wrapper or delete
└── index.ts                      # MODIFY: overview sidecar route

src/renderer/src/
├── vizBackend.ts                 # CREATE
└── api.ts                        # MODIFY: sidecarQuery; remove CHORD_BACKEND_QUERY

src/tests/
├── fastapi_sidecar_proxy.test.ts # CREATE
└── chord_handler.test.ts         # MODIFY or replace with proxy tests
```

---

### Task 1: Pydantic overview schemas

**Files:**
- Modify: `analytics/api/schemas.py`

- [ ] **Step 1: Add models**

```python
class OverviewVector(BaseModel):
    index: list[str]
    counts: list[float]


class OverviewResponse(BaseModel):
    counts_data: OverviewVector
    ann_data: OverviewVector


class OverviewRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
```

- [ ] **Step 2: Commit**

```bash
git add analytics/api/schemas.py
git commit -m "feat(analytics): add Overview pydantic schemas"
```

---

### Task 2: Overview service — validation and errors

**Files:**
- Create: `analytics/api/overview_service.py`
- Create: `analytics/api/tests/test_overview_service.py`

- [ ] **Step 1: Write failing validation tests**

```python
import pytest
from api.overview_service import build_overview_from_duckdb

def test_overview_rejects_empty_names():
    with pytest.raises(ValueError, match="at least one sample"):
        build_overview_from_duckdb(names=[])

def test_overview_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_overview_from_duckdb(names=["a.tsv", "b.tsv"])
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_overview_service.py -v
```

- [ ] **Step 3: Implement minimal service shell**

```python
# analytics/api/overview_service.py
from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import sample_id_from_names
from api.schemas import OverviewResponse, OverviewVector

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def build_overview_from_duckdb(*, names: list[str]) -> OverviewResponse:
    if len(names) == 0:
        raise ValueError("names must contain at least one sample")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on duckdb backend")

    sample_id = sample_id_from_names(names)
    db_file = _db_path(sample_id)
    if not db_file.exists():
        raise FileNotFoundError(f"sample not found: {sample_id}")

    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "int_tax_rollup_resolved" not in tables:
            raise RuntimeError(
                f"int_tax_rollup_resolved not materialized for sample: {sample_id}"
            )
        counts_data = _fetch_counts_data(conn)
        ann_data = _fetch_ann_data(conn)
        return OverviewResponse(counts_data=counts_data, ann_data=ann_data)
    finally:
        conn.close()


def _fetch_counts_data(conn) -> OverviewVector:
    raise NotImplementedError


def _fetch_ann_data(conn) -> OverviewVector:
    raise NotImplementedError
```

- [ ] **Step 4: Run validation tests — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_overview_service.py::test_overview_rejects_empty_names api/tests/test_overview_service.py::test_overview_rejects_comparison -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/overview_service.py analytics/api/tests/test_overview_service.py
git commit -m "feat(analytics): overview service shell with validation"
```

---

### Task 3: Overview service — SQL for counts and ann vectors

**Files:**
- Modify: `analytics/api/overview_service.py`
- Modify: `analytics/api/tests/test_overview_service.py`

- [ ] **Step 1: Write shape smoke test**

```python
import pytest
from api.overview_service import build_overview_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason

@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_overview_from_duckdb_shape(fake_rpkm_db):
    out = build_overview_from_duckdb(names=[f"{SAMPLE_ID}.tsv"])
    assert out.counts_data.index == out.counts_data.counts and len(out.counts_data.index) == len(out.counts_data.counts)
    assert len(out.ann_data.index) == len(out.ann_data.counts)
    assert len(out.counts_data.index) > 0
    assert len(out.ann_data.index) > 0
```

- [ ] **Step 2: Implement `_fetch_counts_data` and `_fetch_ann_data`**

```python
def _rows_to_vector(rows: list[tuple[str, float]]) -> OverviewVector:
    return OverviewVector(
        index=[r[0] for r in rows],
        counts=[float(r[1]) for r in rows],
    )


def _fetch_counts_data(conn) -> OverviewVector:
    if not BRIDGE_TAX_PATH.exists():
        raise FileNotFoundError(f"bridge parquet missing: {BRIDGE_TAX_PATH}")
    bridge = BRIDGE_TAX_PATH.as_posix()
    rows = conn.execute(
        f"""
        WITH phylum_totals AS (
            SELECT resolved_tax_label AS phylum_label, SUM(value) AS total
            FROM int_tax_rollup_resolved
            WHERE requested_rank = 'phylum'
              AND pathway_level = 'superpathway'
            GROUP BY resolved_tax_label
        ),
        phylum_map AS (
            SELECT DISTINCT source_tax_id, resolved_tax_label AS phylum_label
            FROM read_parquet('{bridge}')
            WHERE requested_rank = 'phylum'
        ),
        kingdom_map AS (
            SELECT source_tax_id, resolved_tax_label AS kingdom_label
            FROM read_parquet('{bridge}')
            WHERE requested_rank = 'kingdom'
        ),
        phylum_to_kingdom AS (
            SELECT p.phylum_label, MIN(k.kingdom_label) AS kingdom_label
            FROM phylum_map p
            JOIN kingdom_map k USING (source_tax_id)
            GROUP BY p.phylum_label
        )
        SELECT p.phylum_label, p.total
        FROM phylum_totals p
        LEFT JOIN phylum_to_kingdom k ON k.phylum_label = p.phylum_label
        ORDER BY COALESCE(k.kingdom_label, ''), p.phylum_label ASC
        """
    ).fetchall()
    return _rows_to_vector(rows)


def _fetch_ann_data(conn) -> OverviewVector:
    rows = conn.execute(
        """
        SELECT
            CASE WHEN pathway_key IS NULL THEN 'Unmapped EC' ELSE pathway_label END AS label,
            SUM(value) AS total
        FROM int_tax_rollup_resolved
        WHERE requested_rank = 'phylum'
          AND pathway_level = 'superpathway'
        GROUP BY 1
        ORDER BY label ASC
        """
    ).fetchall()
    return _rows_to_vector(rows)
```

- [ ] **Step 3: Run shape test**

```bash
cd analytics && uv run pytest api/tests/test_overview_service.py::test_build_overview_from_duckdb_shape -v
```

Expected: PASS (requires bridges + fake_rpkm db).

- [ ] **Step 4: Commit**

```bash
git add analytics/api/overview_service.py
git commit -m "feat(analytics): overview SQL for counts and ann vectors"
```

---

### Task 4: Golden tests and dump script

**Files:**
- Modify: `analytics/testing/fake_rpkm_fixture.py`
- Modify: `analytics/testing/dump_fake_rpkm_expectations.py`
- Create: `analytics/api/tests/fixtures/overview_expectations.yaml`
- Modify: `analytics/api/tests/test_overview_service.py`

- [ ] **Step 1: Add fixture paths**

```python
# fake_rpkm_fixture.py
OVERVIEW_YAML = ANALYTICS_DIR / "api/tests/fixtures/overview_expectations.yaml"

def load_overview_expectations() -> dict[str, Any]:
    return load_yaml(OVERVIEW_YAML)
```

- [ ] **Step 2: Extend dump script to write overview YAML**

After building overview via `build_overview_from_duckdb(names=[f"{SAMPLE_ID}.tsv"])`, write:

```yaml
overview:
  counts_data:
    index: [...]
    counts: [...]
  ann_data:
    index: [...]
    counts: [...]
```

Run once:

```bash
cd analytics && uv run python testing/dump_fake_rpkm_expectations.py
```

- [ ] **Step 3: Add golden test**

```python
@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_overview_vectors_match_golden(fake_rpkm_db):
    from testing.fake_rpkm_fixture import SAMPLE_ID, load_overview_expectations

    expected = load_overview_expectations()["overview"]
    out = build_overview_from_duckdb(names=[f"{SAMPLE_ID}.tsv"])
    assert out.counts_data.model_dump() == expected["counts_data"]
    assert out.ann_data.model_dump() == expected["ann_data"]
```

- [ ] **Step 4: Run golden test**

```bash
cd analytics && uv run pytest api/tests/test_overview_service.py::test_overview_vectors_match_golden -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/testing/fake_rpkm_fixture.py analytics/testing/dump_fake_rpkm_expectations.py \
  analytics/api/tests/fixtures/overview_expectations.yaml analytics/api/tests/test_overview_service.py
git commit -m "test(analytics): overview golden expectations on fake_rpkm"
```

---

### Task 5: FastAPI route

**Files:**
- Modify: `analytics/api/main.py`
- Modify: `analytics/api/tests/test_main.py`

- [ ] **Step 1: Write failing TestClient test**

```python
def test_overview_endpoint_envelope(fake_rpkm_db):
    res = client.post("/api/viz/overview", json={"names": ["fake_rpkm.tsv"]})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "counts_data" in body["value"]
    assert "ann_data" in body["value"]


def test_overview_comparison_error_envelope():
    res = client.post("/api/viz/overview", json={"names": ["a.tsv", "b.tsv"]})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "comparison mode" in body["error"]
```

Add `fake_rpkm_db` fixture import from conftest (pytest auto-discovers).

- [ ] **Step 2: Add endpoint to main.py**

```python
from api.overview_service import build_overview_from_duckdb
from api.schemas import OverviewRequest

@app.post("/api/viz/overview")
def overview_endpoint(body: OverviewRequest):
    def _handle():
        return build_overview_from_duckdb(names=body.names).model_dump()

    return wrap_handler(_handle)
```

- [ ] **Step 3: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_main.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/api/main.py analytics/api/tests/test_main.py
git commit -m "feat(analytics): POST /api/viz/overview endpoint"
```

---

### Task 6: Express sidecar proxy (shared)

**Files:**
- Create: `src/server/fastapi_sidecar_proxy.ts`
- Modify: `src/server/chord_handler.ts` (re-export or delete)
- Create: `src/tests/fastapi_sidecar_proxy.test.ts`

- [ ] **Step 1: Write failing proxy tests**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createSidecarProxyHandler } from '../server/fastapi_sidecar_proxy'

describe('createSidecarProxyHandler', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('uses legacy when backend query absent', async () => {
    const legacy = vi.fn().mockReturnValue({ ok: true })
    const handler = createSidecarProxyHandler({
      legacyHandler: legacy,
      apiPath: '/api/viz/overview',
      label: 'overview',
    })
    const req = { query: {}, body: { names: ['x.tsv'] } }
    await handler(req)
    expect(legacy).toHaveBeenCalledWith(req.body)
  })

  it('proxies to FastAPI when backend=duckdb', async () => {
    const fetchFn = vi.fn().mockResolvedValue({
      json: async () => ({ ok: true, value: {} }),
    })
    const handler = createSidecarProxyHandler({
      legacyHandler: vi.fn(),
      apiPath: '/api/viz/overview',
      label: 'overview',
      fetchFn,
      baseUrl: 'http://localhost:8001',
    })
    await handler({ query: { backend: 'duckdb' }, body: { names: ['x.tsv'] } })
    expect(fetchFn).toHaveBeenCalledWith(
      'http://localhost:8001/api/viz/overview',
      expect.objectContaining({ method: 'POST' })
    )
  })
})
```

- [ ] **Step 2: Implement proxy**

```typescript
import { wrapHandler } from './envelope'
import type { ApiEnvelope } from './envelope'

const ANALYTICS_API_URL = process.env.ANALYTICS_API_URL ?? 'http://localhost:8001'

export const createSidecarProxyHandler = (deps: {
  legacyHandler: (params?: unknown) => unknown
  apiPath: string
  label: string
  fetchFn?: typeof fetch
  baseUrl?: string
}) => {
  const fetchImpl = deps.fetchFn ?? fetch
  const baseUrl = deps.baseUrl ?? ANALYTICS_API_URL

  return async (req: {
    query: Record<string, string | undefined>
    body: Record<string, unknown>
  }): Promise<ApiEnvelope> => {
    if (req.query.backend !== 'duckdb') {
      return wrapHandler(deps.legacyHandler)(req.body)
    }
    try {
      const url = `${baseUrl}${deps.apiPath}`
      const res = await fetchImpl(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body),
      })
      return (await res.json()) as ApiEnvelope
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      return { ok: false, error: `${deps.label} duckdb backend unavailable: ${error}` }
    }
  }
}

/** @deprecated Use createSidecarProxyHandler directly */
export const createChordHandler = (deps: {
  legacyHandler: (params?: unknown) => unknown
  fetchFn?: typeof fetch
}) =>
  createSidecarProxyHandler({
    ...deps,
    apiPath: '/api/viz/chord',
    label: 'chord',
  })
```

Move implementation from `chord_handler.ts` or replace file with re-export.

- [ ] **Step 3: Run tests**

```bash
npm test -- src/tests/fastapi_sidecar_proxy.test.ts
```

- [ ] **Step 4: Commit**

```bash
git add src/server/fastapi_sidecar_proxy.ts src/server/chord_handler.ts src/tests/fastapi_sidecar_proxy.test.ts
git commit -m "feat(server): shared FastAPI sidecar proxy; ANALYTICS_API_URL"
```

---

### Task 7: Wire Express overview route

**Files:**
- Modify: `src/server/index.ts`

- [ ] **Step 1: Remove overview from vizRoutes loop; add sidecar handler**

```typescript
import { createSidecarProxyHandler } from './fastapi_sidecar_proxy'

const vizRoutes = [
  // remove overview from here
  { path: '/api/viz/counts', handler: parse_counts },
  ...
]

const overviewHandler = createSidecarProxyHandler({
  legacyHandler: parse_overview,
  apiPath: '/api/viz/overview',
  label: 'overview',
})

app.post('/api/viz/overview', async (req, res) => {
  const envelope = await overviewHandler({
    query: req.query as Record<string, string | undefined>,
    body: req.body,
  })
  res.status(200).json(envelope)
})
```

Keep chord handler pattern consistent (refactor to `createSidecarProxyHandler` if not done in Task 6).

- [ ] **Step 2: Run server tests**

```bash
npm test -- src/tests/server.test.ts
```

- [ ] **Step 3: Commit**

```bash
git add src/server/index.ts
git commit -m "feat(server): overview route via FastAPI sidecar proxy"
```

---

### Task 8: Renderer localStorage toggle

**Files:**
- Create: `src/renderer/src/vizBackend.ts`
- Modify: `src/renderer/src/api.ts`

- [ ] **Step 1: Create vizBackend.ts**

```typescript
import type { Channel } from './api'

const STORAGE_KEY = 'vizBackend'
const MIGRATED_CHANNELS = new Set<Channel>(['chord', 'overview'])

export type VizBackend = 'legacy' | 'sidecar'

export function getVizBackend(): VizBackend {
  return localStorage.getItem(STORAGE_KEY) === 'legacy' ? 'legacy' : 'sidecar'
}

export function sidecarQuery(channel: Channel): string {
  return MIGRATED_CHANNELS.has(channel) && getVizBackend() === 'sidecar'
    ? '?backend=duckdb'
    : ''
}
```

Resolve circular import: export `Channel` type from a small `channels.ts` or define `MIGRATED_CHANNELS` as `string[]` in `vizBackend.ts` and cast in `sidecarQuery`.

Preferred fix — extract channel union:

```typescript
// src/renderer/src/channels.ts
export type Channel = 'handshake' | 'load' | ... 
```

Or pass channel string without importing from api.ts:

```typescript
const MIGRATED = new Set(['chord', 'overview'])

export function sidecarQuery(channel: string): string {
  return MIGRATED.has(channel) && getVizBackend() === 'sidecar' ? '?backend=duckdb' : ''
}
```

- [ ] **Step 2: Update api.ts**

Remove `CHORD_BACKEND_QUERY`. In `endpointFor`:

```typescript
import { sidecarQuery } from './vizBackend'

overview: { method: 'POST', url: `/api/viz/overview${sidecarQuery('overview')}` },
chord: { method: 'POST', url: `/api/viz/chord${sidecarQuery('chord')}` },
```

Note: `endpointFor` is called per request so localStorage changes apply without reload.

- [ ] **Step 3: Manual smoke**

1. `npm run dev` + FastAPI on :8001
2. Load fake_rpkm in UI
3. Overview tab — should hit sidecar by default
4. `localStorage.setItem('vizBackend', 'legacy')` — re-open Overview — legacy path

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/vizBackend.ts src/renderer/src/api.ts
git commit -m "feat(renderer): localStorage viz backend toggle for migrated channels"
```

---

### Task 9: Docs and env var cleanup

**Files:**
- Modify: `analytics/transform/README.md` (CHORD_API_URL → ANALYTICS_API_URL, mention overview)
- Modify: `package.json` script comment if any

- [ ] **Step 1: Grep and replace `CHORD_API_URL` references in docs**

- [ ] **Step 2: Add overview curl example to transform README §Chord API section (rename to Analytics API)

- [ ] **Step 3: Commit**

```bash
git add analytics/transform/README.md
git commit -m "docs: ANALYTICS_API_URL and overview sidecar workflow"
```

---

### Task 10: Full verification

- [ ] **Step 1: Python suite**

```bash
cd analytics && uv run pytest api/tests/ -v
```

- [ ] **Step 2: Node suite**

```bash
npm test
```

- [ ] **Step 3: Manual curl**

```bash
curl -s -X POST 'http://localhost:3001/api/viz/overview?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{"names":["fake_rpkm.tsv"]}' | head -c 200
```

Expected: `{"ok":true,"value":{"counts_data":...`

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| `POST /api/viz/overview` FastAPI | 5 |
| `overview_service.py` SQL | 3 |
| Pydantic `OverviewResponse` | 1, 3 |
| Golden YAML + pytest | 4 |
| `fastapi_sidecar_proxy.ts` | 6 |
| `ANALYTICS_API_URL` | 6 |
| Express overview route | 7 |
| `vizBackend` localStorage, sidecar default | 8 |
| Comparison / empty names errors | 2, 5 |
| Bridge-only phylum sort | 3 |
| Legacy Express default without query param | 6, 7 |

**Deferred (not in plan):** bridge_tax_label_sort reference table, dev UI toggle, TypeScript response types, unknown-header pipeline fix.
