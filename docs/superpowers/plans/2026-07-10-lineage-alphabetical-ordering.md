# Lineage Alphabetical Ordering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch chord tax/ann ordering from abundance-based to hierarchical alphabetical (shared with graph/network), fix krona sibling order to use the full seven-rank lineage tuple, and drop chord `pathway_node` ann level support.

**Architecture:** Stateless `ORDER BY` fragments live in `query_enriched.py` (`lineage_order_by_sql`, new `ann_order_by_sql`). DuckDB orchestration lives in `tax_lineage_order.py` (tax, existing) and new `ann_order.py` (ann). `chord_service.py` deletes ~150 lines of abundance PIVOT SQL and wires the two order modules. `krona_service.py` groups by all lineage label columns and orders with `lineage_order_by_sql()`.

**Tech Stack:** Python 3.14, DuckDB, FastAPI, pytest, uv

**Spec:** `docs/superpowers/specs/2026-07-10-lineage-alphabetical-ordering-design.md`

**Branch / worktree:** `feature/lineage-alphabetical-ordering` → `.worktrees/feature/lineage-alphabetical-ordering/`

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-07-10-lineage-alphabetical-ordering-design.md` — approved design
- `analytics/api/tax_lineage_order.py` — pattern for chord tax order (`tax_cat_order_for_ids_table`)
- `analytics/api/pathway_list_service.py` — chord tax ids temp table pattern (lines 81–92)
- `analytics/api/query_enriched.py` — `lineage_order_by_sql()`, `canonical_pathway_label_sql()`
- `analytics/api/chord_service.py` — abundance PIVOT code to delete
- `analytics/api/krona_service.py` — `_order_by_clause`, `_fetch_taxa`
- `analytics/testing/dump_fake_rpkm_expectations.py` — golden YAML regeneration

**Prerequisites (from worktree root):**

```bash
cd analytics
uv run python transform/scripts/build_reference.py
uv run python transform/scripts/run_pipeline.py \
  --sample-id fake_rpkm \
  --rpkm-path transform/tests/fixtures/fake_rpkm.tsv \
  --tax-rank phylum \
  --pathway-level superpathway
```

**Worktree setup (if not already done):**

```bash
mkdir -p resources/db
MAIN="$(git worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
ln -sf "$MAIN/resources/db/taxonomy.db" resources/db/taxonomy.db
```

---

## File Map

```
analytics/api/
├── query_enriched.py              # MODIFY: add ann_order_by_sql()
├── ann_order.py                   # CREATE: ann_labels_ordered()
├── chord_service.py               # MODIFY: wire order modules; delete abundance PIVOT
├── krona_service.py               # MODIFY: full lineage ORDER BY
└── tests/
    ├── test_query_enriched.py     # MODIFY: ann_order_by_sql tests
    ├── test_ann_order.py          # CREATE
    ├── test_chord_service.py      # MODIFY: ordering + pathway_node rejection
    └── test_krona_service.py        # MODIFY: ORDER BY assertion; golden may change

analytics/testing/
├── fake_rpkm_fixture.py           # MODIFY: add CHORD_ANN_LEVELS constant
└── dump_fake_rpkm_expectations.py # MODIFY: use CHORD_ANN_LEVELS for chord dump

analytics/api/tests/fixtures/
├── chord_expectations.yaml        # REGENERATE: new expected_index; drop pathway_node cases
└── krona_expectations.yaml        # REGENERATE if krona sibling order changes
```

---

### Task 1: `ann_order_by_sql` in query_enriched

**Files:**
- Modify: `analytics/api/query_enriched.py`
- Test: `analytics/api/tests/test_query_enriched.py`

- [ ] **Step 1: Write the failing tests**

Add to `analytics/api/tests/test_query_enriched.py`:

```python
from api.query_enriched import ann_order_by_sql


def test_ann_order_by_sql_superpathway():
    assert ann_order_by_sql("superpathway") == "superpathway_name ASC"


def test_ann_order_by_sql_pathway():
    assert ann_order_by_sql("pathway") == "superpathway_name ASC, pathway_name ASC"


def test_ann_order_by_sql_rejects_pathway_node():
    with pytest.raises(ValueError, match="unsupported ann_level"):
        ann_order_by_sql("pathway_node")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd analytics
