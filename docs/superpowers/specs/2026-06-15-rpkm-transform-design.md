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
| Taxonomy rollup | Resolve via `dim_tax_rank_map`: exact rank → coarser fallback → `Unclassified` | Mart stores `tax_rank_resolved`; exact vs fallback derived by comparing to `tax_rank_requested` |
| EC → pathway join | **LEFT JOIN**; NULL `pathway_key` when unmapped (`is_pathway_mapped = false`) | Preserves knowledge-gap mass in mart |
| Reference taxonomy shape | `dim_tax_rank_map` derived from wide `parents` (long form with self-rows) | Parameterized rank without dynamic SQL columns |
| Pipeline tool | **dbt-first** (dbt-duckdb) with Python model for wide TSV ingest | Single toolchain; `run_results.json` ready for future streaming |
| Constraints | Tiered severity (error / warn / info); profile-ready for v2 | dbt test `severity:` + info singular tests; no profiles in v1 |
| Reporting | dbt artifacts in `transform/target/`; optional `run_context.json` per sample | Conventional dbt layout; no per-run history folders |
| Scope v1 | Analytics pipeline + CLI wrapper + tests | No API changes |
| Scale target | ~100 tax_id columns, ~400–500K gene rows, ~1–2% nonzero cells | ~720K long rows after nonzero filter |

## 3. Repository Layout

```
analytics/
├── pyproject.toml
├── exploration/                # unchanged (EDA)
└── transform/
    ├── dbt_project.yml
    ├── profiles.yml
    ├── models/
    │   ├── reference/
    │   ├── staging/
    │   ├── intermediate/
    │   └── marts/
    ├── seeds/
    ├── tests/
    ├── macros/
    ├── scripts/
    │   └── run_pipeline.py
    ├── data/                   # gitignored — shared reference DuckDB
    │   └── reference.duckdb
    ├── target/                 # gitignored — dbt artifacts (run_results.json, manifest.json)
    └── runs/                   # gitignored — one folder per sample (see §3.3)
        └── {sample_id}/
            ├── sample.duckdb   # materialized tables (latest build)
            ├── run_context.json   # latest vars + overall_status (optional)
            └── mart_pathway_taxonomy_long.parquet   # optional export from wrapper
```

Reference Parquet continues to live at `resources/db/parquet/` (produced by `analytics/exploration/scripts/export_parquet.py`). dbt reads via `read_parquet()` sources or external sources configuration — not duplicated.

## 3.1 Storage Format & Persistence

All models materialize as **DuckDB tables** inside a `.duckdb` database file unless noted otherwise. Parquet is used for **inputs** (reference) and **explicit exports** (mart snapshot per run).

| Layer | When built | Storage | Persisted to disk? | Lifetime |
|---|---|---|---|---|
| **Reference Parquet** | `export_parquet.py` (EDA script) | `resources/db/parquet/*.parquet` | Yes (Git LFS) | Shipped with app; versioned |
| **Reference dbt models** (`dim_tax_rank_map`, `ec_pathway_bridge`) | `dbt build` on reference (distribution / CI) | Tables in shared `transform/data/reference.duckdb` | Yes | Refreshed when Parquet changes |
| **Upload dbt models** (`stg_rpkm_long` … `mart_*`) | `dbt build` on sample upload | Tables in `runs/{sample_id}/sample.duckdb` | Yes | Overwritten on re-upload or param change |
| **Mart export** (optional) | `run_pipeline.py` post-step | `runs/{sample_id}/mart_pathway_taxonomy_long.parquet` | Yes | Overwritten; canonical query target is `sample.duckdb` |
| **dbt artifacts** | each `dbt build` | `transform/target/` | Yes | Overwritten each run (conventional dbt location) |

**Distribution vs upload:** Reference data is read-only input (Parquet → DuckDB tables once). Upload data is written into a **separate per-sample DuckDB file** so re-parameterizing `tax_rank` / `pathway_level` does not re-read the TSV and does not mutate reference tables.

**Views vs tables:** Reference models and `stg_rpkm_long` → **table**. `int_*` and mart may be **table** (v1 default, for inspectability) or **view** (if rebuild latency stays sub-second in profiling — implementation choice).

### 3.2 `.gitignore`

All dbt/DuckDB runtime outputs are **gitignored** — only source SQL, config, seeds, and scripts are committed.

```
# analytics/transform — dbt + DuckDB runtime outputs
analytics/transform/runs/
analytics/transform/data/
analytics/transform/target/
analytics/transform/dbt_packages/
analytics/transform/logs/
analytics/transform/**/*.duckdb
```

Per-sample DuckDB files live at `analytics/transform/runs/{sample_id}/sample.duckdb` (also covered by `runs/`). Reference Parquet under `resources/db/parquet/` remains tracked via Git LFS (unchanged from EDA).

