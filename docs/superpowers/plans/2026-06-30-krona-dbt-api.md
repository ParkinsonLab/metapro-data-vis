# Krona API via dbt Intermediates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI `POST /api/viz/krona` backed by `int_rpkm_by_ec_tax` + `bridge_tax_rollup` + `names` Parquet, Express sidecar proxy, renderer toggle, and golden tests on `fake_rpkm` — preserving the existing nested-tree JSON contract.

**Architecture:** Single DuckDB PIVOT query (exact-rank-gated bridge labels + `names` lookup) returns ordered taxon rows; Python builds the tree via `lineage_segments()` + `upsert_segment()` (no recursive port of `parse_tax_tree`). Express defaults to legacy when `?backend=duckdb` absent; renderer appends query param for migrated channels unless `localStorage.vizBackend === 'legacy'`.

**Tech Stack:** Python 3.14, FastAPI, DuckDB, pytest, Pydantic; Node 22, Express 5, vitest, D3 (renderer sort fix only)

**Branch:** `feature/krona-dbt-api`

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-06-30-krona-dbt-api-design.md` — full design (SQL, tree builder, errors, ORDER BY)
- `analytics/api/chord_service.py` — `_sql_in_list`, DuckDB connect pattern, `BRIDGE_TAX_PATH`
- `analytics/api/overview_service.py` — validation shell, `_db_path`
- `analytics/api/filters.py` — `sample_id_from_names`, `validate_tax_level`
- `analytics/api/envelope.py` — `wrap_handler`
- `analytics/api/tests/test_overview_service.py` — golden test pattern
- `src/server/index.ts` — sidecar route registration (overview/chord)
- `src/server/fastapi_sidecar_proxy.ts` — shared proxy
- `src/renderer/src/vizBackend.ts` — `MIGRATED_CHANNELS`

**Prerequisites:**

```bash
cd analytics
uv run python transform/scripts/build_reference.py   # bridge_tax_rollup.parquet
# names.parquet at repo resources/db/parquet/names.parquet
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
├── filters.py                    # MODIFY: add krona_levels()
├── schemas.py                    # MODIFY: add KronaRequest, KronaNode
├── krona_service.py              # CREATE: SQL + lineage_segments + upsert
├── main.py                       # MODIFY: POST /api/viz/krona
└── tests/
    ├── fixtures/
    │   └── krona_expectations.yaml    # CREATE (via dump script)
    ├── test_krona_tree.py        # CREATE: unit tests (no DuckDB)
    ├── test_krona_service.py     # CREATE: integration + golden
    └── test_main.py              # MODIFY: krona endpoint smoke

analytics/testing/
├── fake_rpkm_fixture.py          # MODIFY: KRONA_YAML + loader + names check
└── dump_fake_rpkm_expectations.py # MODIFY: dump krona goldens

src/server/
└── index.ts                      # MODIFY: move krona to sidecarRoutes

src/renderer/src/
├── vizBackend.ts                 # MODIFY: add 'krona' to MIGRATED_CHANNELS
└── components/Krona.tsx          # MODIFY: hierarchy.sort(null)

src/tests/
└── fastapi_sidecar_proxy.test.ts # MODIFY: krona label case
```

**Builder note:** Use `KronaNode` directly during upsert. Set `subtotal` on internal nodes for accumulation; leaves use `value`. The frontend only reads `value` (via `d3.hierarchy().sum(d => d.value)`) — extra `subtotal` in JSON is harmless and needs no strip pass. Golden tests compare contract fields (`id`, `label`, `value`, `children`, `percentage`) and ignore `subtotal`.

---

### Task 1: Pydantic Krona schemas

**Files:**
- Modify: `analytics/api/schemas.py`

- [ ] **Step 1: Add models**

```python
class KronaNode(BaseModel):
    id: str
    label: str
    percentage: float
    value: float | None = None
    subtotal: float | None = None  # internals during build; frontend ignores (D3 sums leaf value)
    children: list["KronaNode"] | None = None


class KronaRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_rank: str
    selected_taxon: Any = Field(default_factory=dict)
```

- [ ] **Step 2: Commit**

```bash
git add analytics/api/schemas.py
git commit -m "feat(analytics): add Krona pydantic schemas"
```

---

### Task 2: `krona_levels` helper

**Files:**
- Modify: `analytics/api/filters.py`
- Create: `analytics/api/tests/test_krona_levels.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from api.filters import krona_levels, validate_tax_level


def test_krona_levels_phylum():
    assert krona_levels("phylum") == ("phylum", "genus", "species")


def test_krona_levels_genus():
    assert krona_levels("genus") == ("genus", "species")


def test_krona_levels_species():
    assert krona_levels("species") == ("species",)


def test_krona_levels_dedupes_when_tax_rank_is_species():
    assert krona_levels("species") == ("species",)


def test_krona_levels_invalid_rank():
    with pytest.raises(ValueError, match="invalid tax_level"):
        krona_levels("not_a_rank")
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_krona_levels.py -v
```

- [ ] **Step 3: Implement**

```python
def krona_levels(tax_rank: str) -> tuple[str, ...]:
    """dedupe preserving order: [tax_rank, genus, species]."""
    validate_tax_level(tax_rank)
    seen: set[str] = set()
    out: list[str] = []
    for r in (tax_rank, "genus", "species"):
        if r not in seen:
            seen.add(r)
            out.append(r)
    return tuple(out)
```

- [ ] **Step 4: Run — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_krona_levels.py -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/filters.py analytics/api/tests/test_krona_levels.py
git commit -m "feat(analytics): add krona_levels helper"
```

---

### Task 3: Tree builder unit tests (no DuckDB)

**Files:**
- Create: `analytics/api/krona_service.py` (builder functions only)
- Create: `analytics/api/tests/test_krona_tree.py`

- [ ] **Step 1: Write failing tests for `lineage_segments`**

```python
from types import SimpleNamespace

from api.krona_service import Segment, lineage_segments


def _taxon(**kwargs):
    return SimpleNamespace(**kwargs)


def test_lineage_species_leaf_at_last_rank():
    taxon = _taxon(name="Staphylococcus aureus", phylum="Bacillota", genus="Staphylococcus", species="Staphylococcus aureus")
    segs = lineage_segments(taxon, ("phylum", "genus", "species"))
    assert [s.id for s in segs] == ["Bacillota", "Staphylococcus", "Staphylococcus aureus"]
    assert segs[-1].is_leaf is True
    assert segs[-1].label == "Staphylococcus aureus"


def test_lineage_early_leaf_under_phylum():
    taxon = _taxon(name="Lactobacillus sp. 100-5", phylum="Bacillota", genus=None, species=None)
    segs = lineage_segments(taxon, ("phylum", "genus", "species"))
    assert len(segs) == 2
    assert segs[0].id == "Bacillota" and segs[0].is_leaf is False
    assert segs[1].id == "Lactobacillus sp. 100-5"
    assert segs[1].label == "U_Lactobacillus sp. 100-5"
    assert segs[1].is_leaf is True


def test_lineage_orphan_under_root():
    taxon = _taxon(name="999999999", phylum=None, genus=None, species=None)
    segs = lineage_segments(taxon, ("phylum", "genus", "species"))
    assert len(segs) == 1
    assert segs[0].label == "U_999999999"
```

- [ ] **Step 2: Write failing tests for `upsert_segment`**

```python
from api.krona_service import KronaNode, Segment, build_tree_from_taxa, upsert_segment


def test_upsert_creates_internal_then_leaf():
    root = KronaNode(id="root", label="root", children=[], subtotal=0.0, percentage=1.0)
    grand = 10.0
    n1 = upsert_segment(root, Segment("Bacillota", "Bacillota"), 5.0, grand)
    assert n1.id == "Bacillota"
    n2 = upsert_segment(n1, Segment("S. aureus", "S. aureus", is_leaf=True), 5.0, grand)
    assert n2.value == 5.0
    assert root.children[0].id == "Bacillota"
    assert root.children[0].children[0].value == 5.0


def test_upsert_merges_duplicate_leaf_ids():
    root = KronaNode(id="root", label="root", children=[], subtotal=0.0, percentage=1.0)
    leaf = Segment("dup", "dup", is_leaf=True)
    upsert_segment(root, leaf, 3.0, 10.0)
    upsert_segment(root, leaf, 2.0, 10.0)
    node = root.children[0]
    assert node.value == 5.0
    assert node.percentage == 0.5
```

