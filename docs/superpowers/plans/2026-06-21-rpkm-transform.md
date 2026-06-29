# RPKM → Pathway × Taxonomy Transform Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dbt + DuckDB pipeline under `analytics/transform/` that ingests a wide RPKM TSV and produces `mart_pathway_taxonomy_long` — a configurable pathway × taxonomy long table with summed per-taxon values, tiered constraint checks, and persisted run artifacts.

**Architecture:** Distribution-time `build_reference.py` (pure DuckDB SQL) produces two bridge Parquet files. Upload-time `dbt build` reads them as external sources, ingests the TSV via a Python model, and materialises staging → intermediate → mart as DuckDB tables inside `runs/{sample_id}/sample.duckdb`. A thin `run_pipeline.py` wrapper orchestrates env setup, dbt invocation, and artifact writing.

**Tech Stack:** Python 3.14, dbt-core 1.12.0b1, dbt-duckdb ≥1.10.1, mashumaro ≥3.17,<3.18, DuckDB, pytest

---

## Reference Material

Read these before implementing any task:

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — full design spec (all column types, SQL snippets, constraint definitions)
- `.worktrees/exploration-eda/analytics/exploration/docs/data-model.md` — exact table schemas and column names for raw reference Parquet
- `SPEC.md §3.1` — KEY_COLS list and EC# normalization rules

**Key column names from data-model.md (use exactly):**

| Parquet table | Columns used |
|---|---|
| `parents` | `tax_id BIGINT`, `t_kingdom`, `t_phylum`, `t_class`, `t_order`, `t_family`, `t_genus`, `t_species` (all BIGINT, nullable) |
| `names` | `tax_id BIGINT`, `name VARCHAR` |
| `pathway_nodes` | `id VARCHAR`, `name VARCHAR`, `pathway BIGINT` |
| `pathway_superpathways` | `id BIGINT`, `name VARCHAR`, `superpathway VARCHAR` |
| `superpathways` | `id VARCHAR`, `name VARCHAR` |

**EC normalization rules (from SPEC.md + data-model.md):**
- NULL / empty / `none` / `None` / `NA` / `null` (any case) → `'0.0.0.0'`
- Prefix `EC:` or `ec:` → strip prefix, keep rest
- Anything else → keep as-is

**Test fixtures:** `resources/example_data/test_rpkm_1.tsv` (425 K rows, 8 tax_id columns)

---

## File Map

```
analytics/transform/
├── dbt_project.yml
├── profiles.yml
├── models/
│   ├── sources.yml
│   ├── staging/
│   │   ├── schema.yml
│   │   └── stg_rpkm_long.py
│   ├── intermediate/
│   │   ├── schema.yml
│   │   ├── int_rpkm_by_ec_tax.sql
│   │   ├── int_rpkm_pathway.sql
│   │   └── int_tax_rollup_resolved.sql
│   └── marts/
│       ├── schema.yml
│       └── mart_pathway_taxonomy_long.sql
├── tests/
│   ├── assert_bridge_ec_no_zero.sql
│   ├── assert_bridge_tax_7_ranks.sql
│   ├── assert_int_rpkm_3_levels.sql
│   ├── assert_unmapped_mass_conservation.sql
│   ├── assert_mart_classified_taxa_have_keys.sql
│   ├── assert_mart_mapped_pathways_have_keys.sql
│   └── assert_mart_nonempty.sql
├── scripts/
│   ├── build_reference.py
│   └── run_pipeline.py
├── reference/
│   └── parquet/            # Git LFS — populated by build_reference.py
│       └── .gitkeep
└── tests/python/
    ├── test_stg_rpkm_long.py
    └── test_build_reference.py
```

**Modify:**
- `analytics/.gitignore` — append transform runtime ignores

---

## Task 1: Toolchain Gate + Project Scaffold

**Files:**
- Create: `analytics/transform/dbt_project.yml`
- Create: `analytics/transform/profiles.yml`
- Create: `analytics/transform/reference/parquet/.gitkeep`
- Modify: `analytics/.gitignore`

- [ ] **Step 1: Verify toolchain**

```bash
cd analytics && uv sync && uv run dbt --version
```

Expected output contains: `Core: 1.12.0-b1` and `duckdb: 1.10.x`. If not, check `pyproject.toml` pins (`dbt-core==1.12.0b1`, `mashumaro>=3.17,<3.18`, `[tool.uv] prerelease = "allow"`).

- [ ] **Step 2: Generate raw reference Parquet** (prerequisite for Task 3)

```bash
cd analytics && uv run python exploration/scripts/export_parquet.py
```

Expected: `resources/db/parquet/` created with `names.parquet`, `parents.parquet`, `pathway_nodes.parquet`, `pathway_superpathways.parquet`, `superpathways.parquet` (and others). If `resources/db/taxonomy.db` is missing, stop — the DB must exist.

- [ ] **Step 3: Create directory skeleton**

```bash
mkdir -p analytics/transform/models/staging
mkdir -p analytics/transform/models/intermediate
mkdir -p analytics/transform/models/marts
mkdir -p analytics/transform/tests/python
mkdir -p analytics/transform/scripts
mkdir -p analytics/transform/reference/parquet
touch analytics/transform/reference/parquet/.gitkeep
```

- [ ] **Step 4: Write `analytics/transform/dbt_project.yml`**

```yaml
name: 'rpkm_transform'
version: '1.0.0'
config-version: 2

profile: 'rpkm_transform'

model-paths: ["models"]
test-paths: ["tests"]
macro-paths: ["macros"]
target-path: "target"
clean-targets: ["target", "dbt_packages"]

vars:
  tax_rank: "phylum"
  pathway_level: "pathway"
  reference_parquet_dir: "transform/reference/parquet"
  # rpkm_path and sample_id: required at runtime, no defaults
  # raw_parquet_dir: for build_reference.py only, not used by dbt models

models:
  rpkm_transform:
    staging:
      +materialized: table
    intermediate:
      +materialized: table
    marts:
      +materialized: table
```

- [ ] **Step 5: Write `analytics/transform/profiles.yml`**

```yaml
rpkm_transform:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: "{{ env_var('DBT_DUCKDB_PATH', 'runs/default/sample.duckdb') }}"
```

- [ ] **Step 6: Write `.gitkeep` and update `analytics/.gitignore`**

Append to `analytics/.gitignore`:

```
# dbt + DuckDB transform runtime outputs
transform/runs/
transform/data/
transform/target/
transform/dbt_packages/
transform/logs/
transform/**/*.duckdb
```

- [ ] **Step 7: Verify dbt project parses**

```bash
cd analytics && uv run dbt debug --project-dir transform --profiles-dir transform
```

