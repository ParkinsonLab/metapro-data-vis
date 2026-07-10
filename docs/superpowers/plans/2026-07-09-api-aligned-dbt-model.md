# API-Aligned dbt Sample Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 21× fan-out dbt intermediates and runtime reference-parquet API reads with a single `mart_rpkm_enriched` table and wide `bridge_tax_lineage` reference bridge — all six viz endpoints query only `sample.duckdb`.

**Architecture:** Container build produces `bridge_tax_lineage.parquet` (wide, from `names`+`parents`). Upload build joins sample tax_ids/ECs into `dim_sample_taxon` / `dim_sample_ec`, materializes `mart_rpkm_enriched`, and drops `int_rpkm_pathway`, `int_tax_rollup_resolved`, `mart_pathway_taxonomy_long`. API services use `query_enriched.py` helpers mirroring dbt macros for rollup labels and pathway labels.

**Tech Stack:** dbt 1.12 + dbt-duckdb, DuckDB, Python 3.14, FastAPI, pytest

**Worktree:** `.worktrees/feature/api-aligned-dbt-model/` on branch `feature/api-aligned-dbt-model`

**Design spec:** `docs/superpowers/specs/2026-07-08-api-aligned-dbt-model-design.md`

---

## Reference Material

Read before implementing:

- Design spec §3–§6 (bridge shape, mart schema, macro semantics, API patterns)
- `analytics/transform/scripts/build_reference.py` — current `build_bridge_tax_rollup()` (fallback algorithm to mirror in macros)
- `analytics/api/rollup_query.py`, `ec_tax_triples.py`, `tax_lineage_order.py` — code to replace
- `analytics/transform/tests/fixtures/fake_rpkm_pipeline_expectations.yaml` — 21-cell rollup grid
- Measured stress baseline in spec §1.3 / §8 (`stress_rpkm_1`: 386,700 enriched rows, 603 MB current DB)

**Prerequisites:** `resources/db/parquet/{names,parents}.parquet` present; run `build_reference.py` after Task 1 before dbt tasks.

---

## File Map

```
analytics/transform/
├── scripts/
│   ├── build_reference.py              # MODIFY: bridge_tax_lineage replaces rollup
│   └── run_pipeline.py                 # MODIFY: metrics, REQUIRED_BRIDGES, drop --export-mart
├── models/
│   ├── sources.yml                     # MODIFY: bridge_tax_lineage source
│   ├── intermediate/
│   │   ├── dim_sample_taxon.sql        # CREATE
│   │   ├── dim_sample_ec.sql           # CREATE
│   │   ├── int_rpkm_pathway.sql        # DELETE
│   │   └── int_tax_rollup_resolved.sql # DELETE
│   └── marts/
│       ├── mart_rpkm_enriched.sql      # CREATE
│       └── mart_pathway_taxonomy_long.sql  # DELETE
├── macros/
│   ├── resolve_tax_label.sql           # CREATE
│   ├── resolve_tax_id.sql              # CREATE
│   ├── canonical_pathway_label.sql     # CREATE
│   ├── aggregate_pathway_tax.sql       # CREATE (replaces mart_pathway_taxonomy_agg)
│   └── mart_pathway_taxonomy_agg.sql   # DELETE
└── tests/
    ├── assert_bridge_tax_lineage.sql   # CREATE (replaces assert_bridge_tax_7_ranks)
    ├── assert_int_rpkm_3_levels.sql    # DELETE
    ├── assert_mart_*.sql               # MODIFY: target enriched mart
    └── python/
        ├── test_build_reference.py     # MODIFY: lineage tests
        └── test_fake_rpkm_pipeline.py  # MODIFY: query mart_rpkm_enriched

analytics/api/
├── query_enriched.py                   # CREATE: SQL expr builders mirroring macros
├── overview_service.py                 # MODIFY
├── chord_service.py                    # MODIFY
├── pathway_list_service.py             # MODIFY
├── krona_service.py                    # MODIFY
├── graph_service.py                    # MODIFY
├── network_service.py                  # MODIFY
├── rollup_query.py                     # DELETE
├── ec_tax_triples.py                   # DELETE
├── tax_lineage_order.py                # MODIFY: no parquet reads
└── tests/
    ├── test_query_enriched.py          # CREATE
    ├── test_rollup_query.py            # DELETE or repurpose
    └── test_tax_lineage_order.py       # MODIFY
```

