from __future__ import annotations

import duckdb

from api.config import db_path
from api.filters import (
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
    validate_tax_level,
)
from api.query_enriched import (
    ann_filter_where_sql,
    canonical_pathway_label_sql,
    resolve_tax_label_sql,
    taxon_filter_where_sql,
)
from api.schemas import OverviewVector, PathwayListResponse
from api.tax_lineage_order import tax_cat_order_for_ids_table


def build_pathway_list_from_duckdb(
    *,
    names: list[str],
    tax_level: str,
    selected_ann_cat,
    selected_taxon,
) -> PathwayListResponse:
    if len(names) == 0:
        raise ValueError("names must contain at least one sample")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")

    validate_tax_level(tax_level)
    ann_filter = normalise_ann_filter(selected_ann_cat, "pathway")
    if ann_filter is None:
        raise ValueError("selected_ann_cat is required")
    taxon_filter = normalise_taxon_filter(selected_taxon)

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

        ann_sql, ann_params = ann_filter_where_sql(ann_filter, "pathway")
        tax_sql, tax_params = taxon_filter_where_sql(taxon_filter)
        where_sql = f"({ann_sql}) AND ({tax_sql})"
        params = ann_params + tax_params

        pathway_label = canonical_pathway_label_sql("pathway")
        tax_label = resolve_tax_label_sql(tax_level)

        pathway_rows = conn.execute(
            f"""
            SELECT {pathway_label} AS display_label
            FROM mart_rpkm_enriched
            WHERE {where_sql}
            GROUP BY pathway_id, {pathway_label}
            ORDER BY display_label ASC
            """,
            params,
        ).fetchall()
        pathway_names = [r[0] for r in pathway_rows]

        conn.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE pathway_tax_ids AS
            SELECT DISTINCT source_tax_id
            FROM mart_rpkm_enriched
            WHERE {where_sql}
            """,
            params,
        )
        tax_cat_order = tax_cat_order_for_ids_table(
            conn, tax_level=tax_level, ids_table="pathway_tax_ids"
        )

        breakdown_rows = conn.execute(
            f"""
            SELECT
              {pathway_label} AS display_label,
              {tax_label} AS resolved_tax_label,
              SUM(value) AS value
            FROM mart_rpkm_enriched
            WHERE {where_sql}
            GROUP BY pathway_id, {pathway_label}, {tax_label}
            ORDER BY display_label ASC
            """,
            params,
        ).fetchall()

        by_pathway: dict[str, dict[str, float]] = {}
        for label, tax_label_val, value in breakdown_rows:
            by_pathway.setdefault(label, {})
            by_pathway[label][tax_label_val] = by_pathway[label].get(
                tax_label_val, 0.0
            ) + float(value)

        breakdowns: dict[str, OverviewVector] = {}
        for pathway in pathway_names:
            totals = by_pathway.get(pathway, {})
            index = [cat for cat in tax_cat_order if totals.get(cat, 0) > 0]
            counts = [totals[cat] for cat in index]
            breakdowns[pathway] = OverviewVector(index=index, counts=counts)

        return PathwayListResponse(pathways=pathway_names, breakdowns=breakdowns)
    finally:
        conn.close()
