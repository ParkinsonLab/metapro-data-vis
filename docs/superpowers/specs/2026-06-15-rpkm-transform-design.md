# RPKM → Pathway × Taxonomy Transform Pipeline — Design Spec

> **Status:** Draft (2026-06-15, revised toolchain + reference layout; 2026-06-21, bridges as dbt sources + EDA-confirmed bridge filter + output schemas + int_rpkm_pathway UNION ALL all-levels design)  
> **Goal:** Build a dbt + DuckDB pipeline in `analytics/transform/` that ingests a wide RPKM/FPKM sample file and produces a long-form pathway × taxonomy matrix with summed per-taxon column values, configurable taxonomy rank and pathway level, tiered constraint checks, and persisted run artifacts. API integration and chord-matrix derivation are explicitly out of scope for v1.

## 1. Context

Metapro Viz ingests wide TSV output from [MetaPro](https://github.com/ParkinsonLab/MetaPro). Each row is a gene/EC record; integer column headers are NCBI `tax_id` values holding per-taxon abundances. Reference taxonomy and KEGG pathway data live in `resources/db/taxonomy.db` (exported to Parquet for analytics).

Exploratory analysis (`analytics/exploration/`, branch `exploration/eda`) validated data shapes, join semantics, and gotchas documented in `analytics/exploration/docs/data-model.md`. The existing Node app performs a similar aggregation in-memory (`src/server/parse.ts` → `make_count_matrix`) but lacks a reproducible, testable, stage-oriented pipeline.

**Two-phase data availability:**

| Phase | When | Data |
|---|---|---|
| **Distribution** | App install / software distribution | Raw reference Parquet (`resources/db/parquet/`); derived bridge Parquet (`analytics/transform/reference/parquet/`) built by `build_reference.py` and committed via Git LFS |
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
| EC → pathway join | **LEFT JOIN**; `pathway_key IS NULL` when unmapped | Preserves knowledge-gap mass in mart; no boolean flag needed |
| Reference taxonomy shape | `bridge_tax_rank_map` derived from wide `parents` (long form with self-rows) | Parameterized rank without dynamic SQL columns |
| Reference bridges | `bridge_tax_rank_map`, `bridge_ec_pathway`; built at distribution by `build_reference.py` → `reference/parquet/`; consumed at upload as dbt external sources | Pre-computed joins; no dbt build step at upload; no dual-profile complexity |
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
    │   ├── sources.yml          # bridge_tax_rank_map, bridge_ec_pathway as external sources
    │   ├── staging/
    │   ├── intermediate/
    │   └── marts/
    ├── seeds/
    ├── tests/
    ├── macros/
    ├── scripts/
    │   ├── run_pipeline.py
    │   └── build_reference.py   # distribution: pure DuckDB SQL → reference/parquet/
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
| **Derived** bridge tables | `build_reference.py` (pure DuckDB SQL) | `analytics/transform/reference/parquet/*.parquet` |

Raw Parquet is input to `build_reference.py` only. Upload reads **derived** bridge Parquet via dbt external sources — no raw table access, no UNPIVOT/join recomputation at upload.

## 3.1 Storage Format & Persistence

Upload-path models materialize as **DuckDB tables** inside `sample.duckdb` unless noted otherwise. Reference bridges are **dbt external sources** — no build step at upload. Parquet is used for reference inputs/exports and optional mart snapshots.

| Layer | When built | Storage | Persisted to disk? | Lifetime |
|---|---|---|---|---|
| **Raw reference Parquet** | `export_parquet.py` | `resources/db/parquet/*.parquet` | Yes (Git LFS) | Shipped with app; versioned |
| **Derived bridge Parquet** | `build_reference.py` at distribution | `analytics/transform/reference/parquet/*.parquet` | Yes (Git LFS) | Shipped with app; versioned |
| **Bridge dbt sources** (`bridge_tax_rank_map`, `bridge_ec_pathway`) | Declared in `sources.yml`; no build — dbt resolves `{{ source(...) }}` as `read_parquet(...)` at query time | Scanned live from derived Parquet in `sample.duckdb` queries | No DDL stored | Auto-refreshed on Parquet change; no staleness risk |
| **Upload dbt models** (`stg_rpkm_long` … `mart_*`) | `dbt build` on sample upload | Tables in `runs/{sample_id}/sample.duckdb` | Yes | Overwritten on re-upload or param change |
| **Mart export** (optional) | `run_pipeline.py` post-step | `runs/{sample_id}/mart_pathway_taxonomy_long.parquet` | Yes | Overwritten; canonical query target is `sample.duckdb` |
| **dbt artifacts** | each `dbt build` | `transform/target/` | Yes | Overwritten each run (conventional dbt location) |

**Distribution vs upload:** `build_reference.py` (pure DuckDB SQL, no dbt) produces derived bridge Parquet (once, at distribution). Upload loads sample TSV into a **separate per-sample DuckDB file**; upload models reference bridges via `{{ source('reference', '...') }}` which compiles to `read_parquet(...)` — no reference build step, no cross-DB complexity.

**Materialization by phase:**

| Phase | Bridges | Upload models |
|---|---|---|
| **Distribution** | Built by `build_reference.py` DuckDB SQL → `reference/parquet/` | — |
| **Upload** | **dbt sources** — scanned live from derived Parquet, zero build cost | **table** (`stg_rpkm_long`, `int_*`, mart) |

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

Reference bridges must be queryable from upload-path models without cross-database `ref()` issues and **without recomputing** UNPIVOT/joins at upload.

**v1 pattern: pre-built derived Parquet + dbt external sources**

```
Distribution                          Upload
────────────                          ──────
export_parquet.py                     stg_rpkm_long → … → mart
  → resources/db/parquet/ (raw)              ↑
build_reference.py (pure DuckDB SQL)  {{ source('reference', 'bridge_ec_pathway') }}
  → reference/parquet/bridge_*.parquet   → compiled: read_parquet(reference_parquet_dir/…)
```

**Distribution (`build_reference.py`):**  
Pure Python + DuckDB — **no dbt invocation** at this step.
1. Connect DuckDB; read raw Parquet from `resources/db/parquet/`.
2. Run bridge SQL (UNPIVOT / join logic per §6.1–6.2) directly via `conn.execute()`.
3. `COPY … TO 'reference/parquet/bridge_tax_rank_map.parquet'` (and `bridge_ec_pathway.parquet`).
4. Commit / ship derived Parquet via Git LFS.

**Upload:** Bridges are declared as **dbt external sources** in `sources.yml`:

```yaml
# models/sources.yml
sources:
  - name: reference
    tables:
      - name: bridge_tax_rank_map
        meta:
          external_location: "read_parquet('{{ var(\"reference_parquet_dir\") }}/bridge_tax_rank_map.parquet')"
      - name: bridge_ec_pathway
        meta:
          external_location: "read_parquet('{{ var(\"reference_parquet_dir\") }}/bridge_ec_pathway.parquet')"
```

Upload models reference bridges as `{{ source('reference', 'bridge_ec_pathway') }}` — dbt-duckdb compiles this to the `read_parquet(...)` call at query time. No build step, no views, no DDL in `sample.duckdb`.

Upload command is **`dbt build --select stg_rpkm_long+` only**. Wrapper fails fast if derived Parquet files are missing (dev fallback: run `build_reference.py` first).

**Why sources, not models:** Using `source()` rather than `ref()` for pre-built Parquet:
- Eliminates the dual-target/dual-profile complexity entirely — same `profiles.yml` for all runs
- No view staleness — file is re-scanned fresh on every `dbt build`
- Lineage graph correctly shows bridges as external inputs, not dbt-managed tables
- `dbt source freshness` can validate Parquet exists and is recent

| Approach | Pros | Cons |
|---|---|---|
| **Derived Parquet + dbt sources (selected)** | Pre-computed; fast upload; single profile; no staleness; source lineage | Distribution export step; two Parquet roots |
| **Derived Parquet + upload views** | Pre-computed; fast upload | Dual-target complexity; view staleness if Parquet refreshes mid-run |
| **ATTACH staging `reference.duckdb` READ_ONLY** | Pre-built tables; no Parquet export | Cross-DB config; harder to ship/version |
| **Views over raw Parquet at upload** | No export step | Recomputes UNPIVOT/joins on every upload — rejected |

**dbt vars (paths):**

| Var | Points to | Used when |
|---|---|---|
| `raw_parquet_dir` | `resources/db/parquet/` | `build_reference.py` DuckDB SQL |
| `reference_parquet_dir` | `analytics/transform/reference/parquet/` | Upload (source `external_location`) |

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
  build_reference.py (pure DuckDB SQL)
    raw parents parquet       → reference/parquet/bridge_tax_rank_map.parquet
    raw pathway_* parquet     → reference/parquet/bridge_ec_pathway.parquet

[upload — dbt external sources (read_parquet at query time, no build)]
  source('reference', 'bridge_tax_rank_map')   ← reference/parquet/bridge_tax_rank_map.parquet
  source('reference', 'bridge_ec_pathway')     ← reference/parquet/bridge_ec_pathway.parquet

[upload — sample tables]
  stg_rpkm_long             ← Python: wide TSV → long, EC normalize, nonzero filter
       ↓
  int_rpkm_by_ec_tax        ← SUM(value) GROUP BY (ec_normalized, source_tax_id)
       ↓
  int_rpkm_pathway          ← LEFT JOIN source bridge_ec_pathway; UNION ALL three levels, dedup per level
       ↓
  int_tax_rollup_resolved   ← join source bridge_tax_rank_map; exact / fallback / unclassified
       ↓
  mart_pathway_taxonomy_long ← GROUP BY pathway level + taxon; SUM(value)
```

### 5.1 Abundance aggregation semantics (app parity)

Two distinct steps — do not conflate:

1. **Gene aggregation (`int_rpkm_by_ec_tax`):** Multiple genes with the same `(ec_normalized, source_tax_id)` have their `value` **summed before** the pathway join. Matches the app iterating gene rows and accumulating into the same `(EC, taxon)` bucket.

2. **Fan-out dedup (`int_rpkm_pathway`):** After the join, each aggregated row may match multiple `pathway_node` rows. `int_rpkm_pathway` materialises **all three levels** via UNION ALL, applying `SELECT DISTINCT` per branch. Per aggregated row, each distinct `pathway_key` at a given level is counted at most once. At `pathway_node` level no dedup is needed — one row per node is intentional.

| `pathway_level` branch | Dedup key |
|---|---|
| `superpathway` | `(sample_id, ec_normalized, source_tax_id, value, superpathway_id)` |
| `pathway` | `(sample_id, ec_normalized, source_tax_id, value, pathway_id)` |
| `pathway_node` | no dedup — one row per node |

All three branches share the same fixed output schema `(sample_id, ec_normalized, source_tax_id, value, pathway_level, pathway_key, pathway_label)`. Downstream models filter on `pathway_level = var('pathway_level')`.

**`mass_conservation` (under review — H2):** The definition of `mass_conservation` is deferred; `SUM(mart.value) ≈ SUM(stg_rpkm_long.value)` is likely incorrect because mapped ECs legitimately appear in multiple distinct pathways/superpathways, so `SUM(mart)` intentionally exceeds `SUM(stg)` when an EC spans >1 pathway. Correct invariants (per-subset conservation + app-parity reconciliation) will be defined before implementation.

| Model | Rebuilt when | Not rebuilt when |
|---|---|---|
| `bridge_*` (derived Parquet) | Raw Parquet refresh; `build_reference.py` SQL change; explicit re-run | Sample upload; param changes — sources are scanned live, no stale state |
| `stg_rpkm_long` | New/changed RPKM file | `tax_rank` / `pathway_level` change |
| `int_rpkm_by_ec_tax` | `stg_rpkm_long` rebuilds | `tax_rank` / `pathway_level` change |
| `int_rpkm_pathway` | `int_rpkm_by_ec_tax` rebuilds | **neither** `tax_rank` nor `pathway_level` — all three levels pre-computed |
| `int_tax_rollup_resolved` | Upstream rebuild or `tax_rank` var change | `pathway_level` change |
| `mart_pathway_taxonomy_long` | Upstream rebuild, `tax_rank` via upstream, or `pathway_level` change (WHERE filter) | — |

**Typical operations:**

- **Distribution / reference refresh:** `uv run python transform/scripts/build_reference.py` (pure DuckDB SQL — reads raw Parquet, writes derived bridge Parquet to `reference/parquet/`).
- **New upload:** `dbt build --select stg_rpkm_long+` (or wrapper equivalent).
- **Change `tax_rank`:** `dbt build --select int_tax_rollup_resolved+`.
- **Change `pathway_level` only:** `dbt build --select mart_pathway_taxonomy_long` (only the mart's WHERE filter changes; `int_rpkm_pathway` already contains all levels).

**dbt `--select` syntax:** `stg_rpkm_long+` means the model `stg_rpkm_long` **and all downstream** dependencies.

## 6. Model Specifications

### 6.1 `bridge_tax_rank_map` (dbt source)

Built by `build_reference.py` (DuckDB SQL) from raw `parents` Parquet (`raw_parquet_dir`). Output written to `reference/parquet/bridge_tax_rank_map.parquet`. Consumed at upload via `{{ source('reference', 'bridge_tax_rank_map') }}`.

**Build logic (`build_reference.py`):**
1. UNPIVOT non-null `t_kingdom` … `t_species` → `(tax_id, rank_tax_id, rank)`.
2. Add self-rows: for taxa whose finest filled rank equals `rank`, ensure `(tax_id, tax_id, rank)` exists when missing from step 1. Finest rank derived inline from wide columns (same ladder logic as EDA §6); no separate `dim_taxonomy` model.

**Output schema:**

| Column | Type | Notes |
|---|---|---|
| `tax_id` | BIGINT | Source taxon |
| `rank_tax_id` | BIGINT | Tax_id at `rank` (self when at-rank) |
| `rank` | VARCHAR | `kingdom`, `phylum`, `class`, `order`, `family`, `genus`, `species` |

Join taxonomy on `tax_id`, never `names.id` (UUID surrogate).

### 6.2 `bridge_ec_pathway` (dbt source)

Built by `build_reference.py` (DuckDB SQL) from raw `pathway_*` / `superpathways` Parquet. Output written to `reference/parquet/bridge_ec_pathway.parquet`. Consumed at upload via `{{ source('reference', 'bridge_ec_pathway') }}`.

**Output schema:**

| Column | Type | Notes |
|---|---|---|
| `ec_normalized` | VARCHAR | Join key from RPKM |
| `pathway_node_id` | VARCHAR | For `pathway_level = pathway_node` |
| `pathway_id` | BIGINT | FK to `pathway_superpathways.id` |
| `pathway_name` | VARCHAR | Display |
| `superpathway_id` | VARCHAR | FK to `superpathways.id` |
| `superpathway_name` | VARCHAR | Display |

One row per `(ec_normalized, pathway_node_id)`. **Join key:** `ec_normalized` on both RPKM and bridge sides — both produce clean `N.N.N.N` format per §6.3 rules.

When aggregating at `pathway` or `superpathway`, dedup to one count per distinct id at that level (§5.1). Matches app `reduce_to_dict`.

**Bridge row filter (EDA-confirmed):** Select `pathway_nodes` rows matching `regexp_matches(name, '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$')`. This selects exactly the 7,064 EC-dotted rows (all 4-segment) and excludes compound IDs (`C…`), truncated/ellipsis labels, and non-enzyme nodes — without needing a `type` filter.

`pathway_nodes.type` is KGML **graphics shape** (`circle`/`rectangle`/`roundrectangle`), not semantic role. All EC-dotted names are rectangles, but 105 rectangle rows are non-EC (compound IDs, truncated labels) — name-pattern matching is cleaner and correct (EDA §6, data-model.md).

**`0.0.0.0` safety:** `0.0.0.0` is **absent** from `pathway_nodes.name` in the current DB dump (EDA §6: `fallback_token_in_reference = 0`). The 4-segment `^[0-9]+…` pattern would still exclude it — add explicit `AND name != '0.0.0.0'` as a safety guard. Add a dbt source test: `assert_no_bridge_ec_zero` (`ec_normalized != '0.0.0.0'`).

**No `ec:` prefix stripping in bridge SQL:** `pathway_nodes.name` values are already clean `N.N.N.N` in the DB (KGML parser strips the `ec:` prefix at build time). No normalization needed on the bridge side — names match RPKM `ec_normalized` directly.

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

| Column | Type | Notes |
|---|---|---|
| `sample_id` | VARCHAR | From dbt var |
| `gene_id` | VARCHAR | From `GeneID` |
| `ec_normalized` | VARCHAR | Normalized EC string |
| `source_tax_id` | BIGINT | RPKM column header (integer tax_id) |
| `value` | DOUBLE | Per-taxon column value (nonzero only) |

### 6.4 `int_rpkm_by_ec_tax`

`GROUP BY (sample_id, ec_normalized, source_tax_id)` → `SUM(value)`.

Collapses multiple genes sharing the same EC and tax_id column before pathway join. Drops `gene_id` — no longer needed after aggregation.

**Output columns:**

| Column | Type | Notes |
|---|---|---|
| `sample_id` | VARCHAR | From dbt var |
| `ec_normalized` | VARCHAR | Normalized EC string |
| `source_tax_id` | BIGINT | RPKM column header (tax_id) |
| `value` | DOUBLE | `SUM(value)` across genes with same EC + taxon |

### 6.5 `int_rpkm_pathway`

`int_rpkm_by_ec_tax` LEFT JOIN `{{ source('reference', 'bridge_ec_pathway') }}` ON `ec_normalized`, materialised as **three UNION ALL branches** — one per `pathway_level`. Each branch applies `SELECT DISTINCT` over its level-specific key set. The output has a **fixed schema regardless of any dbt var**.

**Structure:**

```sql
-- superpathway branch
SELECT DISTINCT
    base.sample_id, base.ec_normalized, base.source_tax_id, base.value,
    'superpathway'                         AS pathway_level,
    CAST(b.superpathway_id AS VARCHAR)     AS pathway_key,
    b.superpathway_name                    AS pathway_label
FROM int_rpkm_by_ec_tax base
LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
       ON base.ec_normalized = b.ec_normalized

UNION ALL

-- pathway branch
SELECT DISTINCT
    base.sample_id, base.ec_normalized, base.source_tax_id, base.value,
    'pathway'                              AS pathway_level,
    CAST(b.pathway_id AS VARCHAR)          AS pathway_key,
    b.pathway_name                         AS pathway_label
FROM int_rpkm_by_ec_tax base
LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
       ON base.ec_normalized = b.ec_normalized

UNION ALL

-- pathway_node branch (no dedup — one row per node is intentional)
SELECT DISTINCT
    base.sample_id, base.ec_normalized, base.source_tax_id, base.value,
    'pathway_node'                         AS pathway_level,
    b.pathway_node_id                      AS pathway_key,
    NULL                                   AS pathway_label
FROM int_rpkm_by_ec_tax base
LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
       ON base.ec_normalized = b.ec_normalized
```

**Dedup mechanics:** The DISTINCT in each branch operates over exactly `(sample_id, ec_normalized, source_tax_id, value, pathway_level, pathway_key, pathway_label)`. Finer-grain IDs are never present in the branch output, so they cannot prevent collapse — no explicit column-dropping logic needed.

**Unmapped ECs:** The LEFT JOIN produces NULL for all bridge columns. Each branch emits one row with `pathway_key = NULL` and `pathway_label = NULL`. An unmapped EC therefore appears **once per `pathway_level`** in the output — intentional, since downstream always filters to a single level and needs a row to preserve the unmapped mass at that level. `pathway_key IS NULL` identifies unmapped rows.

**Output columns (fixed, all branches):**

| Column | Type | Notes |
|---|---|---|
| `sample_id` | VARCHAR | |
| `ec_normalized` | VARCHAR | |
| `source_tax_id` | BIGINT | |
| `value` | DOUBLE | From `int_rpkm_by_ec_tax` |
| `pathway_level` | VARCHAR | `'superpathway'`, `'pathway'`, or `'pathway_node'` |
| `pathway_key` | VARCHAR | ID at level (CAST to VARCHAR); NULL when unmapped |
| `pathway_label` | VARCHAR | Name at level; NULL when unmapped or `pathway_node` |

**Performance:** Gene aggregation before join reduces input size. `pathway_join_fanout_rate` (§7) measures average bridge matches per `int_rpkm_by_ec_tax` row (mapped only) before dedup.

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

| Case | `taxon_key` | `taxon_label` | `pathway_key` | `pathway_label` |
|---|---|---|---|---|
| Unclassified taxonomy | NULL | `'Unclassified'` | (normal) | (normal) |
| Unmapped EC | (normal) | (normal) | NULL | NULL → mart renders `'Unmapped EC'` |

For unmapped rows, `pathway_key IS NULL` is the signal; per-EC detail remains in `ec_normalized` (carried through, in mart GROUP BY when `pathway_key IS NULL`).

**Run-level params (`tax_rank`, `pathway_level`):** Not echoed on mart or `int_tax_rollup_resolved` rows. Stored in dbt vars during build and in `runs/{sample_id}/run_context.json` after build. Constraints and info metrics reference `{{ var('tax_rank') }}` directly.

Fallback only walks **coarser** ranks (never genus when phylum was requested).

**Output columns (per input row):**

All columns from `int_rpkm_pathway` (fixed schema — see §6.5), plus:

| Column | Type | Notes |
|---|---|---|
| `tax_rank_resolved` | VARCHAR | Actual rank used; NULL when Unclassified |
| `taxon_key` | BIGINT | `rank_tax_id` from bridge; NULL when Unclassified |
| `taxon_label` | VARCHAR | Scientific name from `names`; `'Unclassified'` when null |

**Intentional divergence from app:** `get_parents_at_level` uses a name-based backfill heuristic and does not coarser-fallback. Pipeline behavior is explicit and documented.

### 6.7 `mart_pathway_taxonomy_long`

Filters `int_tax_rollup_resolved` to `WHERE pathway_level = '{{ var("pathway_level") }}'`, then groups by pathway + resolved taxon.

**Mart GROUP BY:** `(pathway_key, pathway_label, taxon_key, taxon_label, tax_rank_resolved, sample_id, pathway_level, CASE WHEN pathway_key IS NOT NULL THEN NULL ELSE ec_normalized END)`.

The `CASE WHEN pathway_key IS NOT NULL THEN NULL ELSE ec_normalized END` expression (aliased as `ec_normalized` in the SELECT) ensures:
- **Mapped rows** collapse across all ECs sharing the same pathway + taxon (`ec_normalized = NULL` in mart).
- **Unmapped rows** remain per-EC (`ec_normalized = <value>` in mart).

`pathway_label` for unmapped rows is `COALESCE(pathway_label, 'Unmapped EC')` — the NULL from the bridge becomes the display sentinel here, not in the intermediate.

This matches the app's cross-EC superpathway aggregation for mapped ECs.

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

| Column | Type | Notes |
|---|---|---|
| `sample_id` | VARCHAR | |
| `pathway_level` | VARCHAR | Selected level from dbt var |
| `pathway_key` | VARCHAR | ID at selected level; NULL when unmapped |
| `pathway_label` | VARCHAR | Name at selected level; `'Unmapped EC'` when unmapped |
| `ec_normalized` | VARCHAR | NULL for mapped rows; EC string for unmapped rows (see GROUP BY note) |
| `tax_rank_resolved` | VARCHAR | Actual rank used (may differ under fallback); NULL when Unclassified |
| `taxon_key` | BIGINT | Resolved tax_id; NULL when Unclassified |
| `taxon_label` | VARCHAR | Scientific name; `'Unclassified'` when null |
| `value` | DOUBLE | `SUM(value)` |

## 7. Constraints

Each constraint has an id, check, stage, default severity, and pass criteria. **Pre-flight checks** (`rpkm_file_readable`) run in Python / wrapper before dbt — not dbt tests.

| ID | Check | Model / stage | Severity | Pass when |
|---|---|---|---|---|
| `rpkm_file_readable` | TSV parses; all KEY_COLS present; ≥1 tax column | **pre-flight** (Python / wrapper) | error | No exception; valid shape |
| `rpkm_tax_columns_present` | ≥1 tax_id column detected | `stg_rpkm_long` | error | tax_column_count ≥ 1 |
| `rpkm_no_negative_values` | All `value >= 0` | `stg_rpkm_long` | error | 0 violating rows |
| `rpkm_tax_id_resolvable` | Every distinct `source_tax_id` in `names` | `stg_rpkm_long` | warn | 0 unmapped tax_ids |
| `rpkm_ec_kegg_coverage` | `distinct mapped ECs / distinct ECs in sample` (mapped = `pathway_key IS NOT NULL`) | `int_rpkm_pathway` | info | Always passes; emits ratio |
| `unmapped_ec_value_rate` | `SUM(value WHERE pathway_key IS NULL) / SUM(value)` | mart | info | Metric only |
| `pathway_join_fanout_rate` | Avg bridge matches per `int_rpkm_by_ec_tax` row before dedup (mapped only) | `int_rpkm_pathway` | info | Metric only; high values imply mass-conservation risk if dedup skipped |
| `mass_conservation` | **Under review (H2)** — see §5.1; current `SUM(mart) ≈ SUM(stg)` claim is incorrect; replace before implementation | mart | warn | TBD |
| `mart_nonempty` | Mart row count > 0 | `mart_pathway_taxonomy_long` | error | count > 0 |
| `mart_classified_taxa_have_keys` | No row where `taxon_label != 'Unclassified'` AND `taxon_key IS NULL` | mart | error | 0 rows |
| `mart_mapped_pathways_have_keys` | No row where `pathway_label != 'Unmapped EC'` AND `pathway_key IS NULL` | mart | error | 0 rows |
| `mart_value_non_null` | All rows: `value IS NOT NULL` | mart | error | 0 nulls |
| `mart_rollup_exact_match_rate` | `SUM(value WHERE tax_rank_resolved = var('tax_rank') AND taxon_label != 'Unclassified') / SUM(value)` | mart | info | Metric only |
| `mart_rollup_fallback_rate` | `SUM(value WHERE tax_rank_resolved != var('tax_rank') AND taxon_label != 'Unclassified') / SUM(value)` | mart | info | Metric only |
| `mart_unclassified_rate` | `SUM(value WHERE taxon_label = 'Unclassified') / SUM(value)` | mart | info | Metric only in v1 |

**Key constraints (replaces `mart_no_null_keys`):** NULL keys are **permitted and expected** for gap rows. Constraints enforce keys only where a real taxonomy/pathway exists:

- **`mart_classified_taxa_have_keys`** — if we resolved a real taxon (`taxon_label != 'Unclassified'`), `taxon_key` must be non-null.
- **`mart_mapped_pathways_have_keys`** — if `pathway_label != 'Unmapped EC'` (i.e. a real pathway name), `pathway_key` must be non-null. Equivalent to `pathway_key IS NULL → pathway_label = 'Unmapped EC'`.
- Unclassified and unmapped rows are identified by NULL key + fixed label, not by a boolean flag.

**Mass conservation definition (under review — H2):** `SUM(mart.value) ≈ SUM(stg_rpkm_long.value)` is incorrect as a global invariant — mapped ECs that belong to multiple distinct pathways/superpathways are intentionally counted once per pathway, so `SUM(mart)` exceeds `SUM(stg)`. The correct invariants are: (a) exact conservation on the unmapped subset, and (b) per-cell value preservation within each pathway bucket. Full definition deferred to H2 resolution before implementation.

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
2. Connect DuckDB in-memory; attach raw Parquet via `read_parquet(raw_parquet_dir/…)`.
3. Execute bridge SQL directly (UNPIVOT / join logic per §6.1–6.2); write results:
   - `COPY … TO 'reference/parquet/bridge_tax_rank_map.parquet' (FORMAT PARQUET)`
   - `COPY … TO 'reference/parquet/bridge_ec_pathway.parquet' (FORMAT PARQUET)`
4. Assert output: no `ec_normalized = '0.0.0.0'` in bridge_ec_pathway; row counts > 0.
5. Commit derived Parquet (Git LFS) and ship with releases.

**No dbt invocation at distribution** — bridge SQL is plain Python+DuckDB. This eliminates `tag:reference`, dual-target profiles, and staging DB management. Run after raw Parquet refresh and in CI to validate bridge SQL.

### 8.1 Invocation

**Direct dbt (local dev):** Running `dbt build` with `--vars` is sufficient for development and debugging.

**`run_pipeline.py` wrapper (CI, fixtures, future API):** Thin orchestration — not a substitute for dbt logic. Responsibilities:

1. Ensure `runs/{sample_id}/` exists; point dbt profile at `runs/{sample_id}/sample.duckdb`
2. Verify derived bridge Parquet exists under `reference/parquet/` (fail with actionable message if not)
3. Pass `--vars` consistently (`sample_id`, `rpkm_path`, `tax_rank`, `pathway_level`, `reference_parquet_dir`)
4. Run `dbt build --select stg_rpkm_long+` (upload path only — bridges consumed as dbt sources, no reference build step)
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
- [ ] `build_reference.py` (pure DuckDB SQL) produces derived bridge Parquet from raw reference Parquet; asserts `ec_normalized != '0.0.0.0'`
- [ ] Upload pipeline produces `mart_pathway_taxonomy_long` for `test_rpkm_1.tsv` at default vars using bridge dbt sources (no `build_reference.py` re-run needed once Parquet is present)
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