- [ ] **Step 3: Run — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_krona_tree.py -v
```

- [ ] **Step 4: Implement builder in `krona_service.py`**

Copy verbatim from spec §5.4 (`Segment`, `lineage_segments`, `upsert_segment`). Use `KronaNode` as the mutable in-memory node (same type returned to the API). Add:

```python
def build_tree_from_taxa(taxa, levels: tuple[str, ...]) -> KronaNode:
    grand_total = sum(float(t.total) for t in taxa)
    root = KronaNode(
        id="root",
        label="root",
        children=[],
        subtotal=grand_total,
        percentage=1.0,
    )
    for taxon in taxa:
        segments = lineage_segments(taxon, levels)
        node = root
        for seg in segments:
            node = upsert_segment(node, seg, float(taxon.total), grand_total)
    return root
```

Implement `lineage_segments` and `upsert_segment` exactly as spec §5.4.2–5.4.3 (`seg.is_leaf` branching first, then `existing`). Type `upsert_segment(parent: KronaNode, ...) -> KronaNode`; append to `parent.children` (default `children=[]` on new internals).

- [ ] **Step 5: Run — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_krona_tree.py -v
```

- [ ] **Step 6: Commit**

```bash
git add analytics/api/krona_service.py analytics/api/tests/test_krona_tree.py
git commit -m "feat(analytics): krona lineage_segments and upsert tree builder"
```

---

### Task 4: Krona service — validation and SQL

**Files:**
- Modify: `analytics/api/krona_service.py`
- Modify: `analytics/api/tests/test_krona_service.py` (create with validation tests)

- [ ] **Step 1: Write failing validation tests**

```python
import pytest
from api.krona_service import build_krona_from_duckdb


def test_krona_rejects_empty_names():
    with pytest.raises(ValueError, match="at least one sample"):
        build_krona_from_duckdb(names=[], tax_rank="phylum", selected_taxon={})


def test_krona_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode not supported on analytics API"):
        build_krona_from_duckdb(names=["a.tsv", "b.tsv"], tax_rank="phylum", selected_taxon={})


def test_krona_rejects_taxon_filter():
    with pytest.raises(ValueError, match="taxon filter not supported on analytics API"):
        build_krona_from_duckdb(
            names=["fake_rpkm.tsv"],
            tax_rank="phylum",
            selected_taxon={"level": "phylum", "name": "Bacillota"},
        )
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_krona_service.py -v
```

- [ ] **Step 3: Implement service shell + SQL**

