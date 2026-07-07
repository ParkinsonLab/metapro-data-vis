from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import (
    normalise_taxon_filter,
    require_graph_pathway_filter,
    sample_id_from_names,
    validate_tax_level,
)
from api.ec_tax_triples import materialize_filtered_triples
from api.graph_matrix import build_graph_matrix
from api.tax_lineage_order import (
    materialize_tax_metadata_from_ids,
    read_tax_metadata_rows,
)

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
TAX_METADATA_TABLE = "graph_tax_metadata"
FILTERED_TRIPLES_TABLE = "filtered_triples"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _fetch_ec_metadata(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT ec_normalized
        FROM (SELECT DISTINCT ec_normalized FROM {FILTERED_TRIPLES_TABLE}) t
        ORDER BY
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 1) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 2) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 3) AS INTEGER), 2147483647),
            COALESCE(TRY_CAST(split_part(ec_normalized, '.', 4) AS INTEGER), 2147483647),
            ec_normalized
        """
    ).fetchall()
    return [{"ec_normalized": ec} for (ec,) in rows]


def _fetch_display_name_triples(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, float]]:
    rows = conn.execute(
        f"""
        SELECT t.ec_normalized, m.display_name, t.value
        FROM {FILTERED_TRIPLES_TABLE} t
        INNER JOIN {TAX_METADATA_TABLE} m USING (source_tax_id)
        """
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

        materialize_filtered_triples(
            conn,
            pathway_filter=pathway_filter,
            taxon_filter=taxon_filter,
        )
        ec_rows = _fetch_ec_metadata(conn)
        materialize_tax_metadata_from_ids(
            conn,
            tax_level=tax_level,
            ids_table=FILTERED_TRIPLES_TABLE,
            output_table=TAX_METADATA_TABLE,
        )
        tax_rows = read_tax_metadata_rows(conn, table=TAX_METADATA_TABLE)
        triples = _fetch_display_name_triples(conn)

        return build_graph_matrix(
            triples=triples,
            ec_rows=ec_rows,
            tax_rows=tax_rows,
        )
    finally:
        conn.close()
