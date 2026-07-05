# Graph API via dbt Intermediates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI `POST /api/viz/graph` backed by `int_rpkm_by_ec_tax` (triples + separate metadata queries), standalone `graph_service` / `graph_matrix`, Express sidecar proxy, renderer toggle — preserving the graph blob JSON contract.

**Architecture:** Triples query reads `int_rpkm_by_ec_tax` with `EXISTS` filters only (no bridge joins), materialised as `filtered_triples`. EC metadata = distinct EC keys with numeric sort; tax metadata = lineage PIVOT + `tax_map`. `graph_matrix.py` builds tax-only outer index, per-EC colors without pathway categories, and fills the symmetric matrix by keyed lookup (no Python sort). Express defaults to legacy; renderer appends `?backend=duckdb` for migrated channels.

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
├── graph_matrix.py                   # CREATE: build_graph_matrix() — pre-ordered rows in, no sort
├── graph_service.py                  # CREATE: filtered_triples + SQL-ordered metadata queries
├── schemas.py                        # MODIFY: GraphRequest
├── main.py                           # MODIFY: POST /api/viz/graph
└── tests/
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

### Task 2: Matrix builder (`graph_matrix.py`)

**Files:**
- Create: `analytics/api/graph_matrix.py`
- Create: `analytics/api/tests/test_graph_matrix.py`

- [ ] **Step 1: Write failing tests**

(Same test fixtures as originally planned — `ec_rows` include `ann_category` and are pre-ordered as returned by `graph_service`.)

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `build_graph_matrix`**

Port gap fillers from `parse.ts` `add_filler_value`. **Do not sort in Python** — trust SQL-ordered `ec_rows` / `tax_rows` from `graph_service`. Build `inner_matrix_index = ['gap_1', *ecs, 'gap_2', *tax_labels, 'gap_3']`. Build `outer_matrix_index` via first-seen dedupe of `ann_category` and `tax_map_value`. Fill matrix by keyed lookup on triples (symmetric). Assign colors via `get_color` / `get_sub_color`. **No zero-row trim.**

Key function signature:

```python
def build_graph_matrix(
    *,
    triples: list[tuple[str, str, float]],  # (ec_normalized, display_name, value)
    ec_rows: list[dict],  # SQL-ordered; each row includes ann_category
    tax_rows: list[dict],  # SQL-ordered
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

### Task 3: Graph service — triples + metadata queries

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
def _materialize_filtered_triples(conn, *, ann_filter, taxon_filter, ann_level) -> None:
    # filtered_triples temp table — §5.1; bridge_ec_long for ann EXISTS

def _fetch_ec_metadata(conn, *, ann_level) -> list[dict]:
    # DISTINCT ec keys from filtered_triples → bridge_ec_dedup
    # ORDER BY superpathway_name, pathway_name, ec_normalized
    # attach ann_category per ann_level

def _materialize_tax_metadata(conn, *, tax_level) -> None:
    # graph_tax_metadata temp table — PIVOT (krona pattern) + names
    # ORDER BY full lineage tuple

def _fetch_labeled_triples(conn) -> list[tuple[str, str, float]]:
    # filtered_triples INNER JOIN graph_tax_metadata

def build_graph_from_duckdb(...) -> dict:
    # validate, connect, check int_rpkm_by_ec_tax
    # filtered_triples → ec metadata → tax metadata → build_graph_matrix
```

Copy ann/taxon EXISTS predicate logic from `rollup_query._ann_predicate` into private helpers in this file (standalone per spec).

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/graph_service.py analytics/api/tests/test_graph_service.py
git commit -m "feat(analytics): add graph_service with split triples/metadata queries"
```

---

### Task 4: FastAPI endpoint

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

### Task 5: Express sidecar + renderer wiring

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

### Task 6: Manual verification

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
| §5.1 triples, EXISTS only, `filtered_triples` | Task 3 |
| §5.2 SQL-ordered metadata queries | Task 3 |
| §5.3–§5.4 ec_map / tax_map | Tasks 2–3 |
| §5.5 / §6 ordering (SQL leaves + dedupe categories) | Tasks 2–3 |
| §7 matrix builder, no trim | Task 2 |
| §8 sidecar wiring | Task 5 |
| §9 testing | Tasks 1–5 |
| §10 errors | Tasks 3–4 |
| §12 acceptance | Task 6 |

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-07-04-graph-dbt-api.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — execute tasks in this session with checkpoints

Which approach do you prefer?
