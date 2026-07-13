from __future__ import annotations

import duckdb

from api.query_enriched import (
    ann_order_by_sql,
    ann_order_distinct_cols_sql,
)


def ann_labels_ordered(
    conn: duckdb.DuckDBPyConnection,
    *,
    ann_level: str,
    where_sql: str,
    params: list,
) -> list[str]:
    distinct_cols = ann_order_distinct_cols_sql(ann_level)
    order_by = ann_order_by_sql(ann_level)
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
