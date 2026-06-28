# Chord Stable Ordering — Design Spec

> **Status:** Implemented (2026-06-27)  
> **Goal:** Preserve relative order of taxa and pathways across rank/level changes so the chord diagram stays visually stable during drill-down. Classes from the same phylum remain colocated at the phylum’s former position; pathway children stay under their superpathway block.

**Parent specs:**
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — DuckDB chord backend
- `docs/superpowers/specs/2026-06-27-chord-reactive-fetch-design.md` — reactive refetch on rank/filter change

**Work isolation:** Branch `feature/chord-dbt-api` in worktree `.worktrees/chord-dbt-api/`.

## 1. Context

### 1.1 Problem

Today, chord label order reshuffles on every refetch because **backend** `build_chord_matrix` uses flat `sorted()` (alphabetical) on unique labels — unrelated labels at a finer rank appear in a different order with no hierarchical relationship to coarser ranks.

**Frontend:** No changes required. `Chord.tsx` does not set `sortGroups`, so arc positions already follow matrix `index` order from the API. Existing `sortSubgroups(d3.descending)` only affects ribbon stacking within each arc, not label position (see §5).
When the user changes taxonomy rank (e.g. phylum → class) via the rank selector, labels at the new rank appear in a different order. Sibling classes from the same phylum are not colocated. The diagram feels unstable.

Arc-click drill-down (filter + rank bump) refetches from the API; stable backend ordering gives order stability for drill-down as well. Arc size growth after filtering is acceptable — only order stability is required for drill-down.

### 1.2 Primary trigger

| Trigger | Order stability required? |
|---|---|
| Manual rank/level selector change | **Yes (primary)** |
| Arc-click drill-down + refetch | **Yes (inherits from backend order)** |
| Filter chip clear | **Yes (same stateless rules)** |

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Ordering strategy | Hierarchical abundance-based only | User preference; alphabetical fallback dropped |
| Sort owner | Backend (`chord_service` + `build_chord_matrix`) | Stateless; same rank always same order |
| Statelessness | Order is a pure function of `(sample, tax_level, ann_level, filters)` | No navigation history; kingdom→class and phylum→class yield identical class order |
| Prefix totals scope | Computed from the **same filtered row set** as pairs | Filtered-out taxa/pathways do not count toward prefix totals |
| API contract | Unchanged (`index`, `count_matrix`, `colors`) | Order implicit in `index` array position |
| Hierarchy lookup for sort | Tax: `bridge_tax_rollup`; pathway: `bridge_ec_pathway` via existing `bridge_ec` temp table (§4.5) | Filtered totals from `chord_prefix_rows`; ancestor **labels** from reference bridges |
| Pathway sort scope | **`superpathway` and `pathway` only** | No UI use case for `pathway_node` stable ordering in v1; see fallback below |
| Reference bridges at sort time | `bridge_tax_rollup` + existing `bridge_ec` temp table | `bridge_ec` already loaded for ann filters; reused for pathway sort hierarchy |
| Ann filter predicates | Existing `bridge_ec` temp table | Same temp table serves filter predicates and pathway sort ancestor lookup |
| Ancestor uniqueness | Assumed valid; validated in dbt (deferred) | No defensive `DISTINCT` dedup in chord service |
| Drill-down arc sizes | May grow after filter | Only order stability matters for drill-down |

## 3. Ordering Model

### 3.1 Rank sequences

**Tax ranks** (coarse → fine):

```
kingdom → phylum → class → order → family → genus → species
```

**Pathway levels** (coarse → fine):

```
superpathway → pathway → pathway_node
```

**Stable ordering scope (pathway axis):** Hierarchical sort applies to **`superpathway` and `pathway` only** (the levels the Chord UI toggles between). At `ann_level = pathway_node`, fall back to flat alphabetical order via `build_chord_matrix` (`ann_order=None`) — same as today.

The Chord UI rank selector uses `kingdom … genus` (no `species`). Reference data and sort SQL include all seven tax ranks for consistency with `int_tax_rollup_resolved`.

### 3.2 Sort key (abundance)

For display rank **R**, each label’s sort key is a prefix of abundance totals at **R and all coarser ranks**, descending, with label as tie-break:

```
(-total_at_kingdom, -total_at_phylum, …, -total_at_R, label)
```