---

### Task 1: `bridge_tax_lineage` in `build_reference.py`

**Files:**
- Modify: `analytics/transform/scripts/build_reference.py`
- Modify: `analytics/transform/tests/python/test_build_reference.py`
- Delete references: `bridge_tax_rollup` in `run_pipeline.py` `REQUIRED_BRIDGES` (Task 10 — can do here)

- [ ] **Step 1: Write failing test for wide lineage schema**

```python
# analytics/transform/tests/python/test_build_reference.py

RANKS = ("kingdom", "phylum", "class", "order", "family", "genus", "species")

def test_bridge_tax_lineage_schema(conn_with_tax):
    from analytics.transform.scripts.build_reference import build_bridge_tax_lineage
    df = build_bridge_tax_lineage(conn_with_tax).df()
    expected = {"tax_id", "display_name"}
    for rank in RANKS:
        expected.add(f"{rank}_id")
        expected.add(f"{rank}_label")
    assert set(df.columns) == expected


def test_bridge_tax_lineage_homo_sapiens(conn_with_tax):
    from analytics.transform.scripts.build_reference import build_bridge_tax_lineage
    df = build_bridge_tax_lineage(conn_with_tax).df()
    row = df[df["tax_id"] == 9606].iloc[0]
    assert row["display_name"] == "Homo sapiens"
    assert row["species_id"] == 9606
    assert row["species_label"] == "Homo sapiens"
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd analytics && uv run pytest transform/tests/python/test_build_reference.py::test_bridge_tax_lineage_schema -v
```

Expected: `ImportError` or `AttributeError: build_bridge_tax_lineage`

- [ ] **Step 3: Implement `build_bridge_tax_lineage()`**

Replace `build_bridge_tax_rollup()` with a wide pivot from `parents` + `names`:

```python
def build_bridge_tax_lineage(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
  if not _table_exists(conn, "bridge_tax_rank_map"):
      build_bridge_tax_rank_map(conn)
  return conn.sql("""
      WITH base AS (
          SELECT DISTINCT tax_id FROM bridge_tax_rank_map
          UNION
          SELECT DISTINCT tax_id FROM parents
      ),
      lineage AS (
          SELECT
              p.tax_id,
              p.t_kingdom AS kingdom_id, p.t_phylum AS phylum_id,
              p.t_class AS class_id, p.t_order AS order_id,
              p.t_family AS family_id, p.t_genus AS genus_id,
              p.t_species AS species_id
          FROM parents p
          JOIN base b ON b.tax_id = p.tax_id
      )
      SELECT
          l.tax_id,
          COALESCE(n_self.name, CAST(l.tax_id AS VARCHAR)) AS display_name,
          l.kingdom_id, nk.name AS kingdom_label,
          l.phylum_id,  np.name AS phylum_label,
          l.class_id,   nc.name AS class_label,
          l.order_id,   no.name AS order_label,
          l.family_id,  nf.name AS family_label,
          l.genus_id,   ng.name AS genus_label,
          l.species_id, ns.name AS species_label
      FROM lineage l
      LEFT JOIN names n_self ON n_self.tax_id = l.tax_id
      LEFT JOIN names nk ON nk.tax_id = l.kingdom_id
      LEFT JOIN names np ON np.tax_id = l.phylum_id
      LEFT JOIN names nc ON nc.tax_id = l.class_id
      LEFT JOIN names no ON no.tax_id = l.order_id
      LEFT JOIN names nf ON nf.tax_id = l.family_id
      LEFT JOIN names ng ON ng.tax_id = l.genus_id
      LEFT JOIN names ns ON ns.tax_id = l.species_id
      ORDER BY l.tax_id
  """)
```

Update `main()` to write `bridge_tax_lineage.parquet` instead of `bridge_tax_rollup.parquet`. Remove `_assert_bridge_tax_rollup`; add `_assert_bridge_tax_lineage` checking row count > 0 and all seven `{rank}_label` columns exist.