uv run pytest api/tests/test_query_enriched.py::test_ann_order_by_sql_superpathway -v
```

Expected: FAIL — `ImportError` or `cannot import name 'ann_order_by_sql'`

- [ ] **Step 3: Implement `ann_order_by_sql`**

Add to `analytics/api/query_enriched.py` after `lineage_order_by_sql`:

```python
def ann_order_by_sql(ann_level: str) -> str:
    """ORDER BY keys for pathway hierarchy on mart_rpkm_enriched."""
    validate_ann_level(ann_level)
    if ann_level == "superpathway":
        return "superpathway_name ASC"
    if ann_level == "pathway":
        return "superpathway_name ASC, pathway_name ASC"
    raise ValueError(f"unsupported ann_level for ann ordering: {ann_level}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest api/tests/test_query_enriched.py -k ann_order_by_sql -v
```

Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add analytics/api/query_enriched.py analytics/api/tests/test_query_enriched.py
git commit -m "feat(api): add ann_order_by_sql for hierarchical pathway sort"
```

---

### Task 2: `ann_order.py` orchestration module

**Files:**
- Create: `analytics/api/ann_order.py`
- Create: `analytics/api/tests/test_ann_order.py`

- [ ] **Step 1: Write the failing integration test**

Create `analytics/api/tests/test_ann_order.py`:

```python
from __future__ import annotations

import pytest

from api.ann_order import ann_labels_ordered
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason

pytestmark = pytest.mark.skipif(not bridges_available(), reason=skip_reason())


def _db_conn(fake_rpkm_db):
    import duckdb
    from pathlib import Path

    db = Path(__file__).resolve().parents[2] / f"transform/runs/{SAMPLE_ID}/sample.duckdb"
    return duckdb.connect(str(db), read_only=True)


def test_ann_labels_ordered_superpathway_alphabetical(fake_rpkm_db):
    conn = _db_conn(fake_rpkm_db)
    try:
        labels = ann_labels_ordered(
            conn, ann_level="superpathway", where_sql="TRUE", params=[]
        )
        assert labels == sorted(labels)
        assert len(labels) > 0
    finally:
        conn.close()


def test_ann_labels_ordered_pathway_hierarchical(fake_rpkm_db):
    conn = _db_conn(fake_rpkm_db)
    try:
        labels = ann_labels_ordered(
            conn, ann_level="pathway", where_sql="TRUE", params=[]
        )
        assert labels != sorted(labels) or len(labels) <= 1
        assert len(labels) > 1
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd analytics
uv run pytest api/tests/test_ann_order.py -v
```

Expected: FAIL — `ModuleNotFoundError: api.ann_order`

- [ ] **Step 3: Implement `ann_order.py`**

Create `analytics/api/ann_order.py`:

```python
from __future__ import annotations

import duckdb

from api.query_enriched import ann_order_by_sql, canonical_pathway_label_sql


def ann_labels_ordered(
    conn: duckdb.DuckDBPyConnection,
    *,
    ann_level: str,
    where_sql: str,
    params: list,
) -> list[str]:
    pathway_label = canonical_pathway_label_sql(ann_level)
    order_by = ann_order_by_sql(ann_level)
    rows = conn.execute(
        f"""
        SELECT DISTINCT {pathway_label} AS display_label
        FROM mart_rpkm_enriched
        WHERE {where_sql}
        ORDER BY {order_by}
        """,
        params,
    ).fetchall()
    return [r[0] for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest api/tests/test_ann_order.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analytics/api/ann_order.py analytics/api/tests/test_ann_order.py
git commit -m "feat(api): add ann_labels_ordered for chord ann axis"
```

---

### Task 3: Refactor `chord_service.py`

**Files:**
- Modify: `analytics/api/chord_service.py`
- Test: `analytics/api/tests/test_chord_service.py` (pathway_node rejection only in this task)

- [ ] **Step 1: Write failing pathway_node rejection test**

Add to `analytics/api/tests/test_chord_service.py`:

```python
def test_chord_rejects_pathway_node_ann_level():
    with pytest.raises(ValueError, match="pathway_node ann_level not supported"):
        build_chord_from_duckdb(
            sample_id=SAMPLE_ID,
            tax_level="phylum",
            ann_level="pathway_node",
            ann_filter=None,
            taxon_filter=None,
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd analytics
uv run pytest api/tests/test_chord_service.py::test_chord_rejects_pathway_node_ann_level -v
```

Expected: FAIL — no error raised (chord currently accepts pathway_node)

- [ ] **Step 3: Rewrite `chord_service.py`**

Replace abundance ordering with shared modules. The refactored `build_chord_from_duckdb` should:

1. After `validate_tax_level` / `validate_ann_level`, reject `pathway_node`:

```python
if ann_level == "pathway_node":
    raise ValueError("pathway_node ann_level not supported on chord")
```

2. After pair query, materialize tax ids and fetch orders:

```python
from api.ann_order import ann_labels_ordered
from api.tax_lineage_order import tax_cat_order_for_ids_table

conn.execute(
    f"""
    CREATE OR REPLACE TEMP TABLE chord_tax_ids AS
    SELECT DISTINCT source_tax_id
    FROM mart_rpkm_enriched
    WHERE {where_sql}
    """,
    params,
)
tax_order = tax_cat_order_for_ids_table(
    conn, tax_level=tax_level, ids_table="chord_tax_ids"
)
ann_order = ann_labels_ordered(
    conn, ann_level=ann_level, where_sql=where_sql, params=params
)
return build_chord_matrix(
    pairs, tax_order=tax_order or None, ann_order=ann_order or None
)
```

3. **Delete** these functions and helpers entirely:
   - `_LINEAGE_RANKS`, `_ANN_ORDER_RANKS`
   - `_rank_totals_cte`
   - `_tax_lineage_select`
   - `_tax_label_totals_long_sql`
   - `_fetch_tax_order`
   - `_ann_level_totals_cte`
   - `_fetch_ann_order`

4. Remove unused imports (`TAX_RANK_ORDER` if no longer needed).

- [ ] **Step 4: Run pathway_node test and pair golden tests**

```bash
uv run pytest api/tests/test_chord_service.py::test_chord_rejects_pathway_node_ann_level -v
uv run pytest api/tests/test_chord_service.py -k "pairs" -v
```

Expected: pathway_node test PASS; pair tests PASS (values unchanged)

- [ ] **Step 5: Commit**

```bash
git add analytics/api/chord_service.py analytics/api/tests/test_chord_service.py
git commit -m "feat(chord): lineage alphabetical tax/ann order; drop pathway_node"
```

---

### Task 4: Chord ordering tests and golden YAML

**Files:**
- Modify: `analytics/api/tests/test_chord_service.py`
- Modify: `analytics/testing/fake_rpkm_fixture.py`
- Modify: `analytics/testing/dump_fake_rpkm_expectations.py`
- Modify: `analytics/api/tests/fixtures/chord_expectations.yaml`

- [ ] **Step 1: Update ordering unit tests**

In `test_chord_service.py`:

**Remove:** `test_pathway_node_ann_order_stays_alphabetical`

**Replace** `test_phylum_rank_tax_order_by_abundance_not_alphabetical` with:

```python
@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_phylum_rank_tax_order_lineage_alphabetical(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    tax_labels = out["index"][gap2 + 1 : -1]
    assert tax_labels == sorted(tax_labels)
```

**Replace** `test_pathway_level_ann_order_groups_by_superpathway` with:

```python
@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_pathway_level_ann_order_hierarchical_alphabetical(fake_rpkm_db):
    from api.ann_order import ann_labels_ordered
    import duckdb
    from pathlib import Path
    from testing.fake_rpkm_fixture import SAMPLE_ID

    db = Path(__file__).resolve().parents[2] / f"transform/runs/{SAMPLE_ID}/sample.duckdb"
    conn = duckdb.connect(str(db), read_only=True)
    try:
        expected = ann_labels_ordered(
            conn, ann_level="pathway", where_sql="TRUE", params=[]
        )
    finally:
        conn.close()

    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="phylum",
        ann_level="pathway",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    ann_labels = out["index"][1:gap2]
    assert ann_labels == expected
```

**Replace** `test_class_rank_tax_labels_colocate_by_phylum_prefix` with a lineage-colocation check using `tax_cat_order_for_ids_table` or by asserting class labels appear in phylum-grouped blocks (optional: compare order against graph tax cats for same filters).

- [ ] **Step 2: Add `CHORD_ANN_LEVELS` to fixture**

In `analytics/testing/fake_rpkm_fixture.py`:

```python
ANN_LEVELS = ("pathway_node", "pathway", "superpathway")
CHORD_ANN_LEVELS = ("pathway", "superpathway")
```

In `dump_fake_rpkm_expectations.py`, change unfiltered chord dump loop:

```python
from testing.fake_rpkm_fixture import CHORD_ANN_LEVELS, ...

unfiltered = [
    dump_chord_case(rank, ann, case_id=f"{rank}_{ann}")
    for rank in RANKS
    for ann in CHORD_ANN_LEVELS
]
```

- [ ] **Step 3: Regenerate chord golden YAML**

```bash
cd analytics
uv run python testing/dump_fake_rpkm_expectations.py
```

- [ ] **Step 4: Run chord tests**

```bash
uv run pytest api/tests/test_chord_service.py -v
```

Expected: all PASS including `test_chord_pairs_and_index`

- [ ] **Step 5: Commit**

```bash
git add analytics/api/tests/test_chord_service.py \
  analytics/testing/fake_rpkm_fixture.py \
  analytics/testing/dump_fake_rpkm_expectations.py \
  analytics/api/tests/fixtures/chord_expectations.yaml
git commit -m "test(chord): lineage alphabetical order assertions and golden refresh"
```

---

### Task 5: Krona full lineage `ORDER BY`

**Files:**
- Modify: `analytics/api/krona_service.py`
- Modify: `analytics/api/tests/test_krona_service.py`

- [ ] **Step 1: Write failing ORDER BY assertion test**

Add to `analytics/api/tests/test_krona_service.py`:

```python
from api.filters import TAX_RANK_ORDER
from api.krona_service import _fetch_taxa
from api.query_enriched import lineage_order_by_sql


def test_fetch_taxa_orders_by_full_lineage(fake_rpkm_db):
    import duckdb
    from testing.fake_rpkm_fixture import SAMPLE_ID, DB_PATH

    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        levels = ("phylum", "genus", "species")
        rows = _fetch_taxa(conn, levels=levels)
        assert len(rows) > 0
        # kingdom is not in krona_levels but must affect order — verify SQL uses full lineage
        assert lineage_order_by_sql().startswith("kingdom")
    finally:
        conn.close()
```

Also export or test `_fetch_taxa` SQL includes `kingdom` in GROUP BY — if `_fetch_taxa` is private, test via sibling order: two genera from different kingdoms should sort by kingdom first (integration test on fake_rpkm if fixture has such taxa).

- [ ] **Step 2: Run test — may pass only after implementation**

```bash
cd analytics
uv run pytest api/tests/test_krona_service.py::test_fetch_taxa_orders_by_full_lineage -v
```

- [ ] **Step 3: Update `krona_service.py`**

1. Import `TAX_RANK_ORDER` from `api.filters` and `lineage_order_by_sql` from `api.query_enriched`.

2. **Delete** `_order_by_clause`.

3. Replace `_fetch_taxa`:

```python
def _fetch_taxa(conn, *, levels: tuple[str, ...]) -> list:
    from api.filters import TAX_RANK_ORDER

    lineage_cols = ", ".join(f"{rank}_label AS {rank}" for rank in levels)
    group_lineage = ", ".join(f"{rank}_label" for rank in TAX_RANK_ORDER)
    order_by = lineage_order_by_sql()
    sql = f"""
    SELECT
        display_name,
        SUM(value) AS total,
        {lineage_cols}
    FROM mart_rpkm_enriched
    GROUP BY source_tax_id, display_name, {group_lineage}
    HAVING SUM(value) > 0
    ORDER BY
        {order_by}
    """
    return conn.execute(sql).fetchall()
```

Note: `group_lineage` lists all seven rank label columns; `lineage_cols` in SELECT only exposes `krona_levels` for `_row_to_taxon`.

- [ ] **Step 4: Run krona tests**

```bash
uv run pytest api/tests/test_krona_service.py -v
```

If golden trees fail sibling order:

```bash
uv run python testing/dump_fake_rpkm_expectations.py --krona
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/krona_service.py analytics/api/tests/test_krona_service.py
# include krona_expectations.yaml if regenerated
git commit -m "feat(krona): order siblings by full lineage tuple"
```

---

### Task 6: Full regression

- [ ] **Step 1: Run full API test suite**

```bash
cd analytics
uv run pytest api/tests/ -q
```

Expected: all tests PASS

- [ ] **Step 2: Push branch**

```bash
git push -u origin HEAD
```

- [ ] **Step 3: Commit any fixups**

If failures, fix and commit before push.

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| Chord tax via `tax_cat_order_for_ids_table` | Task 3 |
| Chord ann via `ann_order.py` / `ann_order_by_sql` | Tasks 1–3 |
| Chord rejects `pathway_node` | Task 3 |
| Delete chord abundance PIVOT | Task 3 |
| Krona full `lineage_order_by_sql()` | Task 5 |
| Graph/network/pathway-list/overview unchanged | No tasks (regression only) |
| `test_query_enriched` ann tests | Task 1 |
| `test_ann_order.py` | Task 2 |
| Chord golden `expected_index` refresh | Task 4 |
| Krona golden refresh if needed | Task 5 |

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-lineage-alphabetical-ordering.md`.

**Worktree:** `.worktrees/feature/lineage-alphabetical-ordering/` (spec committed on `feature/lineage-alphabetical-ordering`)

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — implement tasks in this session with checkpoints

Which approach?