Only ranks ≤ R participate. Examples:

| Display rank | Sort tuple |
|---|---|
| kingdom | `(-kingdom_total, label)` |
| phylum | `(-kingdom_total, -phylum_total, label)` |
| class | `(-kingdom_total, -phylum_total, -class_total, label)` |

**Colocation property:** At class rank, all classes under `Firmicutes` share the same `(-kingdom_total, -phylum_total)` prefix (Firmicutes’ totals). They sort adjacently in the block where `Firmicutes` appeared at phylum rank. They are ordered among themselves by `-class_total`.

**Pathway axis** follows the same pattern for **`superpathway` and `pathway` only** (§3.1). At `ann_level = pathway`:

```
(-superpathway_total, -pathway_total, label)
```

At `ann_level = superpathway`:

```
(-superpathway_total, label)
```

At `ann_level = pathway_node`: hierarchical sort **not applied** — flat alphabetical fallback.

### 3.3 Filters and totals

All totals — prefix and leaf — come from rows that pass the same predicates as the pair query:

- Sample scope
- `selected_taxon` filter (via `source_tax_id` subquery)
- `selected_ann_cat` filter (via `bridge_ec` / pathway predicates)

Mass from filtered-out taxa or pathways does **not** contribute to any rank’s prefix total.

### 3.4 Ancestor completeness (data guarantee)

Missing ancestor ranks in the sort prefix **do not occur** for labels visible in the chord. This is guaranteed by how reference taxonomy and the rollup pipeline are built — not by defensive `COALESCE` in the sort SQL.

**Reference taxonomy (`parents` table):** Every tax_id in `bridge_tax_rank_map` comes from `parents` rank columns (`t_kingdom` … `t_species`). The exploration notebook validates rank ladder completeness: 0 violations for `species_missing_upstream` through `kingdom_with_finer_but_missing_phylum`, and 0 rank transitive snapshot mismatches (see `analytics/exploration/docs/data-model.md` §Reference Tables, §Regression Validation Targets). The taxonomy build notebook (`resources/scripts/make_tax_hierarchy_database_source.ipynb`) walks each tax_id’s lineage and fills all rank slots via `get_all_parents`.

**Rollup bridge (`bridge_tax_rollup`):** Known tax_ids fan out to exactly seven `(source_tax_id, requested_rank)` rows — one per rank from kingdom through species (`build_reference.py` `all_combos` CROSS JOIN). Each row carries a resolved label (exact rank match, coarser fallback, or `'Unclassified'` when the tax_id is in reference but has no match at that rank). This is a **resolved label**, not a missing rank.

**Chord visibility:** The chord query filters `WHERE requested_rank = :tax_level`. Tax_ids absent from `bridge_tax_rollup` (unknown column headers not in reference) produce `requested_rank = NULL` in `int_tax_rollup_resolved` and are **excluded entirely** — they never appear as sort labels (see `2026-06-22-chord-golden-tests-design.md` §12).

**Implication for sort SQL:** For every `source_tax_id` in the chord matrix, `bridge_tax_rollup` provides exactly one `resolved_tax_label` per prefix rank (≤7 rows). Joining `d.source_tax_id` to the bridge and looking up totals in `rank_totals` yields one ancestor total per applicable rank. PIVOT cells for ranks finer than the display rank are NULL for all labels and are no-ops in `ORDER BY … NULLS LAST`. No `COALESCE(..., 0)` fallback is required for missing ancestors.

**`'Unclassified'` labels (in reference):** Participate in ordering like any other resolved label, with their own abundance total at that rank. This covers tax_ids present in `bridge_tax_rollup` that resolve to `'Unclassified'` at a rank (bridge Unclassified case).

### 3.5 Deferred — unknown-header tax_ids (out of scope)

**Problem:** Sample column headers (`source_tax_id`) absent from `bridge_tax_rollup` produce `requested_rank = NULL` in `int_tax_rollup_resolved` and are dropped by `WHERE requested_rank = :tax_level`. Their mass never reaches the chord matrix today. This is a **pre-existing pipeline gap**, not introduced or fixed by stable ordering.

