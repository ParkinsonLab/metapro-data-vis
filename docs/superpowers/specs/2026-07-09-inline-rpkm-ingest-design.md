# Inline RPKM Ingest — Design Spec

> **Status:** Approved (2026-07-09)  
> **Goal:** Remove the materialized `stg_rpkm_long` table by folding wide-TSV ingest and gene aggregation into a single SQL `int_rpkm_by_ec_tax` model — cutting `sample.duckdb` size ~95% on stress fixtures without changing API contracts or downstream grain.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — original ingest rationale (Python model)
- `docs/superpowers/specs/2026-07-08-api-aligned-dbt-model-design.md` — current upload graph (§4.1 amended below)

**Depends on:** API-aligned dbt model migration (PR #15 / `feature/api-aligned-dbt-model`) merged or rebased.

## 1. Context

### 1.1 Problem

After the API-aligned migration, `stg_rpkm_long` is the dominant storage cost in `sample.duckdb`:

| Table | Rows (`stress_rpkm_1`) | Role |
|---|---|---|
| `stg_rpkm_long` | **40,453,328** | Gene × tax_id long form (materialized) |
| `int_rpkm_by_ec_tax` | 386,700 | EC × tax_id aggregated |
| `mart_rpkm_enriched` | 386,700 | API read target |

Measured on clean rebuild (2026-07-09):

| Artifact | Size |
|---|---|
| Full `sample.duckdb` (with `stg`) | **~445 MB** |
| API tables only (no `stg`) | **~22 MB** |

`stg_rpkm_long` exists only as a pipeline convenience — **no API endpoint reads it.** Downstream models need only the aggregated `(sample_id, ec_normalized, source_tax_id, value)` grain.

### 1.2 Why `stg_rpkm_long` was a Python model (historical)

The original design (`2026-06-15-rpkm-transform-design.md` §4) chose a **dbt Python ingest model** because:

1. Per-sample **dynamic tax columns** — rejected “codegen UNPIVOT” in favor of DuckDB `COLUMNS(* EXCLUDE (...))`.
2. **Runtime `rpkm_path` / `sample_id`** vars per upload.
3. **Unit tests without dbt** — logic extracted to `scripts/stg_rpkm_long.py`.

The actual transform was always **SQL executed via DuckDB** (`conn.sql(...)`). Python was the dbt integration and test harness, not a DuckDB capability requirement. The same SQL can live in a dbt SQL model (or macro) with Jinja vars.

### 1.3 Selected approach: A1 — inline SQL ingest

| Option | Decision |
|---|---|
| A1. Fold ingest + aggregate into SQL `int_rpkm_by_ec_tax` | **Selected** |
| A2. Python `int_rpkm_by_ec_tax` calling `_transform()` | Rejected — user prefers pure SQL model |
| A3. Ephemeral `stg` + SQL `int` | Rejected — still computes 40M rows; marginal disk win |
| B. Drop `stg` post-build | Rejected — DuckDB does not reclaim space in-place; must never write `stg` |

**Ingest SQL** lives in a dbt macro `rpkm_ingest_long()` (pure SQL/Jinja). `int_rpkm_by_ec_tax.sql` calls the macro and applies `GROUP BY`. This keeps one SQL definition without a separate Python model or persisted staging table.

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Staging model | **Remove** `stg_rpkm_long` dbt model | Not read by API; dominates disk |
| Ingest implementation | SQL macro + SQL intermediate model | A1; no Python dbt model |
| Output grain | Unchanged — `(sample_id, ec_normalized, source_tax_id)` | Downstream dims/mart unchanged |
| Ingest semantics | Identical to current `scripts/stg_rpkm_long.py` | Golden tests must pass unchanged |
| `gene_id` | Not materialized | Dropped at aggregation (same as today) |
| `Unclassified` KEY_COL | Excluded from unpivot | Unchanged (spec §6.4) |
| EC normalization | Same `CASE` rules | `EC:`, `ec:`, `None`, empty → `0.0.0.0` |
| Nonzero filter | `value > 0` before aggregation | Unchanged |
| Invalid tax headers | `TRY_CAST` → skip row | Unchanged |
| Clean rebuild | Keep `run_pipeline.py` delete-before-build | Prevents orphan tables |
| API JSON contracts | Unchanged | No frontend or API handler changes |
| `scripts/stg_rpkm_long.py` | **Delete** after macro port | Logic moves to `macros/rpkm_ingest_long.sql` |

## 3. Model Graph (replaces §4.1 of parent spec)

```
int_rpkm_by_ec_tax          ← SQL: rpkm_ingest_long() macro + GROUP BY
  → dim_sample_taxon
  → dim_sample_ec
  → mart_rpkm_enriched      ← APIs read this
```

**Removed from graph:** `stg_rpkm_long` (Python dbt model and table).

**Unchanged:** reference bridges, dims, mart, macros, API services.

## 4. `rpkm_ingest_long()` macro

**Location:** `analytics/transform/macros/rpkm_ingest_long.sql`

**Inputs:** dbt vars `rpkm_path`, `sample_id` (required on full pipeline run).

**Logic** (port of `scripts/stg_rpkm_long.py` verbatim):

1. `read_csv(rpkm_path)` — tab-separated, header, `all_varchar=true`, null strings list unchanged.
2. `UNPIVOT` on all columns except fixed KEY_COLS: `GeneID`, `Length`, `Reads`, `EC#`, `RPKM`, `Unclassified`.
3. Normalize `EC#` to `ec_normalized`.
4. `TRY_CAST` tax column name → `source_tax_id` (BIGINT), value → DOUBLE.
5. Filter `value > 0` AND `source_tax_id IS NOT NULL`.

**Jinja escaping:** `rpkm_path` and `sample_id` embedded as string literals with `| replace("'", "''")`.

**Returns:** SQL subquery (no trailing semicolon) suitable for:

```sql
WITH long AS (
    {{ rpkm_ingest_long() }}
)
SELECT ...
FROM long
```

## 5. `int_rpkm_by_ec_tax` (SQL model)

**Location:** `analytics/transform/models/intermediate/int_rpkm_by_ec_tax.sql`

```sql
WITH long AS (
    {{ rpkm_ingest_long() }}
)
SELECT
    sample_id,
    ec_normalized,
    source_tax_id,
    SUM(value) AS value
FROM long
GROUP BY sample_id, ec_normalized, source_tax_id
```

**Materialization:** `table` (unchanged).

**Pre-flight:** If `rpkm_path` or `sample_id` is empty, DuckDB `read_csv('')` fails at build time — same practical behavior as today's Python `ValueError` (optional explicit `{{ exceptions.raise_compiler_error(...) }}` in macro when vars missing).

## 6. Pipeline and config changes

### 6.1 `run_pipeline.py`

| Change | From | To |
|---|---|---|
| dbt select | `stg_rpkm_long+` | `int_rpkm_by_ec_tax+` |
| Clean rebuild | delete `sample.duckdb` before build | unchanged (already implemented) |

### 6.2 `dbt_project.yml`

Remove staging-level `+rpkm_path` / `+sample_id` model configs (no staging models). Vars remain at project `vars:` — consumed by macro.

### 6.3 `models/staging/`

Delete entire staging layer:

- `models/staging/stg_rpkm_long.py`
- `models/staging/schema.yml`

### 6.4 `scripts/stg_rpkm_long.py`

Delete after macro port.

## 7. Tests

### 7.1 Test split (locked in)

| Layer | What | Where |
|---|---|---|
| **fake_rpkm** | Ingest structural cases A1–A4 (zero downstream mass) | TSV + `ingest_expectations` in pipeline YAML only |
| **Micro unit tests** | EC normalization (B1–B3), gene `SUM` (D1) | `test_rpkm_ingest.py` + synthetic `tmp_path` TSVs |
| **dbt singular** | No negative values (C3) | `assert_rpkm_no_negative_values.sql` on `int` |
| **fake_rpkm integration** | Rollup / pathway / tax semantics | Existing `rollup_grid` — unchanged |
| **API goldens** | Chord, overview, graph, krona, network, pathway-list | **Unchanged** |

### 7.2 `fake_rpkm` ingest rows (A1–A4, no isolation column)

Add **two rows** to `fake_rpkm.tsv`. Neither adds mass to `int_rpkm_by_ec_tax`; `rollup_grid` and all API expectation YAMLs stay unchanged.

| Row | Shape | Proves |
|---|---|---|
| `row_ingest_unclass_only` | `Unclassified > 0` (e.g. `5`), **all tax columns `0`** | **A3** — `Unclassified` is a KEY_COL; not unpivoted; no spurious `source_tax_id` |
| `row_ingest_all_zero` | `Unclassified = 0`, **all tax columns `0`** | **A4** — all-zero gene produces no `int` row |

**A3 rationale:** Ingest unpivots tax-id columns only (`COLUMNS(* EXCLUDE (KEY_COLS))`). A row with mass only in `Unclassified` yields no long-form rows after the `value > 0` filter, so downstream totals are unchanged. Golden: `int_row_count` remains **13**; sample-wide assert no `source_tax_id` cast from `Unclassified`.

**A1 / A2:** No TSV change — KEY_COL exclusion and multi-column unpivot are structural; A3 row additionally guards against `Unclassified` being treated as a tax column.

Example TSV rows (EC# arbitrary; no tax mass):

```text
row_ingest_unclass_only   100  1  1.6.5.9  1  5  0  0  0  0  0  0  0  0  0
row_ingest_all_zero       100  1  1.6.5.9  1  0  0  0  0  0  0  0  0  0  0
```

### 7.3 `ingest_expectations` (pipeline YAML only)

Add to `fake_rpkm_pipeline_expectations.yaml` — **not** chord/overview/graph/krona/network YAMLs:

```yaml
ingest_expectations:
  int_row_count: 13
  zero_mass_genes:
    - row_ingest_unclass_only
    - row_ingest_all_zero
  unclassified_not_source_tax_id: true
```

Assert in `test_fake_rpkm_pipeline.py` (or `test_fake_rpkm_ingest.py`): query `int_rpkm_by_ec_tax` row count; optional check that `Unclassified` never appears as `source_tax_id`.

### 7.4 Micro unit tests (`test_rpkm_ingest.py`)

**Replaces:** `test_stg_rpkm_long.py` for cases that must not touch `fake_rpkm`.

Strategy: lightweight Jinja render of `rpkm_ingest_long()` (or `dbt compile` session fixture) + DuckDB execute on synthetic TSV in `tmp_path`.

| Case | Coverage |
|---|---|
| **B1** | `EC:` prefix strip |
| **B2** | `ec:` lowercase prefix |
| **B3** | `None` → `0.0.0.0` |
| **D1** | Two genes, same `(ec_normalized, source_tax_id)` → `SUM(value)` |

**B4** (empty → `0.0.0.0`): already covered by existing `row_ec_unmapped__col_tax_focal` in `fake_rpkm`; no micro test required unless desired.

**Not fixture-tested:** C1 invalid tax header, C2 non-numeric cells (low priority).

### 7.5 dbt singular tests

| Test | Change |
|---|---|
| `assert_rpkm_no_negative_values.sql` | `ref('stg_rpkm_long')` → `ref('int_rpkm_by_ec_tax')`; drop `gene_id` from SELECT |

### 7.6 Integration tests (unchanged)

| Suite | Change |
|---|---|
| `test_fake_rpkm_pipeline.py` | Add `ingest_expectations` asserts; `rollup_grid` unchanged |
| `test_run_pipeline.py` | None |
| API golden tests | None |

## 8. Expected outcomes

### 8.1 Storage (`stress_rpkm_1`, clean rebuild)

| Metric | Before | After (target) |
|---|---|---|
| Tables in `sample.duckdb` | 5 (incl. `stg`) | **4** |
| `sample.duckdb` file size | ~445 MB | **~25 MB** (API tables + DuckDB overhead) |
| `int_rpkm_by_ec_tax` rows | 386,700 | 386,700 (unchanged) |
| `mart_rpkm_enriched` rows | 386,700 | 386,700 (unchanged) |

### 8.2 Build time

TSV is still parsed once per run. Expect **similar or slightly faster** `dbt build` (no 40M-row table write). Exact timing measured at implementation.

### 8.3 API latency

Unchanged — APIs read `mart_rpkm_enriched` only.

## 9. Out of scope

- Dropping `int_rpkm_by_ec_tax` when only `mart` is needed (marginal savings; same row count)
- Incremental models / partial rebuild within `sample.duckdb`
- `--keep-stg` debug flag (add only if requested)
- Changing parent spec §6.4 historical documentation (this addendum supersedes ingest shape only)

## 10. Acceptance criteria

- [ ] No `stg_rpkm_long` table or model in repo
- [ ] `int_rpkm_by_ec_tax.sql` + `rpkm_ingest_long()` macro implement ingest + aggregation
- [ ] `run_pipeline.py` selects `int_rpkm_by_ec_tax+`
- [ ] All pytest + dbt tests pass (`fake_rpkm` ingest + rollup, `test_rpkm_ingest`, stress manual workflow)
- [ ] `ingest_expectations` in pipeline YAML; API golden YAMLs unchanged
- [ ] `stress_rpkm_1` `sample.duckdb` ≤ 50 MB after clean rebuild
- [ ] Golden API tests unchanged (JSON contracts)

## 11. Amendment to parent spec §4.1

`docs/superpowers/specs/2026-07-08-api-aligned-dbt-model-design.md` §4.1 model graph and §1.3 `stg_rpkm_long` row counts are **historical baselines**. Post this change, the upload graph starts at `int_rpkm_by_ec_tax`; `stg_rpkm_long` is not materialized.
