# Lineage Alphabetical Ordering — Design Spec

> **Status:** Approved (2026-07-10)  
> **Goal:** Align all analytics API endpoints on hierarchical **alphabetical** lineage ordering for taxa (and pathway annotations where applicable). Replace chord's abundance-based stable ordering with the same lineage sort contract graph, network, and pathway-list already use for tax. Fix krona to sort siblings by the full seven-rank lineage tuple, not only the ranks visible in the sunburst.

**Supersedes (ordering only):**

- `docs/superpowers/specs/2026-06-27-chord-stable-ordering-design.md` — abundance-based chord ordering
- `docs/superpowers/specs/2026-07-08-api-aligned-dbt-model-design.md` §5.4 — chord abundance sort keys

**Parent specs:**

- `docs/superpowers/specs/2026-07-04-graph-dbt-api-design.md` — graph tax lineage ordering (reference implementation)
- `docs/superpowers/specs/2026-07-05-pathway-list-tax-breakdowns-design.md` — pathway-list tax breakdown ordering
- `docs/superpowers/specs/2026-06-30-krona-dbt-api-design.md` — krona sunburst arc order contract

## 1. Context

Six FastAPI viz endpoints return ordered label lists that drive arc/pie layout (`index` arrays, sunburst siblings, list breakdown `index`). Backend ordering is the layout contract — frontends use `pie.sort(null)` / `hierarchy.sort(null)` and do not re-sort by value.

An audit (2026-07-10) found:

| Endpoint | Tax ordering | Ann / EC ordering | Compliant? |
|---|---|---|---|
| Chord | Abundance DESC by lineage rank totals | Abundance DESC on superpathway/pathway totals | **No** |
| Graph | `lineage_order_by_sql()` via `tax_lineage_order.py` | EC numeric tuple sort | Tax yes |
| Network | Same as graph | N/A (pies follow tax cat order) | Tax yes |
| Pathway-list | `tax_cat_order_for_ids_table` | Pathways flat `display_label ASC` | Tax yes |
| Overview | `kingdom ASC, phylum ASC` | Superpathway flat `label ASC` | Yes |
| Krona | Visible ranks only (`phylum, genus, species` for phylum view) | N/A | **Partial** |

Chord was intentionally built with hierarchical **abundance** ordering (2026-06-27) for visual stability across rank changes. The project direction has since converged on **lineage alphabetical** ordering everywhere. Graph, network, and pathway-list tax breakdowns already share `tax_lineage_order.py`; chord and krona are the remaining gaps.

**Out of scope:**

- Legacy Express (`src/server/parse.ts`) ordering
- Graph EC numeric tuple ordering (acceptable — graph is per-pathway)
- Pathway-list pathway flat alphabetical (acceptable — list is scoped to one superpathway)
- Overview superpathway flat alphabetical (acceptable — top level only)
- Network ann/EC ordering (not applicable)
- Chord `pathway_node` ann level (not supported; see §4)

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Tax ordering (all endpoints) | Full lineage lexicographic ASC: `kingdom, phylum, class, "order", family, genus, species, display_name` | Consistent colocation under ancestors; matches graph/network/pathway-list |
| Chord ann ordering | `superpathway_name ASC` at superpathway level; `superpathway_name ASC, pathway_label ASC` at pathway level | Hierarchical alphabetical on pathway axis |
| Chord `pathway_node` | **Not supported** — reject at validation or treat as invalid `ann_level` | No UI use case; removes alphabetical fallback branch |
| Krona sibling order | Full seven-rank `lineage_order_by_sql()` even when sunburst shows fewer rings | Genera from different phyla/kingdoms sort correctly |
| Krona tree structure | Unchanged — `krona_levels(tax_rank)` still controls visible rings via `lineage_segments()` | Only SQL `ORDER BY` changes, not segment logic |
| Tax order module | `analytics/api/tax_lineage_order.py` (existing) | Shared by graph, network, pathway-list, chord |
| Ann order module | **New** `analytics/api/ann_order.py` (separate from tax module) | Aligns with existing `ann_level` / `ann_filter` naming |
| Ann ORDER BY fragment | **`ann_order_by_sql(ann_level)`** in `query_enriched.py` | Mirrors `lineage_order_by_sql()` — stateless SQL only |
| Chord abundance PIVOT | **Delete** — `_rank_totals_cte`, `_tax_label_totals_long_sql`, `_ann_level_totals_cte`, and related fetch functions | Dead code after lineage switch |
| API contracts | Unchanged response shapes (`index`, `count_matrix`, tree JSON) | Order implicit in array position / upsert order |
| Golden pair data | Chord pair values unchanged; order assertions updated | `chord_expectations.yaml` pairs are value-based |

