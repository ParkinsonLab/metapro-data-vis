from __future__ import annotations

from pathlib import Path

import duckdb

from api.ann_order import ann_labels_ordered
from api.chord_matrix import build_chord_matrix
from api.filters import validate_ann_level, validate_tax_level
from api.query_enriched import (
    ann_filter_where_sql,
    canonical_pathway_label_sql,
    resolve_tax_id_sql,
    resolve_tax_label_sql,
    taxon_filter_where_sql,
)
from api.tax_lineage_order import tax_cat_order_for_ids_table

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _enriched_where(
    *,
    ann_level: str,
    ann_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
) -> tuple[str, list]:
    ann_sql, ann_params = ann_filter_where_sql(ann_filter, ann_level)
    tax_sql, tax_params = taxon_filter_where_sql(taxon_filter)
    return f"({ann_sql}) AND ({tax_sql})", ann_params + tax_params


def build_chord_from_duckdb(
    *,
    sample_id: str,
    tax_level: str,
    ann_level: str,
    ann_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
    names: list[str] | None = None,
) -> dict:
    if names and len(names) > 1:
        raise ValueError("comparison mode not supported on duckdb backend")

    validate_tax_level(tax_level)
    validate_ann_level(ann_level)
    if ann_level == "pathway_node":
        raise ValueError("pathway_node ann_level not supported on chord")

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
            ann_level=ann_level,
            ann_filter=ann_filter,
            taxon_filter=taxon_filter,
        )
        pathway_label = canonical_pathway_label_sql(ann_level)
        tax_label = resolve_tax_label_sql(tax_level)
        tax_id = resolve_tax_id_sql(tax_level)

        pair_sql = f"""
            SELECT
                {pathway_label} AS pathway_label,
                {tax_label} AS resolved_tax_label,
                SUM(value) AS value
            FROM mart_rpkm_enriched
            WHERE {where_sql}
            GROUP BY {tax_id}, {tax_label}, {pathway_label}
            HAVING SUM(value) > 0
        """
        rows = conn.execute(pair_sql, params).fetchall()
        pairs = [(r[0], r[1], float(r[2])) for r in rows]

        conn.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE chord_tax_ids AS
            SELECT DISTINCT source_tax_id
            FROM mart_rpkm_enriched
            WHERE {where_sql}
            """,
            params,
        )
        tax_order = tax_cat_order_for_ids_table(
            conn, tax_level=tax_level, ids_table="chord_tax_ids"
        )
        ann_order = ann_labels_ordered(
            conn, ann_level=ann_level, where_sql=where_sql, params=params
        )
        return build_chord_matrix(
            pairs, tax_order=tax_order or None, ann_order=ann_order or None
        )
    finally:
        conn.close()
