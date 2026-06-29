# Chord API via dbt Intermediates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FastAPI `POST /api/viz/chord` backend that queries precomputed `int_tax_rollup_resolved` in DuckDB, builds the chord matrix in Python, and integrates with Express via `?backend=duckdb` proxy — preserving the existing JSON contract.

**Architecture:** Runtime filters on `int_tax_rollup_resolved` (all request params) → mart-equivalent GROUP BY → `build_chord_matrix()`. Express keeps legacy as default; proxies same path to FastAPI sidecar on `:8001`. dbt macro refactors mart SQL for parity with API aggregation.

**Tech Stack:** Python 3.14, FastAPI, uvicorn, DuckDB, pytest; Node 22, Express 5, vitest, supertest

**Worktree:** `.worktrees/chord-dbt-api/` on branch `feature/chord-dbt-api`

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — full design (filters, errors, route parity)
- `src/server/parse.ts` — legacy matrix + gap filler semantics
- `src/server/utils.ts` — `get_color(i, n)` HSL formula
- `src/server/envelope.ts` — `{ ok, value }` / `{ ok: false, error }`
- `analytics/transform/models/marts/mart_pathway_taxonomy_long.sql` — aggregation to share via macro

**Prerequisite fixture:** `analytics/transform/runs/test_rpkm_1/sample.duckdb` with `int_tax_rollup_resolved` (run `run_pipeline.py` once if missing).

---

## File Map

```
analytics/
├── pyproject.toml                          # MODIFY: add fastapi, uvicorn, httpx
├── api/
│   ├── __init__.py                         # CREATE
│   ├── colors.py                           # CREATE
│   ├── chord_matrix.py                     # CREATE
│   ├── filters.py                          # CREATE: normalise ann/taxon filters
│   ├── chord_service.py                    # CREATE: DuckDB query + orchestration
│   ├── envelope.py                         # CREATE
│   ├── schemas.py                          # CREATE
│   └── main.py                             # CREATE: POST /api/viz/chord
├── api/tests/
│   ├── test_colors.py                      # CREATE
│   ├── test_chord_matrix.py                # CREATE
│   ├── test_filters.py                     # CREATE
│   ├── test_chord_service.py               # CREATE (integration, skip if no duckdb)
│   └── test_main.py                        # CREATE: TestClient
└── transform/
    └── macros/
        └── mart_pathway_taxonomy_agg.sql   # CREATE
    └── models/marts/
        └── mart_pathway_taxonomy_long.sql  # MODIFY: use macro

src/server/
├── chord_handler.ts                        # CREATE
└── index.ts                                # MODIFY: wire chord_handler

src/tests/
└── chord_handler.test.ts                   # CREATE
```

---

### Task 1: Python dependencies and test layout

**Files:**
- Modify: `analytics/pyproject.toml`
- Create: `analytics/api/__init__.py`
- Create: `analytics/api/tests/__init__.py`

- [ ] **Step 1: Add dependencies to `analytics/pyproject.toml`**

Add to `[project] dependencies`:

```toml
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.28",
```

Add to `[tool.pytest.ini_options]`:

```toml
testpaths = ["exploration/scripts", "transform/tests/python", "api/tests"]
```

- [ ] **Step 2: Sync and verify**

```bash
cd analytics && uv sync
```

Expected: resolves without error.

- [ ] **Step 3: Create empty package init files**

```python
# analytics/api/__init__.py
# analytics/api/tests/__init__.py
# (empty files)
```

- [ ] **Step 4: Commit**

```bash
git add analytics/pyproject.toml analytics/uv.lock analytics/api/__init__.py analytics/api/tests/__init__.py
git commit -m "chore(analytics): add FastAPI deps and api test path"
```

---

### Task 2: Port `get_color` with unit tests

**Files:**
- Create: `analytics/api/colors.py`
- Create: `analytics/api/tests/test_colors.py`

- [ ] **Step 1: Write failing test**

```python
# analytics/api/tests/test_colors.py
from api.colors import get_color

def test_get_color_matches_node_formula():
    assert get_color(0, 3) == "hsl(0 75 50)"
    assert get_color(1, 3) == "hsl(90 75 50)"
    assert get_color(2, 3) == "hsl(180 75 50)"
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_colors.py -v
```

Expected: `ModuleNotFoundError: api.colors`

- [ ] **Step 3: Implement `analytics/api/colors.py`**

