# API-Aligned dbt Sample Model — Design Spec

> **Status:** Approved (2026-07-08)  
> **Goal:** Redesign the dbt upload pipeline and reference bridges so all six viz API endpoints read a single enriched mart from `sample.duckdb`, with canonical label/rollup semantics defined once in dbt macros — eliminating runtime reference parquet reads, the 21× intermediate fan-out, and API/API-vs-dbt logic duplication.

**Parent pipeline:** `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md`

**Related specs:**

- `docs/superpowers/specs/2026-06-28-stress-rpkm-generator-design.md` — scale / performance validation target
- `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` — `fake_rpkm` correctness fixture (unchanged)

**Supersedes (in part):** Intermediate/mart shapes and API query patterns described in the chord, overview, pathway-list, krona, graph, and network API design specs. API JSON contracts are unchanged.

## 1. Context

### 1.1 Problem

The rpkm-transform pipeline was built with `mart_pathway_taxonomy_long` as the canonical output, intended to serve API use cases. In practice:

- **No API endpoint reads the mart.** All six viz endpoints query `int_tax_rollup_resolved` or `int_rpkm_by_ec_tax` and re-apply filters, bridge joins, label synthesis, and aggregation at request time.
- **`int_tax_rollup_resolved` stores a 21× fan-out** (7 taxonomy ranks × 3 pathway levels per upstream row), inflating storage (~185K rows for `test_rpkm_1`) while the mart filters to a single rank×level pair.
- **Reference bridges are re-read per request** — notably the full 166 MB `bridge_tax_rollup.parquet` on chord (~310 ms) and krona (~379 ms), despite dbt having already joined bridges at upload.
- **Label semantics diverge** between dbt (`mart_pathway_taxonomy_agg` macro) and API (`PATHWAY_LABEL_SQL` in `rollup_query.py`), creating bug risk (e.g. `pathway_node` rows with `pathway_label = NULL`).

### 1.2 Constraints (locked in during brainstorming)

| Constraint | Choice |
|---|---|
| Primary goal | API query simplicity and correctness (single source of truth for labels/rollup) |
| Scope | All six endpoints in one unified sample data model |
| Build stages | **Separate** — reference bridges at container/distribution build; `sample.duckdb` at upload. Do not merge stages. |
| Reference in sample DB | Do **not** duplicate full reference bridges. Only sample-scoped dimension rows and the enriched mart. |
| Reference parquet | Consolidate to **one** taxonomy bridge (wide format). Do not ship both long and wide. |

### 1.3 Scale and validation targets

Two tiers, mirroring the stress-generator spec:

| Tier | Fixture | Shape | Role |
|---|---|---|---|
| **Correctness** | `fake_rpkm`, `test_rpkm_1` / `test_rpkm_2` | 8–12 tax cols, ~426–461K rows, ~1.7% nonzero | Golden tests, semantic edge cases |
| **Scale / performance** | `stress_rpkm_1` / `stress_rpkm_2` (see `2026-06-28-stress-rpkm-generator-design.md`) | **100** tax cols, 425,828 / 461,112 rows, **0.95** density, pathway-mapped ECs only | Pipeline + API stress validation |

At stress defaults, measured on `stress_rpkm_1` (generated in worktree `.worktrees/feature/api-aligned-dbt-model/`, 2026-07-09):

| Stage / table | Rows | Notes |
|---|---|---|
| Wide TSV | 425,828 rows × 100 tax cols | 388 MB on disk; 95.0% nonzero rate |
| `stg_rpkm_long` | **40,453,328** | After nonzero filter |
| `int_rpkm_by_ec_tax` | **386,700** | = 3,867 ECs × 100 tax_ids (fully saturated) |
| `int_rpkm_pathway` | 1,661,100 | 3× pathway levels + EC fan-out (1.83× per EC-tax pair) |
| `int_tax_rollup_resolved` | **11,627,700** | = 386,700 × 21 rank×level fan-out |
| `mart_rpkm_enriched` (projected) | **386,700** | Same grain as `int_rpkm_by_ec_tax` + denormalized dims |
| `sample.duckdb` (current) | **603 MB** | `dbt build` completes in ~11 s |

