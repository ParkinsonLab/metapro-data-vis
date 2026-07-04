# Graph API via dbt Intermediates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI `POST /api/viz/graph` backed by `int_rpkm_by_ec_tax` (triples + separate metadata queries), standalone `graph_service` / `graph_matrix`, Express sidecar proxy, renderer toggle — preserving the graph blob JSON contract.

**Architecture:** Triples query reads `int_rpkm_by_ec_tax` with `EXISTS` filters only (no bridge joins). Separate metadata queries on distinct triple keys join bridges for pathway/lineage sort keys, `ec_map`, and `tax_map`. `graph_matrix.py` assembles inner/outer indices with hierarchical alphabetical ordering and fills the symmetric matrix by keyed lookup. Express defaults to legacy; renderer appends `?backend=duckdb` for migrated channels.

**Tech Stack:** Python 3.14, FastAPI, DuckDB, pytest; Node 22, Express 5, vitest, React/Plotly

**Spec:** `docs/superpowers/specs/2026-07-04-graph-dbt-api-design.md`

**Branch / worktree:** `feature/graph-dbt-api` → `.worktrees/feature/graph-dbt-api/`

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-07-04-graph-dbt-api-design.md` — approved design (§5 query split, §6 ordering)
- `src/server/parse.ts` — `make_inner_count_matrix`, `add_filler_value` (matrix + gaps; no zero-row trim on DuckDB path)
- `src/server/utils.ts` — `get_color`, `get_sub_color`, `map_lum`
- `analytics/api/krona_service.py` — `int_rpkm_by_ec_tax` query, bridge_tax PIVOT pattern, `NAMES_PATH`
- `analytics/api/chord_service.py` — `_db_path`, DuckDB connect, `BRIDGE_EC_PATH` / `BRIDGE_TAX_PATH` constants
- `analytics/api/rollup_query.py` — `_ann_predicate` / filter SQL patterns (copy into `graph_service`, do **not** import `build_filtered_rollup_rows`)
- `analytics/api/envelope.py`, `analytics/api/filters.py`
- `src/server/index.ts`, `src/server/fastapi_sidecar_proxy.ts`
- `src/renderer/src/vizBackend.ts`, `src/renderer/src/api.ts`

**Prerequisites:**

```bash
cd analytics
uv run python transform/scripts/build_reference.py
uv run python transform/scripts/run_pipeline.py \
  --sample-id fake_rpkm \
  --rpkm-path transform/tests/fixtures/fake_rpkm.tsv \
  --tax-rank phylum \
  --pathway-level superpathway
```

---

## File Map

```
analytics/api/
├── colors.py                         # MODIFY: add map_lum, get_sub_color
├── graph_ordering.py                 # CREATE: tuple sort, category prefix helpers
├── graph_matrix.py                   # CREATE: build_graph_matrix()
├── graph_service.py                  # CREATE: triples + metadata queries
├── schemas.py                        # MODIFY: GraphRequest
├── main.py                           # MODIFY: POST /api/viz/graph
└── tests/
    ├── test_graph_ordering.py        # CREATE
    ├── test_graph_matrix.py          # CREATE
    ├── test_graph_service.py         # CREATE
    └── test_main.py                  # MODIFY: graph endpoint smoke

src/server/
└── index.ts                          # MODIFY: graph → sidecarRoutes

src/renderer/src/
├── vizBackend.ts                     # MODIFY: add 'graph' to MIGRATED_CHANNELS
└── api.ts                            # MODIFY: sidecarQuery('graph')

src/tests/
└── fastapi_sidecar_proxy.test.ts     # MODIFY: graph label case (optional if generic)
```

---

### Task 1: `get_sub_color` in `colors.py`

**Files:**
- Modify: `analytics/api/colors.py`
- Create: `analytics/api/tests/test_colors_graph.py`

- [ ] **Step 1: Write failing tests**

```python
from api.colors import get_color, get_sub_color, map_lum


def test_map_lum_deterministic():
    assert map_lum("abc") == map_lum("abc")
    assert 20 <= map_lum("x") <= 100


def test_get_sub_color_changes_luminance():
    base = get_color(0, 3)
    sub = get_sub_color(base, "1.1.1.1")
    assert sub.startswith("hsl(")
    assert sub != base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd analytics && uv run pytest api/tests/test_colors_graph.py -v`  
Expected: FAIL (`map_lum` not defined)

- [ ] **Step 3: Implement**

```python
BASE_LUM = 50


def map_lum(string: str) -> int:
    hash_val = 0
    for char in string:
        hash_val = (hash_val << 5) - hash_val + ord(char)
        hash_val |= 0
    return abs(int(hash_val % 80)) + 20


def get_sub_color(c: str, label: str) -> str:
    return c.replace(f" {BASE_LUM})", f" {map_lum(label)})")
```

- [ ] **Step 4: Run test — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/colors.py analytics/api/tests/test_colors_graph.py
git commit -m "feat(analytics): add get_sub_color for graph matrix colors"
```

---

### Task 2: Ordering helpers (`graph_ordering.py`)

**Files:**
- Create: `analytics/api/graph_ordering.py`
- Create: `analytics/api/tests/test_graph_ordering.py`

- [ ] **Step 1: Write failing tests**

```python
from api.graph_ordering import (
    TAX_RANKS,
    compare_tuples,
    pathway_sort_key,
    lineage_sort_key,
    ann_category_depth,
    truncate_pathway_tuple,
    truncate_lineage_tuple,
)


def test_compare_tuples_lexicographic():
    assert compare_tuples(("A", "B"), ("A", "C")) < 0
    assert compare_tuples(("A",), ("B",)) < 0


def test_pathway_sort_key_always_three_segments():
    row = {"superpathway_name": "SpA", "pathway_name": "Pw1", "ec_normalized": "1.1.1.1"}
    assert pathway_sort_key(row) == ("SpA", "Pw1", "1.1.1.1")


def test_ann_category_depth():
    assert ann_category_depth("superpathway") == 1
    assert ann_category_depth("pathway") == 2
    assert ann_category_depth("pathway_node") == 2


def test_truncate_lineage_at_phylum():
    row = {
        "kingdom": "Bacteria",
        "phylum": "Bacillota",
        "class": "Bacilli",
        "order": "o",
        "family": "f",
        "genus": "g",
        "species": "s",
        "display_name": "Bacillus subtilis",
    }
    assert truncate_lineage_tuple(row, "phylum") == (
        "Bacteria", "Bacillota"
    )
```

- [ ] **Step 2: Run — FAIL**

Run: `cd analytics && uv run pytest api/tests/test_graph_ordering.py -v`

- [ ] **Step 3: Implement `graph_ordering.py`**

```python
from __future__ import annotations

TAX_RANKS = (
    "kingdom", "phylum", "class", "order", "family", "genus", "species"
)


def compare_tuples(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    for x, y in zip(a, b):
        if x < y:
            return -1
        if x > y:
            return 1
    if len(a) < len(b):
        return -1
    if len(a) > len(b):
        return 1
    return 0


def pathway_sort_key(row: dict) -> tuple[str, str, str]:
    return (
        row["superpathway_name"],
        row["pathway_name"],
        row["ec_normalized"],
    )


def lineage_sort_key(row: dict) -> tuple[str, ...]:
    return tuple(row.get(r) or "" for r in TAX_RANKS) + (row["display_name"],)


def ann_category_depth(ann_level: str) -> int:
    if ann_level == "superpathway":
        return 1
    return 2


def truncate_pathway_tuple(key: tuple[str, str, str], depth: int) -> tuple[str, ...]:
    if depth == 1:
        return (key[0],)
    return (key[0], key[1])


def truncate_lineage_tuple(row: dict, tax_level: str) -> tuple[str, ...]:
    idx = TAX_RANKS.index(tax_level) + 1
    return lineage_sort_key(row)[:idx]
```

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/graph_ordering.py analytics/api/tests/test_graph_ordering.py
git commit -m "feat(analytics): add graph hierarchical ordering helpers"
```

---

### Task 3: Matrix builder (`graph_matrix.py`)

**Files:**
- Create: `analytics/api/graph_matrix.py`
- Create: `analytics/api/tests/test_graph_matrix.py`

- [ ] **Step 1: Write failing tests**

```python
from api.graph_matrix import build_graph_matrix


