# RPKM → Pathway × Taxonomy Transform Pipeline — Design Spec

> **Status:** Draft (2026-06-15)  
> **Goal:** Build a dbt + DuckDB pipeline in `analytics/transform/` that ingests a wide RPKM/FPKM sample file and produces a long-form pathway × taxonomy matrix with summed per-taxon column values, configurable taxonomy rank and pathway level, tiered constraint checks, and persisted run artifacts. API integration and chord-matrix derivation are explicitly out of scope for v1.

## 1. Context

Metapro Viz ingests wide TSV output from [MetaPro](https://github.com/ParkinsonLab/MetaPro). Each row is a gene/EC record; integer column headers are NCBI `tax_id` values holding per-taxon abundances. Reference taxonomy and KEGG pathway data live in `resources/db/taxonomy.db` (exported to Parquet for analytics).

Exploratory analysis (`analytics/exploration/`, branch `exploration/eda`) validated data shapes, join semantics, and gotchas documented in `analytics/exploration/docs/data-model.md`. The existing Node app performs a similar aggregation in-memory (`src/server/parse.ts` → `make_count_matrix`) but lacks a reproducible, testable, stage-oriented pipeline.

**Two-phase data availability:**

| Phase | When | Data |
|---|---|---|
| **Distribution** | App install / software distribution | Reference DB Parquet: `names`, `nodes`, `parents`, `pathway_*`, `superpathways` |
| **Runtime** | User uploads RPKM/FPKM | Sample TSV only |

Future work (out of scope v1): invoke pipeline on upload, stream dbt progress to the Node app, pre-compute intermediates for snappy UI, derive `chord_matrix` in the API layer from `mart_pathway_taxonomy_long`.

**Work isolation:** Branch `feature/rpkm-transform` in worktree `.worktrees/rpkm-transform/`, forked from `exploration/eda`.

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Cell value | Per-taxon **column** values, summed | Matches app behavior and EDA unpivot pattern; not row-level `RPKM` column |
| Pathway level | Configurable: `superpathway` \| `pathway` \| `pathway_node`; default `pathway` | Aligns with domain terms: pathway = `pathway_superpathways` row; pathway_node = EC-on-map instance |
| Canonical output | `mart_pathway_taxonomy_long` only | Rectangular matrix and chord matrix deferred |
| Taxonomy rollup | Resolve via `dim_tax_rank_map` using: exact rank → coarser fallback → `Unclassified` | Lookup table + resolution algorithm; mart includes `tax_rank_resolved` and `rollup_method` |
| Reference taxonomy shape | `dim_tax_rank_map` derived from wide `parents` (long form with self-rows) | Parameterized rank without dynamic SQL columns |
| Pipeline tool | **dbt-first** (dbt-duckdb) with Python model for wide TSV ingest | Single toolchain; `run_results.json` ready for future streaming |
| Constraints | Tiered severity (error / warn / info); profile-ready for v2 | dbt test `severity:` + info singular tests; no profiles in v1 |
| Reporting | Persist dbt artifacts via `--target-path`; minimal `run_context.json` supplement | No duplicate of timing/test data |
| Scope v1 | Analytics pipeline + CLI wrapper + tests | No API changes |
| Scale target | ~100 tax_id columns, ~400–500K gene rows, ~1–2% nonzero cells | ~720K long rows after nonzero filter |

## 3. Repository Layout

```
analytics/
├── pyproject.toml              # add dbt-core, dbt-duckdb
├── exploration/                # unchanged (EDA)
└── transform/
    ├── dbt_project.yml
    ├── profiles.yml
    ├── packages.yml            # if needed
    ├── models/
    │   ├── reference/
    │   │   ├── dim_tax_rank_map.sql
    │   │   └── ec_pathway_bridge.sql
    │   ├── staging/
    │   │   └── stg_rpkm_long.py        # dbt Python model
    │   ├── intermediate/
    │   │   ├── int_rpkm_pathway.sql
    │   │   └── int_tax_rollup_resolved.sql
    │   └── marts/
    │       └── mart_pathway_taxonomy_long.sql
    ├── seeds/
    │   └── rank_order.csv              # kingdom…species ordering
    ├── tests/
    │   └── singular/                   # info metrics, mass conservation
    ├── macros/
    │   └── rank_order.sql
    ├── scripts/
    │   └── run_pipeline.py             # CLI: dbt build + run_context + parquet export
    └── runs/                           # gitignored; per-run artifacts
        └── {sample_id}/{timestamp}/
            ├── run_context.json
            ├── target/                 # dbt --target-path
            └── mart_pathway_taxonomy_long.parquet
```

Reference Parquet continues to live at `resources/db/parquet/` (produced by `analytics/exploration/scripts/export_parquet.py`). dbt reads via `read_parquet()` sources or external sources configuration — not duplicated.

## 3.1 Storage Format & Persistence

All models materialize as **DuckDB tables** inside a `.duckdb` database file unless noted otherwise. Parquet is used for **inputs** (reference) and **explicit exports** (mart snapshot per run).

| Layer | When built | Storage | Persisted to disk? | Lifetime |
|---|---|---|---|---|
| **Reference Parquet** | `export_parquet.py` (EDA script) | `resources/db/parquet/*.parquet` | Yes (Git LFS) | Shipped with app; versioned |
| **Reference dbt models** (`dim_tax_rank_map`, `ec_pathway_bridge`) | `dbt build` on reference (distribution / CI) | Tables in shared `transform/data/reference.duckdb` | Yes | Refreshed when Parquet changes |
| **Upload dbt models** (`stg_rpkm_long` … `mart_*`) | `dbt build` on sample upload | Tables in per-sample `transform/runs/{sample_id}/sample.duckdb` | Yes | One DB file per sample; overwritten on re-upload |
| **Mart export** | `run_pipeline.py` post-step | `runs/{sample_id}/{timestamp}/mart_pathway_taxonomy_long.parquet` | Yes | Immutable snapshot per run |
| **dbt artifacts** | each `dbt build` | `runs/{sample_id}/{timestamp}/target/` | Yes | Per-run via `--target-path` |

**Distribution vs upload:** Reference data is read-only input (Parquet → DuckDB tables once). Upload data is written into a **separate per-sample DuckDB file** so re-parameterizing `tax_rank` / `pathway_level` does not re-read the TSV and does not mutate reference tables.

**Views vs tables:** Reference models and `stg_rpkm_long` → **table**. `int_*` and mart may be **table** (v1 default, for inspectability) or **view** (if rebuild latency stays sub-second in profiling — implementation choice).

## 4. Approach

**Selected: dbt-first with Python ingest model (Approach A).**

Rejected alternatives:
- **Hybrid CLI pre-step + dbt** — split orchestration, broken lineage at ingest.
- **Pure SQL with codegen UNPIVOT** — fragile per-sample column lists.

Python 3.14 + dbt-core ≥ 1.12 (Python 3.14 support merged 2026-05) + dbt-duckdb.

## 5. Model Graph & Rebuild Triggers

```
[reference / distribution time]
  dim_tax_rank_map          ← parents parquet unpivot + self-rows
  ec_pathway_bridge         ← pathway_nodes ⋈ pathway_superpathways ⋈ superpathways

[upload time]
  stg_rpkm_long             ← Python: wide TSV → long, EC normalize, nonzero filter
       ↓
  int_rpkm_pathway          ← join ec_pathway_bridge; all pathway level keys attached
       ↓
  int_tax_rollup_resolved   ← join dim_tax_rank_map; exact / fallback / unclassified
       ↓
  mart_pathway_taxonomy_long ← GROUP BY pathway level + taxon; SUM(value)
```

| Model | Rebuilt when | Not rebuilt when |
|---|---|---|
| `dim_tax_rank_map` | Reference Parquet refresh | RPKM upload; `tax_rank` / `pathway_level` change |
| `ec_pathway_bridge` | Reference Parquet refresh | RPKM upload; param changes |
| `stg_rpkm_long` | New/changed RPKM file | `tax_rank` / `pathway_level` change |
| `int_rpkm_pathway` | `stg_rpkm_long` or reference models rebuild | `pathway_level` change |
| `int_tax_rollup_resolved` | Upstream rebuild or `tax_rank` var change | `pathway_level` change alone |
| `mart_pathway_taxonomy_long` | Upstream rebuild or `tax_rank` / `pathway_level` var change | — |

**Typical operations:**

- **New upload:** full pipeline from `stg_rpkm_long`.
- **Change `tax_rank` or `pathway_level`:** `dbt build --select int_tax_rollup_resolved+` (~seconds).

## 6. Model Specifications

### 6.1 `dim_tax_rank_map` (reference)

Derived from wide `parents` Parquet. Does not modify upstream Parquet.

**Build steps:**
1. UNPIVOT non-null `t_kingdom` … `t_species` → `(tax_id, rank_tax_id, rank)`.
2. Add self-rows: for taxa whose finest filled rank equals `rank`, ensure `(tax_id, tax_id, rank)` exists when missing from step 1. Finest rank derived inline from wide columns (same ladder logic as EDA §6); no separate `dim_taxonomy` model.

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `tax_id` | BIGINT | Source taxon |
| `rank_tax_id` | BIGINT | Tax_id at `rank` (self when at-rank) |
| `rank` | VARCHAR | `kingdom`, `phylum`, `class`, `order`, `family`, `genus`, `species` |

Join taxonomy on `tax_id`, never `names.id` (UUID surrogate).

### 6.2 `ec_pathway_bridge` (reference)

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `ec_normalized` | VARCHAR | Join key from RPKM |
| `pathway_node_id` | VARCHAR | For `pathway_level = pathway_node` |
| `pathway_id` | BIGINT | FK to `pathway_superpathways.id` |
| `pathway_name` | VARCHAR | Display |
| `superpathway_id` | VARCHAR | FK to `superpathways.id` |
| `superpathway_name` | VARCHAR | Display |

One row per `(ec_normalized, pathway_node_id)`. When aggregating at `pathway` or `superpathway`, group by id (not name). Matches app `reduce_to_dict` dedup semantics.

EC normalization (same as EDA / `SPEC.md`): `EC:x.y.z` → `x.y.z`; null/empty/None → `0.0.0.0`.

### 6.3 `stg_rpkm_long` (Python model)

**Input:** dbt var `rpkm_path` (absolute or repo-relative path to wide TSV).

**Logic:**
1. Parse TSV; fixed columns: `GeneID`, `Length`, `Reads`, `EC#`, `RPKM`, `Unclassified`.
2. Remaining headers = integer `tax_id` column names (keep as integers, not renamed to scientific names).
3. Normalize `EC#` per rules above.
4. UNPIVOT tax columns → `(source_tax_id, value)`.
5. Filter `value > 0` (do not materialize zero cells).
6. Coerce invalid numeric cells to skip/null with warn metric.

**Output columns:**

| Column | Notes |
|---|---|
| `sample_id` | From var |
| `gene_id` | From `GeneID` |
| `ec_normalized` | Normalized EC |
| `source_tax_id` | RPKM column header |
| `value` | Per-taxon column value |

### 6.4 `int_rpkm_pathway`

`stg_rpkm_long` **INNER JOIN** `ec_pathway_bridge` ON `ec_normalized`. Unmapped ECs are excluded from this model and downstream marts (v1). Carries all three pathway keys on every row for cheap re-grouping.

**Unmapped ECs (v1 behavior):** Rows whose `ec_normalized` has no KEGG match are dropped here. Coverage is tracked by the `rpkm_ec_kegg_coverage` info constraint. See §6.4.1 for impact if we later allow unmapped ECs to propagate.

#### 6.4.1 Unmapped EC propagation (deferred — impact analysis)

If changed to **LEFT JOIN** with a sentinel pathway (e.g. `pathway_key = 'UNMAPPED_EC'`, `pathway_label = ec_normalized`):

| Area | Impact |
|---|---|
| **Query / mart** | Mart includes an "unmapped EC" bucket alongside real pathways; filter with `WHERE pathway_key != 'UNMAPPED_EC'` to recover v1 behavior |
| **Constraints** | `mass_conservation` compares against full `stg_rpkm_long` sum (not join-filtered); `rpkm_ec_kegg_coverage` unchanged; new info metric: `unmapped_ec_value_rate` |
| **Performance** | More rows in `int_*` and mart (~36% of distinct ECs unmapped in test fixture per EDA §7); still fine at DuckDB scale |
| **Pathway level var** | No fallback logic needed — unmapped ECs have no pathway/superpathway by definition; sentinel is not a coarser pathway level |
| **Optional pattern** | Separate `mart_unmapped_ec_long` (group by EC × taxon only) keeps main mart pathway-only; avoids sentinel in pathway dimension |

Recommendation for v1: keep INNER JOIN; add `mart_unmapped_ec_long` in v1.1 if gap visualization is needed without polluting the pathway mart.

### 6.5 `int_tax_rollup_resolved`

Resolves each row to a taxon at requested rank using `dim_tax_rank_map` and `seeds/rank_order.csv`.

**Rank order (coarse → fine):** kingdom, phylum, class, order, family, genus, species.

**Resolution algorithm** (for var `tax_rank`):

1. **Exact:** row in `dim_tax_rank_map` where `tax_id = source_tax_id` AND `rank = tax_rank` → `rollup_method = 'exact'`, `tax_rank_resolved = tax_rank`.
2. **Fallback:** among rows where `rank_order <= tax_rank_order`, pick finest available (max rank order) → `rollup_method = 'fallback'`, `tax_rank_resolved = that rank`.
3. **Unclassified:** no qualifying row → `rollup_method = 'unclassified'`, `taxon_key = -1`, `taxon_label = 'Unclassified'`.

**Why `taxon_key = -1` instead of NULL:** Sentinels keep `mart_no_null_keys` satisfied, make GROUP BY / joins explicit, and avoid NULL-handling ambiguity in downstream consumers. `-1` is not a valid NCBI tax_id. Alternative: allow NULL when `rollup_method = 'unclassified'` and relax the constraint — semantically cleaner but weaker for keyed exports.

Fallback only walks **coarser** ranks (never genus when phylum was requested).

**Output columns (per input row):**

| Column | Notes |
|---|---|
| (all columns from `int_rpkm_pathway`) | |
| `tax_rank_requested` | Echo of var |
| `tax_rank_resolved` | Actual rank used |
| `taxon_key` | `rank_tax_id` or sentinel `-1` |
| `taxon_label` | From `names` join, or `'Unclassified'` |
| `rollup_method` | `exact` \| `fallback` \| `unclassified` |

**Intentional divergence from app:** `get_parents_at_level` uses a name-based backfill heuristic and does not coarser-fallback. Pipeline behavior is explicit and documented.

### 6.6 `mart_pathway_taxonomy_long`

Groups `int_tax_rollup_resolved` by pathway level (from var `pathway_level`) and resolved taxon.

**Vars:**

| Var | Allowed values | Default |
|---|---|---|
| `rpkm_path` | path to TSV | required on full run |
| `sample_id` | string | required |
| `tax_rank` | kingdom … species | `phylum` |
| `pathway_level` | superpathway, pathway, pathway_node | `pathway` |

**Output columns:**

| Column | Notes |
|---|---|
| `sample_id` | |
| `pathway_level` | Requested level |
| `pathway_key` | Id at selected level |
| `pathway_label` | Name at selected level |
| `tax_rank_requested` | |
| `tax_rank_resolved` | Actual rank used (may differ under fallback) |
| `taxon_key` | |
| `taxon_label` | |
| `rollup_method` | Taxonomy resolution method for this row (see note) |
| `value` | `SUM(value)` |

**Note on `rollup_method` in the mart (taxonomy only):** This column reflects **taxonomy** resolution (exact / fallback / unclassified), not EC→pathway mapping. There is no pathway-level fallback — an EC either maps to KEGG pathway(s) or it does not (§6.4).

When aggregating to `(pathway_key, taxon_key, …)`, different source tax_id rows can resolve to the same taxon via different methods (e.g. one species via exact phylum, another via fallback to kingdom). **Group by `rollup_method` as well** so the mart emits separate rows per `(pathway, taxon, rollup_method)` rather than collapsing methods.

## 7. Constraints

Each constraint has an id, check, stage, default severity, and pass criteria. Implemented as dbt tests (`severity: error|warn`) or singular tests (info metrics).

| ID | Check | Model / stage | Severity | Pass when |
|---|---|---|---|---|
| `rpkm_file_readable` | TSV parses; all KEY_COLS present; ≥1 tax column | pre-`stg_rpkm_long` (Python) | error | No exception; valid shape |
| `rpkm_tax_columns_present` | ≥1 tax_id column detected | `stg_rpkm_long` | error | tax_column_count ≥ 1 |
| `rpkm_no_negative_values` | All `value >= 0` | `stg_rpkm_long` | error | 0 violating rows |
| `rpkm_tax_id_resolvable` | Every distinct `source_tax_id` in `names` | `stg_rpkm_long` | warn | 0 unmapped tax_ids |
| `rpkm_ec_kegg_coverage` | `distinct matched ECs / distinct ECs in sample` | `int_rpkm_pathway` | info | Always passes; emits ratio |
| `pathway_join_fanout_rate` | Avg `int_rpkm_pathway` rows per `stg_rpkm_long` row | `int_rpkm_pathway` | info | Metric only |
| `mass_conservation` | `SUM(mart.value)` ≈ `SUM(int_rpkm_pathway.value)` after accounting for pathway-level dedup | `mart_pathway_taxonomy_long` | warn | Relative delta ≤ 0.01% |
| `mart_nonempty` | Mart row count > 0 | `mart_pathway_taxonomy_long` | error | count > 0 |
| `mart_no_null_keys` | `pathway_key`, `taxon_key`, `value` non-null | `mart_pathway_taxonomy_long` | error | 0 nulls |
| `mart_rollup_exact_match_rate` | `SUM(value WHERE rollup_method='exact') / SUM(value)` | mart | info | Metric only |
| `mart_rollup_fallback_rate` | `SUM(value WHERE rollup_method='fallback') / SUM(value)` | mart | info | Metric only |
| `mart_unclassified_rate` | `SUM(value WHERE rollup_method='unclassified') / SUM(value)` | mart | info | Metric only in v1 (no warn threshold until fixtures establish baseline) |

**Mass conservation definition:** Sum of mart values equals sum of input long values that successfully joined to at least one pathway at the selected pathway level (after EC-pathway dedup). Document exact SQL in the singular test.

**v2 (deferred):** named constraint profiles (`strict` / `permissive`) overriding default severities.

## 8. CLI & Run Artifacts

### 8.1 Invocation

**Direct dbt (local dev):** Running `dbt build` with `--vars` is sufficient for development and debugging.

**`run_pipeline.py` wrapper (CI, fixtures, future API):** Thin orchestration — not a substitute for dbt logic. Responsibilities:

1. Allocate `runs/{sample_id}/{timestamp}/` and pass `--target-path`
2. Pass `--vars` consistently (`sample_id`, `rpkm_path`, `tax_rank`, `pathway_level`)
3. Write `run_context.json` (vars + derived `overall_status`; dbt does not persist vars)
4. Export `mart_pathway_taxonomy_long.parquet` from the sample DuckDB file
5. Single entrypoint for future Node subprocess / CI

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id test_rpkm_1 \
  --rpkm-path ../resources/example_data/test_rpkm_1.tsv \
  --tax-rank phylum \
  --pathway-level pathway
```

Wrapper runs:

```bash
RUN_DIR="transform/runs/${sample_id}/${timestamp}"
dbt build \
  --project-dir transform \
  --profiles-dir transform \
  --target-path "$RUN_DIR/target" \
  --vars "{ rpkm_path, sample_id, tax_rank, pathway_level }"
```

Re-parameterize only:

```bash
dbt build --select int_tax_rollup_resolved+ --vars '{ "tax_rank": "class", ... }'
```

### 8.2 Artifacts

| Artifact | Writer | Contents |
|---|---|---|
| `target/run_results.json` | dbt via `--target-path` | Per-node status, timing, rows affected, test outcomes |
| `target/manifest.json` | dbt | Lineage, compiled SQL |
| `run_context.json` | `run_pipeline.py` | `sample_id`, `rpkm_path`, `tax_rank`, `pathway_level`, timestamps, `artifact_dir`, derived `overall_status` |
| `mart_pathway_taxonomy_long.parquet` | export step in wrapper | Final mart snapshot |

**`overall_status` derivation:**
- `failed` — any error-severity test fails or model error
- `success_with_warnings` — no errors; ≥1 warn
- `success` — all pass

Local dev may use default project-root `target/`; CI and fixture runs use per-run `--target-path`.

Do **not** copy from default `target/` post-hoc.

## 9. Python Environment

Add to `analytics/pyproject.toml`:

- `dbt-core` (≥ 1.12)
- `dbt-duckdb` (≥ 1.10)

Existing: `duckdb`, `jupyter`, etc. from exploration.

```bash
cd analytics && uv sync
```

## 10. Validation Strategy

| Layer | Approach |
|---|---|
| Unit | Python ingest on synthetic wide TSV snippets; rank map from known `parents` subset |
| Integration | `dbt build` on `test_rpkm_1.tsv` and `test_rpkm_2.tsv`; assert mart shape and constraint metrics |
| Regression | Compare mart totals to EDA notebook cross-domain join aggregates (§7) within tolerance |
| CI (deferred) | Run pipeline on test fixtures; fail on error-severity constraints |

## 11. Out of Scope (v1)

- Node API integration / upload hook
- `chord_matrix` derivation (API layer, future)
- Rectangular pathway × taxonomy pivot
- Constraint profiles (D)
- Streaming dbt progress to UI
- FPKM format changes beyond current wide TSV shape (unless compatible)
- Rebuilding `taxonomy.db` from source notebooks

## 12. Future Considerations

- **API integration:** subprocess `run_pipeline.py` on upload; cache `int_rpkm_pathway` per sample; re-run mart on filter/rank/level change.
- **Progress streaming:** parse `run_results.json` events as dbt models complete.
- **Chord bundle:** filter `mart_pathway_taxonomy_long` + `build_chord_matrix()` in shared Python lib (not dbt).
- **Constraint profiles:** YAML severity maps over constraint registry.
- **Comparison mode:** two samples → delta mart (app has `get_delta` precedent).

## 13. Success Criteria

- [ ] Worktree `feature/rpkm-transform` with dbt project under `analytics/transform/`
- [ ] `uv sync` installs dbt dependencies on Python 3.14
- [ ] Reference models build from existing Parquet without DB rebuild
- [ ] Pipeline produces `mart_pathway_taxonomy_long` for `test_rpkm_1.tsv` at default vars
- [ ] Re-run with changed `tax_rank` / `pathway_level` completes in seconds without re-ingesting TSV
- [ ] All error-severity constraints pass on test fixtures
- [ ] Info metrics (EC coverage, exact/fallback/unclassified rates) emitted
- [ ] Per-run artifacts persisted via `--target-path` + `run_context.json` + mart Parquet
- [ ] README under `analytics/transform/` documents two-phase workflow and rebuild triggers

## 14. References

- `analytics/exploration/docs/data-model.md` — domain model, gotchas, join conventions
- `docs/superpowers/specs/2026-06-11-exploratory-analysis-design.md` — EDA design; `analytics/transform/` anticipated here
- `src/server/parse.ts`, `src/server/db_functions.ts` — current app aggregation semantics (parity target for totals, not identical rollup edge cases)
- `SPEC.md` — RPKM wide format, KEY_COLS, EC normalization
