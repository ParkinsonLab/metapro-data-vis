"""Shared int_rpkm_by_ec_tax triple filtering for graph and network."""

from __future__ import annotations

from pathlib import Path

import duckdb

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"

FILTERED_TRIPLES_TABLE = "filtered_triples"


def _ensure_bridge_ec(conn: duckdb.DuckDBPyConnection) -> None:
    if conn.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = 'bridge_ec'"
    ).fetchone():
        return
    if not BRIDGE_EC_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_EC_PATH}")
    path = BRIDGE_EC_PATH.as_posix()
    conn.execute(f"CREATE TEMP TABLE bridge_ec AS SELECT * FROM read_parquet('{path}')")


def _pathway_exists_clause(pathway_filter: dict[str, str] | None) -> tuple[str, list]:
    if pathway_filter is None:
        return "TRUE", []
    return (
        "EXISTS ("
        "  SELECT 1 FROM bridge_ec b"
        "  WHERE b.ec_normalized = r.ec_normalized"
        "    AND b.pathway_name = ?"
        ")",
        [pathway_filter["name"]],
    )


def _taxon_exists_clause(taxon_filter: dict[str, str] | None) -> tuple[str, list]:
    if taxon_filter is None:
        return "TRUE", []
    return (
        "EXISTS ("
        "  SELECT 1 FROM read_parquet(?) t"
        "  WHERE t.source_tax_id = r.source_tax_id"
        "    AND t.requested_rank = ?"
        "    AND t.resolved_tax_label = ?"
        ")",
        [
            BRIDGE_TAX_PATH.as_posix(),
            taxon_filter["level"],
            taxon_filter["name"],
        ],
    )


def materialize_filtered_triples(
    conn: duckdb.DuckDBPyConnection,
    *,
    pathway_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
    output_table: str = FILTERED_TRIPLES_TABLE,
) -> None:
    """One temp table for downstream SQL joins (EXISTS filters only on value scan)."""
    if pathway_filter is not None:
        _ensure_bridge_ec(conn)
    pathway_clause, pathway_params = _pathway_exists_clause(pathway_filter)
    tax_clause, tax_params = _taxon_exists_clause(taxon_filter)
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {output_table} AS
        SELECT r.ec_normalized, r.source_tax_id, r.value
        FROM int_rpkm_by_ec_tax r
        WHERE r.value > 0
          AND ({pathway_clause})
          AND ({tax_clause})
        """,
        pathway_params + tax_params,
    )