Expected: all checks pass except "Connection test" (no sample.duckdb yet — that's fine at this stage, look for `profiles.yml file [OK found]`, `dbt_project.yml file [OK found]`).

- [ ] **Step 8: Commit**

```bash
git add analytics/transform/ analytics/.gitignore
git commit -m "feat: scaffold dbt project structure and toolchain gate"
```

---

## Task 2: `build_reference.py` — bridge_ec_pathway

**Files:**
- Create: `analytics/transform/scripts/build_reference.py` (partial — ec_pathway bridge only)
- Create: `analytics/transform/tests/python/test_build_reference.py` (partial)

- [ ] **Step 1: Write failing test for bridge_ec_pathway**

```python
# analytics/transform/tests/python/test_build_reference.py
from __future__ import annotations
import re
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"

@pytest.fixture
def conn():
    c = duckdb.connect()
    # Load raw parquet as views
    for tbl in ["pathway_nodes", "pathway_superpathways", "superpathways"]:
        c.execute(
            f"CREATE VIEW {tbl} AS SELECT * FROM read_parquet('{RAW_PARQUET_DIR}/{tbl}.parquet')"
        )
    return c


def test_bridge_ec_pathway_schema(conn):
    from analytics.transform.scripts.build_reference import build_bridge_ec_pathway

    rel = build_bridge_ec_pathway(conn)
    df = rel.df()

    assert set(df.columns) == {
        "ec_normalized",
        "pathway_node_id",
        "pathway_id",
        "pathway_name",
        "superpathway_id",
        "superpathway_name",
    }


def test_bridge_ec_pathway_no_zero_ec(conn):
    from analytics.transform.scripts.build_reference import build_bridge_ec_pathway

    rel = build_bridge_ec_pathway(conn)
    df = rel.df()

    assert (df["ec_normalized"] == "0.0.0.0").sum() == 0, "0.0.0.0 found in bridge"


def test_bridge_ec_pathway_ec_pattern(conn):
    from analytics.transform.scripts.build_reference import build_bridge_ec_pathway

    rel = build_bridge_ec_pathway(conn)
    df = rel.df()

    pattern = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
    non_ec = df["ec_normalized"].apply(lambda v: not pattern.match(v))
    assert non_ec.sum() == 0, f"Non-EC rows found: {df[non_ec]['ec_normalized'].unique()[:5]}"


def test_bridge_ec_pathway_row_count(conn):
    from analytics.transform.scripts.build_reference import build_bridge_ec_pathway

    rel = build_bridge_ec_pathway(conn)
    df = rel.df()

    assert len(df) > 0
    # EDA: 7,064 EC-dotted pathway_node rows
    assert len(df) >= 7000, f"Expected ≥7000 rows, got {len(df)}"
```

- [ ] **Step 2: Run test — expect ImportError (module doesn't exist yet)**

```bash
cd analytics && uv run pytest transform/tests/python/test_build_reference.py::test_bridge_ec_pathway_schema -v
```

Expected: `ImportError: No module named 'analytics.transform.scripts.build_reference'`

- [ ] **Step 3: Create `analytics/transform/scripts/__init__.py` and `analytics/transform/__init__.py`**

```bash
touch analytics/transform/__init__.py
touch analytics/transform/scripts/__init__.py
touch analytics/transform/tests/__init__.py
touch analytics/transform/tests/python/__init__.py
```

- [ ] **Step 4: Write `build_bridge_ec_pathway` in `build_reference.py`**

```python
# analytics/transform/scripts/build_reference.py
"""Distribution-time reference bridge builder (pure DuckDB SQL — no dbt)."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[4]
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"
REFERENCE_PARQUET_DIR = Path(__file__).resolve().parents[2] / "reference/parquet"

RANKS = [
    ("kingdom", 1),
    ("phylum", 2),
    ("class", 3),
    ("order", 4),
    ("family", 5),
    ("genus", 6),
    ("species", 7),
]


def _attach_raw(conn: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    """Register raw parquet tables as views."""
    for tbl in ["names", "parents", "pathway_nodes", "pathway_superpathways", "superpathways"]:
        conn.execute(
            f"CREATE OR REPLACE VIEW {tbl} AS "
            f"SELECT * FROM read_parquet('{raw_dir}/{tbl}.parquet')"
        )


def build_bridge_ec_pathway(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """
    Return a DuckDB relation for bridge_ec_pathway.
    One row per (ec_normalized, pathway_node_id).
    Filters to EC-dotted names (4-segment pattern), excludes 0.0.0.0.
    ORDER BY superpathway_id, pathway_id, ec_normalized for Parquet compression.
    """
    return conn.sql("""
        SELECT
            n.name                              AS ec_normalized,
            n.id                                AS pathway_node_id,
            ps.id                               AS pathway_id,
            ps.name                             AS pathway_name,
            s.id                                AS superpathway_id,
            s.name                              AS superpathway_name
        FROM pathway_nodes n
        JOIN pathway_superpathways ps ON n.pathway = ps.id
        JOIN superpathways         s  ON ps.superpathway = s.id
        WHERE regexp_matches(n.name, '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$')
          AND n.name != '0.0.0.0'
        ORDER BY s.id, ps.id, n.name
    """)
```

- [ ] **Step 5: Run failing tests — expect pass**

```bash
cd analytics && uv run pytest transform/tests/python/test_build_reference.py -k "ec_pathway" -v
```

Expected: all 4 `ec_pathway` tests pass.

- [ ] **Step 6: Commit**

```bash
git add analytics/transform/scripts/ analytics/transform/tests/python/test_build_reference.py
git commit -m "feat: build_reference.py - bridge_ec_pathway with tests"
```

---

## Task 3: `build_reference.py` — bridge_tax_rollup + main()

**Files:**
- Modify: `analytics/transform/scripts/build_reference.py`
- Modify: `analytics/transform/tests/python/test_build_reference.py`

- [ ] **Step 1: Write failing tests for bridge_tax_rollup**

Add to `analytics/transform/tests/python/test_build_reference.py`:

```python
@pytest.fixture
def conn_with_tax():
    c = duckdb.connect()
    for tbl in ["names", "parents"]:
        c.execute(
            f"CREATE VIEW {tbl} AS SELECT * FROM read_parquet('{RAW_PARQUET_DIR}/{tbl}.parquet')"
        )
    return c


def test_bridge_tax_rollup_schema(conn_with_tax):
    from analytics.transform.scripts.build_reference import build_bridge_tax_rollup

    rel = build_bridge_tax_rollup(conn_with_tax)
    df = rel.df()

    assert set(df.columns) == {
        "source_tax_id",
        "requested_rank",
        "resolved_tax_id",
        "resolved_tax_rank",
        "resolved_tax_label",
    }


def test_bridge_tax_rollup_seven_ranks(conn_with_tax):
    from analytics.transform.scripts.build_reference import build_bridge_tax_rollup

    rel = build_bridge_tax_rollup(conn_with_tax)
    df = rel.df()

    ranks = set(df["requested_rank"].unique())
    assert ranks == {"kingdom", "phylum", "class", "order", "family", "genus", "species"}


def test_bridge_tax_rollup_one_row_per_tax_rank(conn_with_tax):
    from analytics.transform.scripts.build_reference import build_bridge_tax_rollup

    rel = build_bridge_tax_rollup(conn_with_tax)
    df = rel.df()

    dupes = df.groupby(["source_tax_id", "requested_rank"]).size()
    assert (dupes > 1).sum() == 0, "Duplicate (source_tax_id, requested_rank) rows found"


def test_bridge_tax_rollup_unclassified_label(conn_with_tax):
    from analytics.transform.scripts.build_reference import build_bridge_tax_rollup

    rel = build_bridge_tax_rollup(conn_with_tax)
    df = rel.df()

    # Rows with null resolved_tax_id must have 'Unclassified' label
    null_rows = df[df["resolved_tax_id"].isnull()]
    assert (null_rows["resolved_tax_label"] == "Unclassified").all()


def test_bridge_tax_rollup_known_taxon(conn_with_tax):
    """Homo sapiens (tax_id=9606) should resolve exactly at species rank."""
    from analytics.transform.scripts.build_reference import build_bridge_tax_rollup

    rel = build_bridge_tax_rollup(conn_with_tax)
    df = rel.df()

    row = df[(df["source_tax_id"] == 9606) & (df["requested_rank"] == "species")]
    assert len(row) == 1
    assert row.iloc[0]["resolved_tax_id"] == 9606
    assert row.iloc[0]["resolved_tax_rank"] == "species"
    assert row.iloc[0]["resolved_tax_label"] is not None
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd analytics && uv run pytest transform/tests/python/test_build_reference.py -k "tax_rollup" -v
```

Expected: `ImportError` — function doesn't exist yet.

- [ ] **Step 3: Write `build_bridge_tax_rollup` and `main()` in `build_reference.py`**

Append to `analytics/transform/scripts/build_reference.py`:

```python
def build_bridge_tax_rank_map(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Build bridge_tax_rank_map as an in-memory DuckDB table.
    One row per (tax_id, rank, rank_tax_id): the ancestor at each rank.
    Includes at-rank self-rows (where t_{rank} = tax_id).
    """
    conn.execute("""
        CREATE OR REPLACE TABLE bridge_tax_rank_map AS
        SELECT DISTINCT tax_id, rank, rank_tax_id
        FROM (
            SELECT tax_id, 'kingdom' AS rank, t_kingdom AS rank_tax_id FROM parents WHERE t_kingdom IS NOT NULL
            UNION ALL
            SELECT tax_id, 'phylum',  t_phylum  FROM parents WHERE t_phylum  IS NOT NULL
            UNION ALL
            SELECT tax_id, 'class',   t_class   FROM parents WHERE t_class   IS NOT NULL
            UNION ALL
            SELECT tax_id, 'order',   t_order   FROM parents WHERE t_order   IS NOT NULL
            UNION ALL
            SELECT tax_id, 'family',  t_family  FROM parents WHERE t_family  IS NOT NULL
            UNION ALL
            SELECT tax_id, 'genus',   t_genus   FROM parents WHERE t_genus   IS NOT NULL
            UNION ALL
            SELECT tax_id, 'species', t_species FROM parents WHERE t_species IS NOT NULL
        )
    """)


def build_bridge_tax_rollup(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """
    Return a DuckDB relation for bridge_tax_rollup.
    One row per (source_tax_id, requested_rank): pre-resolved ancestry.
    Exact → coarser fallback → Unclassified (NULL key + 'Unclassified' label).
    ORDER BY requested_rank, source_tax_id for Parquet compression.
    """
    # Ensure bridge_tax_rank_map exists
    if not _table_exists(conn, "bridge_tax_rank_map"):
        build_bridge_tax_rank_map(conn)

    ranks_values = ", ".join(f"('{r}', {o})" for r, o in RANKS)

    return conn.sql(f"""
        WITH ranks(requested_rank, rank_order) AS (
            VALUES {ranks_values}
        ),
        all_combos AS (
            SELECT DISTINCT
                m.tax_id   AS source_tax_id,
                r.requested_rank,
                r.rank_order AS requested_order
            FROM bridge_tax_rank_map m
            CROSS JOIN ranks r
        ),
        -- For each (source_tax_id, requested_rank), find the finest available rank
        -- that is <= requested_order (exact or coarser fallback)
        with_match AS (
            SELECT
                c.source_tax_id,
                c.requested_rank,
                m.rank          AS resolved_tax_rank,
                m.rank_tax_id   AS resolved_tax_id,
                ROW_NUMBER() OVER (
                    PARTITION BY c.source_tax_id, c.requested_rank
                    ORDER BY rr.rank_order DESC   -- finest (largest rank_order) that fits
                ) AS rn
            FROM all_combos c
            JOIN bridge_tax_rank_map m  ON m.tax_id = c.source_tax_id
            JOIN ranks rr               ON rr.requested_rank = m.rank
            WHERE rr.rank_order <= c.requested_order
        ),
        best AS (
            SELECT source_tax_id, requested_rank, resolved_tax_rank, resolved_tax_id
            FROM with_match WHERE rn = 1
        ),
        -- Left join to capture combos with NO match (Unclassified)
        final AS (
            SELECT
                c.source_tax_id,
                c.requested_rank,
                b.resolved_tax_id,
                b.resolved_tax_rank,
                COALESCE(n.name, 'Unclassified') AS resolved_tax_label
            FROM all_combos c
            LEFT JOIN best b ON c.source_tax_id = b.source_tax_id
                             AND c.requested_rank = b.requested_rank
            LEFT JOIN names n ON b.resolved_tax_id = n.tax_id
        )
        SELECT source_tax_id, requested_rank, resolved_tax_id, resolved_tax_rank, resolved_tax_label
        FROM final
        ORDER BY requested_rank, source_tax_id
    """)


def _table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    result = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone()
    return result[0] > 0


def _assert_bridge_ec_pathway(conn: duckdb.DuckDBPyConnection, out_path: Path) -> None:
    zero_rows = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{out_path}') WHERE ec_normalized = '0.0.0.0'"
    ).fetchone()[0]
    assert zero_rows == 0, f"bridge_ec_pathway contains {zero_rows} rows with ec_normalized='0.0.0.0'"
    total = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    assert total > 0, "bridge_ec_pathway is empty"
    print(f"  bridge_ec_pathway: {total:,} rows, 0.0.0.0 check passed")


def _assert_bridge_tax_rollup(conn: duckdb.DuckDBPyConnection, out_path: Path) -> None:
    n_ranks = conn.execute(
        f"SELECT COUNT(DISTINCT requested_rank) FROM read_parquet('{out_path}')"
    ).fetchone()[0]
    assert n_ranks == 7, f"bridge_tax_rollup has {n_ranks} distinct requested_rank values (expected 7)"
    total = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    assert total > 0, "bridge_tax_rollup is empty"
    print(f"  bridge_tax_rollup: {total:,} rows, 7 ranks confirmed")


def main() -> None:
    raw_dir = RAW_PARQUET_DIR
    out_dir = REFERENCE_PARQUET_DIR

    if not raw_dir.exists():
        print(
            f"ERROR: {raw_dir} not found. Run analytics/exploration/scripts/export_parquet.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect()
    _attach_raw(conn, raw_dir)

    print("Building bridge_ec_pathway…")
    ec_path = out_dir / "bridge_ec_pathway.parquet"
    conn.execute(
        f"COPY (SELECT * FROM bridge_ec_pathway_rel) TO '{ec_path}' (FORMAT PARQUET)"
        .replace(
            "bridge_ec_pathway_rel",
            f"({build_bridge_ec_pathway(conn).sql_query()})",
        )
    )
    # Simpler: materialise to table then COPY
    conn.execute("CREATE OR REPLACE TABLE _bridge_ec_pathway AS " +
                 build_bridge_ec_pathway(conn).sql_query())
    conn.execute(f"COPY _bridge_ec_pathway TO '{ec_path}' (FORMAT PARQUET)")
    _assert_bridge_ec_pathway(conn, ec_path)

    print("Building bridge_tax_rank_map…")
    build_bridge_tax_rank_map(conn)

    print("Building bridge_tax_rollup (may take ~1 min for 20M rows)…")
    tax_path = out_dir / "bridge_tax_rollup.parquet"
    conn.execute("CREATE OR REPLACE TABLE _bridge_tax_rollup AS " +
                 build_bridge_tax_rollup(conn).sql_query())
    conn.execute(f"COPY _bridge_tax_rollup TO '{tax_path}' (FORMAT PARQUET)")
    _assert_bridge_tax_rollup(conn, tax_path)

    print("Done. Commit reference/parquet/ via Git LFS.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all build_reference tests**

```bash
cd analytics && uv run pytest transform/tests/python/test_build_reference.py -v
```

Expected: all tests pass. `test_bridge_tax_rollup_known_taxon` may be slow (full parquet scan) — acceptable.

- [ ] **Step 5: Run `build_reference.py` against real data**

```bash
cd analytics && uv run python transform/scripts/build_reference.py
```

Expected output:
```
Building bridge_ec_pathway…
  bridge_ec_pathway: 7,064 rows, 0.0.0.0 check passed
Building bridge_tax_rank_map…
Building bridge_tax_rollup (may take ~1 min for 20M rows)…
  bridge_tax_rollup: ~19,880,938 rows, 7 ranks confirmed
Done. Commit reference/parquet/ via Git LFS.
```

Verify files exist: `ls analytics/transform/reference/parquet/`

- [ ] **Step 6: Commit**

```bash
git add analytics/transform/scripts/build_reference.py \
        analytics/transform/tests/python/test_build_reference.py \
        analytics/transform/reference/parquet/
git commit -m "feat: build_reference.py complete - bridge_ec_pathway + bridge_tax_rollup"
```

---

## Task 4: dbt Sources + stg_rpkm_long

**Files:**
- Create: `analytics/transform/models/sources.yml`
- Create: `analytics/transform/models/staging/stg_rpkm_long.py`
- Create: `analytics/transform/models/staging/schema.yml`
- Create: `analytics/transform/tests/python/test_stg_rpkm_long.py`

- [ ] **Step 1: Write failing unit tests for stg_rpkm_long transformation logic**

```python
# analytics/transform/tests/python/test_stg_rpkm_long.py
"""Unit tests for stg_rpkm_long._transform using synthetic TSV data."""
from __future__ import annotations

import textwrap
from pathlib import Path

import duckdb
import pytest


def _write_tsv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.tsv"
    p.write_text(textwrap.dedent(content).lstrip())
    return p


@pytest.fixture
def conn():
    return duckdb.connect()


def test_unpivot_produces_long_rows(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606\t1234
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t2.0\t0.0
        gene2\t200\t3\tNone\t0.5\t0\t0.0\t4.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()

    # gene1 has nonzero value only for tax_id 9606
    # gene2 has nonzero value only for tax_id 1234
    assert len(df) == 2
    assert set(df["source_tax_id"].tolist()) == {9606, 1234}


def test_zero_values_excluded(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t0.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    assert len(df) == 0


def test_ec_normalization(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        gene2\t100\t5\tec:5.6.7.8\t1.0\t0\t2.0
        gene3\t100\t5\tNone\t1.0\t0\t3.0
        gene4\t100\t5\t\t1.0\t0\t4.0
        gene5\t100\t5\t9.9.9.9\t1.0\t0\t5.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    ecs = dict(zip(df["gene_id"], df["ec_normalized"]))

    assert ecs["gene1"] == "1.2.3.4"
    assert ecs["gene2"] == "5.6.7.8"
    assert ecs["gene3"] == "0.0.0.0"
    assert ecs["gene4"] == "0.0.0.0"
    assert ecs["gene5"] == "9.9.9.9"


def test_unclassified_column_excluded(conn, tmp_path):
    """'Unclassified' is a KEY_COL — must not appear as source_tax_id."""
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t99.0\t1.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    assert "Unclassified" not in df["source_tax_id"].astype(str).tolist()
    assert len(df) == 1  # only 9606 row


def test_sample_id_column(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "my_sample").df()
    assert df["sample_id"].iloc[0] == "my_sample"


def test_output_columns(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    assert list(df.columns) == ["sample_id", "gene_id", "ec_normalized", "source_tax_id", "value"]
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd analytics && uv run pytest transform/tests/python/test_stg_rpkm_long.py -v
```

Expected: `ImportError: No module named 'analytics.transform.scripts.stg_rpkm_long'`

- [ ] **Step 3: Create `analytics/transform/scripts/stg_rpkm_long.py`** (transformation helper — NOT a dbt model)

```python
# analytics/transform/scripts/stg_rpkm_long.py
"""Reusable transformation logic for stg_rpkm_long, testable without dbt context."""
from __future__ import annotations

import duckdb

KEY_COLS = ("GeneID", "Length", "Reads", "EC#", "RPKM", "Unclassified")
_EXCLUDE = ", ".join(f'"{c}"' for c in KEY_COLS)


def _transform(
    conn: duckdb.DuckDBPyConnection, rpkm_path: str, sample_id: str
) -> duckdb.DuckDBPyRelation:
    """
    Read wide RPKM TSV at rpkm_path, UNPIVOT tax_id columns, normalize EC#.
    Returns a DuckDB relation with columns:
        sample_id, gene_id, ec_normalized, source_tax_id (BIGINT), value (DOUBLE)
    Filters value > 0; drops rows where source_tax_id is not a valid integer.
    """
    return conn.sql(f"""
        WITH wide AS (
            SELECT *
            FROM read_csv(
                '{rpkm_path}',
                sep = '\t',
                header = true,
                all_varchar = true,
                nullstr = ['', 'NA', 'null', 'NULL', 'None', 'none']
            )
        ),
        unpivoted AS (
            UNPIVOT wide
            ON COLUMNS(* EXCLUDE ({_EXCLUDE}))
            INTO NAME source_tax_id_col VALUE value_str
        ),
        normalized AS (
            SELECT
                '{sample_id}'::VARCHAR                              AS sample_id,
                "GeneID"                                            AS gene_id,
                CASE
                    WHEN "EC#" IS NULL                              THEN '0.0.0.0'
                    WHEN UPPER("EC#") LIKE 'EC:%'                   THEN TRIM(SUBSTRING("EC#", 4))
                    ELSE "EC#"
                END                                                 AS ec_normalized,
                TRY_CAST(source_tax_id_col AS BIGINT)               AS source_tax_id,
                TRY_CAST(value_str AS DOUBLE)                       AS value
            FROM unpivoted
        )
        SELECT sample_id, gene_id, ec_normalized, source_tax_id, value
        FROM normalized
        WHERE value > 0
          AND source_tax_id IS NOT NULL
    """)
```

- [ ] **Step 4: Create `analytics/transform/models/staging/stg_rpkm_long.py`** (dbt Python model)

```python
# analytics/transform/models/staging/stg_rpkm_long.py
"""dbt Python model: wide RPKM TSV → long form."""
import sys
from pathlib import Path

# Make the scripts helper importable within the dbt execution context
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.stg_rpkm_long import _transform  # noqa: E402


def model(dbt, session):
    dbt.config(materialized="table")

    rpkm_path = dbt.config.get("rpkm_path")
    sample_id = dbt.config.get("sample_id")

    if not rpkm_path:
        raise ValueError("dbt var 'rpkm_path' is required. Pass via --vars '{rpkm_path: /path}'")
    if not sample_id:
        raise ValueError("dbt var 'sample_id' is required. Pass via --vars '{sample_id: name}'")

    return _transform(session, rpkm_path, sample_id)
```

- [ ] **Step 5: Create `analytics/transform/models/sources.yml`**

```yaml
version: 2

sources:
  - name: reference
    description: "Pre-built bridge Parquet files from build_reference.py (distribution artifact)"
    tables:
      - name: bridge_ec_pathway
        description: "EC-to-pathway mapping — one row per (ec_normalized, pathway_node_id)"
        meta:
          external_location: "read_parquet('{{ var(\"reference_parquet_dir\") }}/bridge_ec_pathway.parquet')"

      - name: bridge_tax_rollup
        description: "Pre-resolved taxonomy rollup — one row per (source_tax_id, requested_rank)"
        meta:
          external_location: "read_parquet('{{ var(\"reference_parquet_dir\") }}/bridge_tax_rollup.parquet')"
```

- [ ] **Step 6: Create `analytics/transform/models/staging/schema.yml`**

```yaml
version: 2

models:
  - name: stg_rpkm_long
    description: "Wide RPKM TSV unpivoted to long form. One row per (gene, tax_id) where value > 0."
    columns:
      - name: sample_id
        description: "Sample identifier from dbt var"
        tests:
          - not_null
      - name: gene_id
        tests:
          - not_null
      - name: ec_normalized
        description: "Normalized EC string; 0.0.0.0 for unmapped genes"
        tests:
          - not_null
      - name: source_tax_id
        description: "RPKM column header as integer NCBI tax_id"
        tests:
          - not_null
      - name: value
        description: "Per-taxon column value (nonzero only)"
        tests:
          - not_null
```

- [ ] **Step 7: Run Python unit tests**

```bash
cd analytics && uv run pytest transform/tests/python/test_stg_rpkm_long.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 8: Run dbt on test fixture (smoke test)**

```bash
cd analytics && \
  DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt build \
    --project-dir transform \
    --profiles-dir transform \
    --select stg_rpkm_long \
    --vars '{"rpkm_path": "../resources/example_data/test_rpkm_1.tsv", "sample_id": "test_rpkm_1", "reference_parquet_dir": "transform/reference/parquet"}'
```

Expected: `1 of 1 OK` — stg_rpkm_long materialized. Check row count:

```bash
cd analytics && \
  uv run python -c "import duckdb; c=duckdb.connect('transform/runs/test_rpkm_1/sample.duckdb'); print(c.execute('SELECT COUNT(*) FROM stg_rpkm_long').fetchone())"
```

Expected: ~59,439 rows (nonzero cells from test_rpkm_1.tsv).

- [ ] **Step 9: Commit**

```bash
git add analytics/transform/models/ analytics/transform/scripts/stg_rpkm_long.py \
        analytics/transform/tests/python/test_stg_rpkm_long.py
git commit -m "feat: stg_rpkm_long Python model with unit tests and dbt sources"
```

---

## Task 5: `int_rpkm_by_ec_tax` + `int_rpkm_pathway`

**Files:**
- Create: `analytics/transform/models/intermediate/int_rpkm_by_ec_tax.sql`
- Create: `analytics/transform/models/intermediate/int_rpkm_pathway.sql`
- Create: `analytics/transform/models/intermediate/schema.yml` (partial)

- [ ] **Step 1: Write `int_rpkm_by_ec_tax.sql`**

```sql
-- analytics/transform/models/intermediate/int_rpkm_by_ec_tax.sql
-- Collapse multiple genes with the same (ec_normalized, source_tax_id) before pathway join.
-- Gene aggregation step — see spec §5.1.

SELECT
    sample_id,
    ec_normalized,
    source_tax_id,
    SUM(value) AS value
FROM {{ ref('stg_rpkm_long') }}
GROUP BY sample_id, ec_normalized, source_tax_id
```

- [ ] **Step 2: Write `int_rpkm_pathway.sql`**

```sql
-- analytics/transform/models/intermediate/int_rpkm_pathway.sql
-- LEFT JOIN with bridge_ec_pathway; UNION ALL three pathway levels.
-- Each branch SELECT DISTINCT deduplicates fan-out at the level's grain.
-- Unmapped ECs (pathway_key IS NULL) appear once per pathway_level.
-- Physical ordering: ORDER BY pathway_level, pathway_key for zone-map skipping.

WITH base AS (
    SELECT * FROM {{ ref('int_rpkm_by_ec_tax') }}
),
superpathway_branch AS (
    SELECT DISTINCT
        base.sample_id,
        base.ec_normalized,
        base.source_tax_id,
        base.value,
        'superpathway'                                  AS pathway_level,
        CAST(b.superpathway_id AS VARCHAR)              AS pathway_key,
        b.superpathway_name                             AS pathway_label
    FROM base
    LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
           ON base.ec_normalized = b.ec_normalized
),
pathway_branch AS (
    SELECT DISTINCT
        base.sample_id,
        base.ec_normalized,
        base.source_tax_id,
        base.value,
        'pathway'                                       AS pathway_level,
        CAST(b.pathway_id AS VARCHAR)                   AS pathway_key,
        b.pathway_name                                  AS pathway_label
    FROM base
    LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
           ON base.ec_normalized = b.ec_normalized
),
pathway_node_branch AS (
    SELECT DISTINCT
        base.sample_id,
        base.ec_normalized,
        base.source_tax_id,
        base.value,
        'pathway_node'                                  AS pathway_level,
        b.pathway_node_id                               AS pathway_key,
        NULL::VARCHAR                                   AS pathway_label
    FROM base
    LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
           ON base.ec_normalized = b.ec_normalized
)

SELECT * FROM superpathway_branch
UNION ALL
SELECT * FROM pathway_branch
UNION ALL
SELECT * FROM pathway_node_branch
ORDER BY pathway_level, pathway_key
```

- [ ] **Step 3: Create `analytics/transform/models/intermediate/schema.yml`**

```yaml
version: 2

models:
  - name: int_rpkm_by_ec_tax
    description: >
      Gene-aggregated RPKM: SUM(value) per (ec_normalized, source_tax_id).
      Input to pathway join — gene_id dropped.
    columns:
      - name: sample_id
        tests: [not_null]
      - name: ec_normalized
        tests: [not_null]
      - name: source_tax_id
        tests: [not_null]
      - name: value
        tests: [not_null]

  - name: int_rpkm_pathway
    description: >
      All three pathway levels (superpathway / pathway / pathway_node) via UNION ALL.
      Filter on pathway_level downstream; unmapped ECs have pathway_key IS NULL.
    columns:
      - name: pathway_level
        tests:
          - not_null
          - accepted_values:
              values: ['superpathway', 'pathway', 'pathway_node']

  - name: int_tax_rollup_resolved
    description: >
      int_rpkm_pathway × bridge_tax_rollup: all 7 requested_rank values pre-joined.
      Filter on requested_rank downstream.
    columns:
      - name: requested_rank
        tests:
          - not_null
          - accepted_values:
              values: ['kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']
```

- [ ] **Step 4: Build and verify**

```bash
cd analytics && \
  DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt build \
    --project-dir transform \
    --profiles-dir transform \
    --select int_rpkm_by_ec_tax int_rpkm_pathway \
    --vars '{"rpkm_path": "../resources/example_data/test_rpkm_1.tsv", "sample_id": "test_rpkm_1", "reference_parquet_dir": "transform/reference/parquet"}'
```

Expected: both models pass. Spot-check:

```bash
cd analytics && uv run python -c "
import duckdb
c = duckdb.connect('transform/runs/test_rpkm_1/sample.duckdb')
print('int_rpkm_by_ec_tax rows:', c.execute('SELECT COUNT(*) FROM int_rpkm_by_ec_tax').fetchone()[0])
print('int_rpkm_pathway rows:', c.execute('SELECT COUNT(*) FROM int_rpkm_pathway').fetchone()[0])
print('pathway_level counts:', c.execute(\"SELECT pathway_level, COUNT(*) FROM int_rpkm_pathway GROUP BY 1\").fetchall())
"
```

Expected: `int_rpkm_pathway` has exactly 3× `int_rpkm_by_ec_tax` rows (before dedup — after dedup may be fewer). `pathway_level` shows 3 distinct values.

- [ ] **Step 5: Commit**

```bash
git add analytics/transform/models/intermediate/
git commit -m "feat: int_rpkm_by_ec_tax and int_rpkm_pathway SQL models"
```

---

## Task 6: `int_tax_rollup_resolved` + `mart_pathway_taxonomy_long`

**Files:**
- Create: `analytics/transform/models/intermediate/int_tax_rollup_resolved.sql`
- Create: `analytics/transform/models/marts/mart_pathway_taxonomy_long.sql`
- Create: `analytics/transform/models/marts/schema.yml`

- [ ] **Step 1: Write `int_tax_rollup_resolved.sql`**

```sql
-- analytics/transform/models/intermediate/int_tax_rollup_resolved.sql
-- Joins int_rpkm_pathway with bridge_tax_rollup on source_tax_id.
-- All 7 requested_rank values are stored — no resolution logic at upload.
-- Mart filters to the desired requested_rank + pathway_level.
-- Physical ordering: ORDER BY requested_rank, pathway_level, pathway_key
-- enables DuckDB zone-map skipping (~20/21 row groups per mart run).

SELECT
    p.sample_id,
    p.ec_normalized,
    p.source_tax_id,
    p.value,
    p.pathway_level,
    p.pathway_key,
    p.pathway_label,
    t.requested_rank,
    t.resolved_tax_id,
    t.resolved_tax_rank,
    t.resolved_tax_label
FROM {{ ref('int_rpkm_pathway') }} p
LEFT JOIN {{ source('reference', 'bridge_tax_rollup') }} t
       ON p.source_tax_id = t.source_tax_id
ORDER BY t.requested_rank, p.pathway_level, p.pathway_key
```

- [ ] **Step 2: Write `mart_pathway_taxonomy_long.sql`**

```sql
-- analytics/transform/models/marts/mart_pathway_taxonomy_long.sql
-- Filters int_tax_rollup_resolved to the configured (pathway_level, tax_rank) slice,
-- then aggregates by pathway + resolved taxon.
--
-- GROUP BY uses IDs only; labels are carried via ANY_VALUE() since they are
-- functionally dependent on their IDs.
--
-- IMPORTANT: WHERE requested_rank = var('tax_rank') is the correctness guard.
-- Without it, the same resolved_tax_id could appear for multiple requested_rank values
-- (exact at 'class', fallback at 'phylum'), causing double-counting in the aggregation.
--
-- ec_normalized is NOT in the GROUP BY or output: all unmapped ECs for the same taxon
-- collapse into one 'Unmapped EC' bucket per pathway_key IS NULL + resolved_tax_id.

SELECT
    sample_id,
    pathway_level,
    pathway_key,
    ANY_VALUE(COALESCE(pathway_label, 'Unmapped EC'))   AS pathway_label,
    resolved_tax_id,
    ANY_VALUE(resolved_tax_label)                       AS resolved_tax_label,
    ANY_VALUE(resolved_tax_rank)                        AS resolved_tax_rank,
    SUM(value)                                          AS value
FROM {{ ref('int_tax_rollup_resolved') }}
WHERE pathway_level  = '{{ var("pathway_level") }}'
  AND requested_rank = '{{ var("tax_rank") }}'
GROUP BY sample_id, pathway_level, pathway_key, resolved_tax_id
```

- [ ] **Step 3: Create `analytics/transform/models/marts/schema.yml`**

```yaml
version: 2

models:
  - name: mart_pathway_taxonomy_long
    description: >
      Final pathway × taxonomy long mart. Filtered to the configured
      pathway_level and tax_rank. One row per (pathway_key, resolved_tax_id).
    columns:
      - name: sample_id
        tests: [not_null]
      - name: pathway_level
        tests: [not_null]
      - name: pathway_key
        description: "NULL for unmapped ECs"
      - name: pathway_label
        description: "'Unmapped EC' when pathway_key IS NULL"
        tests: [not_null]
      - name: resolved_tax_id
        description: "NULL for Unclassified taxa"
      - name: resolved_tax_label
        description: "'Unclassified' when resolved_tax_id IS NULL"
        tests: [not_null]
      - name: value
        tests: [not_null]
```

- [ ] **Step 4: Build full pipeline and verify**

```bash
cd analytics && \
  DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt build \
    --project-dir transform \
    --profiles-dir transform \
    --select stg_rpkm_long+ \
    --vars '{"rpkm_path": "../resources/example_data/test_rpkm_1.tsv", "sample_id": "test_rpkm_1", "reference_parquet_dir": "transform/reference/parquet"}'
```

Expected: all models pass tests. Spot-check mart:

```bash
cd analytics && uv run python -c "
import duckdb
c = duckdb.connect('transform/runs/test_rpkm_1/sample.duckdb')
rows = c.execute('SELECT COUNT(*) FROM mart_pathway_taxonomy_long').fetchone()[0]
print('mart rows:', rows)
sample = c.execute('''
    SELECT pathway_key, pathway_label, resolved_tax_label, value
    FROM mart_pathway_taxonomy_long
    WHERE pathway_key IS NOT NULL
    ORDER BY value DESC LIMIT 5
''').fetchall()
for r in sample: print(r)
unmapped = c.execute(\"SELECT COUNT(*) FROM mart_pathway_taxonomy_long WHERE pathway_key IS NULL\").fetchone()[0]
print('unmapped rows:', unmapped)
"
```

Expected: mart has rows, top pathways show non-null pathway_label, unmapped rows present.

- [ ] **Step 5: Test re-parameterization (mart only rebuild)**

```bash
cd analytics && \
  DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt build \
    --project-dir transform \
    --profiles-dir transform \
    --select mart_pathway_taxonomy_long \
    --vars '{"sample_id": "test_rpkm_1", "tax_rank": "class", "pathway_level": "superpathway", "reference_parquet_dir": "transform/reference/parquet"}'
```

Expected: mart rebuilds in seconds (upstream intermediates reused). Mart now filters to class × superpathway.

- [ ] **Step 6: Commit**

```bash
git add analytics/transform/models/intermediate/int_tax_rollup_resolved.sql \
        analytics/transform/models/intermediate/schema.yml \
        analytics/transform/models/marts/
git commit -m "feat: int_tax_rollup_resolved and mart_pathway_taxonomy_long"
```

---

## Task 7: dbt Constraint Tests

**Files:**
- Create: `analytics/transform/tests/assert_bridge_ec_no_zero.sql`
- Create: `analytics/transform/tests/assert_bridge_tax_7_ranks.sql`
- Create: `analytics/transform/tests/assert_int_rpkm_3_levels.sql`
- Create: `analytics/transform/tests/assert_unmapped_mass_conservation.sql`
- Create: `analytics/transform/tests/assert_mart_classified_taxa_have_keys.sql`
- Create: `analytics/transform/tests/assert_mart_mapped_pathways_have_keys.sql`
- Create: `analytics/transform/tests/assert_mart_nonempty.sql`
- Create: `analytics/transform/tests/assert_rpkm_no_negative_values.sql`
- Create: `analytics/transform/tests/warn_rpkm_tax_id_resolvable.sql`

- [ ] **Step 1: Write source integrity tests (error severity)**

```sql
-- analytics/transform/tests/assert_bridge_ec_no_zero.sql
-- FAIL if any bridge row has ec_normalized = '0.0.0.0' (false-mapping guard).
{{ config(severity='error') }}
SELECT ec_normalized
FROM {{ source('reference', 'bridge_ec_pathway') }}
WHERE ec_normalized = '0.0.0.0'
```

```sql
-- analytics/transform/tests/assert_bridge_tax_7_ranks.sql
-- FAIL if bridge_tax_rollup does not have exactly 7 distinct requested_rank values.
{{ config(severity='error') }}
SELECT COUNT(DISTINCT requested_rank) AS n_ranks
FROM {{ source('reference', 'bridge_tax_rollup') }}
HAVING COUNT(DISTINCT requested_rank) != 7
```

- [ ] **Step 2: Write pipeline integrity tests (error severity)**

```sql
-- analytics/transform/tests/assert_int_rpkm_3_levels.sql
-- FAIL if int_rpkm_pathway does not contain exactly 3 distinct pathway_level values.
-- Guards against UNION ALL branch being accidentally dropped.
{{ config(severity='error') }}
SELECT COUNT(DISTINCT pathway_level) AS n_levels
FROM {{ ref('int_rpkm_pathway') }}
HAVING COUNT(DISTINCT pathway_level) != 3
```

```sql
-- analytics/transform/tests/assert_rpkm_no_negative_values.sql
{{ config(severity='error') }}
SELECT gene_id, source_tax_id, value
FROM {{ ref('stg_rpkm_long') }}
WHERE value < 0
```

- [ ] **Step 3: Write mart integrity tests (error severity)**

```sql
-- analytics/transform/tests/assert_mart_nonempty.sql
{{ config(severity='error') }}
SELECT COUNT(*) AS row_count
FROM {{ ref('mart_pathway_taxonomy_long') }}
HAVING COUNT(*) = 0
```

```sql
-- analytics/transform/tests/assert_mart_classified_taxa_have_keys.sql
-- FAIL if any row has a real taxon label but null resolved_tax_id.
{{ config(severity='error') }}
SELECT resolved_tax_label, resolved_tax_id
FROM {{ ref('mart_pathway_taxonomy_long') }}
WHERE resolved_tax_label != 'Unclassified'
  AND resolved_tax_id IS NULL
```

```sql
-- analytics/transform/tests/assert_mart_mapped_pathways_have_keys.sql
-- FAIL if any row has a real pathway name but null pathway_key.
{{ config(severity='error') }}
SELECT pathway_label, pathway_key
FROM {{ ref('mart_pathway_taxonomy_long') }}
WHERE pathway_label != 'Unmapped EC'
  AND pathway_key IS NULL
```

- [ ] **Step 4: Write warn-severity test**

```sql
-- analytics/transform/tests/warn_rpkm_tax_id_resolvable.sql
-- WARN if any source_tax_id has no row in bridge_tax_rollup (tax_id not in reference).
{{ config(severity='warn') }}
SELECT DISTINCT s.source_tax_id
FROM {{ ref('stg_rpkm_long') }} s
LEFT JOIN {{ source('reference', 'bridge_tax_rollup') }} b
       ON s.source_tax_id = b.source_tax_id
WHERE b.source_tax_id IS NULL
```

- [ ] **Step 5: Write unmapped mass conservation warn test**

```sql
-- analytics/transform/tests/assert_unmapped_mass_conservation.sql
-- WARN if the unmapped value total in the mart differs from the upstream
-- unmapped total by more than 0.01%.
-- Unmapped upstream = ec_tax rows whose ec_normalized has no bridge match.
-- Unmapped mart = rows where pathway_key IS NULL (all resolved_tax_ids summed).
{{ config(severity='warn') }}

WITH upstream_unmapped AS (
    SELECT SUM(value) AS total
    FROM {{ ref('int_rpkm_by_ec_tax') }}
    WHERE ec_normalized NOT IN (
        SELECT DISTINCT ec_normalized FROM {{ source('reference', 'bridge_ec_pathway') }}
    )
),
mart_unmapped AS (
    SELECT SUM(value) AS total
    FROM {{ ref('mart_pathway_taxonomy_long') }}
    WHERE pathway_key IS NULL
),
comparison AS (
    SELECT
        u.total                     AS upstream_total,
        m.total                     AS mart_total,
        ABS(u.total - m.total)
            / NULLIF(u.total, 0)    AS relative_delta
    FROM upstream_unmapped u, mart_unmapped m
)
SELECT upstream_total, mart_total, relative_delta
FROM comparison
WHERE relative_delta > 0.0001   -- 0.01% threshold
   OR upstream_total IS NULL
   OR mart_total IS NULL
```

- [ ] **Step 6: Run all tests**

```bash
cd analytics && \
  DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt test \
    --project-dir transform \
    --profiles-dir transform \
    --vars '{"rpkm_path": "../resources/example_data/test_rpkm_1.tsv", "sample_id": "test_rpkm_1", "reference_parquet_dir": "transform/reference/parquet", "tax_rank": "phylum", "pathway_level": "pathway"}'
```

Expected: all error-severity tests pass; warn tests pass or emit warnings. Check output carefully — any FAIL at error severity indicates a bug.

- [ ] **Step 7: Commit**

```bash
git add analytics/transform/tests/
git commit -m "feat: dbt constraint tests - error and warn severity"
```

---

## Task 8: `run_pipeline.py` Wrapper + Info Metrics

**Files:**
- Create: `analytics/transform/scripts/run_pipeline.py`

- [ ] **Step 1: Write `run_pipeline.py`**

```python
# analytics/transform/scripts/run_pipeline.py
"""
Thin orchestration wrapper for the RPKM transform pipeline.
Usage:
    cd analytics
    uv run python transform/scripts/run_pipeline.py \
        --sample-id test_rpkm_1 \
        --rpkm-path ../resources/example_data/test_rpkm_1.tsv \
        --tax-rank phylum \
        --pathway-level pathway \
        [--export-mart]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ANALYTICS_DIR = Path(__file__).resolve().parents[2]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"

REQUIRED_BRIDGES = ["bridge_ec_pathway.parquet", "bridge_tax_rollup.parquet"]

INFO_METRICS_SQL = {
    "rpkm_ec_kegg_coverage": """
        SELECT
            COUNT(DISTINCT ec_normalized) FILTER (
                WHERE pathway_key IS NOT NULL AND pathway_level = 'pathway_node'
            )::DOUBLE / NULLIF(COUNT(DISTINCT ec_normalized), 0)
        FROM int_rpkm_pathway
    """,
    "pathway_join_fanout_rate": """
        SELECT
            COUNT(*) FILTER (
                WHERE pathway_level = 'pathway_node' AND pathway_key IS NOT NULL
            )::DOUBLE /
            NULLIF(COUNT(DISTINCT (ec_normalized, source_tax_id)) FILTER (
                WHERE pathway_key IS NOT NULL
            ), 0)
        FROM int_rpkm_pathway
    """,
    "unmapped_ec_value_rate": """
        SELECT SUM(value) FILTER (WHERE pathway_key IS NULL) / NULLIF(SUM(value), 0)
        FROM mart_pathway_taxonomy_long
    """,
    "mart_rollup_exact_match_rate": """
        SELECT
            SUM(value) FILTER (
                WHERE resolved_tax_rank = requested_rank_val
                  AND resolved_tax_label != 'Unclassified'
            ) / NULLIF(SUM(value), 0)
        FROM (
            SELECT m.*, '{tax_rank}' AS requested_rank_val
            FROM mart_pathway_taxonomy_long m
        )
    """,
    "mart_rollup_fallback_rate": """
        SELECT
            SUM(value) FILTER (
                WHERE resolved_tax_rank != requested_rank_val
                  AND resolved_tax_label != 'Unclassified'
                  AND resolved_tax_id IS NOT NULL
            ) / NULLIF(SUM(value), 0)
        FROM (
            SELECT m.*, '{tax_rank}' AS requested_rank_val
            FROM mart_pathway_taxonomy_long m
        )
    """,
    "mart_unclassified_rate": """
        SELECT SUM(value) FILTER (WHERE resolved_tax_label = 'Unclassified') / NULLIF(SUM(value), 0)
        FROM mart_pathway_taxonomy_long
    """,
}


def _check_bridges(ref_dir: Path) -> None:
    missing = [f for f in REQUIRED_BRIDGES if not (ref_dir / f).exists()]
    if missing:
        print(
            f"ERROR: Missing bridge Parquet files in {ref_dir}: {missing}\n"
            "Run: cd analytics && uv run python transform/scripts/build_reference.py",
            file=sys.stderr,
        )
        sys.exit(1)


def _run_dbt(sample_id: str, rpkm_path: str, tax_rank: str, pathway_level: str) -> dict:
    db_path = TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    vars_dict = {
        "rpkm_path": rpkm_path,
        "sample_id": sample_id,
        "tax_rank": tax_rank,
        "pathway_level": pathway_level,
        "reference_parquet_dir": str(REFERENCE_PARQUET_DIR),
    }
    vars_json = json.dumps(vars_dict)

    env = {**os.environ, "DBT_DUCKDB_PATH": str(db_path)}

    result = subprocess.run(
        [
            "uv", "run", "dbt", "build",
            "--select", "stg_rpkm_long+",
            "--project-dir", str(TRANSFORM_DIR),
            "--profiles-dir", str(TRANSFORM_DIR),
            "--vars", vars_json,
        ],
        cwd=str(ANALYTICS_DIR),
        env=env,
        capture_output=False,  # stream output to terminal
    )
    return {"returncode": result.returncode, "db_path": str(db_path)}


def _parse_overall_status(transform_dir: Path) -> str:
    results_path = transform_dir / "target/run_results.json"
    if not results_path.exists():
        return "unknown"
    try:
        data = json.loads(results_path.read_text())
        statuses = [r.get("status", "") for r in data.get("results", [])]
        if any("error" in s for s in statuses):
            return "failed"
        if any("warn" in s for s in statuses):
            return "success_with_warnings"
        return "success"
    except Exception:
        return "unknown"


def _compute_info_metrics(db_path: str, tax_rank: str) -> dict:
    metrics = {}
    conn = duckdb.connect(db_path, read_only=True)
    for name, sql in INFO_METRICS_SQL.items():
        try:
            value = conn.execute(sql.format(tax_rank=tax_rank)).fetchone()[0]
            metrics[name] = round(float(value), 6) if value is not None else None
        except Exception as e:
            metrics[name] = f"error: {e}"
    return metrics


def _export_mart(db_path: str, sample_id: str) -> str:
    out_path = str(TRANSFORM_DIR / f"runs/{sample_id}/mart_pathway_taxonomy_long.parquet")
    conn = duckdb.connect(db_path)
    conn.execute(
        f"COPY mart_pathway_taxonomy_long TO '{out_path}' (FORMAT PARQUET)"
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RPKM transform pipeline")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--rpkm-path", required=True)
    parser.add_argument("--tax-rank", default="phylum")
    parser.add_argument("--pathway-level", default="pathway")
    parser.add_argument("--export-mart", action="store_true")
    args = parser.parse_args()

    _check_bridges(REFERENCE_PARQUET_DIR)

    dbt_result = _run_dbt(
        args.sample_id, args.rpkm_path, args.tax_rank, args.pathway_level
    )

    overall_status = _parse_overall_status(TRANSFORM_DIR)
    info_metrics = _compute_info_metrics(dbt_result["db_path"], args.tax_rank)

    context = {
        "sample_id": args.sample_id,
        "rpkm_path": args.rpkm_path,
        "tax_rank": args.tax_rank,
        "pathway_level": args.pathway_level,
        "reference_parquet_dir": str(REFERENCE_PARQUET_DIR),
        "dbt_artifacts": str(TRANSFORM_DIR / "target"),
        "overall_status": overall_status,
        "info_metrics": info_metrics,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    context_path = TRANSFORM_DIR / f"runs/{args.sample_id}/run_context.json"
    context_path.write_text(json.dumps(context, indent=2))
    print(f"\nrun_context.json written to {context_path}")
    print(f"overall_status: {overall_status}")

    if args.export_mart:
        mart_path = _export_mart(dbt_result["db_path"], args.sample_id)
        print(f"mart exported to {mart_path}")

    sys.exit(0 if dbt_result["returncode"] == 0 else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the wrapper end-to-end**

```bash
cd analytics && uv run python transform/scripts/run_pipeline.py \
  --sample-id test_rpkm_1 \
  --rpkm-path ../resources/example_data/test_rpkm_1.tsv \
  --tax-rank phylum \
  --pathway-level pathway \
  --export-mart
```

Expected:
- dbt build completes successfully
- `transform/runs/test_rpkm_1/run_context.json` written with `overall_status: "success"` and non-null `info_metrics`
- `transform/runs/test_rpkm_1/mart_pathway_taxonomy_long.parquet` created
- `transform/runs/test_rpkm_1/sample.duckdb` present

Verify info metrics are sensible:

```bash
cat analytics/transform/runs/test_rpkm_1/run_context.json | python3 -m json.tool
```

Expected `rpkm_ec_kegg_coverage` ≈ 0.36 (9,034 ECs in sample, 3,258 hit the bridge per data-model.md / 9,034). Expected `unmapped_ec_value_rate` > 0.

- [ ] **Step 3: Commit**

```bash
git add analytics/transform/scripts/run_pipeline.py
git commit -m "feat: run_pipeline.py wrapper with info metrics and mart export"
```

---

## Task 9: README + Final Verification

**Files:**
- Create: `analytics/transform/README.md`

- [ ] **Step 1: Write README**

```markdown
# RPKM Transform Pipeline

dbt + DuckDB pipeline that ingests a wide RPKM/FPKM TSV and produces
`mart_pathway_taxonomy_long` — a configurable pathway × taxonomy long table.

## Quick start

### 1. Prerequisites

```bash
# Install dependencies (Python 3.14 required)
cd analytics && uv sync

# Export raw reference Parquet (once, from taxonomy.db)
uv run python exploration/scripts/export_parquet.py
```

### 2. Build reference bridges (distribution step — run once per DB refresh)

```bash
cd analytics
uv run python transform/scripts/build_reference.py
```

Outputs `transform/reference/parquet/bridge_ec_pathway.parquet` and
`transform/reference/parquet/bridge_tax_rollup.parquet`. Commit these via Git LFS.

### 3. Run the pipeline on a sample

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id my_sample \
  --rpkm-path /path/to/my_sample.tsv \
  --tax-rank phylum \
  --pathway-level pathway \
  --export-mart
```

Output in `transform/runs/my_sample/`:
- `sample.duckdb` — all materialised tables
- `run_context.json` — vars, overall status, info metrics
- `mart_pathway_taxonomy_long.parquet` — mart export (with `--export-mart`)

### 4. Change tax_rank or pathway_level (fast re-run)

Intermediates are pre-computed for all parameter combinations. Only the mart's
WHERE filter changes — rebuild takes seconds:

```bash
DBT_DUCKDB_PATH=transform/runs/my_sample/sample.duckdb \
  uv run dbt build --project-dir transform --profiles-dir transform \
  --select mart_pathway_taxonomy_long \
  --vars '{"sample_id": "my_sample", "tax_rank": "class", "pathway_level": "superpathway", "reference_parquet_dir": "transform/reference/parquet"}'
```

## Rebuild triggers

| Model | Rebuilt when |
|---|---|
| `bridge_*` (Parquet) | `build_reference.py` re-run after raw Parquet refresh |
| `stg_rpkm_long` | New/changed RPKM file |
| `int_rpkm_by_ec_tax` | `stg_rpkm_long` rebuilds |
| `int_rpkm_pathway` | `int_rpkm_by_ec_tax` rebuilds (all 3 levels pre-computed) |
| `int_tax_rollup_resolved` | `int_rpkm_pathway` rebuilds (all 7 ranks pre-joined) |
| `mart_pathway_taxonomy_long` | Upstream rebuild **or** `tax_rank`/`pathway_level` change |

## Design spec

`docs/superpowers/specs/2026-06-15-rpkm-transform-design.md`
```

- [ ] **Step 2: Full pipeline verification — both test fixtures**

```bash
# test_rpkm_2.tsv (12 tax_id columns — wider fixture)
cd analytics && uv run python transform/scripts/run_pipeline.py \
  --sample-id test_rpkm_2 \
  --rpkm-path ../resources/example_data/test_rpkm_2.tsv \
  --tax-rank genus \
  --pathway-level superpathway
```

Expected: pipeline completes, `run_context.json` written with `overall_status: "success"`.

- [ ] **Step 3: Verify all success criteria from spec §13**

```bash
# Toolchain gate
cd analytics && uv run dbt --version | grep -E "Core|duckdb"

# Error constraints pass
DBT_DUCKDB_PATH=transform/runs/test_rpkm_1/sample.duckdb \
  uv run dbt test --project-dir transform --profiles-dir transform \
  --vars '{"sample_id": "test_rpkm_1", "tax_rank": "phylum", "pathway_level": "pathway", "reference_parquet_dir": "transform/reference/parquet"}' \
  --select tag:error 2>/dev/null || \
uv run dbt test --project-dir transform --profiles-dir transform \
  --vars '{"sample_id": "test_rpkm_1", "tax_rank": "phylum", "pathway_level": "pathway", "reference_parquet_dir": "transform/reference/parquet"}'

# run_context.json present
cat analytics/transform/runs/test_rpkm_1/run_context.json
```

Expected: all checks in spec §13 satisfied.

- [ ] **Step 4: Commit**

```bash
git add analytics/transform/README.md
git commit -m "docs: transform pipeline README with quick start and rebuild triggers"
```

---

## Self-Review Checklist

After writing, verify plan covers every §13 success criterion:

- [x] Worktree `feature/rpkm-transform` with dbt project under `analytics/transform/` → Task 1
- [x] Toolchain gate: `uv sync && uv run dbt --version` → Core 1.12.0-b1 → Task 1 Step 1
- [x] `build_reference.py` produces derived bridge Parquet + asserts no 0.0.0.0 → Tasks 2–3
- [x] Upload pipeline produces `mart_pathway_taxonomy_long` via bridge dbt sources → Tasks 4–6
- [x] Re-run with changed `tax_rank`/`pathway_level` completes in seconds → Task 6 Step 5
- [x] All error-severity constraints pass on test fixtures → Task 7
- [x] Info metrics emitted → Task 8 (`run_context.json`)
- [x] `run_context.json` + optional mart Parquet under `runs/{sample_id}/` → Task 8
- [x] dbt artifacts in `transform/target/` → profiles.yml target-path default
- [x] README documents distribution vs upload workflow → Task 9

---

**Plan complete and saved.** Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints
