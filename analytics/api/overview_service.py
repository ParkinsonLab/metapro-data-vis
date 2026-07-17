from __future__ import annotations

import duckdb

from api.config import db_path
from api.filters import sample_id_from_names
from api.query_enriched import canonical_pathway_label_sql, resolve_tax_label_sql
from api.schemas import OverviewResponse, OverviewVector

_MAPPED_PATHWAY_PREDICATE = (
    "ec_normalized != '0.0.0.0' AND pathway_id IS NOT NULL"
)


def _overview_row_predicate() -> str:
    phylum_label = resolve_tax_label_sql("phylum")
    return f"{_MAPPED_PATHWAY_PREDICATE} AND {phylum_label} != 'Unclassified'"


def build_overview_from_duckdb(*, names: list[str]) -> OverviewResponse:
    if len(names) == 0:
        raise ValueError("names must contain at least one sample")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on duckdb backend")

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
        counts_data = _fetch_counts_data(conn)
        ann_data = _fetch_ann_data(conn)
        return OverviewResponse(counts_data=counts_data, ann_data=ann_data)
    finally:
        conn.close()


def _rows_to_vector(rows: list[tuple[str, float]]) -> OverviewVector:
    return OverviewVector(
        index=[r[0] for r in rows],
        counts=[float(r[1]) for r in rows],
    )


def _fetch_counts_data(conn) -> OverviewVector:
    phylum_label = resolve_tax_label_sql("phylum")
    row_predicate = _overview_row_predicate()
    rows = conn.execute(
        f"""
        WITH labeled AS (
            SELECT
                {phylum_label} AS phylum_label,
                kingdom_label,
                value
            FROM mart_rpkm_enriched
            WHERE {row_predicate}
        )
        SELECT
            phylum_label,
            SUM(value) AS total
        FROM labeled
        GROUP BY phylum_label
        ORDER BY COALESCE(MIN(kingdom_label), ''), phylum_label ASC
        """
    ).fetchall()
    return _rows_to_vector(rows)


def _fetch_ann_data(conn) -> OverviewVector:
    pathway_label = canonical_pathway_label_sql("superpathway")
    row_predicate = _overview_row_predicate()
    rows = conn.execute(
        f"""
        WITH labeled AS (
            SELECT
                {pathway_label} AS label,
                value
            FROM mart_rpkm_enriched
            WHERE {row_predicate}
        )
        SELECT label, SUM(value) AS total
        FROM labeled
        GROUP BY label
        ORDER BY label ASC
        """
    ).fetchall()
    return _rows_to_vector(rows)