```python
REPO_ROOT = ANALYTICS_DIR.parent
NAMES_PATH = REPO_ROOT / "resources/db/parquet/names.parquet"


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _order_by_clause(levels: tuple[str, ...]) -> str:
    if len(levels) == 1:
        return "COALESCE(w.species, d.name)"
    parts: list[str] = []
    for i, rank in enumerate(levels):
        if i == 0:
            parts.append(f"COALESCE(w.{rank}, 'Unclassified ' || d.name)")
        elif i == len(levels) - 1:
            parts.append("COALESCE(w.species, d.name)")
        else:
            parts.append(f"COALESCE(w.{rank}, '')")
    return ",\n    ".join(parts)


def _fetch_taxa(conn, *, levels: tuple[str, ...]) -> list:
    if not BRIDGE_TAX_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_TAX_PATH}")
    if not NAMES_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {NAMES_PATH}")
    rank_in = _sql_in_list(levels)
    order_by = _order_by_clause(levels)
    bridge = BRIDGE_TAX_PATH.as_posix()
    names = NAMES_PATH.as_posix()
    sql = f"""
    WITH totals AS (
        SELECT source_tax_id, SUM(value) AS total
        FROM int_rpkm_by_ec_tax
        GROUP BY source_tax_id
        HAVING SUM(value) > 0
    ),
    named AS (
        SELECT
            t.source_tax_id,
            t.total,
            COALESCE(n.name, CAST(t.source_tax_id AS VARCHAR)) AS name
        FROM totals t
        LEFT JOIN read_parquet('{names}') n ON t.source_tax_id = n.tax_id
    ),
    bridge_gated AS (
        SELECT
            source_tax_id,
            requested_rank,
            CASE
                WHEN resolved_tax_rank = requested_rank
                THEN resolved_tax_label
            END AS label
        FROM read_parquet('{bridge}')
        WHERE requested_rank IN ({rank_in})
    ),
    bridge_wide AS (
        SELECT *
        FROM (
            SELECT source_tax_id, requested_rank, label
            FROM bridge_gated
        )
        PIVOT (MAX(label) FOR requested_rank IN ({rank_in}))
    )
    SELECT d.name, d.total, w.*
    FROM named d
    LEFT JOIN bridge_wide w USING (source_tax_id)
    ORDER BY
        {order_by}
    """
    return conn.execute(sql).fetchall()


def build_krona_from_duckdb(
    *, names: list[str], tax_rank: str, selected_taxon: dict
) -> KronaNode:
    if len(names) == 0:
        raise ValueError("names must contain at least one sample")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")
    if isinstance(selected_taxon, dict):
        level = str(selected_taxon.get("level") or "").strip()
        name = str(selected_taxon.get("name") or "").strip()
        if level and name:
            raise ValueError("taxon filter not supported on analytics API")

    levels = krona_levels(tax_rank)
    sample_id = sample_id_from_names(names)
    db_file = _db_path(sample_id)
    if not db_file.exists():
        raise FileNotFoundError(f"sample not found: {sample_id}")

    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "int_rpkm_by_ec_tax" not in tables:
            raise RuntimeError(
                f"int_rpkm_by_ec_tax not materialized for sample: {sample_id}"
            )
        rows = _fetch_taxa(conn, levels=levels)
        taxa = [_row_to_taxon(r, levels) for r in rows]
        return build_tree_from_taxa(taxa, levels)
    finally:
        conn.close()
```

Add `_row_to_taxon(row, levels)` mapping DuckDB row tuple → namespace with `.name`, `.total`, and `row[rank]` for each rank in `levels`.

- [ ] **Step 4: Run validation tests — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_krona_service.py -v -k "rejects"
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/krona_service.py analytics/api/tests/test_krona_service.py
git commit -m "feat(analytics): krona service SQL and validation"
```

---

### Task 5: Golden tests

**Files:**
- Create: `analytics/api/tests/fixtures/krona_expectations.yaml`
- Modify: `analytics/testing/fake_rpkm_fixture.py`
- Modify: `analytics/testing/dump_fake_rpkm_expectations.py`
- Modify: `analytics/api/tests/test_krona_service.py`

- [ ] **Step 1: Extend fixture module**

In `fake_rpkm_fixture.py`:

```python
KRONA_YAML = ANALYTICS_DIR / "api/tests/fixtures/krona_expectations.yaml"

def load_krona_expectations() -> dict[str, Any]:
    return load_yaml(KRONA_YAML)
```

Add `names.parquet` existence to skip guard (or separate `krona_fixtures_available()`).

- [ ] **Step 2: Add dump helper to `dump_fake_rpkm_expectations.py`**

```python
from api.krona_service import build_krona_from_duckdb

def dump_krona_case(tax_rank: str) -> dict:
    return build_krona_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_rank=tax_rank,
        selected_taxon={},
    ).model_dump(exclude_none=True)
