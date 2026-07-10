# Inline RPKM Ingest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the materialized `stg_rpkm_long` table by inlining wide-TSV ingest into SQL `int_rpkm_by_ec_tax`, cutting `sample.duckdb` from ~445 MB to ~25 MB on stress fixtures.

**Architecture:** Port `scripts/stg_rpkm_long.py` SQL into dbt macro `rpkm_ingest_long()`. `int_rpkm_by_ec_tax.sql` wraps the macro with `GROUP BY`. Delete staging Python model, staging schema, and ingest script. Retarget tests and `run_pipeline.py` select root. Downstream dims/mart/API unchanged.

**Tech Stack:** dbt 1.12 + dbt-duckdb, DuckDB, Python 3.14, pytest

**Worktree:** `.worktrees/feature/inline-rpkm-ingest/` on branch `feature/inline-rpkm-ingest` (branch from `origin/dev` after PR #15 merges, or from `origin/feature/api-aligned-dbt-model` if stacking)

**Design spec:** `docs/superpowers/specs/2026-07-09-inline-rpkm-ingest-design.md`

---

## Reference Material

Read before implementing:

- Design spec §4–§7 (macro SQL, model graph, test migration)
- `analytics/transform/scripts/stg_rpkm_long.py` — SQL to port verbatim
- `analytics/transform/tests/python/test_stg_rpkm_long.py` — behaviors to preserve
- `analytics/transform/scripts/run_pipeline.py` — `stg_rpkm_long+` select + clean rebuild
- Parent spec amendment in `docs/superpowers/specs/2026-07-08-api-aligned-dbt-model-design.md`

**Prerequisites:** API-aligned dbt model work present on branch; `build_reference.py` bridges built; `fake_rpkm` / `test_rpkm_1` fixtures available.

---

## File Map

```
analytics/transform/
├── macros/
│   └── rpkm_ingest_long.sql              # CREATE: ingest SQL (port of stg_rpkm_long.py)
├── models/
│   ├── staging/
│   │   ├── stg_rpkm_long.py              # DELETE
│   │   └── schema.yml                    # DELETE
│   └── intermediate/
│       └── int_rpkm_by_ec_tax.sql        # MODIFY: macro CTE + GROUP BY
├── scripts/
│   ├── stg_rpkm_long.py                  # DELETE
│   └── run_pipeline.py                   # MODIFY: int_rpkm_by_ec_tax+ select
├── dbt_project.yml                       # MODIFY: remove staging var configs
├── README.md                             # MODIFY: model graph
└── tests/
    ├── assert_rpkm_no_negative_values.sql # MODIFY: ref int, drop gene_id
    └── python/
        ├── test_stg_rpkm_long.py         # DELETE
        └── test_rpkm_ingest.py           # CREATE: compile + DuckDB tests

docs/superpowers/
├── specs/2026-07-09-inline-rpkm-ingest-design.md   # (already written)
└── specs/2026-07-08-api-aligned-dbt-model-design.md # (amendment note added)
```

---

### Task 1: `rpkm_ingest_long()` macro

**Files:**
- Create: `analytics/transform/macros/rpkm_ingest_long.sql`
- Reference: `analytics/transform/scripts/stg_rpkm_long.py`

- [ ] **Step 1: Create macro file**

```sql
{# analytics/transform/macros/rpkm_ingest_long.sql #}
{% macro rpkm_ingest_long() %}
{% set rpkm_path = var('rpkm_path') %}
{% set sample_id = var('sample_id') %}
{% if not rpkm_path %}
    {{ exceptions.raise_compiler_error("dbt var 'rpkm_path' is required") }}
{% endif %}
{% if not sample_id %}
    {{ exceptions.raise_compiler_error("dbt var 'sample_id' is required") }}
{% endif %}
{% set safe_path = rpkm_path | replace("'", "''") %}
{% set safe_sample_id = sample_id | replace("'", "''") %}
        WITH wide AS (
            SELECT *
            FROM read_csv(
                '{{ safe_path }}',
                sep = '\t',
                header = true,
                all_varchar = true,
                nullstr = ['', 'NA', 'null', 'NULL', 'None', 'none']
            )
        ),
        unpivoted AS (
            UNPIVOT wide
            ON COLUMNS(* EXCLUDE ("GeneID", "Length", "Reads", "EC#", "RPKM", "Unclassified"))
            INTO NAME source_tax_id_col VALUE value_str
        ),
        normalized AS (
            SELECT
                '{{ safe_sample_id }}'::VARCHAR                          AS sample_id,
                "GeneID"                                                AS gene_id,
                CASE
                    WHEN "EC#" IS NULL                                  THEN '0.0.0.0'
                    WHEN UPPER("EC#") LIKE 'EC:%'                       THEN TRIM(SUBSTRING("EC#", 4))
                    ELSE "EC#"
                END                                                     AS ec_normalized,
                TRY_CAST(source_tax_id_col AS BIGINT)                   AS source_tax_id,
                TRY_CAST(value_str AS DOUBLE)                           AS value
            FROM unpivoted
        )
        SELECT sample_id, gene_id, ec_normalized, source_tax_id, value
        FROM normalized
        WHERE value > 0
          AND source_tax_id IS NOT NULL
{% endmacro %}
```

- [ ] **Step 2: Verify macro compiles**

```bash
cd analytics
DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt compile \
  --select int_rpkm_by_ec_tax \
  --project-dir transform \
  --profiles-dir transform \
  --vars '{"rpkm_path": "../resources/example_data/test_rpkm_1.tsv", "sample_id": "test_rpkm_1"}'
```

Expected: `Compiled node 'int_rpkm_by_ec_tax'` with `read_csv` and `UNPIVOT` in `transform/target/compiled/.../int_rpkm_by_ec_tax.sql`

- [ ] **Step 3: Commit**

```bash
git add analytics/transform/macros/rpkm_ingest_long.sql
git commit -m "feat(transform): add rpkm_ingest_long macro for inline TSV ingest"
```

---

### Task 2: Rewrite `int_rpkm_by_ec_tax.sql`

**Files:**
- Modify: `analytics/transform/models/intermediate/int_rpkm_by_ec_tax.sql`

- [ ] **Step 1: Replace file contents**

```sql
-- Wide RPKM TSV → EC × tax_id grain. Ingest via rpkm_ingest_long(); no materialized staging table.
-- Gene aggregation: SUM(value) per (sample_id, ec_normalized, source_tax_id).

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

- [ ] **Step 2: Run dbt build on test fixture**

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id test_rpkm_1 \
  --rpkm-path ../resources/example_data/test_rpkm_1.tsv \
  --tax-rank phylum \
  --pathway-level pathway
```

Expected: `PASS` with no `stg_rpkm_long` in build output; `overall_status: success`

- [ ] **Step 3: Confirm staging table absent**

```bash
cd analytics
uv run python -c "
import duckdb
from pathlib import Path
p = Path('transform/runs/test_rpkm_1/sample.duckdb')
c = duckdb.connect(str(p), read_only=True)
print(sorted(r[0] for r in c.execute('SHOW TABLES').fetchall()))
c.close()
"
```

Expected: `['dim_sample_ec', 'dim_sample_taxon', 'int_rpkm_by_ec_tax', 'mart_rpkm_enriched']` — no `stg_rpkm_long`

- [ ] **Step 4: Commit**

```bash
git add analytics/transform/models/intermediate/int_rpkm_by_ec_tax.sql
git commit -m "feat(transform): inline RPKM ingest into int_rpkm_by_ec_tax"
```

---

### Task 3: Remove staging layer

**Files:**
- Delete: `analytics/transform/models/staging/stg_rpkm_long.py`
- Delete: `analytics/transform/models/staging/schema.yml`
- Delete: `analytics/transform/scripts/stg_rpkm_long.py`
- Modify: `analytics/transform/dbt_project.yml`
- Modify: `analytics/transform/scripts/run_pipeline.py`

- [ ] **Step 1: Delete staging files**

```bash
rm analytics/transform/models/staging/stg_rpkm_long.py
rm analytics/transform/models/staging/schema.yml
rm analytics/transform/scripts/stg_rpkm_long.py
rmdir analytics/transform/models/staging 2>/dev/null || true
```

- [ ] **Step 2: Update `dbt_project.yml`**

Remove the `staging:` block under `models.rpkm_transform` (lines with `+rpkm_path` / `+sample_id`). Keep project-level `vars:` unchanged.

```yaml
models:
  rpkm_transform:
    intermediate:
      +materialized: table
    marts:
      +materialized: table
```

- [ ] **Step 3: Update `run_pipeline.py` dbt select**

Change line:

```python
"--select", "stg_rpkm_long+",
```

to:

```python
"--select", "int_rpkm_by_ec_tax+",
```

- [ ] **Step 4: Run full test suite**

```bash
cd analytics && uv run pytest -q
```

Expected: failures only in `test_stg_rpkm_long.py` (deleted next task)

- [ ] **Step 5: Commit**

```bash
git add -A analytics/transform/
git commit -m "refactor(transform): remove stg_rpkm_long staging model and script"
```

---

### Task 4: `fake_rpkm` ingest rows + pipeline expectations

**Files:**
- Modify: `analytics/transform/tests/fixtures/fake_rpkm.tsv`
- Modify: `analytics/transform/tests/fixtures/fake_rpkm_pipeline_expectations.yaml`
- Modify: `analytics/transform/tests/python/test_fake_rpkm_pipeline.py`

- [ ] **Step 1: Add two zero-mass rows to TSV**

Append after existing rows (all tax columns `0`):

```text
row_ingest_unclass_only	100	1	1.6.5.9	1	5	0	0	0	0	0	0	0	0	0
row_ingest_all_zero	100	1	1.6.5.9	1	0	0	0	0	0	0	0	0	0	0
```

- [ ] **Step 2: Add `ingest_expectations` to pipeline YAML**

```yaml
ingest_expectations:
  int_row_count: 13
  zero_mass_genes:
    - row_ingest_unclass_only
    - row_ingest_all_zero
  unclassified_not_source_tax_id: true
```

Do **not** change `rollup_grid`.

- [ ] **Step 3: Add ingest asserts to `test_fake_rpkm_pipeline.py`**

```python
def test_ingest_expectations(fake_rpkm_db):
    conn = duckdb.connect(fake_rpkm_db, read_only=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM int_rpkm_by_ec_tax").fetchone()[0]
        assert n == _expectations["ingest_expectations"]["int_row_count"]
        # optional: assert no string 'Unclassified' in source_tax_id (always BIGINT)
    finally:
        conn.close()
```

- [ ] **Step 4: Rebuild fake_rpkm DB and run rollup tests**

```bash
rm -f analytics/transform/runs/fake_rpkm/sample.duckdb
cd analytics && uv run pytest transform/tests/python/test_fake_rpkm_pipeline.py -v
```

Expected: all PASS including rollup_grid; no API YAML changes

- [ ] **Step 5: Commit**

```bash
git add analytics/transform/tests/fixtures/ analytics/transform/tests/python/test_fake_rpkm_pipeline.py
git commit -m "test(transform): fake_rpkm ingest expectations for A3/A4"
```

---

### Task 5: Micro ingest unit tests (B1–B3, D1)

**Files:**
- Delete: `analytics/transform/tests/python/test_stg_rpkm_long.py`
- Create: `analytics/transform/tests/python/test_rpkm_ingest.py`

- [ ] **Step 1: Create slim micro-test file** (Jinja render of `rpkm_ingest_long()` + `GROUP BY`, or `dbt compile` fixture)

Tests only:

| Test | Case |
|---|---|
| `test_ec_prefix_stripped` | B1: `EC:1.2.3.4` → `1.2.3.4` |
| `test_ec_lower_prefix_stripped` | B2: `ec:5.6.7.8` → `5.6.7.8` |
| `test_ec_none_maps_to_zero` | B3: `None` → `0.0.0.0` |
| `test_gene_aggregation_sums` | D1: two genes same EC×tax → `value = 5` |

- [ ] **Step 2: Delete old test file**

```bash
rm analytics/transform/tests/python/test_stg_rpkm_long.py
```

- [ ] **Step 3: Run micro tests**

```bash
cd analytics && uv run pytest transform/tests/python/test_rpkm_ingest.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/transform/tests/python/
git commit -m "test(transform): micro ingest tests for EC normalization and gene SUM"
```

---

### Task 6: Retarget dbt singular test + docs

**Files:**
- Modify: `analytics/transform/tests/assert_rpkm_no_negative_values.sql`
- Modify: `analytics/transform/README.md`

- [ ] **Step 1: Update singular test**

```sql
{{ config(severity='error') }}
SELECT ec_normalized, source_tax_id, value
FROM {{ ref('int_rpkm_by_ec_tax') }}
WHERE value < 0
```

- [ ] **Step 2: Update README model graph**

Replace:

```
stg_rpkm_long
  → int_rpkm_by_ec_tax
```

with:

```
int_rpkm_by_ec_tax          (inline TSV ingest + gene aggregation)
```

Remove `stg_rpkm_long` from rebuild triggers table; add note that ingest runs inside `int_rpkm_by_ec_tax`.

- [ ] **Step 3: Run dbt test + fake_rpkm**

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id test_rpkm_1 \
  --rpkm-path ../resources/example_data/test_rpkm_1.tsv
uv run pytest transform/tests/python/test_fake_rpkm_pipeline.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add analytics/transform/tests/assert_rpkm_no_negative_values.sql analytics/transform/README.md
git commit -m "docs(transform): update graph and tests for inline ingest"
```

---

### Task 7: Stress validation

**Files:**
- None (validation only)

- [ ] **Step 1: Clean rebuild stress fixture**

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id stress_rpkm_1 \
  --rpkm-path ../resources/example_data/stress_rpkm_1.tsv \
  --tax-rank phylum \
  --pathway-level pathway
```

- [ ] **Step 2: Record size and row counts**

```bash
cd analytics
uv run python -c "
import duckdb
from pathlib import Path
p = Path('transform/runs/stress_rpkm_1/sample.duckdb')
c = duckdb.connect(str(p), read_only=True)
tables = sorted(r[0] for r in c.execute('SHOW TABLES').fetchall())
for t in tables:
    n = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t}: {n:,}')
c.close()
print(f'size_mb: {p.stat().st_size / 1e6:.1f}')
"
```

Expected:
- No `stg_rpkm_long` table
- `int_rpkm_by_ec_tax`: 386,700 rows
- `size_mb` ≤ 50

- [ ] **Step 3: Full pytest**

```bash
cd analytics && uv run pytest -q
```

Expected: all PASS

- [ ] **Step 4: Commit (if any benchmark notes added to design spec)**

Optional: append measured stress numbers to `docs/superpowers/specs/2026-07-09-inline-rpkm-ingest-design.md` §8.1.

---

## Self-Review

| Spec requirement | Task |
|---|---|
| `rpkm_ingest_long()` macro | Task 1 |
| SQL `int_rpkm_by_ec_tax` | Task 2 |
| Remove staging model/script | Task 3 |
| `run_pipeline.py` select change | Task 3 |
| fake_rpkm A3/A4 ingest expectations | Task 4 |
| Micro tests B1–B3, D1 | Task 5 |
| Singular test retarget | Task 6 |
| Stress size ≤ 50 MB | Task 7 |
| API unchanged | No task (verified by existing golden tests) |

No placeholders remain.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-09-inline-rpkm-ingest.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks
2. **Inline Execution** — run tasks in this session with checkpoints

**Which approach?**