def test_build_graph_matrix_shape_and_gaps():
    triples = [("1.1.1.1", "TaxA", 10.0), ("1.1.1.2", "TaxB", 5.0)]
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
        {"ec_normalized": "1.1.1.2", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
    ]
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
        {"display_name": "TaxB", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
    ]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    assert out["inner_matrix_index"][0] == "gap_1"
    assert "gap_2" in out["inner_matrix_index"]
    assert out["inner_matrix_index"][-1] == "gap_3"
    assert len(out["inner_count_matrix"]) == len(out["inner_matrix_index"])
    assert out["tax_map"]["TaxA"] == "PhA"
    assert "1.1.1.1" in out["colors"]
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `build_graph_matrix`**

Port gap fillers from `parse.ts` `add_filler_value`. Sort EC rows by `pathway_sort_key`, tax rows by `lineage_sort_key`. Build `inner_matrix_index = ['gap_1', *ecs, 'gap_2', *tax_labels, 'gap_3']`. Fill matrix by keyed lookup on triples (symmetric). Build `outer_matrix_index` from sorted ann/tax categories (prefix truncation per §6.2). Assign colors via `get_color` / `get_sub_color`. **No zero-row trim.**

Key function signature:

```python
def build_graph_matrix(
    *,
    triples: list[tuple[str, str, float]],  # (ec_normalized, display_name, value)
    ec_rows: list[dict],
    tax_rows: list[dict],
    ann_level: str,
    tax_level: str,
) -> dict:
    ...
```

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/graph_matrix.py analytics/api/tests/test_graph_matrix.py
git commit -m "feat(analytics): add graph_matrix builder"
```

---

### Task 4: Graph service — triples + metadata queries

**Files:**
- Create: `analytics/api/graph_service.py`
- Create: `analytics/api/tests/test_graph_service.py`

- [ ] **Step 1: Write failing integration tests**

```python
import pytest
from api.graph_service import build_graph_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_graph_from_duckdb_shape(fake_rpkm_db):
    out = build_graph_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        ann_level="superpathway",
        selected_ann_cat={},
        selected_taxon={},
    )
    assert "inner_count_matrix" in out
    assert out["inner_matrix_index"][0] == "gap_1"
    assert len(out["inner_count_matrix"]) == len(out["inner_matrix_index"])
    assert out["tax_map"]


def test_build_graph_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_graph_from_duckdb(
            names=["a.tsv", "b.tsv"],
            tax_level="phylum",
            ann_level="superpathway",
            selected_ann_cat={},
            selected_taxon={},
        )
```

Add test asserting triples row count equals `len({(ec, tax_id) for ...})` — no fan-out from joins.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `graph_service.py`**

Structure:

```python
def _fetch_triples(conn, *, ann_filter, taxon_filter, ann_level) -> list[tuple[str, int, float]]:
    # EXISTS filters only — §5.1

def _fetch_ec_metadata(conn, triples, *, ann_level) -> list[dict]:
    # DISTINCT ec keys → bridge_ec_pathway; dedupe pathway tuple per EC

def _fetch_tax_metadata(conn, triples, *, tax_level) -> list[dict]:
    # DISTINCT source_tax_id → PIVOT (krona pattern) + names
    # tax_map_value = w.<tax_level>

def build_graph_from_duckdb(...) -> dict:
    # validate, connect, check int_rpkm_by_ec_tax
    # triples → metadata → build_graph_matrix
    # map triples to (ec, display_name, value) for matrix