- [ ] **Step 4: Run lineage tests — expect PASS**

```bash
cd analytics && uv run pytest transform/tests/python/test_build_reference.py -v -k lineage
```

- [ ] **Step 5: Build reference parquets locally**

```bash
cd analytics && uv run python transform/scripts/build_reference.py
ls -lh transform/reference/parquet/
```

Expected: `bridge_tax_lineage.parquet` present; no new `bridge_tax_rollup.parquet` write.

- [ ] **Step 6: Commit**

```bash
git add analytics/transform/scripts/build_reference.py analytics/transform/tests/python/test_build_reference.py
git commit -m "feat(transform): replace bridge_tax_rollup with wide bridge_tax_lineage"
```

---

### Task 2: dbt source + rollup macros

**Files:**
- Modify: `analytics/transform/models/sources.yml`
- Create: `analytics/transform/macros/resolve_tax_label.sql`
- Create: `analytics/transform/macros/resolve_tax_id.sql`
- Create: `analytics/transform/macros/canonical_pathway_label.sql`
- Create: `analytics/transform/macros/aggregate_pathway_tax.sql`
- Create: `analytics/transform/tests/python/test_rollup_macros.py`

- [ ] **Step 1: Update `sources.yml`**

```yaml
      - name: bridge_tax_lineage
        description: "Wide taxonomy lineage — one row per tax_id"
        meta:
          external_location: "read_parquet('{{ var(\"reference_parquet_dir\") }}/bridge_tax_lineage.parquet')"
```

Remove `bridge_tax_rollup` source entry.

- [ ] **Step 2: Write macro tests (Python, compile macros via dbt or inline SQL)**

```python
# analytics/transform/tests/python/test_rollup_macros.py
import duckdb

def test_resolve_tax_label_fallback():
    conn = duckdb.connect()
    # species absent, genus present → genus label
    sql = """
    SELECT CASE 'species'
      WHEN 'species' THEN COALESCE(NULL, 'GenusName', NULL, NULL, NULL, NULL, NULL, 'Unclassified')
    END AS lbl
    """
    assert conn.execute(sql).fetchone()[0] == "GenusName"

def test_canonical_pathway_label_node_is_ec():
    conn = duckdb.connect()
    row = conn.execute("""
      SELECT CASE
        WHEN '1.1.1.1' = '0.0.0.0' OR NULL IS NULL THEN 'Unmapped EC'
        WHEN 'pathway_node' = 'pathway_node' THEN '1.1.1.1'
        ELSE 'ignored'
      END
    """).fetchone()
    assert row[0] == '1.1.1.1'
```

Expand with full `resolve_tax_label` branches for all seven ranks (copy COALESCE chains from spec §3.3).

- [ ] **Step 3: Implement macros**

`resolve_tax_label.sql` — Jinja macro emitting COALESCE chain per `tax_level` argument referencing `kingdom_label` … `species_label` column names passed as strings or use fixed column refs.

`canonical_pathway_label.sql`:

```sql
{% macro canonical_pathway_label(ann_level, ec_col, pathway_id_col, pathway_name_col, superpathway_name_col) %}
CASE
  WHEN {{ ec_col }} = '0.0.0.0' OR {{ pathway_id_col }} IS NULL THEN 'Unmapped EC'
  WHEN '{{ ann_level }}' = 'pathway_node' THEN {{ ec_col }}
  WHEN '{{ ann_level }}' = 'superpathway' THEN {{ superpathway_name_col }}
  ELSE {{ pathway_name_col }}
END
{% endmacro %}
```

`aggregate_pathway_tax.sql` — `GROUP BY` on `resolve_tax_label(...)` and `canonical_pathway_label(...)` with `SUM(value)`.

- [ ] **Step 4: Run macro tests**

```bash
cd analytics && uv run pytest transform/tests/python/test_rollup_macros.py -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/transform/models/sources.yml analytics/transform/macros/*.sql analytics/transform/tests/python/test_rollup_macros.py
git commit -m "feat(dbt): add resolve_tax_label and canonical_pathway_label macros"
```

---

### Task 3: `dim_sample_taxon` and `dim_sample_ec`

