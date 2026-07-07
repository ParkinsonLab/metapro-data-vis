# Network API via dbt Intermediates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI `POST /api/viz/network` returning `{ nodes, edges, colors }` — static pathway graph from reference Parquet plus per-EC tax pies from `int_rpkm_by_ec_tax` — with Express sidecar proxy and renderer toggle.

**Architecture:** `network_service.py` loads pathway topology from `resources/db/parquet` (same source as `build_reference.py`), materialises `filtered_triples` with `EXISTS` filters only, joins tax metadata for `GROUP BY ec_normalized, tax_map_value`, then `network_assembly.py` applies layout transform, attaches pies by `node.label`, embeds edge node objects, and assigns lineage-ordered category colors. Express defaults to legacy `parse_network`.

**Tech Stack:** Python 3.14, FastAPI, DuckDB, pytest; Node 22, Express 5, vitest, React/d3

**Spec:** `docs/superpowers/specs/2026-07-05-network-dbt-api-design.md`

**Branch / worktree:** `feature/network-dbt-api` → `.worktrees/feature/network-dbt-api/`

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-07-05-network-dbt-api-design.md` — approved design (§4.4 duplicate EC labels, §5 query rules)
- `src/server/data_functions.ts` — `parse_network` (layout formula, pie attachment)
- `analytics/api/graph_service.py` — `_materialize_filtered_triples`, `_materialize_tax_metadata`, `_taxon_exists_clause`
- `analytics/api/graph_matrix.py` — `_dedupe_preserve_order`, category `get_color` pattern
- `analytics/transform/scripts/build_reference.py` — `RAW_PARQUET_DIR`, pathway table names
- `analytics/api/envelope.py`, `analytics/api/filters.py`, `analytics/api/colors.py`
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
├── network_assembly.py               # CREATE: layout, pies, edges, colors (pure, no SQL)
├── network_service.py                # CREATE: static graph + triples + orchestration
├── schemas.py                        # MODIFY: NetworkRequest
├── main.py                           # MODIFY: POST /api/viz/network
└── tests/
    ├── test_network_assembly.py      # CREATE
    ├── test_network_service.py       # CREATE
    ├── test_main.py                  # MODIFY: network endpoint smoke
    └── fixtures/
        └── network_expectations.yaml # CREATE (via dump script)

analytics/testing/
├── fake_rpkm_fixture.py              # MODIFY: NETWORK_YAML, load/extract helpers
└── dump_fake_rpkm_expectations.py    # MODIFY: --network flag

src/server/
└── index.ts                          # MODIFY: network → sidecarRoutes

src/renderer/src/
├── vizBackend.ts                     # MODIFY: add 'network' to MIGRATED_CHANNELS
└── api.ts                            # MODIFY: sidecarQuery('network')
```

**Pathway Parquet note:** Topology files live in `resources/db/parquet/` (`pathway_nodes`, `pathway_edges`, `pathway_superpathways`) — same as `build_reference.py` `RAW_PARQUET_DIR`. Only bridge files are copied to `analytics/transform/reference/parquet/`.

---

### Task 1: Pure assembly helpers (`network_assembly.py`)

**Files:**
- Create: `analytics/api/network_assembly.py`
- Create: `analytics/api/tests/test_network_assembly.py`

- [ ] **Step 1: Write failing tests**

