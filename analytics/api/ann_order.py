from __future__ import annotations

import duckdb

from api.query_enriched import ann_order_by_sql, canonical_pathway_label_sql


def ann_labels_ordered(
    conn: duckdb.DuckDBPyConnection,
    *,
    ann_level: str,
    where_sql: str,
    params: list,
) -> list[str]:
    pathway_label = canonical_pathway_label_sql(ann_level)
    order_by = ann_order_by_sql(ann_level)
    rows = conn.execute(
        f"""
        SELECT DISTINCT {pathway_label} AS display_label
        FROM mart_rpkm_enriched
        WHERE {where_sql}
        ORDER BY {order_by}
        """,
        params,
    ).fetchall()
    return [r[0] for r in rows]
