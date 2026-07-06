from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import TAX_RANK_ORDER, validate_tax_level

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"
REPO_ROOT = ANALYTICS_DIR.parent
NAMES_PATH = REPO_ROOT / "resources/db/parquet/names.parquet"


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def lineage_order_by_sql() -> str:
    parts = list(TAX_RANK_ORDER) + ["display_name"]
    return ", ".join(f'"{rank}"' if rank == "order" else rank for rank in parts)


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
    if not BRIDGE_TAX_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_TAX_PATH}")
    if not NAMES_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {NAMES_PATH}")

    rank_in = _sql_in_list(TAX_RANK_ORDER)
    lineage_cols = ", ".join(f"COALESCE(w.{rank}, '') AS {rank}" for rank in TAX_RANK_ORDER)
    order_by = lineage_order_by_sql()
    bridge = BRIDGE_TAX_PATH.as_posix()
    names = NAMES_PATH.as_posix()
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {output_table} AS
        WITH ids AS (
            SELECT DISTINCT source_tax_id FROM {ids_table}
        ),
        bridge_gated AS (
            SELECT
                b.source_tax_id,
                b.requested_rank,
                b.resolved_tax_label AS label
            FROM read_parquet('{bridge}') b
            INNER JOIN ids i ON b.source_tax_id = i.source_tax_id
            WHERE b.requested_rank IN ({rank_in})
        ),
        bridge_wide AS (
            SELECT *
            FROM (
                SELECT source_tax_id, requested_rank, label
                FROM bridge_gated
            )
            PIVOT (MAX(label) FOR requested_rank IN ({rank_in}))
        )
        SELECT
            d.source_tax_id,
            {lineage_cols},
            COALESCE(n.name, CAST(d.source_tax_id AS VARCHAR)) AS display_name,
            COALESCE(
                NULLIF(w.{tax_level}, ''),
                COALESCE(n.name, CAST(d.source_tax_id AS VARCHAR))
            ) AS tax_map_value
        FROM ids d
        LEFT JOIN bridge_wide w USING (source_tax_id)
        LEFT JOIN read_parquet('{names}') n ON d.source_tax_id = n.tax_id
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
) -> list[str]:
    materialize_tax_metadata_from_ids(
        conn, tax_level=tax_level, ids_table=ids_table
    )
    return tax_cat_order_from_metadata_rows(read_tax_metadata_rows(conn))