```python
from api.network_assembly import (
    apply_layout,
    attach_pies_to_nodes,
    build_category_colors,
    dedupe_preserve_order,
    embed_edges,
)


def test_apply_layout_swaps_and_scales():
    nodes = [{"id": "n1", "label": "1.1.1.1", "type": "rectangle", "x": 1000, "y": 1100}]
    out = apply_layout(nodes, width=900, height=550)
    assert out[0]["x"] == (1100 / 1100) * 900 - 900 / 2 + 100
    assert out[0]["y"] == (1000 / 1000) * 550 - 550 / 2


def test_dedupe_preserve_order():
    assert dedupe_preserve_order(["B", "A", "B", "C"]) == ["B", "A", "C"]


def test_build_category_colors():
    colors = build_category_colors(["Bacillota", "Pseudomonadota"])
    assert colors["Bacillota"] == "hsl(0 75 50)"
    assert colors["Pseudomonadota"] == "hsl(90 75 50)"


def test_attach_pies_by_label_not_id():
    tax_cats = ["Bacillota"]
    ec_values = {"1.1.1.1": [42.0]}
    nodes = [
        {"id": "a", "label": "1.1.1.1", "type": "rectangle", "x": 0, "y": 0},
        {"id": "b", "label": "1.1.1.1", "type": "rectangle", "x": 1, "y": 1},
        {"id": "c", "label": "C00001", "type": "circle", "x": 2, "y": 2},
    ]
    out = attach_pies_to_nodes(nodes, tax_cats=tax_cats, ec_values=ec_values)
    assert out[0]["values"] == [{"id": "Bacillota", "value": 42.0}]
    assert out[1]["values"] == [{"id": "Bacillota", "value": 42.0}]
    assert out[2]["values"] == []


def test_embed_edges_resolves_node_objects():
    nodes = [
        {"id": "s", "label": "A", "type": "rectangle", "x": 0, "y": 0, "values": []},
        {"id": "t", "label": "B", "type": "rectangle", "x": 1, "y": 1, "values": []},
    ]
    edges = embed_edges([{"source": "s", "target": "t"}], nodes)
    assert edges[0]["source"]["id"] == "s"
    assert edges[0]["target"]["label"] == "B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd analytics && uv run pytest api/tests/test_network_assembly.py -v`  
Expected: FAIL (`ModuleNotFoundError: network_assembly`)

- [ ] **Step 3: Implement**

```python
from __future__ import annotations

from api.colors import get_color


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def apply_layout(nodes: list[dict], *, width: float, height: float) -> list[dict]:
    placed = []
    for node in nodes:
        placed.append({
            **node,
            "x": (node["y"] / 1100) * width - width / 2 + 100,
            "y": (node["x"] / 1000) * height - height / 2,
        })
    return placed


def build_category_colors(tax_cats: list[str]) -> dict[str, str]:
    return {cat: get_color(i, len(tax_cats)) for i, cat in enumerate(tax_cats)}


def attach_pies_to_nodes(
    nodes: list[dict],
    *,
    tax_cats: list[str],
    ec_values: dict[str, list[float]],
) -> list[dict]:
    zeros = [0.0] * len(tax_cats)
    out = []
    for node in nodes:
        pie = ec_values.get(node["label"])
        values = (
            [{"id": cat, "value": v} for cat, v in zip(tax_cats, pie)]
            if pie is not None
            else []
        )
        out.append({**node, "values": values})
    return out


def embed_edges(edges: list[dict], nodes: list[dict]) -> list[dict]:
    by_id = {n["id"]: n for n in nodes}
    return [
        {"source": by_id.get(e["source"]), "target": by_id.get(e["target"])}
        for e in edges
    ]
```

- [ ] **Step 4: Run test — PASS**

Run: `cd analytics && uv run pytest api/tests/test_network_assembly.py -v`

- [ ] **Step 5: Commit**

```bash
git add analytics/api/network_assembly.py analytics/api/tests/test_network_assembly.py
git commit -m "feat(analytics): add network assembly helpers for layout and pies"
```

---

### Task 2: Static graph loader

**Files:**
- Create: `analytics/api/network_service.py` (partial — static graph functions first)
- Create: `analytics/api/tests/test_network_service.py` (static graph tests)

- [ ] **Step 1: Write failing tests**

```python
import pytest

from api.network_service import load_static_graph

PATHWAY = "Oxidative phosphorylation"


def test_load_static_graph_returns_nodes_and_edges():
    graph = load_static_graph(PATHWAY)
    assert len(graph["nodes"]) > 0
    assert len(graph["edges"]) > 0
    node = graph["nodes"][0]
    assert {"id", "label", "x", "y", "type"} <= set(node.keys())


def test_load_static_graph_unknown_pathway():
    graph = load_static_graph("__no_such_pathway__")
    assert graph == {"nodes": [], "edges": []}
```

- [ ] **Step 2: Run — FAIL**

Run: `cd analytics && uv run pytest api/tests/test_network_service.py::test_load_static_graph_returns_nodes_and_edges -v`

- [ ] **Step 3: Implement static graph loader in `network_service.py`**

