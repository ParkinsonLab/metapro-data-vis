from __future__ import annotations

import duckdb

from api.filters import validate_ann_level
from api.query_enriched import ann_order_by_sql, canonical_pathway_label_sql


def _distinct_cols(pathway_label: str, ann_level: str) -> str:
    validate_ann_level(ann_level)
    cols = f"{pathway_label} AS display_label, superpathway_name"
    if ann_level == "pathway":
        cols += ", pathway_name"
    return cols


def ann_labels_ordered(
    conn: duckdb.DuckDBPyConnection,
    *,
    ann_level: str,
    where_sql: str,
    params: list,
) -> list[str]:
    pathway_label = canonical_pathway_label_sql(ann_level)
    order_by = ann_order_by_sql(ann_level)
    distinct_cols = _distinct_cols(pathway_label, ann_level)
    rows = conn.execute(
        f"""
        SELECT display_label
        FROM (
            SELECT DISTINCT {distinct_cols}
            FROM mart_rpkm_enriched
            WHERE {where_sql}
        ) sub
        ORDER BY {order_by}
        """,
        params,
    ).fetchall()
    return [r[0] for r in rows]