## 3. Architecture

### 3.1 Module division (mirrors tax)

| Layer | Tax | Ann |
|---|---|---|
| **`query_enriched.py`** | `resolve_tax_label_sql`, `lineage_order_by_sql()` | `canonical_pathway_label_sql` (existing), **`ann_order_by_sql(ann_level)`** (new) |
| **Order orchestration** | `tax_lineage_order.py` — temp tables, dedupe, `tax_cat_order_for_ids_table` | **`ann_order.py`** — `ann_labels_ordered(conn, …)` |
| **Has `conn`?** | Orchestration modules only | Orchestration modules only |

`query_enriched` owns stateless SQL fragments (dbt-macro mirrors + `ORDER BY` column lists). Order modules run DuckDB queries and return `list[str]`.

### 3.2 Data flow

```
mart_rpkm_enriched (filtered)
        │
        ├─► query_enriched.py
        │     lineage_order_by_sql()     ann_order_by_sql()
        │     resolve_tax_label_sql()    canonical_pathway_label_sql()
        │
        ├─► tax_lineage_order.py         ann_order.py
        │     tax_cat_order_for_ids…     ann_labels_ordered()
        │
        ├─► graph_service ──► graph_matrix
        ├─► network_service
        ├─► pathway_list_service
        ├─► chord_service ──► chord_matrix   (MODIFY: use both order modules)
        └─► krona_service                    (MODIFY: full lineage ORDER BY)
```

| Module | Role |
|---|---|
| `query_enriched.py` | Stateless SQL: filters, label resolution, **`lineage_order_by_sql()`** and **`ann_order_by_sql()`** |
| `tax_lineage_order.py` | Tax metadata materialization + `tax_cat_order_for_ids_table` (existing; chord adopts) |
| `ann_order.py` | **New** — `ann_labels_ordered()` for chord; imports `ann_order_by_sql` + `canonical_pathway_label_sql` |
| `chord_service.py` | Pair query unchanged; tax/ann order from shared modules; abundance PIVOT removed |
| `krona_service.py` | `_fetch_taxa` selects all lineage cols; `ORDER BY lineage_order_by_sql()` |

## 4. Chord Changes

### 4.1 Tax axis

Replace `_fetch_tax_order` (abundance PIVOT) with the graph/pathway-list pattern:

1. `CREATE OR REPLACE TEMP TABLE chord_tax_ids AS SELECT DISTINCT source_tax_id FROM mart_rpkm_enriched WHERE {filters}`
2. `tax_order = tax_cat_order_for_ids_table(conn, tax_level=…, ids_table="chord_tax_ids")`
3. Pass to `build_chord_matrix(pairs, tax_order=tax_order, ann_order=…)`

### 4.2 Ann axis

**`query_enriched.py`** — add ORDER BY fragment (raw mart columns, not `canonical_pathway_label_sql` CASE):

```python
def ann_order_by_sql(ann_level: str) -> str:
  if ann_level == "superpathway":
      return "superpathway_name ASC"
  if ann_level == "pathway":
      return "superpathway_name ASC, pathway_name ASC"
  raise ValueError(f"unsupported ann_level for ann ordering: {ann_level}")
```

**`ann_order.py`** — orchestration:

```python
def ann_labels_ordered(
    conn, *, ann_level: str, where_sql: str, params: list,
) -> list[str]:
    pathway_label = canonical_pathway_label_sql(ann_level)
    order_by = ann_order_by_sql(ann_level)
    # SELECT DISTINCT {pathway_label} AS display_label
    # FROM mart_rpkm_enriched WHERE {where_sql}
    # ORDER BY {order_by}
```

Thinner than `tax_lineage_order` — no temp metadata table; chord only needs distinct display labels in hierarchical order.

At `ann_level = pathway_node`: **not supported**. `build_chord_from_duckdb` rejects with `ValueError("pathway_node ann_level not supported on chord")` before any DB work. Global `VALID_ANN_LEVELS` is unchanged (other endpoints may still reference the level in filters); chord simply does not accept it as a display level.

Remove `pathway_node` branch from chord ann ordering and `test_pathway_node_ann_order_stays_alphabetical`.

