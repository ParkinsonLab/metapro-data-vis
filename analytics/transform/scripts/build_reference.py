"""Distribution-time reference bridge builder (pure DuckDB SQL — no dbt)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(subprocess.check_output(
    ['git', 'rev-parse', '--show-toplevel'],
    cwd=Path(__file__).parent
).decode().strip())
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
