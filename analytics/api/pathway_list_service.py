from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import (
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
    validate_tax_level,
)
from api.rollup_query import build_filtered_rollup_rows
from api.schemas import OverviewVector, PathwayListResponse
from api.tax_lineage_order import tax_cat_order_for_ids_table

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


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
    db_file = _db_path(sample_id)
    if not db_file.exists():
        raise FileNotFoundError(f"sample not found: {sample_id}")

    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "int_tax_rollup_resolved" not in tables:
            raise RuntimeError(
                f"int_tax_rollup_resolved not materialized for sample: {sample_id}"
            )

        build_filtered_rollup_rows(
            conn,
            tax_level=tax_level,
            ann_level="pathway",
            ann_filter=ann_filter,
            taxon_filter=taxon_filter,
        )

        pathway_rows = conn.execute(
            """
            SELECT cf.pathway_label AS display_label
            FROM filtered_rollup_rows cf
            WHERE cf.requested_rank = ?
              AND cf.pathway_level = 'pathway'
            GROUP BY cf.pathway_key, cf.pathway_label
            ORDER BY display_label ASC
            """,
            [tax_level],
        ).fetchall()
        pathway_names = [r[0] for r in pathway_rows]

        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE pathway_tax_ids AS
            SELECT DISTINCT cf.source_tax_id
            FROM filtered_rollup_rows cf
            WHERE cf.requested_rank = ?
              AND cf.pathway_level = 'pathway'
            """,
            [tax_level],
        )
        tax_cat_order = tax_cat_order_for_ids_table(
            conn, tax_level=tax_level, ids_table="pathway_tax_ids"
        )

        breakdown_rows = conn.execute(
            """
            SELECT
              cf.pathway_label AS display_label,
              cf.resolved_tax_label,
              SUM(cf.value) AS value
            FROM filtered_rollup_rows cf
            WHERE cf.requested_rank = ?
              AND cf.pathway_level = 'pathway'
            GROUP BY cf.pathway_key, cf.pathway_label, cf.resolved_tax_label
            ORDER BY display_label ASC
            """,
            [tax_level],
        ).fetchall()

        by_pathway: dict[str, dict[str, float]] = {}
        for label, tax_label, value in breakdown_rows:
            by_pathway.setdefault(label, {})
            by_pathway[label][tax_label] = by_pathway[label].get(tax_label, 0.0) + float(
                value
            )

        breakdowns: dict[str, OverviewVector] = {}
        for pathway in pathway_names:
            totals = by_pathway.get(pathway, {})
            index = [cat for cat in tax_cat_order if totals.get(cat, 0) > 0]
            counts = [totals[cat] for cat in index]
            breakdowns[pathway] = OverviewVector(index=index, counts=counts)

        return PathwayListResponse(pathways=pathway_names, breakdowns=breakdowns)
    finally:
        conn.close()