**Contrast with unmapped EC (working):** Unmapped ECs are preserved by a LEFT JOIN in `int_rpkm_pathway` (`pathway_key IS NULL`), fan out through tax rollup with valid `requested_rank` values, and render as `'Unmapped EC'` via `COALESCE(pathway_label, 'Unmapped EC')` in the mart and `PATHWAY_LABEL_SQL` in `chord_service.py`. Unknown tax_ids fail earlier: the tax LEFT JOIN yields NULL `requested_rank`, so no COALESCE in chord SQL can recover them.

**Deferred fix (pipeline, not chord ordering):** Synthesize seven `requested_rank` rows with `'Unclassified'` for unknown-header tax_ids in `int_tax_rollup_resolved` (UNION pattern). Once that lands, stable ordering applies automatically — no chord-service special case.

**Authoritative docs:**

| Doc | Section | Content |
|---|---|---|
| `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` | §6.6 | Unmapped EC: LEFT JOIN preserves rows; `pathway_key IS NULL` |
| `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` | §6.7 | Unknown header tax_id case; deferred UNION fix |
| `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` | §6.8 | Mart `COALESCE(pathway_label, 'Unmapped EC')` |
| `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` | §12 | Three-case table (known / bridge Unclassified / unknown header); fixture `999999999` |
| `analytics/exploration/docs/data-model.md` | RPKM Wide Format, Edge evidence | Test fixtures: 100% tax_id header match; production samples may differ |

**This spec assumes:** Only labels that already reach `int_tax_rollup_resolved` with a non-null `requested_rank` are ordered. Unknown-header mass remains excluded until the pipeline fix above is implemented.

**Also deferred (separate):** Ancestor-uniqueness per `(display_label, anc_rank)` — dbt test (§8.4); duplicate-ancestor validation, not missing-ancestor handling.

## 4. Architecture

### 4.1 Pipeline overview

```
build_chord_from_duckdb()
  ├─ CREATE TEMP bridge_tax       (reference rollup — tax sort ancestor labels)
  ├─ CREATE TEMP chord_prefix_rows  (filtered rows through display rank/level — prefix scope)
  ├─ SELECT pairs                 (existing matrix cell logic)
  ├─ SELECT tax display_label …   (pivot + ORDER BY → tax_order)
  ├─ SELECT ann display_label …   (pivot + ORDER BY → ann_order; skip if ann_level = pathway_node)
  └─ build_chord_matrix(pairs, tax_order, ann_order)
```

`build_chord_matrix` remains a pure matrix builder (no DB access). It accepts explicit order lists instead of flat `sorted()`.

### 4.2 Shared prefix-row temp table (`chord_prefix_rows`)

One `CREATE TEMP TABLE chord_prefix_rows AS …` per request, reused by all downstream queries. Rows are filter-scoped **and** rank/level-scoped to the **prefix** through the current display rank and pathway level (coarser ancestors included; finer ranks/levels excluded):

```sql
CREATE TEMP TABLE chord_prefix_rows AS
SELECT
    source_tax_id,
    requested_rank,
    resolved_tax_label,
    resolved_tax_id,
    pathway_key,
    pathway_level,
    pathway_label,
    ec_normalized,
    value
FROM int_tax_rollup_resolved t
WHERE requested_rank IN (…)          -- ranks_from_root_to(tax_level): coarser + display rank only
  AND pathway_level IN (…)           -- ann_levels_from_root_to(ann_level): coarser + display level only
  AND (<tax_subquery>)
  AND (<ann_sql>)
```

**Filter scope:** One shared temp table per request. `requested_rank` is restricted to `ranks_from_root_to(tax_level)`; `pathway_level` is restricted to `ann_levels_from_root_to(ann_level)`. Both sort axes and the pair query read from this table — finer ranks/levels are never loaded.

**Pair query reads:** `chord_prefix_rows WHERE requested_rank = :tax_level AND pathway_level = :ann_level` with existing `GROUP BY pathway_key, resolved_tax_id, labels`.

### 4.3 Pair query (unchanged semantics)

The existing pair aggregation moves to read from `chord_prefix_rows`:

```sql
SELECT
    <PATHWAY_LABEL_SQL> AS pathway_label,
    t.resolved_tax_label,
    SUM(t.value) AS value
FROM chord_prefix_rows t
WHERE t.requested_rank = ?
  AND t.pathway_level = ?
GROUP BY t.pathway_key, t.resolved_tax_id,
         <PATHWAY_LABEL_SQL>,
         t.resolved_tax_label
HAVING SUM(t.value) > 0
```