```

Write YAML keys `krona_phylum`, `krona_genus` (minimum per spec).

- [ ] **Step 3: Generate initial goldens**

```bash
cd analytics && uv run python testing/dump_fake_rpkm_expectations.py --krona
```

Inspect `krona_expectations.yaml`: leaf ids must be **scientific names** (not raw tax_ids except `999999999`). Compare shape to spec §4.2 example; document §6.2 watch items in YAML comments if bridge resolves deeper than legacy.

- [ ] **Step 4: Write parametrized golden test**

```python
import pytest
from api.krona_service import build_krona_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, load_krona_expectations


def _assert_trees_close(actual: dict, expected: dict, tol: float = 1e-9):
    """Compare contract fields only; ignore extra keys (e.g. subtotal on internals)."""
    for key in ("id", "label", "percentage"):
        if key == "percentage":
            assert actual[key] == pytest.approx(expected[key], abs=tol)
        else:
            assert actual[key] == expected[key]
    if "value" in expected:
        assert actual.get("value") == pytest.approx(expected["value"], abs=tol)
        assert not actual.get("children")
    else:
        act_children = sorted(actual.get("children") or [], key=lambda n: n["id"])
        exp_children = sorted(expected.get("children") or [], key=lambda n: n["id"])
        assert len(act_children) == len(exp_children)
        for a, e in zip(act_children, exp_children):
            _assert_trees_close(a, e, tol)


@pytest.mark.parametrize("case", ["krona_phylum", "krona_genus"])
def test_krona_tree_matches_golden(case, fake_rpkm_db):
    expected = load_krona_expectations()[case]
    out = build_krona_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"], tax_rank=case.replace("krona_", ""), selected_taxon={}
    ).model_dump(exclude_none=True)
    _assert_trees_close(out, expected)
```

Replace naive sort with recursive deep-equality helper (copy pattern from spec §8.1).

- [ ] **Step 5: Run golden tests**

```bash
cd analytics && uv run pytest api/tests/test_krona_service.py -v
```

- [ ] **Step 6: Commit**

```bash
git add analytics/api/tests/fixtures/krona_expectations.yaml \
  analytics/testing/fake_rpkm_fixture.py \
  analytics/testing/dump_fake_rpkm_expectations.py \
  analytics/api/tests/test_krona_service.py
