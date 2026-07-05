from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import (
    TAX_RANK_ORDER,
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
    validate_ann_level,
    validate_tax_level,
)
from api.graph_matrix import build_graph_matrix

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"
REPO_ROOT = ANALYTICS_DIR.parent
NAMES_PATH = REPO_ROOT / "resources/db/parquet/names.parquet"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _lineage_order_by_sql() -> str:
    parts = list(TAX_RANK_ORDER) + ["display_name"]
    return ", ".join(f'"{rank}"' if rank == "order" else rank for rank in parts)


def _ann_filter_key(ann_filter: dict[str, str], ann_level: str) -> tuple[str, str]:
    name = ann_filter["name"]
    if ann_level == "superpathway":
        return "superpathway_label", name
    if ann_filter["level"] == "pathway":
        return "pathway", name
    return "superpathway", name


def _ensure_bridge_ec(conn: duckdb.DuckDBPyConnection) -> None:
    if conn.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = 'bridge_ec_long'"
    ).fetchone():
        return
    if not BRIDGE_EC_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_EC_PATH}")

    path = BRIDGE_EC_PATH.as_posix()
    conn.execute(f"CREATE TEMP TABLE bridge_ec AS SELECT * FROM read_parquet('{path}')")
    conn.execute(
        """
        CREATE TEMP TABLE bridge_ec_long AS
        SELECT DISTINCT ec_normalized, filter_level, filter_name
        FROM (
            SELECT
                ec_normalized,
                CASE
                    WHEN ec_normalized = '0.0.0.0' THEN 'Unmapped EC'
                    ELSE COALESCE(superpathway_name, ec_normalized)
                END AS superpathway_label,
                pathway_name AS pathway,
                superpathway_name AS superpathway
            FROM bridge_ec
        )
        UNPIVOT (filter_name FOR filter_level IN (superpathway_label, pathway, superpathway))
        WHERE filter_name IS NOT NULL
        """
    )


def _ann_exists_clause(ann_filter: dict[str, str] | None, ann_level: str) -> tuple[str, list]:
    if ann_filter is None:
        return "TRUE", []
    filter_level, filter_name = _ann_filter_key(ann_filter, ann_level)
    return (
        "EXISTS ("
        "  SELECT 1 FROM bridge_ec_long b"
        "  WHERE b.ec_normalized = r.ec_normalized"
        "    AND b.filter_level = ? AND b.filter_name = ?"
        ")",
        [filter_level, filter_name],
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


def _materialize_filtered_triples(
    conn: duckdb.DuckDBPyConnection,
    *,
    ann_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
    ann_level: str,
) -> None:
    """Like chord's filtered_rollup_rows — one temp table for downstream SQL joins."""
    _ensure_bridge_ec(conn)
    ann_clause, ann_params = _ann_exists_clause(ann_filter, ann_level)
    tax_clause, tax_params = _taxon_exists_clause(taxon_filter)
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE filtered_triples AS
        SELECT r.ec_normalized, r.source_tax_id, r.value
        FROM int_rpkm_by_ec_tax r
        WHERE r.value > 0
          AND ({ann_clause})
          AND ({tax_clause})
        """,
        ann_params + tax_params,
    )


def _fetch_ec_metadata(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT ec_normalized
        FROM (SELECT DISTINCT ec_normalized FROM filtered_triples) t
        ORDER BY
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 1) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 2) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 3) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 4) AS INTEGER), 2147483647),
            ec_normalized
        """
    ).fetchall()
    return [{"ec_normalized": ec} for (ec,) in rows]


def _materialize_tax_metadata(conn: duckdb.DuckDBPyConnection, *, tax_level: str) -> None:
    if not BRIDGE_TAX_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_TAX_PATH}")
    if not NAMES_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {NAMES_PATH}")

    rank_in = _sql_in_list(TAX_RANK_ORDER)
    lineage_cols = ", ".join(f"COALESCE(w.{rank}, '') AS {rank}" for rank in TAX_RANK_ORDER)
    order_by = _lineage_order_by_sql()
    bridge = BRIDGE_TAX_PATH.as_posix()
    names = NAMES_PATH.as_posix()
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE graph_tax_metadata AS
        WITH ids AS (
            SELECT DISTINCT source_tax_id FROM filtered_triples
        ),
        bridge_gated AS (
            SELECT
                source_tax_id,
                requested_rank,
                resolved_tax_label AS label
            FROM read_parquet('{bridge}')
            WHERE requested_rank IN ({rank_in})
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


def _read_tax_metadata(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT display_name, COALESCE(tax_map_value, '')
        FROM graph_tax_metadata
        """
    ).fetchall()
    return [{"display_name": name, "tax_map_value": tax_map_value} for name, tax_map_value in rows]


def _fetch_labeled_triples(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, float]]:
    rows = conn.execute(
        """
        SELECT t.ec_normalized, m.display_name, t.value
        FROM filtered_triples t
        INNER JOIN graph_tax_metadata m USING (source_tax_id)
        """
    ).fetchall()
    return [(str(ec), str(display_name), float(value)) for ec, display_name, value in rows]


def build_graph_from_duckdb(
    *,
    names: list[str],
    tax_level: str,
    ann_level: str,
    selected_ann_cat: dict | str,
    selected_taxon: dict,
) -> dict:
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")

    validate_tax_level(tax_level)
    validate_ann_level(ann_level)

    ann_filter = normalise_ann_filter(selected_ann_cat, ann_level)
    taxon_filter = normalise_taxon_filter(selected_taxon)
    sample_id = sample_id_from_names(names)
    db_file = _db_path(sample_id)
    if not db_file.exists():
        raise FileNotFoundError(f"sample not found: {sample_id}")

    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "int_rpkm_by_ec_tax" not in tables:
            raise RuntimeError(
                f"int_rpkm_by_ec_tax not materialized for sample: {sample_id}"
            )

        _materialize_filtered_triples(
            conn,
            ann_filter=ann_filter,
            taxon_filter=taxon_filter,
            ann_level=ann_level,
        )
        ec_rows = _fetch_ec_metadata(conn)
        _materialize_tax_metadata(conn, tax_level=tax_level)
        tax_rows = _read_tax_metadata(conn)
        triples = _fetch_labeled_triples(conn)

        return build_graph_matrix(
            triples=triples,
            ec_rows=ec_rows,
            tax_rows=tax_rows,
            ann_level=ann_level,
            tax_level=tax_level,
        )
    finally:
        conn.close()
