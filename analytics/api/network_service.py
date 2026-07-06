from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import (
    TAX_RANK_ORDER,
    normalise_taxon_filter,
    sample_id_from_names,
    validate_tax_level,
)
from api.network_assembly import (
    apply_layout,
    attach_pies_to_nodes,
    build_category_colors,
    dedupe_preserve_order,
    embed_edges,
)

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"
REPO_ROOT = ANALYTICS_DIR.parent
NAMES_PATH = REPO_ROOT / "resources/db/parquet/names.parquet"
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"
PATHWAY_SUPERPATHWAYS = RAW_PARQUET_DIR / "pathway_superpathways.parquet"
PATHWAY_NODES = RAW_PARQUET_DIR / "pathway_nodes.parquet"
PATHWAY_EDGES = RAW_PARQUET_DIR / "pathway_edges.parquet"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _lineage_order_by_sql() -> str:
    parts = list(TAX_RANK_ORDER) + ["display_name"]
    return ", ".join(f'"{rank}"' if rank == "order" else rank for rank in parts)


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


def _materialize_filtered_triples(
    conn: duckdb.DuckDBPyConnection,
    *,
    pathway_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
) -> None:
    if pathway_filter is not None:
        _ensure_bridge_ec(conn)
    pathway_clause, pathway_params = _pathway_exists_clause(pathway_filter)
    tax_clause, tax_params = _taxon_exists_clause(taxon_filter)
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE filtered_triples AS
        SELECT r.ec_normalized, r.source_tax_id, r.value
        FROM int_rpkm_by_ec_tax r
        WHERE r.value > 0
          AND ({pathway_clause})
          AND ({tax_clause})
        """,
        pathway_params + tax_params,
    )


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
        CREATE OR REPLACE TEMP TABLE network_tax_metadata AS
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
        SELECT source_tax_id, COALESCE(tax_map_value, '')
        FROM network_tax_metadata
        """
    ).fetchall()
    return [
        {"source_tax_id": source_tax_id, "tax_map_value": tax_map_value}
        for source_tax_id, tax_map_value in rows
    ]


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
        if "int_rpkm_by_ec_tax" not in tables:
            raise RuntimeError(
                f"int_rpkm_by_ec_tax not materialized for sample: {sample_id}"
            )

        _materialize_filtered_triples(
            conn,
            pathway_filter={"name": pathway_name},
            taxon_filter=taxon_filter,
        )

        triple_count = conn.execute("SELECT COUNT(*) FROM filtered_triples").fetchone()[0]
        nodes = static["nodes"]
        edges = static["edges"]

        if triple_count == 0:
            nodes = apply_layout(nodes, width=width, height=height)
            nodes = attach_pies_to_nodes(nodes, tax_cats=[], ec_values={})
            edges = embed_edges(edges, nodes)
            return {"nodes": nodes, "edges": edges, "colors": {}}

        _materialize_tax_metadata(conn, tax_level=tax_level)
        tax_meta = _read_tax_metadata(conn)
        tax_cats = dedupe_preserve_order([row["tax_map_value"] for row in tax_meta])

        rows = conn.execute(
            """
            SELECT t.ec_normalized, m.tax_map_value, SUM(t.value) AS value
            FROM filtered_triples t
            INNER JOIN network_tax_metadata m ON t.source_tax_id = m.source_tax_id
            GROUP BY t.ec_normalized, m.tax_map_value
            """
        ).fetchall()

        cat_idx = {cat: i for i, cat in enumerate(tax_cats)}
        ec_values: dict[str, list[float]] = {}
        for ec, tax_map_value, value in rows:
            if ec not in ec_values:
                ec_values[ec] = [0.0] * len(tax_cats)
            ec_values[ec][cat_idx[tax_map_value]] += float(value)

        nodes = apply_layout(nodes, width=width, height=height)
        nodes = attach_pies_to_nodes(nodes, tax_cats=tax_cats, ec_values=ec_values)
        edges = embed_edges(edges, nodes)
        colors = build_category_colors(tax_cats)

        return {"nodes": nodes, "edges": edges, "colors": colors}
    finally:
        conn.close()