git commit -m "test(analytics): krona golden expectations on fake_rpkm"
```

---

### Task 6: FastAPI endpoint

**Files:**
- Modify: `analytics/api/main.py`
- Modify: `analytics/api/tests/test_main.py`

- [ ] **Step 1: Write smoke test**

```python
def test_krona_endpoint_envelope(fake_rpkm_db):
    res = client.post(
        "/api/viz/krona",
        json={"names": ["fake_rpkm.tsv"], "tax_rank": "phylum", "selected_taxon": {}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["value"]["id"] == "root"
    assert "children" in body["value"]


def test_krona_comparison_error_envelope():
    res = client.post(
        "/api/viz/krona",
        json={"names": ["a.tsv", "b.tsv"], "tax_rank": "phylum", "selected_taxon": {}},
    )
    body = res.json()
    assert body["ok"] is False
    assert "comparison mode" in body["error"]
```

- [ ] **Step 2: Add route**

```python
from api.krona_service import build_krona_from_duckdb
from api.schemas import KronaRequest


@app.post("/api/viz/krona")
def krona_endpoint(body: KronaRequest):
    def _handle():
        return build_krona_from_duckdb(
            names=body.names,
            tax_rank=body.tax_rank,
            selected_taxon=body.selected_taxon,
        ).model_dump(exclude_none=True)

    return wrap_handler(_handle)
```

- [ ] **Step 3: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_main.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/api/main.py analytics/api/tests/test_main.py
git commit -m "feat(analytics): POST /api/viz/krona endpoint"
```

---

### Task 7: Express sidecar route

**Files:**
- Modify: `src/server/index.ts`

- [ ] **Step 1: Move krona from `vizRoutes` to `sidecarRoutes`**

```typescript
const vizRoutes = [
  { path: '/api/viz/counts', handler: parse_counts },
  // krona removed
  { path: '/api/viz/network', handler: parse_network },
  { path: '/api/viz/pathway-list', handler: parse_pathway_list },
]

const sidecarRoutes = [
  { path: '/api/viz/overview', label: 'overview', legacyHandler: parse_overview },
  { path: '/api/viz/chord', label: 'chord', legacyHandler: parse_ec_chord },
  { path: '/api/viz/krona', label: 'krona', legacyHandler: parse_krona },
]
```

- [ ] **Step 2: Manual smoke (optional)**

```bash
# FastAPI on :8001, Express on :3001
curl -X POST 'http://localhost:3001/api/viz/krona?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{"names": ["fake_rpkm.tsv"], "tax_rank": "phylum", "selected_taxon": {}}'
```

- [ ] **Step 3: Commit**

```bash
git add src/server/index.ts
git commit -m "feat(server): proxy krona to analytics sidecar"
```

---

### Task 8: Renderer toggle + Krona sort

**Files:**
- Modify: `src/renderer/src/vizBackend.ts`
- Modify: `src/renderer/src/components/Krona.tsx`

- [ ] **Step 1: Add krona to migrated channels**

```typescript
const MIGRATED_CHANNELS = new Set(['chord', 'overview', 'krona'])
```

- [ ] **Step 2: Fix partition sort in `Krona.tsx`**

Replace:

```typescript
.sort((a, b) => b.value - a.value)
```

with:

```typescript
.sort(null)
```

so arc order follows backend `children` order (spec §4.2).

- [ ] **Step 3: Commit**

```bash
git add src/renderer/src/vizBackend.ts src/renderer/src/components/Krona.tsx
git commit -m "feat(renderer): krona sidecar default and preserve sibling order"
```

---

### Task 9: Proxy unit test for krona label

**Files:**
- Modify: `src/tests/fastapi_sidecar_proxy.test.ts`

- [ ] **Step 1: Add krona case**

```typescript
it('returns krona error envelope when fetch fails', async () => {
  const fetchFn = vi.fn().mockRejectedValue(new Error('connection refused'))
  const handler = createSidecarProxyHandler({
    legacyHandler: vi.fn(),
    apiPath: '/api/viz/krona',
    label: 'krona',
    fetchFn,
  })
  const out = await handler({ query: { backend: 'duckdb' }, body: {} })
  expect(out).toEqual({
    ok: false,
    error: 'krona duckdb backend unavailable: connection refused',
  })
})
```

Note: shared proxy uses `{label} duckdb backend unavailable` (same as chord/overview). Spec §3.1 wording differs; align in a follow-up if desired.

- [ ] **Step 2: Run vitest**

```bash
npm run test -- src/tests/fastapi_sidecar_proxy.test.ts
```

- [ ] **Step 3: Commit**

```bash
git add src/tests/fastapi_sidecar_proxy.test.ts
git commit -m "test(server): krona sidecar proxy error envelope"
```

---

## Self-Review (spec coverage)

| Spec section | Task |
|---|---|
| §2 locked decisions (data source, upsert builder, ORDER BY) | 3, 4 |
| §4 request/response contract | 1, 6 |
| §5 SQL PIVOT + exact-rank gating | 4 |
| §5.4 lineage_segments + upsert_segment | 3 |
| §5.5 sample lookup | 4 |
| §6 deviations (document in golden comments) | 5 |
| §7 repository layout | all tasks |
| §8 golden + proxy tests | 5, 9 |
| §10 checklist | all tasks |

**Gap watch:** §6.2 Mammaliicoccus / early `U_` vs full depth — validate during Task 5 golden dump; do not silently match legacy if bridge is correct.

---

## Verification (end-to-end)

```bash
cd analytics && uv run pytest api/tests/test_krona_tree.py api/tests/test_krona_service.py api/tests/test_main.py -v
npm run test -- src/tests/fastapi_sidecar_proxy.test.ts
```

Manual: load `fake_rpkm` in app, open Krona tab (sidecar default), confirm sunburst arc order is alphabetical by rank (not by value size).