```python
BASE_LUM = 50

def get_color(i: int, n: int) -> str:
    hue = int((360 / (n + 1)) * i)
    return f"hsl({hue} 75 {BASE_LUM})"
```

- [ ] **Step 4: Run test — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_colors.py -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/colors.py analytics/api/tests/test_colors.py
git commit -m "feat(api): port get_color from Node utils"
```

---

### Task 3: `build_chord_matrix` with unit tests

**Files:**
- Create: `analytics/api/chord_matrix.py`
- Create: `analytics/api/tests/test_chord_matrix.py`

- [ ] **Step 1: Write failing tests**

```python
# analytics/api/tests/test_chord_matrix.py
from api.chord_matrix import build_chord_matrix

def test_build_chord_matrix_structure():
    pairs = [("PathA", "TaxA", 10.0), ("PathB", "TaxB", 5.0)]
    out = build_chord_matrix(pairs)
    assert out["index"][0] == "gap_1"
    assert out["index"][-1] == "gap_3"
    assert "gap_2" in out["index"]
    n = len(out["index"])
    assert len(out["count_matrix"]) == n
    assert all(len(row) == n for row in out["count_matrix"])

def test_build_chord_matrix_symmetric():
    pairs = [("PathA", "TaxA", 10.0)]
    out = build_chord_matrix(pairs)
    idx = out["index"]
    i_ann = idx.index("PathA")
    i_tax = idx.index("TaxA")
    assert out["count_matrix"][i_ann][i_tax] == 10.0
    assert out["count_matrix"][i_tax][i_ann] == 10.0

def test_build_chord_matrix_gap_fillers():
    pairs = [("PathA", "TaxA", 8.0)]
    out = build_chord_matrix(pairs)
    idx = out["index"]
    flat_sum = sum(sum(row) for row in out["count_matrix"])
    assert out["count_matrix"][idx.index("gap_1")][idx.index("gap_1")] == flat_sum / 4
    assert out["count_matrix"][idx.index("gap_2")][idx.index("gap_2")] == flat_sum / 2
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_chord_matrix.py -v
```

- [ ] **Step 3: Implement `analytics/api/chord_matrix.py`**

```python
from __future__ import annotations

from api.colors import get_color

GAPS = ("gap_1", "gap_2", "gap_3")


def build_chord_matrix(pairs: list[tuple[str, str, float]]) -> dict:
    ann_cats = sorted({ann for ann, _, _ in pairs})
    tax_cats = sorted({tax for _, tax, _ in pairs})
    index = ["gap_1", *ann_cats, "gap_2", *tax_cats, "gap_3"]
    n = len(index)
    pos = {name: i for i, name in enumerate(index)}
    matrix = [[0.0] * n for _ in range(n)]

    for ann, tax, val in pairs:
        if val <= 0:
            continue
        ai, ti = pos.get(ann), pos.get(tax)
        if ai is None or ti is None:
            continue
        matrix[ai][ti] += val
        matrix[ti][ai] += val

    flat_sum = sum(sum(row) for row in matrix)
    for gap_name, div in (("gap_1", 4), ("gap_2", 2), ("gap_3", 4)):
        i = pos[gap_name]
        matrix[i][i] = flat_sum / div

    colors = {
        **{c: get_color(i, len(ann_cats)) for i, c in enumerate(ann_cats)},
        **{c: get_color(i, len(tax_cats)) for i, c in enumerate(tax_cats)},
    }

    return {
        "count_matrix": matrix,
        "index": index,
        "colors": colors,
        "tax_map": {},
        "ann_map": {},
    }
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_chord_matrix.py -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/chord_matrix.py analytics/api/tests/test_chord_matrix.py
git commit -m "feat(api): build_chord_matrix from pathway×tax pairs"
```

---

### Task 4: Filter normalisation

**Files:**
- Create: `analytics/api/filters.py`
- Create: `analytics/api/tests/test_filters.py`

- [ ] **Step 1: Write failing tests**

```python
# analytics/api/tests/test_filters.py
from api.filters import normalise_ann_filter, normalise_taxon_filter, sample_id_from_names

def test_sample_id_strips_tsv():
    assert sample_id_from_names(["test_rpkm_1.tsv"]) == "test_rpkm_1"

def test_ann_filter_empty():
    assert normalise_ann_filter({}, "superpathway") is None
    assert normalise_ann_filter("", "superpathway") is None