This query is **not replaced** by the sort queries — different grouping grain.

### 4.4 Tax sort query

**Reference bridge** (loaded once per request, same pattern as `bridge_ec` for ann filters):

```sql
CREATE TEMP TABLE bridge_tax AS
SELECT source_tax_id, requested_rank, resolved_tax_label
FROM read_parquet('…/bridge_tax_rollup.parquet')
```

The parquet holds ~20M rows globally; the join keys on `source_tax_id` from `d` (sample-sized — typically tens to hundreds of tax_ids).

**Step 1 — rank totals** (one pass over `chord_prefix_rows`):

```sql
-- Aggregates away row-level fan-out: one total per (rank, label). No join — no fan-out.
CREATE TEMP TABLE rank_totals AS
SELECT requested_rank, resolved_tax_label, SUM(value) AS total
FROM chord_prefix_rows
GROUP BY requested_rank, resolved_tax_label
```

**Step 2 — long format** (display labels joined to ancestor totals via bridge):

```sql
CREATE TEMP TABLE tax_label_totals_long AS
SELECT
    d.display_label,
    b.requested_rank AS anc_rank,
    rt.total         AS anc_total
FROM (
    -- One row per (source_tax_id, display_label) at the display rank and pathway slice.
    -- Taxonomy is identical across pathway levels for a given (source_tax_id, requested_rank),
    -- so DISTINCT alone would suffice without the pathway_level filter; the filter matches
    -- the pair-query slice and avoids scanning 2–3× redundant rows.
    SELECT DISTINCT source_tax_id, resolved_tax_label AS display_label
    FROM chord_prefix_rows
    WHERE requested_rank = :tax_level
      AND pathway_level = :ann_level
) d
-- At most 7 rows per source_tax_id (one per rank in bridge_tax_rollup).
JOIN bridge_tax b ON b.source_tax_id = d.source_tax_id
JOIN rank_totals rt
  ON rt.requested_rank = b.requested_rank
 AND rt.resolved_tax_label = b.resolved_tax_label
```

**Why `bridge_tax_rollup` not `chord_prefix_rows` self-join:** Taxonomy is a property of `source_tax_id` — the bridge has exactly one `resolved_tax_label` per `(source_tax_id, requested_rank)`. Self-joining `chord_prefix_rows` on `source_tax_id` would re-read the same ancestor labels once per EC×pathway row (fan-out grows with EC/pathway cardinality, not rank depth). The bridge caps Step 2 at ≤7 rows per tax_id.

**Assumption:** For each `(display_label, anc_rank)` there is exactly one `anc_total`. Duplicate `(display_label, anc_rank, anc_total)` tuples can still arise when multiple `source_tax_id`s share a display label at coarse ranks — `PIVOT MAX` dedupes in Step 3. Conflicting ancestor mappings for the same `(display_label, anc_rank)` are a data bug — caught by a deferred dbt test (§8.4).

**Step 3 — pivot + order** (static SQL; hardcoded full rank list):

```sql
-- Collapses duplicate (display_label, anc_rank) rows when multiple tax_ids share a label.
SELECT display_label
FROM tax_label_totals_long
PIVOT (
    MAX(anc_total)   -- MAX is dedup only; all duplicates share the same anc_total
    FOR anc_rank IN (
        'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'
    )
)
GROUP BY display_label
ORDER BY
    kingdom DESC NULLS LAST,
    phylum  DESC NULLS LAST,
    class   DESC NULLS LAST,
    "order" DESC NULLS LAST,
    family  DESC NULLS LAST,
    genus   DESC NULLS LAST,
    species DESC NULLS LAST,
    display_label
```

DuckDB creates columns for all ranks in the `IN` list; ranks not present in `rank_totals` are NULL for every row. NULL columns in `ORDER BY … NULLS LAST` are ties — they do not affect relative order among labels. No Python-generated `CASE WHEN` or dynamic `ORDER BY`.

`MAX(anc_total)` in `PIVOT` satisfies aggregate syntax; with the ancestor-uniqueness assumption there is one value per cell.

### 4.5 Pathway sort query

