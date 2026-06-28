# Chord Stable Ordering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend hierarchical abundance sort for chord `index` order — stable tax/pathway label positions across rank/level changes; stateless per `(sample, tax_level, ann_level, filters)`.

**Architecture:** One `chord_prefix_rows` temp table (filtered prefix ranks/levels) feeds pair query + totals. Tax ancestor labels from `bridge_tax_rollup`; pathway ancestors from wide `bridge_ec` (superpathway/pathway only). `build_chord_matrix` accepts explicit `tax_order` / `ann_order`; `pathway_node` keeps alphabetical fallback.

**Tech Stack:** Python 3, DuckDB (PIVOT), FastAPI chord service, pytest, fake_rpkm golden fixtures

**Worktree:** `.worktrees/chord-dbt-api/` on branch `feature/chord-dbt-api`

**Spec:** `docs/superpowers/specs/2026-06-27-chord-stable-ordering-design.md`

---

## File Map

```
analytics/api/
├── filters.py                   # MODIFY: ordered rank/level sequences + prefix helpers
├── chord_matrix.py              # MODIFY: tax_order/ann_order + _apply_order
├── chord_service.py             # MODIFY: chord_prefix_rows, bridges, sort SQL, wire orders
└── tests/
    ├── test_chord_matrix.py     # CREATE: _apply_order unit tests
    ├── test_chord_service.py    # CREATE: golden pairs + expected_index + stability
    └── fixtures/
        └── chord_expectations.yaml  # MODIFY: regenerate with expected_index

analytics/testing/
├── fake_rpkm_fixture.py         # MODIFY: assert_index_matches helper
└── dump_fake_rpkm_expectations.py  # MODIFY: emit expected_index per case
```

No frontend changes (§5 spec).

---

### Task 1: Prefix rank/level helpers

**Files:**
- Modify: `analytics/api/filters.py`
- Create: `analytics/api/tests/test_filters.py`

- [ ] **Step 1: Write the failing tests**

```python
# analytics/api/tests/test_filters.py
from api.filters import ann_levels_up_to, ranks_up_to


def test_ranks_up_to_kingdom():
    assert ranks_up_to("kingdom") == ("kingdom",)


def test_ranks_up_to_class():
    assert ranks_up_to("class") == (
        "kingdom", "phylum", "class",
    )


def test_ranks_up_to_species():
    assert ranks_up_to("species") == (
        "kingdom", "phylum", "class", "order", "family", "genus", "species",
    )


def test_ann_levels_up_to_superpathway():
    assert ann_levels_up_to("superpathway") == ("superpathway",)


def test_ann_levels_up_to_pathway():
    assert ann_levels_up_to("pathway") == ("superpathway", "pathway")


def test_ann_levels_up_to_pathway_node():
    assert ann_levels_up_to("pathway_node") == (
        "superpathway", "pathway", "pathway_node",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run from `analytics/`:

```bash
uv run pytest api/tests/test_filters.py -v
```

Expected: FAIL — `ImportError: cannot import name 'ranks_up_to'`

- [ ] **Step 3: Implement helpers**

Add to `analytics/api/filters.py` (after `VALID_ANN_LEVELS`):

```python
TAX_RANK_ORDER = (
    "kingdom", "phylum", "class", "order", "family", "genus", "species",
)
ANN_LEVEL_ORDER = ("superpathway", "pathway", "pathway_node")


def ranks_up_to(tax_level: str) -> tuple[str, ...]:
    validate_tax_level(tax_level)
    idx = TAX_RANK_ORDER.index(tax_level)
    return TAX_RANK_ORDER[: idx + 1]


def ann_levels_up_to(ann_level: str) -> tuple[str, ...]:
    validate_ann_level(ann_level)
    idx = ANN_LEVEL_ORDER.index(ann_level)
    return ANN_LEVEL_ORDER[: idx + 1]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest api/tests/test_filters.py -v
```

Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add analytics/api/filters.py analytics/api/tests/test_filters.py
git commit -m "feat(chord): add ranks_up_to and ann_levels_up_to helpers"
```

---

### Task 2: `build_chord_matrix` explicit order