def test_ann_filter_string_superpathway():
    f = normalise_ann_filter("Carbohydrate Metabolism", "superpathway")
    assert f == {"level": "superpathway", "name": "Carbohydrate Metabolism"}

def test_ann_filter_string_at_pathway_level():
    f = normalise_ann_filter("Carbohydrate Metabolism", "pathway")
    assert f == {"level": "superpathway", "name": "Carbohydrate Metabolism"}

def test_taxon_filter_empty():
    assert normalise_taxon_filter({}) is None
    assert normalise_taxon_filter({"level": "", "name": ""}) is None

def test_taxon_filter_set():
    f = normalise_taxon_filter({"level": "phylum", "name": "Bacillota"})
    assert f == {"level": "phylum", "name": "Bacillota"}
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_filters.py -v
```

- [ ] **Step 3: Implement `analytics/api/filters.py`**

```python
from __future__ import annotations

from typing import Any

VALID_TAX_RANKS = frozenset(
    {"kingdom", "phylum", "class", "order", "family", "genus", "species"}
)
VALID_ANN_LEVELS = frozenset({"superpathway", "pathway"})


def sample_id_from_names(names: list[str]) -> str:
    base = names[0]
    if base.endswith(".tsv"):
        return base[:-4]
    return base


def normalise_ann_filter(raw: Any, ann_level: str) -> dict[str, str] | None:
    if not raw:
        return None
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        level = "superpathway" if ann_level == "pathway" else ann_level
        return {"level": level, "name": name}
    if isinstance(raw, dict):
        level = str(raw.get("level") or "").strip()
        name = str(raw.get("name") or "").strip()
        if level and name:
            return {"level": level, "name": name}
    return None