**Scope:** `ann_level IN ('superpathway', 'pathway')` only. Reuses the existing `bridge_ec` temp table (from `bridge_ec_pathway.parquet`, already loaded for ann filter predicates). Wide bridge shape — ancestor names are **columns on the same row** as `ec_normalized` (`superpathway_name`, `pathway_name`).

At `ann_level = pathway_node`: skip this query; pass `ann_order=None` to `build_chord_matrix` (alphabetical fallback).

**Step 1 — level totals** (one pass over `chord_prefix_rows`):

```sql
-- Aggregates away row-level fan-out: one total per (pathway_level, label). No join — no fan-out.
CREATE TEMP TABLE ann_level_totals AS
SELECT pathway_level, <PATHWAY_LABEL_SQL> AS ann_label, SUM(value) AS total
FROM chord_prefix_rows
GROUP BY pathway_level, <PATHWAY_LABEL_SQL>
```

**Step 2 — long format** (display labels joined to ancestor totals via wide `bridge_ec`):

At **`ann_level = superpathway`** — no ancestor prefix; leaf total only:

```sql
CREATE TEMP TABLE ann_label_totals_long AS
SELECT
    d.display_label,
    'superpathway' AS anc_level,
    lt.total       AS anc_total
FROM (
    SELECT DISTINCT <PATHWAY_LABEL_SQL> AS display_label
    FROM chord_prefix_rows
    WHERE pathway_level = 'superpathway'
      AND requested_rank = :tax_level
) d
JOIN ann_level_totals lt
  ON lt.pathway_level = 'superpathway'
 AND lt.ann_label = d.display_label
```

At **`ann_level = pathway`** — superpathway prefix via bridge column pick:

```sql
CREATE TEMP TABLE ann_label_totals_long AS
SELECT
    d.display_label,
    'superpathway' AS anc_level,
    lt.total       AS anc_total
FROM (
    -- DISTINCT collapses multi-node EC fan-out in bridge_ec (same superpathway per EC).
    SELECT DISTINCT
        <PATHWAY_LABEL_SQL> AS display_label,
        b.superpathway_name
    FROM chord_prefix_rows cf
    LEFT JOIN bridge_ec b ON cf.ec_normalized = b.ec_normalized
    WHERE cf.pathway_level = 'pathway'
      AND cf.requested_rank = :tax_level
) d
JOIN ann_level_totals lt
  ON lt.pathway_level = 'superpathway'
 AND lt.ann_label = d.superpathway_name

UNION ALL

SELECT
    d.display_label,
    'pathway' AS anc_level,
    lt.total  AS anc_total
FROM (
    SELECT DISTINCT <PATHWAY_LABEL_SQL> AS display_label
    FROM chord_prefix_rows
    WHERE pathway_level = 'pathway'
      AND requested_rank = :tax_level
) d
JOIN ann_level_totals lt
  ON lt.pathway_level = 'pathway'
 AND lt.ann_label = d.display_label
```

**Why wide `bridge_ec` not `chord_prefix_rows` self-join:** Pathway hierarchy is per EC. The wide bridge carries `superpathway_name` and `pathway_name` on the same row — ancestor lookup is a column pick after joining on `ec_normalized`, not a self-join across materialized `pathway_level` fan-out. `LEFT JOIN` handles unmapped ECs (`superpathway_name` NULL → `ORDER BY … NULLS LAST`).

**Step 3 — pivot + order** (static SQL; two-level list only):

```sql
SELECT display_label
FROM ann_label_totals_long
PIVOT (
    MAX(anc_total)
    FOR anc_level IN ('superpathway', 'pathway')
)
GROUP BY display_label
ORDER BY
    superpathway DESC NULLS LAST,
    pathway      DESC NULLS LAST,
    display_label
```

**At `ann_level = superpathway`:** only the `superpathway` column is populated; `pathway` is NULL for all rows — no-op in `ORDER BY … NULLS LAST`.

**Tax vs pathway sort (summary):**

| | Tax sort (§4.4) | Pathway sort (§4.5) |
|---|---|---|
| Bridge | `bridge_tax_rollup` (long: one row per rank) | `bridge_ec_pathway` (wide: ancestor columns per EC) |
| Scope | All seven tax ranks | `superpathway`, `pathway` only |
| Display filter (`d`) | `requested_rank = :tax_level AND pathway_level = :ann_level` | `pathway_level = :ann_level AND requested_rank = :tax_level` |
| Ancestor lookup | `JOIN bridge_tax ON source_tax_id` (≤7 rows/tax_id) | `LEFT JOIN bridge_ec ON ec_normalized`; read `superpathway_name` |
| Fallback | — | `pathway_node` → flat `sorted()` |