**Files:**
- Create: `analytics/transform/models/intermediate/dim_sample_taxon.sql`
- Create: `analytics/transform/models/intermediate/dim_sample_ec.sql`
- Modify: `analytics/transform/models/intermediate/schema.yml`

- [ ] **Step 1: Write `dim_sample_taxon.sql`**

```sql
WITH sample_tax_ids AS (
    SELECT DISTINCT source_tax_id FROM {{ ref('int_rpkm_by_ec_tax') }}
)
SELECT
    s.source_tax_id,
    COALESCE(b.display_name, CAST(s.source_tax_id AS VARCHAR)) AS display_name,
    b.kingdom_id, b.kingdom_label,
    b.phylum_id,  b.phylum_label,
    b.class_id,   b.class_label,
    b.order_id,   b.order_label,
    b.family_id,  b.family_label,
    b.genus_id,   b.genus_label,
    b.species_id, b.species_label
FROM sample_tax_ids s
LEFT JOIN {{ source('reference', 'bridge_tax_lineage') }} b
       ON s.source_tax_id = b.tax_id
```

- [ ] **Step 2: Write `dim_sample_ec.sql`**

```sql
WITH sample_ecs AS (
    SELECT DISTINCT ec_normalized FROM {{ ref('int_rpkm_by_ec_tax') }}
)
SELECT DISTINCT
    s.ec_normalized,
    b.pathway_node_id,
    b.pathway_id,
    b.pathway_name,
    b.superpathway_id,
    b.superpathway_name
FROM sample_ecs s
LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
       ON s.ec_normalized = b.ec_normalized
```

Use `SELECT DISTINCT` or `ANY_VALUE` aggregation if EC bridge fan-out produces multiple pathway_node rows per EC — verify against `fake_rpkm`.

- [ ] **Step 3: Build dims only on fake_rpkm**

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id fake_rpkm \
  --rpkm-path transform/tests/fixtures/fake_rpkm.tsv \
  --tax-rank phylum --pathway-level pathway
# If old models still exist, use: dbt build --select dim_sample_taxon dim_sample_ec
```

- [ ] **Step 4: Assert row counts**

```bash
cd analytics && uv run python -c "
import duckdb
c = duckdb.connect('transform/runs/fake_rpkm/sample.duckdb')
print('taxon', c.execute('SELECT COUNT(*) FROM dim_sample_taxon').fetchone())
print('ec', c.execute('SELECT COUNT(*) FROM dim_sample_ec').fetchone())
"
```

Expected: taxon rows = distinct tax_ids in fixture (~10); ec rows = distinct ECs.

- [ ] **Step 5: Commit**

```bash
git add analytics/transform/models/intermediate/dim_sample_*.sql analytics/transform/models/intermediate/schema.yml
git commit -m "feat(dbt): add sample-scoped taxon and EC dimension models"
```

---

### Task 4: `mart_rpkm_enriched`

**Files:**
- Create: `analytics/transform/models/marts/mart_rpkm_enriched.sql`
- Modify: `analytics/transform/models/marts/schema.yml`
- Modify: `analytics/transform/dbt_project.yml` (ensure marts materialized as table)

- [ ] **Step 1: Write `mart_rpkm_enriched.sql`**

Join `int_rpkm_by_ec_tax` + dims; `ORDER BY superpathway_id, pathway_id, ec_normalized, source_tax_id`.

- [ ] **Step 2: Add schema tests**

`not_null` on `sample_id`, `ec_normalized`, `source_tax_id`, `value`; relationships to dims optional.

- [ ] **Step 3: Build on fake_rpkm and test_rpkm_1**

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py --sample-id fake_rpkm --rpkm-path transform/tests/fixtures/fake_rpkm.tsv
uv run python transform/scripts/run_pipeline.py --sample-id test_rpkm_1 --rpkm-path ../resources/example_data/test_rpkm_1.tsv
```

- [ ] **Step 4: Verify row count matches `int_rpkm_by_ec_tax`**