**Acceptance:** correctness fixtures must pass golden tests; stress fixtures must complete `run_pipeline.py` and serve all six API endpoints within interactive latency (benchmark on `stress_rpkm_1` post-migration).

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Sample read target | `mart_rpkm_enriched` | Primary API table; promoted to mart layer |
| Taxonomy reference | `bridge_tax_lineage.parquet` (wide) replaces `bridge_tax_rollup.parquet` (long) | One container artifact; no 7× row duplication |
| Lineage vs resolved labels | Store **exact lineage** on sample dims; **resolve at query time** via shared macro | Avoid redundant columns; fallback is deterministic |
| Unmapped EC label | **Derived at query time** via `canonical_pathway_label()` macro | Single definition; not stored |
| `pathway_node` display label | `ec_normalized` | Pathway node **is** the EC on the map |
| `mart_pathway_taxonomy_long` | **Retire** in the migration PR | Never consumed by API; validation moves to enriched mart + API golden tests |
| Network static graph | Still reads `resources/db/parquet/pathway_*.parquet` at request time | Distribution-time layout topology, not sample abundance |
| API JSON contracts | Unchanged | No frontend changes |

## 3. Reference Parquet (Container Build)

### 3.1 Replace `bridge_tax_rollup` with `bridge_tax_lineage`

**Remove:** `bridge_tax_rollup.parquet` (long form: one row per `(tax_id, requested_rank)`, ~20M rows, ~166 MB).

**Add:** `bridge_tax_lineage.parquet` (wide form: one row per `tax_id`, ~2.8M rows).