### 4.3 Code to delete from `chord_service.py`

- `_LINEAGE_RANKS`, `_ANN_ORDER_RANKS` (if unused after refactor)
- `_rank_totals_cte`
- `_tax_lineage_select`
- `_tax_label_totals_long_sql`
- `_fetch_tax_order` (abundance version)
- `_ann_level_totals_cte`
- `_fetch_ann_order` (abundance version)

`build_chord_matrix` / `_apply_order` in `chord_matrix.py` unchanged — still accepts explicit order lists.

## 5. Krona Changes

### 5.1 Problem

`_order_by_clause(levels)` builds `ORDER BY` from `krona_levels(tax_rank)` only — e.g. phylum view sorts `phylum, genus, species`. Coarser ranks (kingdom, class, …) are ignored, so siblings at the same displayed rank may appear in a different order than graph/chord would place them.

### 5.2 Fix

In `_fetch_taxa`:

1. **SELECT** all `TAX_RANK_ORDER` label columns plus `display_name` (for row → taxon mapping), in addition to `SUM(value)` and `krona_levels` columns used by `lineage_segments`.
2. **ORDER BY** `lineage_order_by_sql()` from `query_enriched.py` (import only the SQL fragment; no tax_lineage_order dependency required).
3. **GROUP BY** unchanged: `source_tax_id, display_name, {krona_levels cols}`.
4. **`_order_by_clause`** — delete or replace with `lineage_order_by_sql()`; no longer level-scoped.
5. **Tree building** — unchanged: `build_tree_from_taxa(taxa, krona_levels(tax_rank))`.

Upsert append order = sunburst arc order (existing contract).

## 6. Endpoints — No Change

| Endpoint | Reason |
|---|---|
| Graph | Tax lineage ASC + EC numeric tuple already correct |
| Network | Inherits graph tax cat order |
| Pathway-list | Tax breakdown lineage ASC; pathways flat alpha within one superpathway |
| Overview | Kingdom→phylum and superpathway flat alpha already correct |

## 7. Testing

### 7.1 Chord (`test_chord_service.py`)

| Test | Action |
|---|---|
| `test_phylum_rank_tax_order_by_abundance_not_alphabetical` | Rename/rewrite → assert tax labels match lineage alphabetical order |
| `test_pathway_level_ann_order_groups_by_superpathway` | Rewrite → assert ann labels sorted by `(superpathway, pathway)` lexicographic |
| `test_pathway_node_ann_order_stays_alphabetical` | **Remove** (pathway_node not supported) |
| `test_class_rank_tax_labels_colocate_by_phylum_prefix` | Rewrite → assert lineage colocation (same phylum block), not abundance prefix |
| Pair golden tests | Unchanged (values only) |

### 7.2 Krona (`test_krona_service.py`)

- Regenerate `krona_expectations.yaml` if sibling arc order changes on `fake_rpkm`.
- Add unit test: genus view `ORDER BY` clause includes `kingdom` before `genus` (mock or SQL string assertion).

### 7.3 New / updated tests

**`test_query_enriched.py`:** `ann_order_by_sql` for superpathway and pathway levels.

**`test_ann_order.py`:** `ann_labels_ordered` returns labels in hierarchical alphabetical order on `fake_rpkm`.

### 7.4 Regression

- `test_graph_network_parity.py` — unchanged.
- `test_pathway_list_service.py` — unchanged.
- `test_tax_lineage_order.py` — unchanged.
- Full `uv run pytest api/tests/ -q` on `fake_rpkm` fixture.

## 8. Implementation Notes

- **Minimal diff:** chord_service shrinks significantly once abundance PIVOT is removed.
- **No frontend changes** — order is backend-only.
- **Colors:** `get_color(i, n)` is index-position-based; label colors may shift when order changes — expected and acceptable.
- **Comparison mode:** unchanged (still rejected on DuckDB backend).

## 9. Open Items (resolved)

| Question | Resolution |
|---|---|
| Abundance vs alphabetical for chord? | Full lineage alphabetical (option A) |
| Ann helpers location? | `ann_order_by_sql()` in `query_enriched.py`; orchestration in `ann_order.py` |
| Ann naming? | `ann_order` (not "lineage") — aligns with `ann_level`, `ann_filter` |
| Chord pathway_node? | Not supported |
| Graph EC / pathway-list / overview ann? | No change |