```bash
cd analytics && uv run python -c "
import duckdb
for s in ['fake_rpkm','test_rpkm_1']:
  c=duckdb.connect(f'transform/runs/{s}/sample.duckdb')
  a=c.execute('SELECT COUNT(*) FROM int_rpkm_by_ec_tax').fetchone()[0]
  b=c.execute('SELECT COUNT(*) FROM mart_rpkm_enriched').fetchone()[0]
  assert a==b, (s,a,b)
  print(s, a)
"
```

- [ ] **Step 5: Commit**

```bash
git add analytics/transform/models/marts/mart_rpkm_enriched.sql analytics/transform/models/marts/schema.yml
git commit -m "feat(dbt): add mart_rpkm_enriched join mart"
```

---

### Task 5: Port `fake_rpkm` rollup grid tests

**Files:**
- Modify: `analytics/transform/tests/python/test_fake_rpkm_pipeline.py`
- Create helper: `analytics/testing/enriched_query.py` (SQL builder using same semantics as macros)

- [ ] **Step 1: Add query helper that aggregates enriched mart at (tax_level, ann_level)**

```python
def fetch_rollup_cell(conn, *, ec, tax_id, tax_level, ann_level):
    sql = """
    SELECT
      <canonical_pathway_label> AS pathway_label,
      <resolve_tax_label> AS resolved_tax_label,
      SUM(value) AS value
    FROM mart_rpkm_enriched
    WHERE ec_normalized = ? AND source_tax_id = ?
    GROUP BY 1, 2
    """
```

For `pathway_node` level, expect `pathway_label = ec` (not 'Unmapped EC') when EC is mapped — **update YAML expectations** if current fixture expects `'Unmapped EC'` for pathway_node on mapped EC `1.6.5.9` (spec says node label = ec_normalized). Cross-check fixture: rows say `pathway_label: Unmapped EC` for pathway_node — this may be **old bug**. Per approved spec §4.7, pathway_node label = `ec_normalized`. Update `fake_rpkm_pipeline_expectations.yaml` pathway_node rows to `pathway_label: 1.6.5.9`.

- [ ] **Step 2: Rewrite tests to use `mart_rpkm_enriched`**

Replace `int_tax_rollup_resolved` queries; expect 21 logical cells via aggregation (not 21 raw rows).

- [ ] **Step 3: Run tests**

```bash
cd analytics && uv run pytest transform/tests/python/test_fake_rpkm_pipeline.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/transform/tests/python/test_fake_rpkm_pipeline.py \
        analytics/transform/tests/fixtures/fake_rpkm_pipeline_expectations.yaml \
        analytics/testing/enriched_query.py
git commit -m "test(transform): port fake_rpkm rollup grid to mart_rpkm_enriched"
```

---

### Task 6: `query_enriched.py` API helpers

**Files:**
- Create: `analytics/api/query_enriched.py`
- Create: `analytics/api/tests/test_query_enriched.py`

- [ ] **Step 1: Write failing tests for SQL expression builders**

```python
from api.query_enriched import resolve_tax_label_sql, canonical_pathway_label_sql

def test_resolve_tax_label_sql_phylum():
    sql = resolve_tax_label_sql("phylum")
    assert "phylum_label" in sql
    assert "kingdom_label" in sql

def test_canonical_pathway_label_sql_node():
    sql = canonical_pathway_label_sql("pathway_node")
    assert "ec_normalized" in sql
```

- [ ] **Step 2: Implement helpers** mirroring dbt macro COALESCE chains and CASE for pathway labels. Export `lineage_order_by_sql()` (move from `tax_lineage_order.py` without parquet).