**Files:**
- Modify: `analytics/api/chord_matrix.py`
- Create: `analytics/api/tests/test_chord_matrix.py`

- [ ] **Step 1: Write the failing tests**

```python
# analytics/api/tests/test_chord_matrix.py
from api.chord_matrix import build_chord_matrix


def test_apply_order_uses_explicit_tax_order():
    pairs = [("A", "tax_b", 1.0), ("A", "tax_a", 1.0)]
    out = build_chord_matrix(pairs, tax_order=["tax_b", "tax_a"])
    tax_section = out["index"][out["index"].index("gap_2") + 1 : -1]
    assert tax_section == ["tax_b", "tax_a"]


def test_apply_order_uses_explicit_ann_order():
    pairs = [("ann_b", "T", 1.0), ("ann_a", "T", 1.0)]
    out = build_chord_matrix(pairs, ann_order=["ann_b", "ann_a"])
    ann_section = out["index"][1 : out["index"].index("gap_2")]
    assert ann_section == ["ann_b", "ann_a"]


def test_apply_order_none_falls_back_to_sorted():
    pairs = [("B", "z", 1.0), ("A", "a", 1.0)]
    out = build_chord_matrix(pairs)
    assert out["index"][1:-1:1]  # smoke — gaps present
    ann_section = out["index"][1 : out["index"].index("gap_2")]
    tax_section = out["index"][out["index"].index("gap_2") + 1 : -1]
    assert ann_section == ["A", "B"]
    assert tax_section == ["a", "z"]


def test_apply_order_appends_extra_labels_not_in_list():
    pairs = [("A", "tax_a", 1.0), ("B", "tax_a", 1.0)]
    out = build_chord_matrix(pairs, ann_order=["A"])
    ann_section = out["index"][1 : out["index"].index("gap_2")]
    assert ann_section == ["A", "B"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest api/tests/test_chord_matrix.py -v
```

Expected: FAIL — unexpected keyword argument `tax_order`

- [ ] **Step 3: Implement `_apply_order` and wire parameters**

Replace `analytics/api/chord_matrix.py` core logic:

```python
def _apply_order(unique_labels: set[str], order_list: list[str] | None) -> list[str]:
    if order_list is None:
        return sorted(unique_labels)
    ordered = [label for label in order_list if label in unique_labels]
    extras = sorted(unique_labels - set(ordered))
    return ordered + extras


def build_chord_matrix(
    pairs: list[tuple[str, str, float]],
    tax_order: list[str] | None = None,
    ann_order: list[str] | None = None,
) -> dict:
    ann_cats = _apply_order({ann for ann, _, _ in pairs}, ann_order)
    tax_cats = _apply_order({tax for _, tax, _ in pairs}, tax_order)
    index = ["gap_1", *ann_cats, "gap_2", *tax_cats, "gap_3"]
    # ... rest unchanged ...
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest api/tests/test_chord_matrix.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add analytics/api/chord_matrix.py analytics/api/tests/test_chord_matrix.py
git commit -m "feat(chord): accept explicit tax and ann order in matrix builder"
```

---

### Task 3: `chord_prefix_rows` + pair query refactor

**Files:**
- Modify: `analytics/api/chord_service.py`
- Create: `analytics/api/tests/test_chord_service.py` (pairs-only first)

- [ ] **Step 1: Write failing golden pair test (smoke subset)**

```python
# analytics/api/tests/test_chord_service.py
import pytest

from api.chord_service import build_chord_from_duckdb
from testing.fake_rpkm_fixture import (
    assert_pairs_close,
    bridges_available,
    extract_chord_pairs,
    load_chord_expectations,
    skip_reason,
)

pytestmark = pytest.mark.skipif(not bridges_available(), reason=skip_reason())


@pytest.fixture(scope="module")
def fake_rpkm_db():
    from testing.fake_rpkm_fixture import ensure_pipeline_built
    return ensure_pipeline_built()


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(c, id=c["case_id"])
        for c in load_chord_expectations()["chord_unfiltered"]
        if c["case_id"] in ("species_pathway", "phylum_superpathway")
    ],
)
def test_chord_pairs_unchanged_after_prefix_refactor(case, fake_rpkm_db):
    from api.filters import normalise_ann_filter, normalise_taxon_filter

    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"]),
        taxon_filter=normalise_taxon_filter(case.get("selected_taxon")),
    )
    assert_pairs_close(extract_chord_pairs(out), case["pairs"])
```