Filtered totals always from `chord_prefix_rows`.

### 4.6 `build_chord_matrix` changes

```python
def build_chord_matrix(
    pairs: list[tuple[str, str, float]],
    tax_order: list[str] | None = None,
    ann_order: list[str] | None = None,
) -> dict:
    tax_cats = _apply_order({tax for _, tax, _ in pairs}, tax_order)
    ann_cats = _apply_order({ann for ann, _, _ in pairs}, ann_order)
    ...
```

`_apply_order(unique_labels, order_list)`:

1. If `order_list` provided: emit labels in that order, then any extras not in the list (should not occur in production).
2. If `None`: fall back to `sorted()` for existing tests/callers without order lists — used for **`pathway_node`** ann level (§4.5) and legacy callers.

Colors continue to index by position in `ann_cats` / `tax_cats` after ordering.

## 5. Frontend (no changes)

Stable label order is entirely determined by backend `index` array order. **No frontend changes in scope.**

`Chord.tsx` uses `d3.chord().padAngle(0).sortSubgroups(d3.descending)` and does **not** set `sortGroups`. Relevant D3 behavior:

| API | Used? | Effect |
|---|---|---|
| `sortGroups` | No | Would reorder arcs around the ring — **not** in our code |
| `sortSubgroups(d3.descending)` | Yes | Ribbon slice stack order within each arc (largest flow first) — **does not move labels** |
| Matrix `index` order | Via API | Default group order → **label position on the ring** |

**Out of scope:** Removing or changing `sortSubgroups`. It does not conflict with stable ordering; keeping it preserves existing ribbon-stacking behavior.

## 6. Complexity

**Variables** (per chord request):

| Symbol | Meaning |
|---|---|
| `n` | Rows in `chord_prefix_rows` (`int_tax_rollup_resolved` rows at prefix ranks/levels + filters) |
| `t` | Distinct tax labels at display rank (`resolved_tax_label` count on tax side) |
| `a` | Distinct annotation labels at display rank (`pathway_label` count on ann side) |

| | Per request |
|---|---|
| Extra SQL | `bridge_tax` temp table + shared `chord_prefix_rows` + `rank_totals` / `ann_level_totals` + two pivot/order SELECTs |
| Time | O(n) scan for filtered rows + O(n) for level/rank totals + O(t × 7) tax bridge join + O(a) pathway bridge join + O(a log a + t log t) sort |
| Memory | Temp tables in DuckDB; negligible vs matrix build O((t+a)²) |
| Persistent storage | None |

Compared to flat alphabetical sort, hierarchical abundance adds one grouped aggregation pass over filtered rows — not one query per rank.

## 7. File Changes

| File | Change |
|---|---|
| `analytics/api/chord_service.py` | Load `bridge_tax_rollup` temp table; shared `chord_prefix_rows`; tax/ann order queries (ann sort skipped at `pathway_node`); pass order lists to matrix builder |
| `analytics/api/chord_matrix.py` | Accept `tax_order` / `ann_order`; `_apply_order` helper |
| `analytics/testing/dump_fake_rpkm_expectations.py` | Emit `expected_index` per golden case |
| `analytics/api/tests/fixtures/chord_expectations.yaml` | Add `expected_index` assertions |

No API route or response schema changes.

## 8. Testing

### 8.1 Golden tests — index order

Existing golden tests compare sorted `(pathway_label, resolved_tax_label, value)` pairs (order-independent). Add `expected_index` alongside `expected_pairs`:

```yaml
- case_id: phylum_pathway
  tax_level: phylum
  ann_level: pathway
  expected_pairs: [...]
  expected_index:
    - gap_1
    - Oxidative phosphorylation
    - Glycolysis
    - gap_2
    - Firmicutes
    - Proteobacteria
    - gap_3
```

Regenerate expectations via `dump_fake_rpkm_expectations.py` after implementation. Fixture RPKM values are fixed — index order is fully deterministic.

### 8.2 Cross-rank stability assertion