- [ ] **Step 3: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_query_enriched.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/api/query_enriched.py analytics/api/tests/test_query_enriched.py
git commit -m "feat(api): add query_enriched SQL helpers for mart_rpkm_enriched"
```

---

### Task 7: Rewrite overview + krona services

**Files:**
- Modify: `analytics/api/overview_service.py`
- Modify: `analytics/api/krona_service.py`
- Modify: `analytics/api/tests/test_overview_service.py`
- Modify: `analytics/api/tests/test_krona_service.py`

- [ ] **Step 1: Overview — remove `read_parquet(bridge)`**, query `mart_rpkm_enriched`:

```sql
SELECT resolve_tax_label('phylum', ...) AS phylum_label, kingdom_label, SUM(value)
FROM mart_rpkm_enriched
GROUP BY 1, 2
ORDER BY kingdom_label, phylum_label
```

- [ ] **Step 2: Krona — aggregate by `source_tax_id`**, select lineage columns from mart; remove bridge/names parquet reads.

- [ ] **Step 3: Run golden tests**

```bash
cd analytics && uv run pytest api/tests/test_overview_service.py api/tests/test_krona_service.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/api/overview_service.py analytics/api/krona_service.py api/tests/test_overview_service.py api/tests/test_krona_service.py
git commit -m "refactor(api): overview and krona read mart_rpkm_enriched only"
```

---

### Task 8: Rewrite chord + pathway-list services

**Files:**
- Modify: `analytics/api/chord_service.py`
- Modify: `analytics/api/pathway_list_service.py`
- Delete: `analytics/api/rollup_query.py`
- Modify: `analytics/api/tests/test_chord_service.py`
- Modify: `analytics/api/tests/test_pathway_list_service.py`
- Delete: `analytics/api/tests/test_rollup_query.py`

- [ ] **Step 1: Replace `build_filtered_rollup_rows`** with enriched-mart WHERE filters on `superpathway_name`, `pathway_name`, `ec_normalized`, and `resolve_tax_label` for taxon filter.

- [ ] **Step 2: Chord ordering** — compute from aggregated totals on `kingdom_label`… columns in mart; no `bridge_tax` temp table.

- [ ] **Step 3: Run chord + pathway-list tests**

```bash
cd analytics && uv run pytest api/tests/test_chord_service.py api/tests/test_pathway_list_service.py -v
```

- [ ] **Step 4: Commit**

```bash
git add analytics/api/chord_service.py analytics/api/pathway_list_service.py api/tests/
git rm analytics/api/rollup_query.py analytics/api/tests/test_rollup_query.py
git commit -m "refactor(api): chord and pathway-list use mart_rpkm_enriched"
```

---

### Task 9: Rewrite graph + network services

**Files:**
- Modify: `analytics/api/graph_service.py`
- Modify: `analytics/api/network_service.py`
- Delete: `analytics/api/ec_tax_triples.py`
- Modify: `analytics/api/tax_lineage_order.py` — read lineage from mart aggregates, not parquet
- Modify: related tests

- [ ] **Step 1: Graph** — filter `mart_rpkm_enriched` by `pathway_name = ?`; `GROUP BY ec_normalized, resolve_tax_label(tax_level, ...)`.

- [ ] **Step 2: Network** — same value query; keep `pathway_*.parquet` reads for layout only.

- [ ] **Step 3: Refactor `tax_lineage_order`** to build metadata from distinct tax_ids in a filtered mart subset.

- [ ] **Step 4: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_graph_service.py api/tests/test_network_service.py api/tests/test_graph_network_parity.py -v
```

- [ ] **Step 5: Commit**

```bash
git rm analytics/api/ec_tax_triples.py
git add analytics/api/graph_service.py analytics/api/network_service.py analytics/api/tax_lineage_order.py api/tests/
git commit -m "refactor(api): graph and network use mart_rpkm_enriched for values"
```

---

### Task 10: Remove old dbt models + update pipeline

**Files:**
- Delete: `int_rpkm_pathway.sql`, `int_tax_rollup_resolved.sql`, `mart_pathway_taxonomy_long.sql`, `mart_pathway_taxonomy_agg.sql`
- Modify: `assert_mart_*.sql`, `warn_rpkm_tax_id_resolvable.sql`, `assert_int_rpkm_3_levels.sql`
- Modify: `analytics/transform/scripts/run_pipeline.py`
- Modify: `analytics/transform/README.md`

- [ ] **Step 1: Delete old models and fix dbt tests**

Replace `assert_mart_nonempty` to count `mart_rpkm_enriched` rows > 0. Rewrite `warn_rpkm_tax_id_resolvable` to flag unknown tax_ids in `dim_sample_taxon` where all lineage labels null.

- [ ] **Step 2: Update `run_pipeline.py`**

```python
REQUIRED_BRIDGES = ["bridge_ec_pathway.parquet", "bridge_tax_lineage.parquet"]
```