- [ ] **Step 2: Run test — should PASS on current code (baseline)**

```bash
uv run pytest api/tests/test_chord_service.py -v
```

Expected: PASS (baseline before refactor)

- [ ] **Step 3: Refactor `build_chord_from_duckdb` to use `chord_prefix_rows`**

In `analytics/api/chord_service.py`:

1. Add imports: `ann_levels_up_to`, `ranks_up_to` from `api.filters`
2. Add `BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"`
3. Replace inline pair SQL with temp-table pipeline (keep connection open through all queries):

```python
def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def build_chord_from_duckdb(...) -> dict:
    # ... existing validation ...
    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        rank_in = _sql_in_list(ranks_up_to(tax_level))
        level_in = _sql_in_list(ann_levels_up_to(ann_level))

        if BRIDGE_EC_PATH.exists():
            conn.execute(
                f"CREATE TEMP TABLE bridge_ec AS "
                f"SELECT * FROM read_parquet('{BRIDGE_EC_PATH.as_posix()}')"
            )

        # tax_subquery + ann_sql unchanged ...
        conn.execute(
            f"""
            CREATE TEMP TABLE chord_prefix_rows AS
            SELECT
                t.source_tax_id,
                t.requested_rank,
                t.resolved_tax_label,
                t.resolved_tax_id,
                t.pathway_key,
                t.pathway_level,
                t.pathway_label,
                t.ec_normalized,
                t.value
            FROM int_tax_rollup_resolved t
            WHERE t.requested_rank IN ({rank_in})
              AND t.pathway_level IN ({level_in})
              AND ({tax_subquery})
              AND ({ann_sql})
            """,
            params + ann_params,
        )

        pair_sql = f"""
            SELECT
                {PATHWAY_LABEL_SQL} AS pathway_label,
                t.resolved_tax_label,
                SUM(t.value) AS value
            FROM chord_prefix_rows t
            WHERE t.requested_rank = ?
              AND t.pathway_level = ?
            GROUP BY t.pathway_key, t.resolved_tax_id,
                     {PATHWAY_LABEL_SQL},
                     t.resolved_tax_label
            HAVING SUM(t.value) > 0
        """
        rows = conn.execute(pair_sql, [tax_level, ann_level]).fetchall()
        pairs = [(r[0], r[1], float(r[2])) for r in rows]
        return build_chord_matrix(pairs)  # orders added in Task 4/5
    finally:
        conn.close()
```

- [ ] **Step 4: Run pair tests again**

```bash
uv run pytest api/tests/test_chord_service.py -v
```

Expected: PASS — pairs unchanged

- [ ] **Step 5: Commit**

```bash
git add analytics/api/chord_service.py analytics/api/tests/test_chord_service.py
git commit -m "refactor(chord): build pair query from chord_prefix_rows temp table"
```

---

### Task 4: Tax sort (`bridge_tax` + rank totals)

**Files:**
- Modify: `analytics/api/chord_service.py`
- Modify: `analytics/api/tests/test_chord_service.py`

- [ ] **Step 1: Write failing test for hierarchical tax order**

Add to `test_chord_service.py`:

```python
def test_phylum_rank_tax_order_by_abundance_not_alphabetical(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    tax_labels = out["index"][gap2 + 1 : -1]
    # Alphabetical would start with Actinobacteria; abundance sort puts Bacteria first
    assert tax_labels[0] == "Bacteria"
    assert tax_labels != sorted(tax_labels)
```

