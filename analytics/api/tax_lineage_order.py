from __future__ import annotations

import duckdb

from api.filters import TAX_RANK_ORDER, validate_tax_level
from api.query_enriched import lineage_order_by_sql, resolve_tax_label_sql


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def tax_cat_order_from_metadata_rows(rows: list[dict]) -> list[str]:
    return dedupe_preserve_order(
        [row["tax_map_value"] for row in rows if row.get("tax_map_value")]
    )


def materialize_tax_metadata_from_ids(
    conn: duckdb.DuckDBPyConnection,
    *,
    tax_level: str,
    ids_table: str,
    output_table: str = "tax_lineage_metadata",
) -> None:
    validate_tax_level(tax_level)
    lineage_cols = ", ".join(f"COALESCE(m.{rank}_label, '') AS {rank}" for rank in TAX_RANK_ORDER)
    tax_label = resolve_tax_label_sql(tax_level, prefix="m")
    order_by = lineage_order_by_sql()
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {output_table} AS
        SELECT DISTINCT
            m.source_tax_id,
            {lineage_cols},
            m.display_name,
            {tax_label} AS tax_map_value
        FROM mart_rpkm_enriched m
        INNER JOIN (SELECT DISTINCT source_tax_id FROM {ids_table}) ids
          ON m.source_tax_id = ids.source_tax_id
        ORDER BY {order_by}
        """
    )


def read_tax_metadata_rows(
    conn: duckdb.DuckDBPyConnection,
    *,
    table: str = "tax_lineage_metadata",
) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT display_name, COALESCE(tax_map_value, '')
        FROM {table}
        ORDER BY {lineage_order_by_sql()}
        """
    ).fetchall()
    return [
        {"display_name": name, "tax_map_value": tax_map_value}
        for name, tax_map_value in rows
    ]


def tax_cat_order_for_ids_table(
    conn: duckdb.DuckDBPyConnection,
    *,
    tax_level: str,
    ids_table: str,
    output_table: str = "tax_lineage_metadata",
) -> list[str]:
    materialize_tax_metadata_from_ids(
        conn,
        tax_level=tax_level,
        ids_table=ids_table,
        output_table=output_table,
    )
    return tax_cat_order_from_metadata_rows(
        read_tax_metadata_rows(conn, table=output_table)
    )
