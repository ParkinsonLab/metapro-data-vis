"""SQL helpers for querying mart_rpkm_enriched with dbt macro semantics."""
from __future__ import annotations

from typing import Any

import duckdb

RANKS = ("species", "genus", "family", "order", "class", "phylum", "kingdom")
ANN_LEVELS = ("pathway_node", "pathway", "superpathway")

_LINEAGE_ORDER = ("kingdom", "phylum", "class", "order", "family", "genus", "species")


def _lineage_ref(rank: str, suffix: str, prefix: str = "") -> str:
    if prefix:
        return f"{prefix}.{rank}_{suffix}"
    return f"{rank}_{suffix}"


def resolve_tax_label_sql(tax_level: str, prefix: str = "") -> str:
    """Mirror resolve_tax_label dbt macro (§3.3 fallback walk)."""
    try:
        start = _LINEAGE_ORDER.index(tax_level)
    except ValueError as exc:
        raise ValueError(f"unknown tax_level: {tax_level!r}") from exc
    chain = [_lineage_ref(rank, "label", prefix) for rank in _LINEAGE_ORDER[start:]]
    chain.append("'Unclassified'")
    return f"COALESCE({', '.join(chain)})"


def canonical_pathway_label_sql(
    ann_level: str,
    ec_col: str = "ec_normalized",
    pathway_id_col: str = "pathway_id",
    pathway_name_col: str = "pathway_name",
    superpathway_name_col: str = "superpathway_name",
) -> str:
    """Mirror canonical_pathway_label dbt macro (§4.7)."""
    return f"""CASE
  WHEN {ec_col} = '0.0.0.0' OR {pathway_id_col} IS NULL THEN 'Unmapped EC'
  WHEN '{ann_level}' = 'pathway_node' THEN {ec_col}
  WHEN '{ann_level}' = 'superpathway' THEN {superpathway_name_col}
  ELSE {pathway_name_col}
END"""


def rollup_cell_sql(tax_level: str, ann_level: str) -> str:
    pathway_label = canonical_pathway_label_sql(ann_level)
    tax_label = resolve_tax_label_sql(tax_level)
    return f"""
SELECT
    {pathway_label} AS pathway_label,
    {tax_label} AS resolved_tax_label,
    SUM(value) AS value
FROM mart_rpkm_enriched
WHERE ec_normalized = ? AND source_tax_id = ?
GROUP BY 1, 2
"""


def fetch_rollup_cell(
    conn: duckdb.DuckDBPyConnection,
    *,
    ec: str,
    tax_id: int,
    tax_level: str,
    ann_level: str,
) -> tuple[Any, ...] | None:
    return conn.execute(rollup_cell_sql(tax_level, ann_level), [ec, tax_id]).fetchone()


def count_rollup_cells(
    conn: duckdb.DuckDBPyConnection,
    *,
    ec: str,
    tax_id: int,
) -> int:
    return sum(
        1
        for rank in RANKS
        for ann in ANN_LEVELS
        if fetch_rollup_cell(conn, ec=ec, tax_id=tax_id, tax_level=rank, ann_level=ann)
        is not None
    )
