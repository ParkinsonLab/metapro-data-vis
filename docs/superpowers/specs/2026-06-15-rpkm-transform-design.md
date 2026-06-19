# RPKM → Pathway × Taxonomy Transform Pipeline — Design Spec

> **Status:** Draft (2026-06-15, revised toolchain + reference layout)  
> **Goal:** Build a dbt + DuckDB pipeline in `analytics/transform/` that ingests a wide RPKM/FPKM sample file and produces a long-form pathway × taxonomy matrix with summed per-taxon column values, configurable taxonomy rank and pathway level, tiered constraint checks, and persisted run artifacts. API integration and chord-matrix derivation are explicitly out of scope for v1.

## 1. Context

Metapro Viz ingests wide TSV output from [MetaPro](https://github.com/ParkinsonLab/MetaPro). Each row is a gene/EC record; integer column headers are NCBI `tax_id` values holding per-taxon abundances. Reference taxonomy and KEGG pathway data live in `resources/db/taxonomy.db` (exported to Parquet for analytics).

Exploratory analysis (`analytics/exploration/`, branch `exploration/eda`) validated data shapes, join semantics, and gotchas documented in `analytics/exploration/docs/data-model.md`. The existing Node app performs a similar aggregation in-memory (`src/server/parse.ts` → `make_count_matrix`) but lacks a reproducible, testable, stage-oriented pipeline.

**Two-phase data availability:**

| Phase | When | Data |
|---|---|---|
| **Distribution** | App install / software distribution | Raw reference Parquet (`resources/db/parquet/`); derived bridge Parquet (`analytics/transform/reference/parquet/`) |
| **Runtime** | User uploads RPKM/FPKM | Sample TSV only |

Future work (out of scope v1): invoke pipeline on upload, stream dbt progress to the Node app, pre-compute intermediates for snappy UI, derive `chord_matrix` in the API layer from `mart_pathway_taxonomy_long`.

**Work isolation:** Branch `feature/rpkm-transform` in worktree `.worktrees/rpkm-transform/`, forked from `exploration/eda`.

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Cell value | Per-taxon **column** values, summed | Matches app behavior and EDA unpivot pattern; not row-level `RPKM` column |
| Pathway level | Configurable: `superpathway` \| `pathway` \| `pathway_node`; default `pathway` | Aligns with domain terms: pathway = `pathway_superpathways` row; pathway_node = EC-on-map instance |
| Canonical output | `mart_pathway_taxonomy_long` only | Rectangular matrix and chord matrix deferred |
| Taxonomy rollup | Resolve via `bridge_tax_rank_map`: exact rank → coarser fallback → `Unclassified` | Mart stores `tax_rank_resolved`; exact vs fallback derived via `tax_rank` var / `run_context.json` |
| EC → pathway join | **LEFT JOIN**; NULL `pathway_key` when unmapped (`is_pathway_mapped = false`) | Preserves knowledge-gap mass in mart |
| Reference taxonomy shape | `bridge_tax_rank_map` derived from wide `parents` (long form with self-rows) | Parameterized rank without dynamic SQL columns |
| Reference bridges | `bridge_tax_rank_map`, `bridge_ec_pathway`; built at distribution → `reference/parquet/` | Pre-computed joins; upload reads derived Parquet only |
| Pipeline tool | **dbt-first** (dbt-duckdb) with Python model for wide TSV ingest | Single toolchain; `run_results.json` ready for future streaming |
| Constraints | Tiered severity (error / warn / info); profile-ready for v2 | dbt test `severity:` + info singular tests; no profiles in v1 |
| Reporting | dbt artifacts in `transform/target/`; `run_context.json` when using wrapper | Conventional dbt layout; no per-run history |
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
    │   ├── run_pipeline.py
    │   └── build_reference.py   # distribution: dbt tag:reference + export to reference/parquet/
    ├── reference/
    │   └── parquet/             # versioned — derived bridge tables (Git LFS)
    │       ├── bridge_tax_rank_map.parquet
    │       └── bridge_ec_pathway.parquet
    ├── data/                   # gitignored — optional staging DB during distribution build
    ├── target/                 # gitignored — dbt artifacts (run_results.json, manifest.json)
    └── runs/                   # gitignored — one folder per sample (see §3.3)
        └── {sample_id}/
            ├── sample.duckdb   # materialized tables (latest build)
            ├── run_context.json   # written by wrapper (latest vars + overall_status)
            └── mart_pathway_taxonomy_long.parquet   # optional export from wrapper
```

**Two reference Parquet layers (different provenance):**

| Layer | Produced by | Location |
|---|---|---|
| **Raw** table exports | `export_parquet.py` from `taxonomy.db` | `resources/db/parquet/*.parquet` |
| **Derived** bridge tables | `build_reference.py` / `dbt build --select tag:reference` | `analytics/transform/reference/parquet/*.parquet` |

Raw Parquet is input to distribution-time dbt reference models only. Upload reads **derived** bridge Parquet — not raw tables, not recomputed UNPIVOT/joins.

## 3.1 Storage Format & Persistence

Upload-path models materialize as **DuckDB tables** inside `sample.duckdb` unless noted otherwise. Reference bridge models at upload are **views**. Parquet is used for reference inputs/exports and optional mart snapshots.

| Layer | When built | Storage | Persisted to disk? | Lifetime |
|---|---|---|---|---|
| **Raw reference Parquet** | `export_parquet.py` | `resources/db/parquet/*.parquet` | Yes (Git LFS) | Shipped with app; versioned |
| **Derived bridge Parquet** | `build_reference.py` at distribution | `analytics/transform/reference/parquet/*.parquet` | Yes (Git LFS) | Shipped with app; versioned |
| **Reference dbt models** (`bridge_tax_rank_map`, `bridge_ec_pathway`) | Distribution builds tables; upload reads derived Parquet | **Views** over derived Parquet in `sample.duckdb` (see §3.4) | View DDL in `sample.duckdb` | Refreshed when derived Parquet changes |
| **Upload dbt models** (`stg_rpkm_long` … `mart_*`) | `dbt build` on sample upload | Tables in `runs/{sample_id}/sample.duckdb` | Yes | Overwritten on re-upload or param change |
| **Mart export** (optional) | `run_pipeline.py` post-step | `runs/{sample_id}/mart_pathway_taxonomy_long.parquet` | Yes | Overwritten; canonical query target is `sample.duckdb` |
| **dbt artifacts** | each `dbt build` | `transform/target/` | Yes | Overwritten each run (conventional dbt location) |

**Distribution vs upload:** Raw Parquet → dbt reference SQL → derived bridge Parquet (once, at distribution). Upload loads sample TSV into a **separate per-sample DuckDB file** and joins pre-built bridges via thin views — no reference recomputation on the upload path.

**Materialization by phase:**

| Phase | Reference models | Upload models |
|---|---|---|
| **Distribution** | **table** (staging DB) → export to `reference/parquet/` | — |
| **Upload** | **view** over derived Parquet in `sample.duckdb` | **table** (`stg_rpkm_long`, `int_*`, mart) |

`int_*` and mart may be **view** instead of table if rebuild latency stays sub-second in profiling — implementation choice.

### 3.2 `.gitignore`

All dbt/DuckDB **runtime** outputs are **gitignored** — source SQL, config, seeds, scripts, and **`reference/parquet/`** (derived bridges) are committed.

```
# analytics/transform — dbt + DuckDB runtime outputs
analytics/transform/runs/
analytics/transform/data/
analytics/transform/target/
analytics/transform/dbt_packages/
analytics/transform/logs/
analytics/transform/**/*.duckdb
```

**Not gitignored:** `analytics/transform/reference/parquet/` (derived bridge Parquet, Git LFS) and `resources/db/parquet/` (raw exports, Git LFS).

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
| `stg_rpkm_long`, `int_rpkm_by_ec_tax` | unchanged | unchanged |
| `int_rpkm_pathway` | unchanged | **full replace** (fan-out dedup is level-specific) |
| `int_tax_rollup_resolved` | **full replace** | unchanged |
| `mart_pathway_taxonomy_long` | **full replace** | **full replace** |

**v2 (deferred):** optional param-keyed cache if users need simultaneous access to multiple `(tax_rank, pathway_level)` combos without re-run.

### 3.4 Reference data access

Reference bridge models must be queryable from upload-path models without cross-database `ref()` issues and **without recomputing** UNPIVOT/joins at upload.

**v1 pattern: pre-built derived Parquet + upload views**

```
Distribution                          Upload
────────────                          ──────
export_parquet.py                     stg_rpkm_long → … → mart
  → resources/db/parquet/ (raw)
dbt build --select tag:reference
  → tables in staging DB
build_reference.py
  → reference/parquet/bridge_*.parquet   ref('bridge_ec_pathway') etc.
                                        → views scan derived Parquet
```

**Distribution (`build_reference.py`):**
1. `dbt build --select tag:reference` — reference SQL reads **raw** Parquet from `resources/db/parquet/`; materializes **tables** in a staging DB (`data/reference.duckdb`, gitignored).
2. `COPY … TO 'reference/parquet/bridge_tax_rank_map.parquet'` (and `bridge_ec_pathway.parquet`).
3. Commit / ship derived Parquet via Git LFS.

**Upload:** Reference models are **views** in `sample.duckdb` over **derived** Parquet:

```sql
-- models/reference/bridge_ec_pathway.sql (upload profile, materialized: view)
SELECT * FROM read_parquet('{{ var("reference_parquet_dir") }}/bridge_ec_pathway.parquet')
```

Upload command is **`dbt build --select stg_rpkm_long+` only** — no `tag:reference`. Wrapper fails fast if derived Parquet files are missing (dev fallback: run `build_reference.py` first).

**Implementation note:** Distribution and upload use different dbt **targets** (or profiles) for the same model names — distribution target materializes **tables** from raw Parquet (`raw_parquet_dir`); upload target materializes **views** over derived Parquet (`reference_parquet_dir`). `build_reference.py` runs the distribution target then exports tables to `reference/parquet/`.

| Approach | Pros | Cons |
|---|---|---|
| **Derived Parquet + upload views (selected)** | Pre-computed at distribution; fast upload joins; single `sample.duckdb`; `ref()` works natively | Distribution export step; two Parquet roots to document |
| **ATTACH staging `reference.duckdb` READ_ONLY** | Pre-built tables; no Parquet export | Cross-DB config; harder to ship/version |
| **Views over raw Parquet at upload** | No export step | Recomputes UNPIVOT/joins on every upload — rejected |

**dbt vars (paths):**

| Var | Points to | Used when |
|---|---|---|
| `raw_parquet_dir` | `resources/db/parquet/` | Distribution (`tag:reference` SQL) |
| `reference_parquet_dir` | `analytics/transform/reference/parquet/` | Upload (reference views) |

Upload/run vars (`rpkm_path`, `sample_id`, `tax_rank`, `pathway_level`) — see §6.7.

**Between-sample delta (future):** attach `runs/A/sample.duckdb` and `runs/B/sample.duckdb`; join marts on `(pathway_key, taxon_key)`. Reference layout does not affect delta.

## 4. Approach

**Selected: dbt-first with Python ingest model (Approach A).**

Rejected alternatives:
- **Hybrid CLI pre-step + dbt** — split orchestration, broken lineage at ingest.
- **Pure SQL with codegen UNPIVOT** — fragile per-sample column lists.

Python 3.14 (repo pin) + **dbt-core 1.12.0b1** (beta; Python 3.14 support) + dbt-duckdb. See §9.

## 5. Model Graph & Rebuild Triggers

```
[distribution — build once, ship derived Parquet]
  bridge_tax_rank_map       ← raw parents parquet; export → reference/parquet/
  bridge_ec_pathway           ← raw pathway_* parquet; export → reference/parquet/

[upload — views over derived Parquet in sample.duckdb]
  bridge_tax_rank_map         ← read_parquet(reference/parquet/…)
  bridge_ec_pathway           ← read_parquet(reference/parquet/…)

[upload — sample tables]
  stg_rpkm_long             ← Python: wide TSV → long, EC normalize, nonzero filter
       ↓
  int_rpkm_by_ec_tax        ← SUM(value) GROUP BY (ec_normalized, source_tax_id)
       ↓
  int_rpkm_pathway          ← LEFT JOIN bridge_ec_pathway; dedupe fan-out per row at selected level
       ↓
  int_tax_rollup_resolved   ← join bridge_tax_rank_map; exact / fallback / unclassified
       ↓
  mart_pathway_taxonomy_long ← GROUP BY pathway level + taxon; SUM(value)
```

### 5.1 Abundance aggregation semantics (app parity)

Two distinct steps — do not conflate:

1. **Gene aggregation (`int_rpkm_by_ec_tax`):** Multiple genes with the same `(ec_normalized, source_tax_id)` have their `value` **summed before** the pathway join. Matches the app iterating gene rows and accumulating into the same `(EC, taxon)` bucket.

2. **Fan-out dedup (`int_rpkm_pathway` → mart):** After the join, each aggregated row may match multiple `pathway_node` rows. **Per aggregated row**, count `value` at most **once per `pathway_key` at the selected level** (matches app `reduce_to_dict` Set dedup). At `pathway_node` level, do not dedup across nodes — intentional multi-count.

| `pathway_level` | Fan-out dedup |
|---|---|
| `superpathway` | one count per `(int_rpkm_by_ec_tax row, superpathway_id)` |
| `pathway` | one count per `(row, pathway_id)` |
| `pathway_node` | no dedup — one row per node |

**`mass_conservation`:** `SUM(mart.value)` ≈ `SUM(stg_rpkm_long.value)` after gene aggregation and pathway-level dedup (not raw fan-out row count).

| Model | Rebuilt when | Not rebuilt when |
|---|---|---|
| `bridge_tax_rank_map`, `bridge_ec_pathway` (derived Parquet) | Raw Parquet refresh; reference SQL change; `build_reference.py` re-run | Sample upload; param changes |
| `bridge_*` (upload views) | Derived Parquet refresh; first upload per sample | Param changes; re-upload if views persist |
| `stg_rpkm_long` | New/changed RPKM file | `tax_rank` / `pathway_level` change |
| `int_rpkm_by_ec_tax` | `stg_rpkm_long` rebuilds | `tax_rank` / `pathway_level` change |
| `int_rpkm_pathway` | `int_rpkm_by_ec_tax` rebuilds; `pathway_level` var change | `tax_rank` change alone |
| `int_tax_rollup_resolved` | Upstream rebuild or `tax_rank` var change | `pathway_level` change alone |
| `mart_pathway_taxonomy_long` | Upstream rebuild or `pathway_level` var change; also `tax_rank` via upstream | — |

**Typical operations:**

- **Distribution / reference refresh:** `uv run python transform/scripts/build_reference.py` (runs `dbt build --select tag:reference` + Parquet export).
- **New upload:** `dbt build --select stg_rpkm_long+` (or wrapper equivalent — **no** `tag:reference`).
- **Change `tax_rank`:** `dbt build --select int_tax_rollup_resolved+`.
- **Change `pathway_level` only:** `dbt build --select int_rpkm_pathway+` (pathway dedup is level-specific) or `mart_pathway_taxonomy_long+`.

**dbt `--select` syntax:** `stg_rpkm_long+` means the model `stg_rpkm_long` **and all downstream** dependencies.

## 6. Model Specifications

### 6.1 `bridge_tax_rank_map` (reference, `tag:reference`)

Derived from wide `parents` raw Parquet (`raw_parquet_dir`). Does not modify upstream Parquet. Exported to `reference/parquet/bridge_tax_rank_map.parquet` at distribution.

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

### 6.2 `bridge_ec_pathway` (reference, `tag:reference`)

Derived from raw `pathway_*` / `superpathways` Parquet. Exported to `reference/parquet/bridge_ec_pathway.parquet` at distribution.

**Columns:**

| Column | Type | Notes |
|---|---|---|
| `ec_normalized` | VARCHAR | Join key from RPKM |
| `pathway_node_id` | VARCHAR | For `pathway_level = pathway_node` |
| `pathway_id` | BIGINT | FK to `pathway_superpathways.id` |
| `pathway_name` | VARCHAR | Display |
| `superpathway_id` | VARCHAR | FK to `superpathways.id` |
| `superpathway_name` | VARCHAR | Display |

One row per `(ec_normalized, pathway_node_id)`. **Join key:** `ec_normalized = normalize(pathway_nodes.name)` on both RPKM and bridge sides (same rules as §6.3).

When aggregating at `pathway` or `superpathway`, dedup to one count per distinct id at that level (§5.1). Matches app `reduce_to_dict`.

**`pathway_nodes.type` filter:** deferred post-EDA (not v1). EC numbers are enzyme commission identifiers and should not match non-enzyme node names in practice; app also joins without type filter.

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

**Source `Unclassified` column:** `Unclassified` is a fixed KEY_COL (not a tax_id column). Its abundance is **excluded** from unpivot and the pipeline — distinct from rollup `'Unclassified'` taxon label (§6.6). Documented analytical gap for v1; not required for app parity.

**Output columns:**

| Column | Notes |
|---|---|
| `sample_id` | From var |
| `gene_id` | From `GeneID` |
| `ec_normalized` | Normalized EC |
| `source_tax_id` | RPKM column header |
| `value` | Per-taxon column value |

### 6.4 `int_rpkm_by_ec_tax`

`GROUP BY (sample_id, ec_normalized, source_tax_id)` → `SUM(value)`.

Collapses multiple genes sharing the same EC and tax_id column before pathway join. Drops `gene_id` — no longer needed after aggregation.

### 6.5 `int_rpkm_pathway`

`int_rpkm_by_ec_tax` **LEFT JOIN** `bridge_ec_pathway` ON `ec_normalized`. Apply **fan-out dedup** (§5.1) before downstream models.

**Mapped ECs:** After fan-out dedup (§5.1), at most one counted row per `(int_rpkm_by_ec_tax row, pathway_key at selected level)` for mapped ECs. Before dedup, one aggregated row may match many `pathway_node` rows.

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

**Performance:** Gene aggregation reduces row count before join. `pathway_join_fanout_rate` (§7) monitors fan-out multiplier — early warning if dedup is skipped.

### 6.6 `int_tax_rollup_resolved`

Resolves each row to a taxon at requested rank using `bridge_tax_rank_map` and `seeds/rank_order.csv`.

**Rank order (coarse → fine):** kingdom, phylum, class, order, family, genus, species.

**Resolution algorithm** (for var `tax_rank`):

1. **Exact:** row in `bridge_tax_rank_map` where `tax_id = source_tax_id` AND `rank = tax_rank` → `tax_rank_resolved = tax_rank`.
2. **Fallback:** among rows where `rank_order <= tax_rank_order`, pick finest available (max rank order) → `tax_rank_resolved = that rank` (coarser than requested).
3. **Unclassified:** no qualifying row → `taxon_key = NULL`, `taxon_label = 'Unclassified'`, `tax_rank_resolved = NULL`.

**Deriving resolution type** (not stored on mart — use `tax_rank` dbt var or `run_context.json`):

| Condition | Meaning |
|---|---|
| `taxon_label = 'Unclassified'` (equivalently `taxon_key IS NULL`) | Unclassified |
| `tax_rank_resolved = {{ var('tax_rank') }}` | Exact match |
| else (non-null `taxon_key`) | Coarser fallback |

Example (requested rank = phylum via var): taxon A resolves to Bacteroidota at phylum (exact); taxon B with unknown phylum resolves to kingdom Pseudomonadati (fallback). These are **different `(taxon_key, tax_rank_resolved)` pairs** in the mart — no extra grouping dimension needed.

**NULL keys for gap rows** (no synthetic tax_ids or pathway ids):

| Case | `taxon_key` | `taxon_label` | `pathway_key` | `pathway_label` | `is_pathway_mapped` |
|---|---|---|---|---|---|
| Unclassified taxonomy | NULL | `'Unclassified'` | (normal) | (normal) | true or false |
| Unmapped EC | (normal) | (normal) | NULL | `'Unmapped EC'` | `false` |

For unmapped rows, `pathway_label` is a **fixed display string**; per-EC detail remains in `ec_normalized` (carried through from `int_rpkm_pathway`, in mart GROUP BY when `is_pathway_mapped = false`).

**Run-level params (`tax_rank`, `pathway_level`):** Not echoed on mart or `int_tax_rollup_resolved` rows. Stored in dbt vars during build and in `runs/{sample_id}/run_context.json` after build. Constraints and info metrics reference `{{ var('tax_rank') }}` directly.

Fallback only walks **coarser** ranks (never genus when phylum was requested).

**Output columns (per input row):**

| Column | Notes |
|---|---|
| (all columns from `int_rpkm_pathway`) | includes `is_pathway_mapped`, `ec_normalized` |
| `tax_rank_resolved` | Actual rank used; NULL when Unclassified |
| `taxon_key` | `rank_tax_id` or NULL |
| `taxon_label` | From `names` join, or `'Unclassified'` |

**Intentional divergence from app:** `get_parents_at_level` uses a name-based backfill heuristic and does not coarser-fallback. Pipeline behavior is explicit and documented.

### 6.7 `mart_pathway_taxonomy_long`

Groups `int_tax_rollup_resolved` by pathway level (from var `pathway_level`) and resolved taxon.

**Mart GROUP BY:** `(pathway_key, pathway_label, taxon_key, taxon_label, tax_rank_resolved, sample_id, pathway_level, is_pathway_mapped, ec_normalized)` — include `ec_normalized` in GROUP BY when `is_pathway_mapped = false` so unmapped EC rows stay separate.

Different source tax_ids that resolve to the same `(taxon_key, tax_rank_resolved)` aggregate together — regardless of whether they arrived via exact or fallback path. Different fallback targets (e.g. Bacteroidota vs Pseudomonadati) remain separate rows.

**Vars (upload / full pipeline):**

| Var | Allowed values | Default |
|---|---|---|
| `rpkm_path` | path to TSV | required on full run |
| `sample_id` | string | required |
| `tax_rank` | kingdom … species | `phylum` |
| `pathway_level` | superpathway, pathway, pathway_node | `pathway` |
| `reference_parquet_dir` | path to derived bridge Parquet | `analytics/transform/reference/parquet/` |

Path vars for distribution builds — see §3.4 (`raw_parquet_dir`).

**Output columns:**

| Column | Notes |
|---|---|
| `sample_id` | |
| `pathway_level` | Requested level |
| `pathway_key` | Id at selected level; NULL when unmapped |
| `pathway_label` | Name at selected level; `'Unmapped EC'` when unmapped |
| `is_pathway_mapped` | `true` / `false` |
| `ec_normalized` | EC string; distinguishes unmapped rows in mart |
| `tax_rank_resolved` | Actual rank used (may differ under fallback); NULL when Unclassified |
| `taxon_key` | Resolved tax_id; NULL when Unclassified |
| `taxon_label` | |
| `value` | `SUM(value)` |

## 7. Constraints

Each constraint has an id, check, stage, default severity, and pass criteria. **Pre-flight checks** (`rpkm_file_readable`) run in Python / wrapper before dbt — not dbt tests.

| ID | Check | Model / stage | Severity | Pass when |
|---|---|---|---|---|
| `rpkm_file_readable` | TSV parses; all KEY_COLS present; ≥1 tax column | **pre-flight** (Python / wrapper) | error | No exception; valid shape |
| `rpkm_tax_columns_present` | ≥1 tax_id column detected | `stg_rpkm_long` | error | tax_column_count ≥ 1 |
| `rpkm_no_negative_values` | All `value >= 0` | `stg_rpkm_long` | error | 0 violating rows |
| `rpkm_tax_id_resolvable` | Every distinct `source_tax_id` in `names` | `stg_rpkm_long` | warn | 0 unmapped tax_ids |
| `rpkm_ec_kegg_coverage` | `distinct mapped ECs / distinct ECs in sample` | `int_rpkm_pathway` | info | Always passes; emits ratio |
| `unmapped_ec_value_rate` | `SUM(value WHERE NOT is_pathway_mapped) / SUM(value)` | mart | info | Metric only |
| `pathway_join_fanout_rate` | Avg bridge matches per `int_rpkm_by_ec_tax` row before dedup (mapped only) | `int_rpkm_pathway` | info | Metric only; high values imply mass-conservation risk if dedup skipped |
| `mass_conservation` | `SUM(mart.value)` ≈ `SUM(stg_rpkm_long.value)` after gene agg + pathway dedup | mart | warn | Relative delta ≤ 0.01% |
| `mart_nonempty` | Mart row count > 0 | `mart_pathway_taxonomy_long` | error | count > 0 |
| `mart_classified_taxa_have_keys` | No row where `taxon_label != 'Unclassified'` AND `taxon_key IS NULL` | mart | error | 0 rows |
| `mart_mapped_pathways_have_keys` | No row where `is_pathway_mapped = true` AND `pathway_key IS NULL` | mart | error | 0 rows |
| `mart_value_non_null` | All rows: `value IS NOT NULL` | mart | error | 0 nulls |
| `mart_rollup_exact_match_rate` | `SUM(value WHERE tax_rank_resolved = var('tax_rank') AND taxon_label != 'Unclassified') / SUM(value)` | mart | info | Metric only |
| `mart_rollup_fallback_rate` | `SUM(value WHERE tax_rank_resolved != var('tax_rank') AND taxon_label != 'Unclassified') / SUM(value)` | mart | info | Metric only |
| `mart_unclassified_rate` | `SUM(value WHERE taxon_label = 'Unclassified') / SUM(value)` | mart | info | Metric only in v1 |

**Key constraints (replaces `mart_no_null_keys`):** NULL keys are **permitted and expected** for gap rows. Constraints enforce keys only where a real taxonomy/pathway exists:

- **`mart_classified_taxa_have_keys`** — if we resolved a real taxon (`taxon_label != 'Unclassified'`), `taxon_key` must be non-null.
- **`mart_mapped_pathways_have_keys`** — if `is_pathway_mapped = true`, `pathway_key` must be non-null.
- Unclassified and unmapped rows are excluded by label / flag, not by synthetic sentinel ids.

Using **`is_pathway_mapped`** (not `pathway_label != 'Unmapped EC'`) for pathway checks avoids ambiguity if labels change. Taxonomy side uses the fixed `'Unclassified'` label.

**Mass conservation definition:** `SUM(mart.value)` equals `SUM(stg_rpkm_long.value)` — gene aggregation is lossless; pathway fan-out dedup ensures no inflation at `pathway`/`superpathway` levels. Document exact SQL in the singular test.

**Sample path safety:** `sample_id` is an opaque label for `runs/{sample_id}/`. **Path sanitization is the upload/API layer's responsibility** (v1 CLI uses trusted fixture names).

**v2 (deferred):** named constraint profiles (`strict` / `permissive`) overriding default severities.

## 8. CLI & Run Artifacts

### 8.0 Distribution — reference build

```bash
cd analytics
uv run python transform/scripts/build_reference.py
```

Steps:
1. Verify raw Parquet exists under `resources/db/parquet/` (run `export_parquet.py` if missing).
2. `dbt build --select tag:reference` against staging DB (`data/reference.duckdb`).
3. Export `bridge_tax_rank_map` and `bridge_ec_pathway` to `reference/parquet/`.

Run at distribution, after raw Parquet refresh, and in CI to validate reference SQL. Derived Parquet is committed (Git LFS) and shipped with releases.

### 8.1 Invocation

**Direct dbt (local dev):** Running `dbt build` with `--vars` is sufficient for development and debugging.

**`run_pipeline.py` wrapper (CI, fixtures, future API):** Thin orchestration — not a substitute for dbt logic. Responsibilities:

1. Ensure `runs/{sample_id}/` exists; point dbt profile at `runs/{sample_id}/sample.duckdb`
2. Verify derived bridge Parquet exists under `reference/parquet/` (fail with actionable message if not)
3. Pass `--vars` consistently (`sample_id`, `rpkm_path`, `tax_rank`, `pathway_level`, `reference_parquet_dir`)
4. Run `dbt build --select stg_rpkm_long+` (upload path only — reference views materialized from derived Parquet)
5. Write `runs/{sample_id}/run_context.json` (vars + derived `overall_status` parsed from `target/run_results.json`)
6. Optionally export mart Parquet to `runs/{sample_id}/mart_pathway_taxonomy_long.parquet`
7. Single entrypoint for future Node subprocess / CI

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
dbt build --select stg_rpkm_long+ \
  --project-dir transform \
  --profiles-dir transform \
  --vars "{ rpkm_path, sample_id, tax_rank, pathway_level, reference_parquet_dir }"
```

dbt writes to `transform/target/` by default (no custom `--target-path`).

Re-parameterize only:

```bash
dbt build --select int_tax_rollup_resolved+ --vars '{ "tax_rank": "class", ... }'
```

### 8.2 Artifacts

| Artifact | Location | Writer | Contents |
|---|---|---|---|
| `bridge_*.parquet` | `transform/reference/parquet/` | `build_reference.py` | Derived reference bridges; versioned, shipped |
| `target/run_results.json` | `transform/target/` | dbt | Per-node status, timing, test outcomes |
| `target/manifest.json` | `transform/target/` | dbt | Lineage, compiled SQL |
| `run_context.json` | `runs/{sample_id}/` | wrapper | `tax_rank`, `pathway_level`, `sample_id`, `rpkm_path`, `overall_status`, pointer to `transform/target/` |
| `mart_pathway_taxonomy_long.parquet` | `runs/{sample_id}/` | wrapper (optional) | Mart export; query `sample.duckdb` directly otherwise |

**`overall_status` derivation** (from `target/run_results.json`):
- `failed` — any error-severity test fails or model error
- `success_with_warnings` — no errors; ≥1 warn
- `success` — all pass

Artifacts are overwritten each run. No run-history retention in v1.

## 9. Python Environment

Stay on **Python 3.14** (repo pin). Pin in `analytics/pyproject.toml`:

```toml
dependencies = [
    "dbt-core==1.12.0b1",
    "dbt-duckdb>=1.10.1",
    "mashumaro>=3.17,<3.18",  # explicit — uv may otherwise resolve 3.14 transitively
    # duckdb, jupyter, etc. from exploration
]

[tool.uv]
prerelease = "allow"
```

**Why 1.12 beta:** Python 3.14 support landed in dbt-core **1.12.0-b1** ([changelog](https://github.com/dbt-labs/dbt-core/blob/v1.12.0b1/CHANGELOG.md), [issue #12098](https://github.com/dbt-labs/dbt-core/issues/12098)). Stable 1.11.x does **not** support 3.14. Upgrade to 1.12 stable when released; until then pin the beta.

**Why explicit `mashumaro`:** dbt 1.12 allows `mashumaro>=3.9,<3.18`, but other transitive deps can pin **3.14**, which still crashes on Python 3.14. Pin **3.17+** explicitly in `pyproject.toml`.

### 9.1 Toolchain verification gate

**First implementation task:** `uv sync && dbt --version` must succeed on Python 3.14 before building models.

**Verified 2026-06-15 on Python 3.14.2:**

| Package | Version | Result |
|---|---|---|
| `dbt-core` | 1.11.11 (stable) | **Fails** — `mashumaro.exceptions.UnserializableField` at import |
| `dbt-core` | 2.0.0a2 | **Fails** — same error (wrong release line; not the 1.12 beta) |
| `dbt-core` | **1.12.0b1** + `mashumaro` 3.17+ | **Works** — `dbt --version` succeeds; `dbt-duckdb` 1.10.1 compatible |

The failure mode on unsupported combos is an import-time mashumaro error (`Field "schema" … in JSONObjectSchema is not serializable`), before any dbt command runs. Fixing mashumaro alone on 1.11.x is insufficient — use **dbt-core 1.12.0b1** plus explicit **mashumaro 3.17+**.

```bash
cd analytics && uv sync && uv run dbt --version
# Expected: Core 1.12.0-b1; Plugins: duckdb 1.10.x
```

## 10. Validation Strategy

| Layer | Approach |
|---|---|
| Unit | Python ingest on synthetic wide TSV snippets; rank map from known `parents` subset |
| Integration | `build_reference.py` then `dbt build --select stg_rpkm_long+` on test fixtures; assert mart shape and constraint metrics |
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
- [ ] Toolchain gate passes: `uv sync && uv run dbt --version` → Core **1.12.0-b1** on Python 3.14 (§9.1)
- [ ] `build_reference.py` produces derived bridge Parquet from raw reference Parquet
- [ ] Upload pipeline produces `mart_pathway_taxonomy_long` for `test_rpkm_1.tsv` at default vars **without** running `tag:reference`
- [ ] Re-run with changed `tax_rank` / `pathway_level` completes in seconds without re-ingesting TSV
- [ ] All error-severity constraints pass on test fixtures
- [ ] Info metrics (EC coverage, exact/fallback/unclassified rates) emitted
- [ ] `run_context.json` + optional mart Parquet under `runs/{sample_id}/`; dbt artifacts in `transform/target/`
- [ ] README under `analytics/transform/` documents distribution (`build_reference.py`) vs upload workflow and rebuild triggers

## 14. References

- `analytics/exploration/docs/data-model.md` — domain model, gotchas, join conventions
- `docs/superpowers/specs/2026-06-11-exploratory-analysis-design.md` — EDA design; `analytics/transform/` anticipated here
- `src/server/parse.ts`, `src/server/db_functions.ts` — current app aggregation semantics (parity target for totals, not identical rollup edge cases)
- `SPEC.md` — RPKM wide format, KEY_COLS, EC normalization
- [Upgrading to v1.12](https://docs.getdbt.com/docs/dbt-versions/core-upgrade/upgrading-to-v1.12) — dbt Python 3.14 support (1.12 beta)