def normalise_taxon_filter(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    level = str(raw.get("level") or "").strip()
    name = str(raw.get("name") or "").strip()
    if level and name:
        return {"level": level, "name": name}
    return None


def validate_tax_level(tax_level: str) -> None:
    if tax_level not in VALID_TAX_RANKS:
        raise ValueError(f"invalid tax_level: {tax_level}")


def validate_ann_level(ann_level: str) -> None:
    if ann_level not in VALID_ANN_LEVELS:
        raise ValueError(f"invalid ann_level: {ann_level}")
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_filters.py -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/filters.py analytics/api/tests/test_filters.py
git commit -m "feat(api): normalise chord request filters"
```

---

### Task 5: dbt macro + refactor mart

**Files:**
- Create: `analytics/transform/macros/mart_pathway_taxonomy_agg.sql`
- Modify: `analytics/transform/models/marts/mart_pathway_taxonomy_long.sql`

- [ ] **Step 1: Create macro**

```sql
{# analytics/transform/macros/mart_pathway_taxonomy_agg.sql #}
{% macro mart_pathway_taxonomy_agg(from_relation) %}
SELECT
    sample_id,
    pathway_level,
    pathway_key,
    ANY_VALUE(COALESCE(pathway_label, 'Unmapped EC'))   AS pathway_label,
    resolved_tax_id,
    ANY_VALUE(resolved_tax_label)                       AS resolved_tax_label,
    ANY_VALUE(resolved_tax_rank)                        AS resolved_tax_rank,
    SUM(value)                                          AS value
FROM {{ from_relation }}
GROUP BY sample_id, pathway_level, pathway_key, resolved_tax_id
{% endmacro %}
```

- [ ] **Step 2: Refactor mart to use macro**

Replace `analytics/transform/models/marts/mart_pathway_taxonomy_long.sql` body with:

```sql
WITH filtered AS (
    SELECT *
    FROM {{ ref('int_tax_rollup_resolved') }}
    WHERE pathway_level  = '{{ var("pathway_level") }}'
      AND requested_rank = '{{ var("tax_rank") }}'
)
{{ mart_pathway_taxonomy_agg('filtered') }}
```

- [ ] **Step 3: Verify dbt compiles** (requires existing sample.duckdb or parse-only)

```bash
cd analytics
DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt parse --project-dir transform --profiles-dir transform
```

Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add analytics/transform/macros/mart_pathway_taxonomy_agg.sql \
        analytics/transform/models/marts/mart_pathway_taxonomy_long.sql
git commit -m "refactor(dbt): extract mart_pathway_taxonomy_agg macro"
```

---

### Task 6: DuckDB query service

**Files:**
- Create: `analytics/api/chord_service.py`
- Create: `analytics/api/tests/test_chord_service.py`

- [ ] **Step 1: Write integration test (skip if fixture missing)**

```python
# analytics/api/tests/test_chord_service.py
from pathlib import Path
import pytest

from api.chord_service import build_chord_from_duckdb, TRANSFORM_DIR

FIXTURE_DB = TRANSFORM_DIR / "runs/test_rpkm_1/sample.duckdb"
pytestmark = pytest.mark.skipif(
    not FIXTURE_DB.exists(), reason="run_pipeline.py fixture not built"
)


def test_build_chord_from_duckdb_shape():
    out = build_chord_from_duckdb(
        sample_id="test_rpkm_1",
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
    )
    assert "count_matrix" in out
    assert out["index"][0] == "gap_1"
    assert len(out["count_matrix"]) == len(out["index"])

def test_build_chord_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_chord_from_duckdb(
            sample_id="test_rpkm_1",
            tax_level="phylum",
            ann_level="superpathway",
            ann_filter=None,
            taxon_filter=None,
            names=["a.tsv", "b.tsv"],
        )
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_chord_service.py -v
```

- [ ] **Step 3: Implement `analytics/api/chord_service.py`**

```python
from __future__ import annotations

from pathlib import Path

import duckdb

from api.chord_matrix import build_chord_matrix
from api.filters import validate_ann_level, validate_tax_level

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _ann_predicate(ann_filter: dict[str, str] | None, ann_level: str) -> tuple[str, list]:
    if ann_filter is None:
        return "TRUE", []
    level, name = ann_filter["level"], ann_filter["name"]
    if ann_level == "superpathway":
        return "COALESCE(t.pathway_label, 'Unmapped EC') = ?", [name]
    if level == "pathway":
        return (
            "t.pathway_key IN ("
            "  SELECT CAST(pathway_id AS VARCHAR) FROM bridge_ec "
            "  WHERE pathway_name = ?"
            ")", [name],
        )
    return (
        "t.pathway_key IN ("
        "  SELECT CAST(pathway_id AS VARCHAR) FROM bridge_ec "
        "  WHERE superpathway_name = ?"
        ")", [name],
    )


def build_chord_from_duckdb(
    *,
    sample_id: str,
    tax_level: str,
    ann_level: str,
    ann_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
    names: list[str] | None = None,
) -> dict:
    if names and len(names) > 1:
        raise ValueError("comparison mode not supported on duckdb backend")

    validate_tax_level(tax_level)
    validate_ann_level(ann_level)

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

        if BRIDGE_EC_PATH.exists():
            conn.execute(
                f"CREATE TEMP TABLE bridge_ec AS "
                f"SELECT * FROM read_parquet('{BRIDGE_EC_PATH.as_posix()}')"
            )

        tax_subquery = "TRUE"
        params: list = [tax_level, ann_level]
        if taxon_filter:
            tax_subquery = (
                "t.source_tax_id IN ("
                "  SELECT DISTINCT source_tax_id FROM int_tax_rollup_resolved"
                "  WHERE requested_rank = ? AND resolved_tax_label = ?"
                ")"
            )
            params.extend([taxon_filter["level"], taxon_filter["name"]])

        ann_sql, ann_params = _ann_predicate(ann_filter, ann_level)

        sql = f"""
            SELECT
                COALESCE(t.pathway_label, 'Unmapped EC') AS pathway_label,
                t.resolved_tax_label AS resolved_tax_label,
                SUM(t.value) AS value
            FROM int_tax_rollup_resolved t
            WHERE t.requested_rank = ?
              AND t.pathway_level = ?
              AND ({tax_subquery})
              AND ({ann_sql})
            GROUP BY t.pathway_key, t.resolved_tax_id,
                     COALESCE(t.pathway_label, 'Unmapped EC'),
                     t.resolved_tax_label
            HAVING SUM(t.value) > 0
        """
        rows = conn.execute(sql, params + ann_params).fetchall()
    finally:
        conn.close()

    pairs = [(r[0], r[1], float(r[2])) for r in rows]
    return build_chord_matrix(pairs)
```

- [ ] **Step 4: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_chord_service.py -v
```

Expected: PASS if fixture exists; SKIP otherwise.

- [ ] **Step 5: Commit**

```bash
git add analytics/api/chord_service.py analytics/api/tests/test_chord_service.py
git commit -m "feat(api): query int_tax_rollup_resolved for chord pairs"
```

---

### Task 7: FastAPI app with route parity

**Files:**
- Create: `analytics/api/envelope.py`
- Create: `analytics/api/schemas.py`
- Create: `analytics/api/main.py`
- Create: `analytics/api/tests/test_main.py`

- [ ] **Step 1: Write envelope + schemas**

```python
# analytics/api/envelope.py
from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")

def wrap_handler(fn: Callable[..., T], *args, **kwargs) -> dict:
    try:
        return {"ok": True, "value": fn(*args, **kwargs)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
```

```python
# analytics/api/schemas.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChordRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_level: str
    ann_level: str
    selected_ann_cat: Any = Field(default_factory=dict)
    selected_taxon: Any = Field(default_factory=dict)
```

- [ ] **Step 2: Write failing TestClient test**

```python
# analytics/api/tests/test_main.py
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.chord_service import TRANSFORM_DIR

client = TestClient(app)
FIXTURE_DB = TRANSFORM_DIR / "runs/test_rpkm_1/sample.duckdb"


@pytest.mark.skipif(not FIXTURE_DB.exists(), reason="fixture not built")
def test_chord_endpoint_envelope():
    res = client.post(
        "/api/viz/chord",
        json={
            "names": ["test_rpkm_1.tsv"],
            "tax_level": "phylum",
            "ann_level": "superpathway",
            "selected_ann_cat": {},
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "count_matrix" in body["value"]


def test_chord_comparison_error_envelope():
    res = client.post(
        "/api/viz/chord",
        json={
            "names": ["a.tsv", "b.tsv"],
            "tax_level": "phylum",
            "ann_level": "superpathway",
            "selected_ann_cat": {},
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "comparison mode" in body["error"]
```

- [ ] **Step 3: Implement `analytics/api/main.py`**

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chord_service import build_chord_from_duckdb
from api.envelope import wrap_handler
from api.filters import (
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
)
from api.schemas import ChordRequest

app = FastAPI(title="Metapro Viz API (Python)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/viz/chord")
def chord_endpoint(body: ChordRequest):
    def _handle():
        if len(body.names) == 0:
            raise ValueError("names must contain at least one sample")
        if len(body.names) > 1:
            raise ValueError("comparison mode not supported on duckdb backend")
        sample_id = sample_id_from_names(body.names)
        ann_filter = normalise_ann_filter(body.selected_ann_cat, body.ann_level)
        taxon_filter = normalise_taxon_filter(body.selected_taxon)
        return build_chord_from_duckdb(
            sample_id=sample_id,
            tax_level=body.tax_level,
            ann_level=body.ann_level,
            ann_filter=ann_filter,
            taxon_filter=taxon_filter,
            names=body.names,
        )

    return wrap_handler(_handle)
```

- [ ] **Step 4: Run tests**

```bash
cd analytics && uv run pytest api/tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/envelope.py analytics/api/schemas.py analytics/api/main.py \
        analytics/api/tests/test_main.py
git commit -m "feat(api): FastAPI POST /api/viz/chord with envelope parity"
```

---

### Task 8: Express proxy handler

**Files:**
- Create: `src/server/chord_handler.ts`
- Modify: `src/server/index.ts`
- Create: `src/tests/chord_handler.test.ts`

- [ ] **Step 1: Write failing proxy test**

```typescript
// src/tests/chord_handler.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createChordHandler } from '../server/chord_handler'

describe('createChordHandler', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('uses legacy handler when backend query param absent', async () => {
    const legacy = vi.fn().mockReturnValue({ count_matrix: [] })
    const handler = createChordHandler({ legacyHandler: legacy })
    const req = { query: {}, body: { names: ['x.tsv'] } } as any
    const out = await handler(req)
    expect(legacy).toHaveBeenCalledWith(req.body)
    expect(out).toEqual({ ok: true, value: { count_matrix: [] } })
  })
})
```

- [ ] **Step 2: Implement `src/server/chord_handler.ts`**

```typescript
import { wrapHandler } from './envelope'
import type { ApiEnvelope } from './envelope'

const CHORD_API_URL = process.env.CHORD_API_URL ?? 'http://localhost:8001'

type ChordBody = Record<string, unknown>

export const createChordHandler = (deps: {
  legacyHandler: (params?: unknown) => unknown
  fetchFn?: typeof fetch
}) => {
  const fetchImpl = deps.fetchFn ?? fetch

  return async (req: { query: Record<string, string | undefined>; body: ChordBody }): Promise<ApiEnvelope> => {
    if (req.query.backend !== 'duckdb') {
      return wrapHandler(deps.legacyHandler)(req.body)
    }

    try {
      const url = `${CHORD_API_URL}/api/viz/chord`
      const res = await fetchImpl(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body)
      })
      const envelope = (await res.json()) as ApiEnvelope
      return envelope
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err)
      return { ok: false, error: `chord duckdb backend unavailable: ${error}` }
    }
  }
}
```

- [ ] **Step 3: Wire in `src/server/index.ts`**

Replace direct `parse_ec_chord` on chord route:

```typescript
import { createChordHandler } from './chord_handler'

// inside createApp(), replace chord in vizRoutes loop with dedicated handler:
const chordHandler = createChordHandler({ legacyHandler: parse_ec_chord })

app.post('/api/viz/chord', async (req, res) => {
  const envelope = await chordHandler({ query: req.query as Record<string, string | undefined>, body: req.body })
  res.status(200).json(envelope)
})
```

Remove `{ path: '/api/viz/chord', handler: parse_ec_chord }` from `vizRoutes` array.

- [ ] **Step 4: Run tests**

```bash
npm test -- src/tests/chord_handler.test.ts
npm run typecheck:server
```

- [ ] **Step 5: Commit**

```bash
git add src/server/chord_handler.ts src/server/index.ts src/tests/chord_handler.test.ts
git commit -m "feat(server): proxy /api/viz/chord?backend=duckdb to FastAPI"
```

---

### Task 9: Dev scripts and README snippet

**Files:**
- Modify: `package.json`
- Modify: `analytics/transform/README.md` (short chord API section)

- [ ] **Step 1: Add npm script**

In `package.json` `"scripts"`:

```json
"dev:chord-api": "cd analytics && uv run uvicorn api.main:app --port 8001 --reload"
```

Update `"dev"` to optionally document running chord-api in a third terminal (comment in README only — do not change concurrent dev unless desired).

- [ ] **Step 2: Append to `analytics/transform/README.md`**

```markdown
## Chord API (FastAPI sidecar)

Requires `runs/{sample_id}/sample.duckdb` with `int_tax_rollup_resolved`.

```bash
# Terminal A
cd analytics && uv run uvicorn api.main:app --port 8001

# Terminal B — Express proxy
curl -X POST 'http://localhost:3001/api/viz/chord?backend=duckdb' ...
```
```

- [ ] **Step 3: Final verification**

```bash
cd analytics && uv run pytest api/tests/ -v
npm test
npm run typecheck
```

- [ ] **Step 4: Commit**

```bash
git add package.json analytics/transform/README.md
git commit -m "docs: chord FastAPI sidecar dev workflow"
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| FastAPI `POST /api/viz/chord` route parity | Task 7 |
| `{ ok, value }` envelope, HTTP 200 | Task 7, 8 |
| Query `int_tax_rollup_resolved` at runtime | Task 6 |
| All params as pre-aggregation filters | Task 4, 6 |
| Mart macro shared with dbt | Task 5 |
| `build_chord_matrix()` Python port | Task 3 |
| Express proxy `?backend=duckdb` | Task 8 |
| Legacy default unchanged | Task 8 |
| Single-sample only / comparison error | Task 6, 7 |
| strip-extension sample_id | Task 4 |
| No run_context.json | (no task — intentionally omitted) |
| `ann_map` `{}` in v1 | Task 3 |

---

## Manual Smoke Test (after all tasks)

```bash
# Build fixture if needed
cd analytics && uv run python transform/scripts/run_pipeline.py \
  --sample-id test_rpkm_1 \
  --rpkm-path ../resources/example_data/test_rpkm_1.tsv \
  --tax-rank phylum --pathway-level superpathway

# Start sidecar + API
cd analytics && uv run uvicorn api.main:app --port 8001 &
npm run dev:api &

curl -s -X POST 'http://localhost:8001/api/viz/chord' \
  -H 'Content-Type: application/json' \
  -d '{"names":["test_rpkm_1.tsv"],"tax_level":"genus","ann_level":"superpathway","selected_ann_cat":{},"selected_taxon":{}}' \
  | python -m json.tool | head -20
```

Expected: `"ok": true`, `"index"` starts with `"gap_1"`, `tax_level=genus` works without dbt rebuild.