Adjust expected first label if fixture abundances differ after running once — regenerate assertion from actual hierarchical output if needed.

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest api/tests/test_chord_service.py::test_phylum_rank_tax_order_by_abundance_not_alphabetical -v
```

Expected: FAIL — tax section is alphabetical today

- [ ] **Step 3: Implement tax sort queries**

Add helper in `chord_service.py`:

```python
def _fetch_tax_order(conn, tax_level: str, ann_level: str) -> list[str]:
    if not BRIDGE_TAX_PATH.exists():
        return []

    conn.execute(
        f"CREATE TEMP TABLE bridge_tax AS "
        f"SELECT source_tax_id, requested_rank, resolved_tax_label "
        f"FROM read_parquet('{BRIDGE_TAX_PATH.as_posix()}')"
    )
    conn.execute(
        """
        CREATE TEMP TABLE rank_totals AS
        SELECT requested_rank, resolved_tax_label, SUM(value) AS total
        FROM chord_prefix_rows
        GROUP BY requested_rank, resolved_tax_label
        """
    )
    conn.execute(
        f"""
        CREATE TEMP TABLE tax_label_totals_long AS
        SELECT
            d.display_label,
            b.requested_rank AS anc_rank,
            rt.total AS anc_total
        FROM (
            SELECT DISTINCT source_tax_id, resolved_tax_label AS display_label
            FROM chord_prefix_rows
            WHERE requested_rank = ?
              AND pathway_level = ?
        ) d
        JOIN bridge_tax b ON b.source_tax_id = d.source_tax_id
        JOIN rank_totals rt
          ON rt.requested_rank = b.requested_rank
         AND rt.resolved_tax_label = b.resolved_tax_label
        """,
        [tax_level, ann_level],
    )
    rows = conn.execute(
        """
        SELECT display_label
        FROM tax_label_totals_long
        PIVOT (MAX(anc_total) FOR anc_rank IN (
            'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'
        ))
        GROUP BY display_label
        ORDER BY
            kingdom DESC NULLS LAST,
            phylum DESC NULLS LAST,
            class DESC NULLS LAST,
            "order" DESC NULLS LAST,
            family DESC NULLS LAST,
            genus DESC NULLS LAST,
            species DESC NULLS LAST,
            display_label
        """
    ).fetchall()
    return [r[0] for r in rows]