Rewrite `INFO_METRICS_SQL` to query `mart_rpkm_enriched`. Remove `--export-mart` flag and mart parquet COPY.

- [ ] **Step 3: Full dbt build on fake_rpkm + test_rpkm_1**

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py --sample-id fake_rpkm --rpkm-path transform/tests/fixtures/fake_rpkm.tsv
uv run python transform/scripts/run_pipeline.py --sample-id test_rpkm_1 --rpkm-path ../resources/example_data/test_rpkm_1.tsv
```

Expected: no `int_tax_rollup_resolved` or `mart_pathway_taxonomy_long` in DB.

- [ ] **Step 4: Run all analytics tests**

```bash
cd analytics && uv run pytest transform/tests/python api/tests -v
```

- [ ] **Step 5: Commit**

```bash
git add -A analytics/transform analytics/api
git commit -m "refactor(transform): remove fan-out intermediates and legacy mart"
```

---

### Task 11: Stress validation + latency benchmark

**Files:** none (manual validation)

- [ ] **Step 1: Rebuild reference + pipeline on stress sample** (in worktree)

```bash
cd analytics && uv run python transform/scripts/build_reference.py
uv run python transform/scripts/generate_stress_rpkm.py --output-dir ../resources/example_data
uv run python transform/scripts/run_pipeline.py \
  --sample-id stress_rpkm_1 \
  --rpkm-path ../resources/example_data/stress_rpkm_1.tsv
```

- [ ] **Step 2: Record metrics**

```bash
cd analytics && uv run python -c "
import time, duckdb
from api.chord_service import build_chord_from_duckdb
from api.krona_service import build_krona_from_duckdb
db='transform/runs/stress_rpkm_1/sample.duckdb'
c=duckdb.connect(db)
print('enriched rows', c.execute('SELECT COUNT(*) FROM mart_rpkm_enriched').fetchone())
import os; print('db MB', os.path.getsize(db)/1e6)
"
```

- [ ] **Step 3: Verify acceptance thresholds** (spec §11)

- `mart_rpkm_enriched` rows = 386,700
- Chord < 200 ms, krona < 100 ms on stress_rpkm_1
- `test_rpkm_1` chord/krona < 50 ms

- [ ] **Step 4: Document measured post-migration numbers in spec §8** (optional follow-up commit)

---

### Task 12: Docs + push

- [ ] **Step 1: Update `analytics/transform/README.md`** — new model graph, `bridge_tax_lineage`, remove mart export docs.

- [ ] **Step 2: Push feature branch**

```bash
git push -u origin feature/api-aligned-dbt-model
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --repo sibyl229/metapro-data-vis --base dev --head feature/api-aligned-dbt-model \
  --title "feat(analytics): API-aligned dbt sample model" \
  --body "$(cat <<'EOF'
## Summary
- Replace bridge_tax_rollup with wide bridge_tax_lineage
- Add mart_rpkm_enriched; remove 21× fan-out intermediates
- All six viz APIs query sample.duckdb only (no reference parquet reads)

## Test plan
- [ ] pytest transform/tests/python api/tests
- [ ] stress_rpkm_1 pipeline + latency benchmarks
EOF
)"
```

---

## Self-Review (spec coverage)

| Spec requirement | Task |
|---|---|
| `bridge_tax_lineage` replaces long rollup | Task 1 |
| `dim_sample_taxon` / `dim_sample_ec` sample-scoped | Task 3 |
| `mart_rpkm_enriched` primary API table | Task 4 |
| Query-time `resolve_tax_label` / `canonical_pathway_label` | Tasks 2, 6 |
| All six endpoints on enriched mart | Tasks 7–9 |
| Retire `mart_pathway_taxonomy_long` | Task 10 |
| Port fake_rpkm 21-cell grid | Task 5 |
| Stress baselines | Task 11 |
| `run_pipeline.py` updates | Task 10 |

**Note:** Task 5 may require updating `fake_rpkm_pipeline_expectations.yaml` pathway_node labels from `'Unmapped EC'` to `ec_normalized` per approved spec — verify against chord golden tests before changing expectations.