```

Copy ann/taxon EXISTS predicate logic from `rollup_query._ann_predicate` into private helpers in this file (standalone per spec).

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/graph_service.py analytics/api/tests/test_graph_service.py
git commit -m "feat(analytics): add graph_service with split triples/metadata queries"
```

---

### Task 5: FastAPI endpoint

**Files:**
- Modify: `analytics/api/schemas.py`
- Modify: `analytics/api/main.py`
- Modify: `analytics/api/tests/test_main.py`

- [ ] **Step 1: Add `GraphRequest` (= `ChordRequest` fields)**

```python
class GraphRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_level: str
    ann_level: str
    selected_ann_cat: Any = Field(default_factory=dict)
    selected_taxon: Any = Field(default_factory=dict)
```

- [ ] **Step 2: Add endpoint**

```python
from api.graph_service import build_graph_from_duckdb
from api.schemas import GraphRequest

@app.post("/api/viz/graph")
def graph_endpoint(body: GraphRequest):
    def _handle():
        if len(body.names) == 0:
            raise ValueError("names must contain at least one sample")
        return build_graph_from_duckdb(
            names=body.names,
            tax_level=body.tax_level,
            ann_level=body.ann_level,
            selected_ann_cat=body.selected_ann_cat,
            selected_taxon=body.selected_taxon,
        )
    return wrap_handler(_handle)
```

- [ ] **Step 3: Add smoke test in `test_main.py`**

- [ ] **Step 4: Run `cd analytics && uv run pytest api/tests/ -v` — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/schemas.py analytics/api/main.py analytics/api/tests/test_main.py
git commit -m "feat(analytics): expose POST /api/viz/graph"
```

---

### Task 6: Express sidecar + renderer wiring

**Files:**
- Modify: `src/server/index.ts`
- Modify: `src/renderer/src/vizBackend.ts`
- Modify: `src/renderer/src/api.ts`
- Modify: `src/tests/fastapi_sidecar_proxy.test.ts` (graph label case)

- [ ] **Step 1: Move graph to `sidecarRoutes` in `index.ts`**

Remove from `vizRoutes`; add:

```typescript
{ path: '/api/viz/graph', label: 'graph', legacyHandler: parse_graph },
```

- [ ] **Step 2: Add `'graph'` to `MIGRATED_CHANNELS` in `vizBackend.ts`**

- [ ] **Step 3: Update `api.ts`**

```typescript
graph: { method: 'POST', url: `/api/viz/graph${sidecarQuery('graph')}` },
```

- [ ] **Step 4: Run `npm test` — PASS**

- [ ] **Step 5: Commit**

```bash
git add src/server/index.ts src/renderer/src/vizBackend.ts src/renderer/src/api.ts src/tests/fastapi_sidecar_proxy.test.ts
git commit -m "feat(graph): wire graph endpoint to analytics sidecar"
```

---

### Task 7: Manual verification

- [ ] **Step 1: Start stack**

```bash
# terminal 1: analytics API
cd analytics && uv run uvicorn api.main:app --port 8001

# terminal 2: express + vite
npm run dev
```

- [ ] **Step 2: Load `fake_rpkm` test data; open Graph tab with sidecar backend**

- [ ] **Step 3: Select ECs in Network; confirm 3D plot renders**

- [ ] **Step 4: Toggle `localStorage.vizBackend = 'legacy'`; confirm legacy path still works**

---

## Spec Coverage Checklist

| Spec section | Task |
|---|---|
| §5.1 triples, EXISTS only | Task 4 |
| §5.2 metadata queries | Task 4 |
| §5.3–§5.4 ec_map / tax_map | Tasks 3–4 |
| §5.5 / §6 ordering | Tasks 2–3 |
| §7 matrix builder, no trim | Task 3 |
| §8 sidecar wiring | Task 6 |
| §9 testing | Tasks 1–6 |
| §10 errors | Task 4–5 |
| §12 acceptance | Task 7 |

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-07-04-graph-dbt-api.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — execute tasks in this session with checkpoints

Which approach do you prefer?