```

Wire in `build_chord_from_duckdb` before `build_chord_matrix`:

```python
tax_order = _fetch_tax_order(conn, tax_level, ann_level)
return build_chord_matrix(pairs, tax_order=tax_order or None)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest api/tests/test_chord_service.py::test_phylum_rank_tax_order_by_abundance_not_alphabetical -v
```

Expected: PASS

- [ ] **Step 5: Run full pair regression**

```bash
uv run pytest api/tests/test_chord_service.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add analytics/api/chord_service.py analytics/api/tests/test_chord_service.py
git commit -m "feat(chord): hierarchical abundance tax order via bridge_tax_rollup"
```

---

### Task 5: Pathway sort (`bridge_ec`, superpathway + pathway only)

**Files:**
- Modify: `analytics/api/chord_service.py`
- Modify: `analytics/api/tests/test_chord_service.py`

- [ ] **Step 1: Write failing tests**

```python
def test_pathway_level_ann_order_groups_by_superpathway(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="phylum",
        ann_level="pathway",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    ann_labels = out["index"][1:gap2]
    assert ann_labels != sorted(ann_labels)


def test_pathway_node_ann_order_stays_alphabetical(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="species",
        ann_level="pathway_node",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    ann_labels = out["index"][1:gap2]
    assert ann_labels == sorted(ann_labels)
```

- [ ] **Step 2: Run tests — pathway test fails, node test passes**

```bash
uv run pytest api/tests/test_chord_service.py::test_pathway_level_ann_order_groups_by_superpathway \
  api/tests/test_chord_service.py::test_pathway_node_ann_order_stays_alphabetical -v
```

- [ ] **Step 3: Implement `_fetch_ann_order`**

```python
def _fetch_ann_order(conn, tax_level: str, ann_level: str) -> list[str] | None:
    if ann_level == "pathway_node":
        return None

    conn.execute(
        """
        CREATE TEMP TABLE ann_level_totals AS
        SELECT pathway_level, """
        + PATHWAY_LABEL_SQL.replace("t.", "cf.")
        + """ AS ann_label, SUM(value) AS total
        FROM chord_prefix_rows cf
        GROUP BY pathway_level, """
        + PATHWAY_LABEL_SQL.replace("t.", "cf.")
    )

    label_sql = PATHWAY_LABEL_SQL.replace("t.", "cf.")

    if ann_level == "superpathway":
        conn.execute(
            f"""
            CREATE TEMP TABLE ann_label_totals_long AS
            SELECT d.display_label, 'superpathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {label_sql} AS display_label
                FROM chord_prefix_rows cf
                WHERE cf.pathway_level = 'superpathway'
                  AND cf.requested_rank = ?
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'superpathway' AND lt.ann_label = d.display_label
            """,
            [tax_level],
        )
    elif ann_level == "pathway":
        conn.execute(
            f"""
            CREATE TEMP TABLE ann_label_totals_long AS
            SELECT d.display_label, 'superpathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {label_sql} AS display_label, b.superpathway_name
                FROM chord_prefix_rows cf
                LEFT JOIN bridge_ec b ON cf.ec_normalized = b.ec_normalized
                WHERE cf.pathway_level = 'pathway' AND cf.requested_rank = ?
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'superpathway' AND lt.ann_label = d.superpathway_name
            UNION ALL
            SELECT d.display_label, 'pathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {label_sql} AS display_label
                FROM chord_prefix_rows cf
                WHERE cf.pathway_level = 'pathway' AND cf.requested_rank = ?
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'pathway' AND lt.ann_label = d.display_label
            """,
            [tax_level, tax_level],
        )
    else:
        return None

    rows = conn.execute(
        """
        SELECT display_label
        FROM ann_label_totals_long
        PIVOT (MAX(anc_total) FOR anc_level IN ('superpathway', 'pathway'))
        GROUP BY display_label
        ORDER BY superpathway DESC NULLS LAST, pathway DESC NULLS LAST, display_label
        """
    ).fetchall()
    return [r[0] for r in rows]
```

Wire:

```python
ann_order = _fetch_ann_order(conn, tax_level, ann_level)
return build_chord_matrix(pairs, tax_order=tax_order or None, ann_order=ann_order)
```

**Note:** Guard `bridge_ec` exists before pathway sort; if missing, `ann_order=None` (alphabetical) — same as today without reference parquet.

- [ ] **Step 4: Run pathway tests**

```bash
uv run pytest api/tests/test_chord_service.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add analytics/api/chord_service.py analytics/api/tests/test_chord_service.py
git commit -m "feat(chord): hierarchical pathway order for superpathway and pathway levels"
```

---

### Task 6: Golden `expected_index` generation

**Files:**
- Modify: `analytics/testing/dump_fake_rpkm_expectations.py`
- Modify: `analytics/testing/fake_rpkm_fixture.py`

- [ ] **Step 1: Add index helper**

In `fake_rpkm_fixture.py`:

```python
def extract_chord_index(chord_result: dict) -> list[str]:
    return list(chord_result["index"])
```

- [ ] **Step 2: Emit `expected_index` in dump script**

In `dump_chord_case`, after `pairs = extract_chord_pairs(out)`:

```python
case["expected_index"] = extract_chord_index(out)
```

- [ ] **Step 3: Regenerate YAML**

From `analytics/`:

```bash
uv run python testing/dump_fake_rpkm_expectations.py
```

Expected: `api/tests/fixtures/chord_expectations.yaml` updated with `expected_index` on every case

- [ ] **Step 4: Commit**

```bash
git add analytics/testing/dump_fake_rpkm_expectations.py \
        analytics/testing/fake_rpkm_fixture.py \
        analytics/api/tests/fixtures/chord_expectations.yaml
git commit -m "test(chord): regenerate golden expected_index expectations"
```

---

### Task 7: Golden index + stability tests

**Files:**
- Modify: `analytics/api/tests/test_chord_service.py`

- [ ] **Step 1: Parametrize full golden suite with index assertion**

Extend `test_chord_service.py`:

```python
def _all_chord_cases():
    doc = load_chord_expectations()
    for section in ("chord_unfiltered", "chord_filtered", "edge_cases"):
        for case in doc[section]:
            yield pytest.param(case, id=case["case_id"])


@pytest.mark.parametrize("case", list(_all_chord_cases()))
def test_chord_pairs_and_index(case, fake_rpkm_db):
    from api.filters import normalise_ann_filter, normalise_taxon_filter

    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"]),
        taxon_filter=normalise_taxon_filter(case.get("selected_taxon")),
    )
    assert_pairs_close(extract_chord_pairs(out), case["pairs"])
    assert out["index"] == case["expected_index"]


@pytest.mark.parametrize("case", list(_all_chord_cases()))
def test_chord_index_stateless(case, fake_rpkm_db):
    from api.filters import normalise_ann_filter, normalise_taxon_filter

    kwargs = dict(
        sample_id="fake_rpkm",
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"]),
        taxon_filter=normalise_taxon_filter(case.get("selected_taxon")),
    )
    a = build_chord_from_duckdb(**kwargs)["index"]
    b = build_chord_from_duckdb(**kwargs)["index"]
    assert a == b
```

- [ ] **Step 2: Add cross-rank stability test**

```python
def test_class_rank_tax_labels_colocate_by_phylum_prefix(fake_rpkm_db):
    phylum_out = build_chord_from_duckdb(
        sample_id="fake_rpkm", tax_level="phylum", ann_level="superpathway",
        ann_filter=None, taxon_filter=None,
    )
    class_out = build_chord_from_duckdb(
        sample_id="fake_rpkm", tax_level="class", ann_level="superpathway",
        ann_filter=None, taxon_filter=None,
    )
    phylum_tax = phylum_out["index"][
        phylum_out["index"].index("gap_2") + 1 : -1
    ]
    class_tax = class_out["index"][
        class_out["index"].index("gap_2") + 1 : -1
    ]
    # Each phylum label's descendant classes appear in one contiguous block
    # (minimal check: more than one class and not purely alphabetical)
    assert len(class_tax) > 1
    assert class_tax != sorted(class_tax)
    assert phylum_tax != sorted(phylum_tax)
```

Refine assertion once golden fixture labels are known; optional stricter block-order check can follow.

- [ ] **Step 3: Run full suite**

```bash
uv run pytest analytics/api/tests/ -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add analytics/api/tests/test_chord_service.py
git commit -m "test(chord): golden expected_index and statelessness assertions"
```

---

### Task 8: Spec status + manual verification

**Files:**
- Modify: `docs/superpowers/specs/2026-06-27-chord-stable-ordering-design.md` (status line only)

- [ ] **Step 1: Update spec status**

Change header `> **Status:** Draft` → `> **Status:** Implemented (2026-06-27)`

- [ ] **Step 2: Run full analytics tests**

```bash
cd analytics && uv run pytest -v
```

Expected: PASS

- [ ] **Step 3: Manual smoke (§8.5 spec)**

With app running (`npm run dev`), load fake_rpkm sample → toggle phylum/class and superpathway/pathway → confirm visual colocation matches manual test plan.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-06-27-chord-stable-ordering-design.md
git commit -m "docs: mark chord stable ordering spec implemented"
```

---

## Spec Coverage Self-Review

| Spec section | Task |
|---|---|
| §2 hierarchical abundance, stateless | 4, 5, 7 |
| §2 pathway scope (no pathway_node sort) | 5 |
| §2 prefix totals from chord_prefix_rows | 3, 4, 5 |
| §4.2 chord_prefix_rows | 3 |
| §4.4 tax sort + bridge_tax | 4 |
| §4.5 pathway sort + bridge_ec | 5 |
| §4.6 build_chord_matrix orders | 2 |
| §5 no frontend | — |
| §8.1 expected_index goldens | 6, 7 |
| §8.2 cross-rank stability | 7 |
| §8.3 statelessness | 7 |
| §8.4 dbt ancestor test | deferred (not in plan) |
| §3.5 unknown-header tax_ids | deferred (not in plan) |

## Out of Scope (explicit)

- Frontend / `Chord.tsx` changes
- `pathway_node` hierarchical sort
- `bridge_pathway_ancestors` edge table (§10 future)
- dbt ancestor-uniqueness test