Built by `build_reference.py` from raw `names` + `parents` Parquet (same source data as today's rollup). No dependency on the long bridge.

| Column | Type | Source | Notes |
|---|---|---|---|
| `tax_id` | BIGINT | `parents` | Join key (= RPKM column header `source_tax_id`) |
| `display_name` | VARCHAR | `names` | Scientific name of the taxon itself |
| `kingdom_id` … `species_id` | BIGINT | `parents` | Exact ancestor tax_id at each rank; NULL when absent |
| `kingdom_label` … `species_label` | VARCHAR | `names` join on ancestor ids | Exact ancestor label at each rank; NULL when absent |

**Physical ordering:** `ORDER BY tax_id` (or `ORDER BY kingdom_id, phylum_id, …, tax_id` if compression improves).

**Estimated size:** ~30–50 MB (8 label + 8 id columns vs 5 columns × 7 rows per taxon in long form).

### 3.2 Unchanged reference artifacts

| File | Size | Role |
|---|---|---|
| `bridge_ec_pathway.parquet` | ~283 KB | EC → pathway hierarchy; used at upload only |
| `resources/db/parquet/names.parquet` | ~137 MB | Input to `build_reference.py`; not read by API |
| `resources/db/parquet/parents.parquet` | — | Input to `build_reference.py`; not read by API |
| `resources/db/parquet/pathway_*.parquet` | ~3.5 MB total | Network layout only; distribution-time reads |

### 3.3 Rollup fallback (query-time, not stored)

When the user selects `tax_level` (= requested rank), the resolved label for grouping is:

1. **Exact:** use `{tax_level}_label` if not NULL.
2. **Fallback:** if exact is NULL, walk toward coarser ranks (next rank up in `kingdom → … → species` order) and use the first non-null label.
3. **Unclassified:** if no ancestor label exists, `'Unclassified'`.

This matches the algorithm in today's `build_bridge_tax_rollup()`:

```sql
-- resolve_tax_label(tax_level, kingdom_label, phylum_label, …, species_label)
-- Implemented as a dbt macro and mirrored in analytics/api/query_enriched.py
CASE tax_level
  WHEN 'species' THEN COALESCE(species_label, genus_label, family_label, order_label, class_label, phylum_label, kingdom_label, 'Unclassified')
  WHEN 'genus'   THEN COALESCE(genus_label, family_label, …, 'Unclassified')
  -- … one branch per rank, walking toward kingdom
  WHEN 'kingdom' THEN COALESCE(kingdom_label, 'Unclassified')
END
```

Resolved **tax_id** for grouping (when needed) follows the same walk using `{rank}_id` columns.

**Unknown header tax_ids** (present in RPKM but absent from `bridge_tax_lineage`): `dim_sample_taxon` still gets a row with all lineage columns NULL and `display_name = CAST(tax_id AS VARCHAR)`. Query-time resolution yields `'Unclassified'` at every rank — not silently dropped.

### 3.4 dbt source declaration

Update `models/sources.yml`:

```yaml
sources:
  - name: reference
    tables:
      - name: bridge_ec_pathway
      - name: bridge_tax_lineage   # replaces bridge_tax_rollup
```

## 4. Upload Pipeline (dbt Models)

### 4.1 Model graph

```
stg_rpkm_long
  → int_rpkm_by_ec_tax
  → dim_sample_taxon          # sample tax_ids only (~8–100 rows)
  → dim_sample_ec             # sample ECs only
  → mart_rpkm_enriched        # APIs read this
```

**Dropped:** `int_rpkm_pathway`, `int_tax_rollup_resolved`, `mart_pathway_taxonomy_long`.

### 4.2 `int_rpkm_by_ec_tax` (unchanged grain)

| Column | Notes |
|---|---|
| `sample_id` | dbt var |
| `ec_normalized` | |
| `source_tax_id` | |
| `value` | `SUM` of gene-level values sharing EC + taxon |

### 4.3 `dim_sample_taxon`

**Grain:** one row per `source_tax_id` present in `int_rpkm_by_ec_tax`.

Built by joining distinct sample tax_ids to `{{ source('reference', 'bridge_tax_lineage') }}` (gated — only sample ids, not a full 2.8M scan at materialization if DuckDB pushdown works; otherwise explicit `WHERE tax_id IN (SELECT DISTINCT source_tax_id FROM int_rpkm_by_ec_tax)`).

| Column | Notes |
|---|---|
| `source_tax_id` | PK |
| `display_name` | From bridge or `CAST(source_tax_id AS VARCHAR)` when unknown |
| `kingdom_id` … `species_id` | Exact ancestor ids |
| `kingdom_label` … `species_label` | Exact ancestor labels |

No resolved columns stored. No `requested_rank` fan-out.

### 4.4 `dim_sample_ec`

**Grain:** one row per `ec_normalized` present in `int_rpkm_by_ec_tax`.

Join to `bridge_ec_pathway` (LEFT JOIN — unmapped ECs retained).

| Column | Notes |
|---|---|
| `ec_normalized` | PK |
| `pathway_node_id` | NULL when unmapped |
| `pathway_id`, `pathway_name` | NULL when unmapped |
| `superpathway_id`, `superpathway_name` | NULL when unmapped |

No `pathway_display_label` stored. Unmapped state = `pathway_id IS NULL`.

### 4.5 `mart_rpkm_enriched`

**Grain:** `(ec_normalized, source_tax_id)` — same as `int_rpkm_by_ec_tax`.

```sql
SELECT
    r.sample_id,
    r.ec_normalized,
    r.source_tax_id,
    r.value,
    e.pathway_node_id,
    e.pathway_id,
    e.pathway_name,
    e.superpathway_id,
    e.superpathway_name,
    t.display_name,
    t.kingdom_id, t.kingdom_label,
    t.phylum_id,  t.phylum_label,
    -- … all lineage id/label pairs through species
FROM int_rpkm_by_ec_tax r
LEFT JOIN dim_sample_ec    e USING (ec_normalized)
LEFT JOIN dim_sample_taxon t USING (source_tax_id)
```

**Materialization:** `table` with `ORDER BY superpathway_id, pathway_id, ec_normalized, source_tax_id` for zone-map skipping on common filters.

**Row count:** equals `int_rpkm_by_ec_tax` row count — at most one row per `(ec_normalized, source_tax_id)` pair present in the sample. Upper bound ~387K per stress file (3,867 ECs × 100 tax cols); ~8.8K for sparse `test_rpkm_1`. Replaces the old `int_tax_rollup_resolved` 21× fan-out (~185K × 21 ≈ 3.9M row-equivalent for `test_rpkm_1`).

### 4.6 Shared macros

| Macro | Used by | Purpose |
|---|---|---|
| `resolve_tax_label(tax_level, lineage_labels…)` | dbt tests, API SQL | Fallback rollup label |
| `resolve_tax_id(tax_level, lineage_ids…)` | dbt tests, API SQL | Fallback rollup id |
| `canonical_pathway_label(ann_level, ec, pathway_id, pathway_name, superpathway_name)` | dbt tests, API SQL | Pathway display label |
| `aggregate_pathway_tax(from_relation, tax_level, ann_level)` | dbt tests (replaces `mart_pathway_taxonomy_agg`) | `GROUP BY` enriched fact at requested levels |

### 4.7 `canonical_pathway_label` semantics

```sql
CASE
  WHEN ec_normalized = '0.0.0.0' OR pathway_id IS NULL
    THEN 'Unmapped EC'
  WHEN ann_level = 'pathway_node'
    THEN ec_normalized
  WHEN ann_level = 'superpathway'
    THEN superpathway_name
  ELSE pathway_name
END
```

| `ann_level` | Label |
|---|---|
| `superpathway` | `superpathway_name` |
| `pathway` | `pathway_name` |
| `pathway_node` | `ec_normalized` |
| Unmapped | `'Unmapped EC'` |

## 5. API Layer

### 5.1 Principles

- All abundance/rollup queries read **`mart_rpkm_enriched`** only.
- No `read_parquet` of `bridge_*` or `names` in API services.
- Shared column helpers in `analytics/api/query_enriched.py` mirror dbt macros (same semantics; consider generating from one source in a follow-up).
- Delete or gut: `rollup_query.py`, `ec_tax_triples.py`, `tax_lineage_order.py` parquet paths.

### 5.2 Per-endpoint data sources

| Endpoint | Primary source | Other reads |
|---|---|---|
| `POST /api/viz/overview` | `mart_rpkm_enriched` | — |
| `POST /api/viz/chord` | `mart_rpkm_enriched` | — |
| `POST /api/viz/pathway-list` | `mart_rpkm_enriched` | — |
| `POST /api/viz/krona` | `mart_rpkm_enriched` (`GROUP BY source_tax_id`) | — |
| `POST /api/viz/graph` | `mart_rpkm_enriched` | — |
| `POST /api/viz/network` | `mart_rpkm_enriched` (EC × tax values) | `resources/db/parquet/pathway_{superpathways,nodes,edges}.parquet` for static layout |

### 5.3 Query patterns (sketch)

**Overview** — hardcoded `tax_level = phylum`, `ann_level = superpathway`:

```sql
-- counts_data: GROUP BY resolve_tax_label('phylum', …), order by kingdom_label
-- ann_data: GROUP BY canonical_pathway_label('superpathway', …)
```

**Chord / pathway-list / graph** — parameterized `tax_level`, `ann_level`, optional filters:

```sql
SELECT
  canonical_pathway_label(ann_level, …) AS pathway_label,
  resolve_tax_label(tax_level, …)       AS tax_label,
  SUM(value) AS value
FROM mart_rpkm_enriched
WHERE <ann_filter predicates on superpathway_name / pathway_name / ec_normalized>
  AND <taxon_filter on resolve_tax_label at filter rank>
GROUP BY pathway_key equivalent, resolved tax key, labels
```

**Krona** — aggregate to taxon totals, pass lineage columns to existing Python tree builder:

```sql
SELECT
  display_name,
  SUM(value) AS total,
  kingdom_label, …, species_label   -- exact lineage for tree segments
FROM mart_rpkm_enriched
GROUP BY source_tax_id, display_name, lineage columns
```

**Network** — same value query as graph; layout from distribution parquets unchanged.

### 5.4 Chord / pathway-list ordering

Compute arc order from aggregated totals on lineage columns already denormalized on `mart_rpkm_enriched` rows — same sort keys as today (kingdom DESC, phylum DESC, …). No bridge PIVOT, no full bridge scan.

## 6. Retiring `mart_pathway_taxonomy_long`

### 6.1 Current role

| Consumer | Usage |
|---|---|
| API | **None** |
| `run_pipeline.py` | Info metrics (`unmapped_ec_value_rate`, rollup match/fallback rates); optional `--export-mart` Parquet |
| dbt singular tests | `assert_mart_nonempty`, `assert_mart_mapped_pathways_have_keys`, `assert_mart_classified_taxa_have_keys`, `assert_unmapped_mass_conservation` |
| `test_fake_rpkm_pipeline.py` | Tests **`int_tax_rollup_resolved`**, not the mart (21-row rollup grid) |

The mart was designed as the API read target but that integration never shipped. The API reads intermediates instead.

### 6.2 Recommendation: retire in the migration PR

**Do not keep `mart_pathway_taxonomy_long` as a parallel model**, even temporarily. It adds a second aggregation path that duplicates `mart_rpkm_enriched` + `aggregate_pathway_tax()` and perpetuates the confusion that caused this redesign.

Validation during migration is better served by:

1. **Port `fake_rpkm_pipeline_expectations.yaml`** — same 21 expected cells, but query `mart_rpkm_enriched` with `aggregate_pathway_tax(tax_level, ann_level)` + macros instead of `int_tax_rollup_resolved`. This is a strict equivalence check on the semantics we care about.

2. **API golden tests** (`fake_rpkm`, `test_rpkm_*` YAML fixtures) — end-to-end validation across all six endpoints. These are the real contract tests.

3. **Rewrite dbt singular tests** to target `mart_rpkm_enriched` or a dbt test query using `aggregate_pathway_tax()` at default vars (`tax_rank = phylum`, `pathway_level = pathway`).

4. **Update `run_pipeline.py`** — compute info metrics from `mart_rpkm_enriched` + macros; remove `--export-mart` or replace with optional export of `mart_rpkm_enriched` (or a param-filtered aggregate snapshot if external consumers need rectangular output).

**Optional one-time diff (not required):** Before deleting the old models, a developer can run old and new pipelines side-by-side in a worktree and compare `aggregate_pathway_tax(mart_rpkm_enriched)` against old `mart_pathway_taxonomy_long` for one sample. This is a manual sanity check, not a permanent artifact.

### 6.3 Artifacts to remove

| Artifact | Action |
|---|---|
| `models/marts/mart_pathway_taxonomy_long.sql` | Delete |
| `mart_pathway_taxonomy_agg.sql` | Rename/refactor → `aggregate_pathway_tax.sql` |
| `models/intermediate/int_rpkm_pathway.sql` | Delete |
| `models/intermediate/int_tax_rollup_resolved.sql` | Delete |
| `bridge_tax_rollup.parquet` | Stop building; remove from `REQUIRED_BRIDGES` |
| `assert_int_rpkm_3_levels.sql` | Delete or replace |
| `warn_rpkm_tax_id_resolvable.sql` | Rewrite against `dim_sample_taxon` unknown-tax handling |

## 7. Migration & Testing

### 7.1 Implementation order

1. Add `bridge_tax_lineage` to `build_reference.py`; remove `bridge_tax_rollup` build.
2. Add dbt macros (`resolve_tax_label`, `canonical_pathway_label`, `aggregate_pathway_tax`).
3. Add `dim_sample_taxon`, `dim_sample_ec`, `mart_rpkm_enriched`.
4. Port `test_fake_rpkm_pipeline.py` expectations to new query path.
5. Rewrite API services to read `mart_rpkm_enriched`.
6. Confirm API golden tests pass unchanged output.
7. Delete old intermediates, mart, and API parquet-read code.
8. Update `run_pipeline.py`, README, and prior design spec cross-references.

### 7.2 Test matrix

| Test | Change |
|---|---|
| `test_fake_rpkm_pipeline.py` | Query `mart_rpkm_enriched` + macros; keep 21-row grid expectations |
| API golden YAML tests | Should pass without expectation changes |
| `assert_mart_nonempty` etc. | Rewrite for enriched mart or aggregate query |
| `test_build_reference.py` | Assert `bridge_tax_lineage` schema; 7 lineage columns; no `bridge_tax_rollup` |
| `assert_bridge_tax_7_ranks.sql` | Replace with lineage-column presence test on wide bridge |

### 7.3 Backward compatibility

- **Container images** must rebuild reference parquets (`build_reference.py`) before upload pipeline works.
- **Existing `sample.duckdb` files** on disk are invalid after migration — require re-run of `run_pipeline.py` per sample.
- **API JSON contracts:** unchanged.

## 8. Expected Outcomes

### Sparse sample (`test_rpkm_1` — correctness)

| Metric | Current | Expected |
|---|---|---|
| `int_tax_rollup_resolved` rows | 185,150 | 0 (removed) |
| `mart_rpkm_enriched` rows | — | ~8,800 |
| `sample.duckdb` size | 7.3 MB | ~3–5 MB (estimate) |
| Chord request latency | ~375 ms | ~20–40 ms |
| Krona request latency | ~379 ms | ~15–30 ms |

### Stress sample (`stress_rpkm_1` — measured baseline, 2026-07-09)

Generated and pipelined in `.worktrees/feature/api-aligned-dbt-model/`.

| Metric | Current (measured) | Expected post-migration |
|---|---|---|
| `stg_rpkm_long` rows | 40,453,328 | unchanged |
| `int_rpkm_by_ec_tax` rows | 386,700 | folded into `mart_rpkm_enriched` |
| `int_rpkm_pathway` rows | 1,661,100 | 0 (removed) |
| `int_tax_rollup_resolved` rows | 11,627,700 | 0 (removed) |
| `mart_rpkm_enriched` rows | — | **386,700** |
| `sample.duckdb` size | **603 MB** | Smaller — removes 11.6M-row rollup + 1.7M-row pathway tables; `stg_rpkm_long` still dominates (~40M rows). Exact size measured at implementation. |
| `dbt build` time | ~11 s | TBD (rollup build was 3.9 s of total) |
| Chord request latency | **586 ms** | < 200 ms (no full bridge scan) |
| Krona request latency | **447 ms** | < 100 ms |
| Overview request latency | **195 ms** | < 50 ms |

### Both tiers

| Metric | Current | Expected |
|---|---|---|
| API reference parquet reads | 1–3 per request | 0 (network layout excepted) |
| Label logic locations | dbt macro + `PATHWAY_LABEL_SQL` | dbt macro + `query_enriched.py` mirror |

## 9. Out of Scope

- Multi-sample comparison mode on DuckDB backend
- Upload endpoint that triggers dbt on file ingest
- Retiring legacy Node viz handlers
- Pushing network static graph into `sample.duckdb`
- Auto-generating Python SQL helpers from dbt macros (acceptable follow-up)

## 10. Open Questions (resolved)

| Question | Resolution |
|---|---|
| Store resolved labels or infer? | Infer at query time via `resolve_tax_label()` |
| Store Unmapped EC label? | Derive via `canonical_pathway_label()` |
| Promote enriched fact to mart? | Yes → `mart_rpkm_enriched` |
| Keep `mart_pathway_taxonomy_long` for migration? | No — retire in same PR; port tests to enriched mart |
| Keep both wide and long taxonomy bridge? | No — wide `bridge_tax_lineage` only |
| `pathway_node` label | `ec_normalized` (not `pathway_name`) |

## 11. Acceptance Criteria

- [ ] `build_reference.py` produces `bridge_tax_lineage.parquet`; `bridge_tax_rollup.parquet` is no longer built or referenced
- [ ] Upload pipeline produces `mart_rpkm_enriched`; old intermediates and `mart_pathway_taxonomy_long` are gone
- [ ] All six API endpoints pass golden tests without JSON contract changes
- [ ] No API service reads `analytics/transform/reference/parquet/` or `names.parquet` (network layout parquets excepted)
- [ ] `fake_rpkm` 21-cell rollup grid passes against new query path
- [ ] `resolve_tax_label` and `canonical_pathway_label` semantics match §3.3 and §4.7
- [ ] Chord + krona latency on `test_rpkm_1` drops below 50 ms (local benchmark)
- [ ] `stress_rpkm_1` completes `run_pipeline.py` and serves all six API endpoints (manual stress workflow per stress-generator spec §9)
- [ ] Chord latency on `stress_rpkm_1` drops below 200 ms; krona below 100 ms (local benchmark, post-migration)
