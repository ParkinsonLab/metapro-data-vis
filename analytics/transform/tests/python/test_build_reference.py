from __future__ import annotations
import re
import subprocess
from pathlib import Path

import duckdb
import pytest

REPO_ROOT = Path(subprocess.check_output(
    ['git', 'rev-parse', '--show-toplevel'],
    cwd=Path(__file__).parent
).decode().strip())
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"

@pytest.fixture
def conn():
    c = duckdb.connect()
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
    assert len(df) >= 7000, f"Expected ≥7000 rows, got {len(df)}"


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
    null_rows = df[df["resolved_tax_id"].isnull()]
    # Conditional: if any null resolved_tax_id rows exist, their label must be 'Unclassified'.
    # (All taxa in this DB are fully resolvable, so null_rows may legitimately be empty.)
    if len(null_rows) > 0:
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