### 3.3 `runs/` folder structure (rationale)

**One folder per sample — latest state only.** No timestamp subfolders or run history in v1.

```
runs/{sample_id}/
  sample.duckdb                        # all upload-path dbt tables
  run_context.json                     # vars + overall_status from last build
  mart_pathway_taxonomy_long.parquet   # optional; wrapper export only
```

| Path | Role | On re-run |
|---|---|---|
| `sample.duckdb` | Working DuckDB for this sample | Tables replaced in place (see below) |
| `run_context.json` | Last invocation metadata | Overwritten |
| `mart_….parquet` | Portable export of mart | Overwritten if wrapper exports |

**dbt artifacts** (`run_results.json`, `manifest.json`) live in **`transform/target/`** — the conventional project-root location. Not duplicated under `runs/`. Overwritten on each `dbt build`.

**Not cached (v1):** `sample.duckdb` holds only the latest `(tax_rank, pathway_level)`. Re-run replaces tables in place; previous param versions are not retained.

**What is reused vs replaced on param change:**

| Model | `tax_rank` change | `pathway_level` change only |
|---|---|---|
| `stg_rpkm_long` | unchanged | unchanged |
| `int_rpkm_pathway` | unchanged | unchanged |
| `int_tax_rollup_resolved` | **full replace** | unchanged |
| `mart_pathway_taxonomy_long` | **full replace** | **full replace** |

**v2 (deferred):** optional param-keyed cache (e.g. `mart_pathway_taxonomy_long__phylum__pathway` table or partition) if users flip ranks frequently and need simultaneous access without re-run.

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
  int_rpkm_pathway          ← LEFT JOIN ec_pathway_bridge; UNMAPPED_EC sentinel when unmapped
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

- **New upload:** full pipeline from `stg_rpkm_long`; `sample.duckdb` tables replaced.
- **Change `tax_rank`:** `dbt build --select int_tax_rollup_resolved+` — replaces `int_tax_rollup_resolved` + mart in `sample.duckdb`.
- **Change `pathway_level` only:** `dbt build --select mart_pathway_taxonomy_long` — replaces mart only (~seconds).

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

`stg_rpkm_long` **LEFT JOIN** `ec_pathway_bridge` ON `ec_normalized`. Carries all three pathway keys on matched rows for cheap re-grouping.

**Mapped ECs:** One row per `(stg_rpkm_long row × matching bridge row)` — same fan-out as before when an EC maps to multiple pathway nodes.

**Unmapped ECs:** When no bridge match, emit **one row** with pathway sentinels:

| Column | Unmapped value |
|---|---|
| `pathway_node_id` | NULL |
| `pathway_id` | NULL |
| `pathway_name` | NULL |
| `superpathway_id` | NULL |
| `superpathway_name` | NULL |
| `is_pathway_mapped` | `false` |

At mart time, unmapped rows use `pathway_key = NULL`, `pathway_label = 'Unmapped EC'`, `is_pathway_mapped = false`. There is no pathway-level fallback (an EC either maps to KEGG or it does not).

**Performance:** Unmapped rows do not fan out; total row count ≈ mapped fan-out + unmapped long rows. Well within DuckDB scale for test fixtures (~36% of distinct ECs unmapped per EDA §7).

### 6.5 `int_tax_rollup_resolved`

Resolves each row to a taxon at requested rank using `dim_tax_rank_map` and `seeds/rank_order.csv`.

**Rank order (coarse → fine):** kingdom, phylum, class, order, family, genus, species.

**Resolution algorithm** (for var `tax_rank`):

1. **Exact:** row in `dim_tax_rank_map` where `tax_id = source_tax_id` AND `rank = tax_rank` → `tax_rank_resolved = tax_rank`.
2. **Fallback:** among rows where `rank_order <= tax_rank_order`, pick finest available (max rank order) → `tax_rank_resolved = that rank` (coarser than requested).
3. **Unclassified:** no qualifying row → `taxon_key = NULL`, `taxon_label = 'Unclassified'`, `tax_rank_resolved = NULL`.

**Deriving resolution type** (not stored — computed from mart columns + `tax_rank_requested`):

| Condition | Meaning |
|---|---|
| `taxon_label = 'Unclassified'` (equivalently `taxon_key IS NULL`) | Unclassified |
| `tax_rank_resolved = tax_rank_requested` | Exact match |
| else (non-null `taxon_key`) | Coarser fallback |

Example (your scenario, `tax_rank_requested = phylum`): taxon A resolves to Bacteroidota at phylum (exact); taxon B with unknown phylum resolves to kingdom Pseudomonadati (fallback). These are **different `(taxon_key, tax_rank_resolved)` pairs** in the mart — no extra grouping dimension needed.

**NULL keys for gap rows** (no synthetic tax_ids or pathway ids):

| Case | `taxon_key` | `taxon_label` | `pathway_key` | `pathway_label` | `is_pathway_mapped` |
|---|---|---|---|---|---|
| Unclassified taxonomy | NULL | `'Unclassified'` | (normal) | (normal) | true or false |
| Unmapped EC | (normal) | (normal) | NULL | `'Unmapped EC'` | `false` |

For unmapped rows, `pathway_label` is a **fixed display string**; per-EC detail remains in `ec_normalized` (carried through from `int_rpkm_pathway`, in mart GROUP BY when `is_pathway_mapped = false`).

**`tax_rank_requested`:** Not echoed on `int_tax_rollup_resolved`. The var is fixed for the entire intermediate build (model rebuilds when it changes). Echo **only on `mart_pathway_taxonomy_long`** and in `run_context.json` — avoids redundant columns on ~720K intermediate rows.

Fallback only walks **coarser** ranks (never genus when phylum was requested).

**Output columns (per input row):**

| Column | Notes |
|---|---|
| (all columns from `int_rpkm_pathway`) | includes `is_pathway_mapped`, `ec_normalized` |
| `tax_rank_resolved` | Actual rank used; NULL when Unclassified |
| `taxon_key` | `rank_tax_id` or NULL |
| `taxon_label` | From `names` join, or `'Unclassified'` |

**Intentional divergence from app:** `get_parents_at_level` uses a name-based backfill heuristic and does not coarser-fallback. Pipeline behavior is explicit and documented.

### 6.6 `mart_pathway_taxonomy_long`

Groups `int_tax_rollup_resolved` by pathway level (from var `pathway_level`) and resolved taxon.

**Mart GROUP BY:** `(pathway_key, pathway_label, taxon_key, taxon_label, tax_rank_resolved, tax_rank_requested, sample_id, pathway_level, is_pathway_mapped, ec_normalized)` — include `ec_normalized` in GROUP BY when `is_pathway_mapped = false` so unmapped EC rows stay separate.

Different source tax_ids that resolve to the same `(taxon_key, tax_rank_resolved)` aggregate together — regardless of whether they arrived via exact or fallback path. Different fallback targets (e.g. Bacteroidota vs Pseudomonadati) remain separate rows.

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
| `pathway_key` | Id at selected level; NULL when unmapped |
| `pathway_label` | Name at selected level; `'Unmapped EC'` when unmapped |
| `is_pathway_mapped` | `true` / `false` |
| `ec_normalized` | EC string; distinguishes unmapped rows in mart |
| `tax_rank_requested` | Echo of var (mart only) |
| `tax_rank_resolved` | Actual rank used (may differ under fallback); NULL when Unclassified |
| `taxon_key` | Resolved tax_id; NULL when Unclassified |
| `taxon_label` | |
| `value` | `SUM(value)` |

## 7. Constraints

Each constraint has an id, check, stage, default severity, and pass criteria. Implemented as dbt tests (`severity: error|warn`) or singular tests (info metrics).

| ID | Check | Model / stage | Severity | Pass when |
|---|---|---|---|---|
| `rpkm_file_readable` | TSV parses; all KEY_COLS present; ≥1 tax column | pre-`stg_rpkm_long` (Python) | error | No exception; valid shape |
| `rpkm_tax_columns_present` | ≥1 tax_id column detected | `stg_rpkm_long` | error | tax_column_count ≥ 1 |
| `rpkm_no_negative_values` | All `value >= 0` | `stg_rpkm_long` | error | 0 violating rows |
| `rpkm_tax_id_resolvable` | Every distinct `source_tax_id` in `names` | `stg_rpkm_long` | warn | 0 unmapped tax_ids |
| `rpkm_ec_kegg_coverage` | `distinct mapped ECs / distinct ECs in sample` | `int_rpkm_pathway` | info | Always passes; emits ratio |
| `unmapped_ec_value_rate` | `SUM(value WHERE NOT is_pathway_mapped) / SUM(value)` | mart | info | Metric only |
| `pathway_join_fanout_rate` | Avg `int_rpkm_pathway` rows per `stg_rpkm_long` row (mapped only) | `int_rpkm_pathway` | info | Metric only |
| `mass_conservation` | `SUM(mart.value)` ≈ `SUM(stg_rpkm_long.value)` | `mart_pathway_taxonomy_long` | warn | Relative delta ≤ 0.01% |
| `mart_nonempty` | Mart row count > 0 | `mart_pathway_taxonomy_long` | error | count > 0 |
| `mart_classified_taxa_have_keys` | No row where `taxon_label != 'Unclassified'` AND `taxon_key IS NULL` | mart | error | 0 rows |
| `mart_mapped_pathways_have_keys` | No row where `is_pathway_mapped = true` AND `pathway_key IS NULL` | mart | error | 0 rows |
| `mart_value_non_null` | All rows: `value IS NOT NULL` | mart | error | 0 nulls |
| `mart_rollup_exact_match_rate` | `SUM(value WHERE tax_rank_resolved = tax_rank_requested AND taxon_label != 'Unclassified') / SUM(value)` | mart | info | Metric only |
| `mart_rollup_fallback_rate` | `SUM(value WHERE tax_rank_resolved != tax_rank_requested AND taxon_label != 'Unclassified') / SUM(value)` | mart | info | Metric only |
| `mart_unclassified_rate` | `SUM(value WHERE taxon_label = 'Unclassified') / SUM(value)` | mart | info | Metric only in v1 |

