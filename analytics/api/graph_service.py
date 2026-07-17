from __future__ import annotations

import duckdb

from api.config import db_path
from api.filters import (
    normalise_taxon_filter,
    require_graph_pathway_filter,
    sample_id_from_names,
    validate_tax_level,
)
from api.graph_matrix import build_graph_matrix
from api.query_enriched import taxon_filter_where_sql
from api.tax_lineage_order import (
    materialize_tax_metadata_from_ids,
    read_tax_metadata_rows,
)

FILTERED_IDS_TABLE = "graph_tax_ids"
TAX_METADATA_TABLE = "graph_tax_metadata"


def _enriched_where(
    *,
    pathway_name: str,
    taxon_filter: dict[str, str] | None,
) -> tuple[str, list]:
    tax_sql, tax_params = taxon_filter_where_sql(taxon_filter)
    return f"pathway_name = ? AND ({tax_sql})", [pathway_name] + tax_params


def _materialize_filtered_ids(
    conn: duckdb.DuckDBPyConnection,
    *,
    where_sql: str,
    params: list,
) -> None:
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {FILTERED_IDS_TABLE} AS
        SELECT DISTINCT source_tax_id
        FROM mart_rpkm_enriched
        WHERE {where_sql}
        """,
        params,
    )


def _fetch_ec_metadata(
    conn: duckdb.DuckDBPyConnection,
    *,
    where_sql: str,
    params: list,
) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT ec_normalized
        FROM mart_rpkm_enriched
        WHERE {where_sql}
        GROUP BY ec_normalized
        ORDER BY
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 1) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 2) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 3) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 4) AS INTEGER), 2147483647),
            ec_normalized
        """,
        params,
    ).fetchall()
    return [{"ec_normalized": ec} for (ec,) in rows]


def _fetch_display_name_triples(
    conn: duckdb.DuckDBPyConnection,
    *,
    where_sql: str,
    params: list,
) -> list[tuple[str, str, float]]:
    rows = conn.execute(
        f"""
        SELECT ec_normalized, display_name, SUM(value) AS value
        FROM mart_rpkm_enriched
        WHERE {where_sql}
        GROUP BY ec_normalized, source_tax_id, display_name
        HAVING SUM(value) > 0
        """,
        params,
    ).fetchall()
    return [(str(ec), str(display_name), float(value)) for ec, display_name, value in rows]


def build_graph_from_duckdb(
    *,
    names: list[str],
    tax_level: str,
    selected_ann_cat: dict | str,
    selected_taxon: dict,
) -> dict:
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")

    validate_tax_level(tax_level)

    pathway_filter = require_graph_pathway_filter(selected_ann_cat)
    taxon_filter = normalise_taxon_filter(selected_taxon)
    pathway_name = pathway_filter["name"]
    sample_id = sample_id_from_names(names)
    db_file = db_path(sample_id)
    if not db_file.exists():
        raise FileNotFoundError(f"sample not found: {sample_id}")

    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "mart_rpkm_enriched" not in tables:
            raise RuntimeError(
                f"mart_rpkm_enriched not materialized for sample: {sample_id}"
            )

        where_sql, params = _enriched_where(
            pathway_name=pathway_name,
            taxon_filter=taxon_filter,
        )
        _materialize_filtered_ids(conn, where_sql=where_sql, params=params)
        ec_rows = _fetch_ec_metadata(conn, where_sql=where_sql, params=params)
        materialize_tax_metadata_from_ids(
            conn,
            tax_level=tax_level,
            ids_table=FILTERED_IDS_TABLE,
            output_table=TAX_METADATA_TABLE,
        )
        tax_rows = read_tax_metadata_rows(conn, table=TAX_METADATA_TABLE)
        triples = _fetch_display_name_triples(conn, where_sql=where_sql, params=params)

        return build_graph_matrix(
            triples=triples,
            ec_rows=ec_rows,
            tax_rows=tax_rows,
        )
    finally:
        conn.close()
