from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import (
    normalise_taxon_filter,
    sample_id_from_names,
    validate_tax_level,
)
from api.network_assembly import (
    apply_layout,
    attach_pies_to_nodes,
    build_category_colors,
    embed_edges,
)
from api.query_enriched import resolve_tax_label_sql, taxon_filter_where_sql
from api.tax_lineage_order import (
    materialize_tax_metadata_from_ids,
    read_tax_metadata_rows,
    tax_cat_order_from_metadata_rows,
)

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REPO_ROOT = ANALYTICS_DIR.parent
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"
PATHWAY_SUPERPATHWAYS = RAW_PARQUET_DIR / "pathway_superpathways.parquet"
PATHWAY_NODES = RAW_PARQUET_DIR / "pathway_nodes.parquet"
PATHWAY_EDGES = RAW_PARQUET_DIR / "pathway_edges.parquet"
FILTERED_IDS_TABLE = "network_tax_ids"
TAX_METADATA_TABLE = "network_tax_metadata"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


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


def _has_matching_values(
    conn: duckdb.DuckDBPyConnection,
    *,
    where_sql: str,
    params: list,
) -> bool:
    row = conn.execute(
        f"SELECT COUNT(*) FROM mart_rpkm_enriched WHERE {where_sql}",
        params,
    ).fetchone()
    return bool(row and row[0] > 0)


def _fetch_ec_values_by_tax_cat(
    conn: duckdb.DuckDBPyConnection,
    *,
    where_sql: str,
    params: list,
    tax_level: str,
    tax_cats: list[str],
) -> dict[str, list[float]]:
    if not tax_cats:
        return {}
    tax_label = resolve_tax_label_sql(tax_level)
    value_exprs = ", ".join(
        "COALESCE(SUM(CASE WHEN tax_map_value = ? THEN value END), 0.0)"
        for _ in tax_cats
    )
    rows = conn.execute(
        f"""
        SELECT ec_normalized, [{value_exprs}]
        FROM (
            SELECT
                ec_normalized,
                {tax_label} AS tax_map_value,
                SUM(value) AS value
            FROM mart_rpkm_enriched
            WHERE {where_sql}
            GROUP BY ec_normalized, {tax_label}
        ) aggregated
        GROUP BY ec_normalized
        """,
        tax_cats + params,
    ).fetchall()
    return {str(ec): [float(v) for v in values] for ec, values in rows}


def _require_pathway_parquet() -> None:
    for path in (PATHWAY_SUPERPATHWAYS, PATHWAY_NODES, PATHWAY_EDGES):
        if not path.exists():
            raise FileNotFoundError(f"reference parquet missing: {path}")


def load_static_graph(pathway_name: str) -> dict:
    _require_pathway_parquet()
    conn = duckdb.connect()
    try:
        psp = PATHWAY_SUPERPATHWAYS.as_posix()
        nodes_p = PATHWAY_NODES.as_posix()
        edges_p = PATHWAY_EDGES.as_posix()
        row = conn.execute(
            f"SELECT id FROM read_parquet('{psp}') WHERE name = ?",
            [pathway_name],
        ).fetchone()
        if row is None:
            return {"nodes": [], "edges": []}
        pathway_id = row[0]
        nodes = conn.execute(
            f"""
            SELECT id, name AS label, x, y, type
            FROM read_parquet('{nodes_p}')
            WHERE pathway = ?
            """,
            [pathway_id],
        ).fetchdf()
        edges = conn.execute(
            f"""
            SELECT source, target
            FROM read_parquet('{edges_p}')
            WHERE pathway = ?
            """,
            [pathway_id],
        ).fetchdf()
        return {
            "nodes": nodes.to_dict(orient="records"),
            "edges": edges.to_dict(orient="records"),
        }
    finally:
        conn.close()


def build_network_from_duckdb(
    *,
    names: list[str],
    tax_level: str,
    selected_taxon: dict,
    pathway_name: str,
    width: float,
    height: float,
) -> dict:
    if not pathway_name or not pathway_name.strip():
        raise ValueError("pathway_name is required")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")

    validate_tax_level(tax_level)
    taxon_filter = normalise_taxon_filter(selected_taxon)
    pathway_name = pathway_name.strip()

    static = load_static_graph(pathway_name)
    if not static["nodes"]:
        return {"nodes": [], "edges": [], "colors": {}}

    sample_id = sample_id_from_names(names)
    db_file = _db_path(sample_id)
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
        nodes = static["nodes"]
        edges = static["edges"]

        if not _has_matching_values(conn, where_sql=where_sql, params=params):
            nodes = apply_layout(nodes, width=width, height=height)
            nodes = attach_pies_to_nodes(nodes, tax_cats=[], ec_values={})
            edges = embed_edges(edges, nodes)
            return {"nodes": nodes, "edges": edges, "colors": {}}

        _materialize_filtered_ids(conn, where_sql=where_sql, params=params)
        materialize_tax_metadata_from_ids(
            conn,
            tax_level=tax_level,
            ids_table=FILTERED_IDS_TABLE,
            output_table=TAX_METADATA_TABLE,
        )
        tax_cats = tax_cat_order_from_metadata_rows(
            read_tax_metadata_rows(conn, table=TAX_METADATA_TABLE)
        )
        ec_values = _fetch_ec_values_by_tax_cat(
            conn,
            where_sql=where_sql,
            params=params,
            tax_level=tax_level,
            tax_cats=tax_cats,
        )

        nodes = apply_layout(nodes, width=width, height=height)
        nodes = attach_pies_to_nodes(nodes, tax_cats=tax_cats, ec_values=ec_values)
        edges = embed_edges(edges, nodes)
        colors = build_category_colors(tax_cats)

        return {"nodes": nodes, "edges": edges, "colors": colors}
    finally:
        conn.close()