**Key constraints (replaces `mart_no_null_keys`):** NULL keys are **permitted and expected** for gap rows. Constraints enforce keys only where a real taxonomy/pathway exists:

- **`mart_classified_taxa_have_keys`** — if we resolved a real taxon (`taxon_label != 'Unclassified'`), `taxon_key` must be non-null.
- **`mart_mapped_pathways_have_keys`** — if `is_pathway_mapped = true`, `pathway_key` must be non-null.
- Unclassified and unmapped rows are excluded by label / flag, not by synthetic sentinel ids.

Using **`is_pathway_mapped`** (not `pathway_label != 'Unmapped EC'`) for pathway checks avoids ambiguity if labels change. Taxonomy side uses the fixed `'Unclassified'` label.

**Mass conservation definition:** Sum of mart values equals sum of all `stg_rpkm_long` values (LEFT JOIN preserves full long mass). Document exact SQL in the singular test.

**v2 (deferred):** named constraint profiles (`strict` / `permissive`) overriding default severities.

## 8. CLI & Run Artifacts

### 8.1 Invocation

**Direct dbt (local dev):** Running `dbt build` with `--vars` is sufficient for development and debugging.

**`run_pipeline.py` wrapper (CI, fixtures, future API):** Thin orchestration — not a substitute for dbt logic. Responsibilities:

1. Ensure `runs/{sample_id}/` exists; point dbt profile at `runs/{sample_id}/sample.duckdb`
2. Pass `--vars` consistently (`sample_id`, `rpkm_path`, `tax_rank`, `pathway_level`)
3. Run `dbt build` (artifacts land in `transform/target/`)
4. Write `runs/{sample_id}/run_context.json` (vars + derived `overall_status` parsed from `target/run_results.json`)
5. Optionally export mart Parquet to `runs/{sample_id}/mart_pathway_taxonomy_long.parquet`
6. Single entrypoint for future Node subprocess / CI

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
dbt build \
  --project-dir transform \
  --profiles-dir transform \
  --vars "{ rpkm_path, sample_id, tax_rank, pathway_level }"
```

dbt writes to `transform/target/` by default (no custom `--target-path`).

Re-parameterize only:

```bash
dbt build --select int_tax_rollup_resolved+ --vars '{ "tax_rank": "class", ... }'
```

### 8.2 Artifacts

| Artifact | Location | Writer | Contents |
|---|---|---|---|
| `target/run_results.json` | `transform/target/` | dbt | Per-node status, timing, test outcomes |
| `target/manifest.json` | `transform/target/` | dbt | Lineage, compiled SQL |
| `run_context.json` | `runs/{sample_id}/` | wrapper | vars, `overall_status`, pointer to `transform/target/` |
| `mart_pathway_taxonomy_long.parquet` | `runs/{sample_id}/` | wrapper (optional) | Mart export; query `sample.duckdb` directly otherwise |

**`overall_status` derivation** (from `target/run_results.json`):
- `failed` — any error-severity test fails or model error
- `success_with_warnings` — no errors; ≥1 warn
- `success` — all pass

Artifacts are overwritten each run. No run-history retention in v1.

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
- [ ] `run_context.json` + optional mart Parquet under `runs/{sample_id}/`; dbt artifacts in `transform/target/`
- [ ] README under `analytics/transform/` documents two-phase workflow and rebuild triggers

## 14. References

- `analytics/exploration/docs/data-model.md` — domain model, gotchas, join conventions
- `docs/superpowers/specs/2026-06-11-exploratory-analysis-design.md` — EDA design; `analytics/transform/` anticipated here
- `src/server/parse.ts`, `src/server/db_functions.ts` — current app aggregation semantics (parity target for totals, not identical rollup edge cases)
- `SPEC.md` — RPKM wide format, KEY_COLS, EC normalization