For the fake_rpkm fixture, assert that class-rank `index` tax section (between `gap_2` and `gap_3`) groups classes by phylum block in the same relative order as phylum-rank labels appeared at phylum rank. At minimum: two cases at different tax ranks with overlapping hierarchy produce consistent prefix ordering (automated check or documented manual case).

### 8.3 Statelessness assertion

Run the same golden case twice; assert identical `index`. Optionally shuffle input row order in fixture processing — assert identical `index`.

### 8.4 Deferred dbt validation

Add a dbt test (separate task) asserting unique ancestor per `(display_label, anc_rank)` — e.g. no class label maps to two different phylum labels for the same sample. Not in scope for the chord ordering implementation.

### 8.5 Manual test plan

- [ ] Load test files → Chord at phylum rank → note tax arc order
- [ ] Switch to class rank → classes from same phylum are adjacent; phylum blocks in same relative order
- [ ] Switch kingdom → class directly → same class order as phylum → class path
- [ ] Toggle superpathway ↔ pathway → pathway children stay under superpathway block
- [ ] At `pathway_node` ann level → alphabetical order (no regression from today)
- [ ] Apply taxon filter → order stable within filtered subset; filtered-out mass excluded from totals
- [ ] Arc-click drill-down → order stable; arcs may grow (acceptable)

## 9. Success Criteria

- [ ] Rank selector changes produce hierarchy-stable label order (tax axis; pathway axis at `superpathway` / `pathway` only)
- [ ] Same `(sample, tax_level, ann_level, filters)` always returns the same `index` order
- [ ] Classes colocate by phylum; pathways colocate by superpathway
- [ ] Filtered-out taxa/pathways excluded from prefix abundance totals
- [ ] API response shape unchanged
- [ ] Golden tests assert `expected_index`
- [ ] Arc label order on the ring matches backend `index` (no frontend change required; existing D3 layout already uses matrix index order)

## 10. Future Considerations

- **`pathway_node` hierarchical sort** — no current UI use case; v1 uses flat alphabetical fallback at `pathway_node`. Add when drill-down reaches EC-node level and stable colocation is required.
- **`bridge_pathway_ancestors` edge table** — potential derived reference artifact: `(display_level, display_label, anc_level, anc_label[, pathway_key])` tuples built from `bridge_ec_pathway` at `build_reference.py` time. Would make pathway Step 2 symmetric with tax sort (join on display label, no EC in sort SQL). Deferred in favor of wide `bridge_ec` column pick for v1.
- **Unknown-header tax_ids in chord** — deferred pipeline fix; synthesize seven rank rows with `'Unclassified'` in `int_tax_rollup_resolved`. See §3.5; `2026-06-15-rpkm-transform-design.md` §6.7; `2026-06-22-chord-golden-tests-design.md` §12. Stable ordering requires no chord-service changes once this lands.
- **dbt ancestor-uniqueness test** — validate `(display_label, anc_rank) → anc_label` is unique per sample (§8.4)
- **Node legacy backend** — `parse_ec_data` in `src/server/parse.ts` still uses flat `sortBy`; out of scope unless Node chord path is revived
- **Comparison mode** — not supported on DuckDB backend; ordering spec applies when comparison is added

## 11. References

- `analytics/api/chord_service.py` — current pair query
- `analytics/api/chord_matrix.py` — current flat sort
- `src/renderer/src/components/Chord.tsx` — D3 chord layout (unchanged; reference for `sortSubgroups` behavior)
- `analytics/transform/models/intermediate/int_tax_rollup_resolved.sql` — all-rank fanout per source_tax_id
- DuckDB PIVOT docs — `IN` list with missing values → NULL columns
- `analytics/exploration/docs/data-model.md` — rank ladder completeness, RPKM tax_id header joins
- `resources/scripts/make_tax_hierarchy_database_source.ipynb` — lineage walk filling all rank slots
- `analytics/transform/scripts/build_reference.py` — `bridge_tax_rank_map`, `bridge_tax_rollup` seven-rank fanout
- `docs/superpowers/specs/2026-06-27-chord-reactive-fetch-design.md` — refetch on rank change
- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline semantics; §6.6 unmapped EC; §6.7 unknown tax_id deferral
- `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` — §12 unknown header tax_id behavior and fixture
