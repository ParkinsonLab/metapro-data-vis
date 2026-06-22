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