```python
from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"
PATHWAY_SUPERPATHWAYS = RAW_PARQUET_DIR / "pathway_superpathways.parquet"
PATHWAY_NODES = RAW_PARQUET_DIR / "pathway_nodes.parquet"
PATHWAY_EDGES = RAW_PARQUET_DIR / "pathway_edges.parquet"


def _require_pathway_parquet() -> None:
    for path in (PATHWAY_SUPERPATHWAYS, PATHWAY_NODES, PATHWAY_EDGES):
        if not path.exists():
            raise FileNotFoundError(f"reference parquet missing: {path}")


def load_static_graph(pathway_name: str) -> dict:
    _require_pathway_parquet()
    conn = duckdb.connect()
    try:
        psp = PATHWAY_SUPERPATHWAYS.as_posix()
        nodes_p = PATHWAY_NODES.as_posix()
        edges_p = PATHWAY_EDGES.as_posix()
        row = conn.execute(
            f"SELECT id FROM read_parquet('{psp}') WHERE name = ?",
            [pathway_name],
        ).fetchone()
        if row is None:
            return {"nodes": [], "edges": []}
        pathway_id = row[0]
        nodes = conn.execute(
            f"""
            SELECT id, name AS label, x, y, type
            FROM read_parquet('{nodes_p}')
            WHERE pathway = ?
            """,
            [pathway_id],
        ).fetchdf()
        edges = conn.execute(
            f"""
            SELECT source, target
            FROM read_parquet('{edges_p}')
            WHERE pathway = ?
            """,
            [pathway_id],
        ).fetchdf()
        return {
            "nodes": nodes.to_dict(orient="records"),
            "edges": edges.to_dict(orient="records"),
        }
    finally:
        conn.close()
```

- [ ] **Step 4: Run static graph tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/network_service.py analytics/api/tests/test_network_service.py
git commit -m "feat(analytics): load static pathway graph from reference parquet"
```

---

### Task 3: Network service — triples, pies, full response

**Files:**
- Modify: `analytics/api/network_service.py`
- Modify: `analytics/api/tests/test_network_service.py`

- [ ] **Step 1: Write failing integration tests**

```python
import pytest

from api.network_service import build_network_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason

PATHWAY = "Oxidative phosphorylation"
WIDTH, HEIGHT = 900, 550


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_network_from_duckdb_shape(fake_rpkm_db):
    out = build_network_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        selected_taxon={},
        pathway_name=PATHWAY,
        width=WIDTH,
        height=HEIGHT,
    )
    assert "nodes" in out and "edges" in out and "colors" in out
    assert len(out["nodes"]) > 0
    with_pie = [n for n in out["nodes"] if any(v["value"] > 0 for v in n["values"])]
    assert len(with_pie) > 0
    assert out["edges"][0]["source"] is not None
    assert isinstance(out["edges"][0]["source"], dict)


def test_build_network_requires_pathway_name():
    with pytest.raises(ValueError, match="pathway_name is required"):
        build_network_from_duckdb(
            names=["fake_rpkm.tsv"],
            tax_level="phylum",
            selected_taxon={},
            pathway_name="",
            width=WIDTH,
            height=HEIGHT,
        )


def test_build_network_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_network_from_duckdb(
            names=["a.tsv", "b.tsv"],
            tax_level="phylum",
            selected_taxon={},
            pathway_name=PATHWAY,
            width=WIDTH,
            height=HEIGHT,
        )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_network_empty_pies_on_impossible_taxon_filter(fake_rpkm_db):
    out = build_network_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        selected_taxon={"level": "phylum", "name": "__no_such_phylum__"},
        pathway_name=PATHWAY,
        width=WIDTH,
        height=HEIGHT,
    )
    assert len(out["nodes"]) > 0
    assert out["colors"] == {}
    for n in out["nodes"]:
        assert n["values"] == []
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `build_network_from_duckdb`**

Copy `_materialize_filtered_triples`, `_taxon_exists_clause`, `_ensure_bridge_ec`, `_materialize_tax_metadata` pattern from `graph_service.py`. Differences:

- Pathway filter: always `{"name": pathway_name}` (no `require_graph_pathway_filter`)
- After metadata, aggregate:

```python
rows = conn.execute(
    """
    SELECT t.ec_normalized, m.tax_map_value, SUM(t.value) AS value
    FROM filtered_triples t
    INNER JOIN network_tax_metadata m USING (source_tax_id)
    GROUP BY t.ec_normalized, m.tax_map_value
    """
).fetchall()
```

- Build `tax_cats` from lineage-ordered metadata: `dedupe_preserve_order([row["tax_map_value"] for row in tax_rows])`
- Build `ec_values: dict[str, list[float]]` — dense arrays per EC aligned to `tax_cats`
- Call `apply_layout` → `attach_pies_to_nodes` → `embed_edges` → `build_category_colors`
- Early return `{ nodes: [], edges: [], colors: {} }` when `load_static_graph` is empty

Rename temp table to `network_tax_metadata` (copy SQL from `graph_service._materialize_tax_metadata`, table name only).

- [ ] **Step 4: Run service tests — PASS**

Run: `cd analytics && uv run pytest api/tests/test_network_service.py -v`

- [ ] **Step 5: Commit**

```bash
git add analytics/api/network_service.py analytics/api/tests/test_network_service.py
git commit -m "feat(analytics): add build_network_from_duckdb with EC tax pies"
```

---

### Task 4: FastAPI endpoint

**Files:**
- Modify: `analytics/api/schemas.py`
- Modify: `analytics/api/main.py`
- Modify: `analytics/api/tests/test_main.py`

- [ ] **Step 1: Add schema**

```python
class NetworkRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_level: str
    selected_taxon: Any = Field(default_factory=dict)
    pathway_name: str
    width: float = 900
    height: float = 550
```

- [ ] **Step 2: Add endpoint**

```python
from api.network_service import build_network_from_duckdb
from api.schemas import NetworkRequest

@app.post("/api/viz/network")
def network_endpoint(body: NetworkRequest):
    def _handle():
        if len(body.names) == 0:
            raise ValueError("names must contain at least one sample")
        return build_network_from_duckdb(
            names=body.names,
            tax_level=body.tax_level,
            selected_taxon=body.selected_taxon,
            pathway_name=body.pathway_name,
            width=body.width,
            height=body.height,
        )

    return wrap_handler(_handle)
```

- [ ] **Step 3: Add smoke test**

```python
@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_network_endpoint(client, fake_rpkm_db):
    res = client.post(
        "/api/viz/network",
        json={
            "names": ["fake_rpkm.tsv"],
            "tax_level": "phylum",
            "selected_taxon": {},
            "pathway_name": "Oxidative phosphorylation",
            "width": 900,
            "height": 550,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["value"]["nodes"]
```

- [ ] **Step 4: Run `cd analytics && uv run pytest api/tests/test_main.py -v` — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/api/schemas.py analytics/api/main.py analytics/api/tests/test_main.py
git commit -m "feat(analytics): expose POST /api/viz/network"
```

---

### Task 5: Golden expectations

**Files:**
- Modify: `analytics/testing/fake_rpkm_fixture.py`
- Modify: `analytics/testing/dump_fake_rpkm_expectations.py`
- Create: `analytics/api/tests/fixtures/network_expectations.yaml` (generated)
- Modify: `analytics/api/tests/test_network_service.py`

- [ ] **Step 1: Add fixture helpers to `fake_rpkm_fixture.py`**

```python
NETWORK_YAML = ANALYTICS_DIR / "api/tests/fixtures/network_expectations.yaml"

def load_network_expectations() -> dict[str, Any]:
    return load_yaml(NETWORK_YAML)

def extract_network_ec_values(out: dict, ec: str) -> list[list]:
    node = next(n for n in out["nodes"] if n["label"] == ec and n["values"])
    return [[v["id"], v["value"]] for v in node["values"] if v["value"] > 0]

def extract_network_colors(out: dict) -> dict[str, str]:
    return out["colors"]
```

- [ ] **Step 2: Add `dump_network_expectations` to dump script**

Cases (mirror spec §8.1):

| case_id | pathway_name | tax_level | selected_taxon |
|---|---|---|---|
| `pathway_phylum_baseline` | Oxidative phosphorylation | phylum | {} |
| `pathway_species_tax_rank` | Oxidative phosphorylation | species | {} |
| `pathway_kingdom_tax_rank` | Oxidative phosphorylation | kingdom | {} |
| `pathway_and_taxon_filter` | Oxidative phosphorylation | phylum | `{level: species, name: <focal>}` |
| `pathway_methane_metabolism` | Methane metabolism | phylum | {} |
| `unknown_pathway` | `__no_such_pathway__` | phylum | {} |

Each case stores: `focal_ec`, `expected_values` (non-zero pairs for focal EC), `expected_colors` keys, `expected_layout` for one node `{label, x, y}` with tolerance.

Add CLI flag: `--network`

Run: `cd analytics && uv run python testing/dump_fake_rpkm_expectations.py --network`

- [ ] **Step 3: Add parametrized golden tests**

```python
@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _cases, ids=[c["case_id"] for c in _cases])
def test_network_golden(case, fake_rpkm_db):
    out = build_network_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level=case["tax_level"],
        selected_taxon=case.get("selected_taxon", {}),
        pathway_name=case["pathway_name"],
        width=case.get("width", 900),
        height=case.get("height", 550),
    )
    if case["case_id"] == "unknown_pathway":
        assert out == {"nodes": [], "edges": [], "colors": {}}
        return
    assert set(out["colors"].keys()) == set(case["expected_color_keys"])
    assert_pairs_close(extract_network_ec_values(out, case["focal_ec"]), case["expected_values"])
```

- [ ] **Step 4: Generate YAML and run golden tests — PASS**

- [ ] **Step 5: Commit**

```bash
git add analytics/testing/fake_rpkm_fixture.py analytics/testing/dump_fake_rpkm_expectations.py \
  analytics/api/tests/fixtures/network_expectations.yaml analytics/api/tests/test_network_service.py
git commit -m "test(analytics): add network golden expectations on fake_rpkm"
```

---

### Task 6: Express sidecar + renderer wiring

**Files:**
- Modify: `src/server/index.ts`
- Modify: `src/renderer/src/vizBackend.ts`
- Modify: `src/renderer/src/api.ts`

- [ ] **Step 1: Move network to `sidecarRoutes` in `index.ts`**

Remove `parse_network` from `vizRoutes`. Add to `sidecarRoutes`:

```typescript
{ path: '/api/viz/network', label: 'network', legacyHandler: parse_network },
```

- [ ] **Step 2: Renderer toggle**

`vizBackend.ts`:

```typescript
const MIGRATED_CHANNELS = new Set([
  'chord', 'graph', 'overview', 'krona', 'pathway_list', 'network',
])
```

`api.ts`:

```typescript
network: { method: 'POST', url: `/api/viz/network${sidecarQuery('network')}` },
```

- [ ] **Step 3: Run Node tests**

Run: `npm test`  
Expected: all pass (sidecar proxy already tested generically via chord stand-in)

- [ ] **Step 4: Commit**

```bash
git add src/server/index.ts src/renderer/src/vizBackend.ts src/renderer/src/api.ts
git commit -m "feat(viz): wire network endpoint to FastAPI sidecar"
```

---

### Task 7: End-to-end verification

- [ ] **Step 1: Run full Python test suite**

```bash
cd analytics && uv run pytest api/tests/ -v
```

Expected: all pass

- [ ] **Step 2: Run full Node test suite**

```bash
npm test
```

Expected: all pass

- [ ] **Step 3: Manual smoke (optional)**

1. Start FastAPI: `cd analytics && uv run uvicorn api.main:app --port 8001`
2. Start app: `npm run dev`
3. Load test files → Chord → superpathway → Network → click pathway
4. Confirm node pie wedges in sidecar mode (default `vizBackend`)

- [ ] **Step 4: Push branch**

```bash
git push origin feature/network-dbt-api
```

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| `int_rpkm_by_ec_tax` + EXISTS filters | Task 3 |
| Static graph from reference Parquet | Task 2 |
| Layout transform formula | Task 1 |
| Pies keyed by `node.label` | Task 1, 3 |
| Lineage-ordered `tax_cats` + `get_color` | Task 1, 3 |
| Embedded edge node objects | Task 1 |
| `pathway_name` request contract | Task 4 |
| Error handling (comparison, missing pathway_name, etc.) | Task 3, 4 |
| Express sidecar + renderer toggle | Task 6 |
| Golden tests | Task 5 |
| Unknown pathway → empty graph | Task 2, 5 |
| Taxon filter → empty pies | Task 3 |

## Out of Scope (do not implement)

- `counts` endpoint migration
- `get_sub_color` on pie wedges
- Shared extraction from `graph_service.py`
- Retiring legacy `parse_network`
