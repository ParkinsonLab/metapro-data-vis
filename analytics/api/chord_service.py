from __future__ import annotations

from pathlib import Path

import duckdb

from api.chord_matrix import build_chord_matrix
from api.filters import TAX_RANK_ORDER, validate_ann_level, validate_tax_level
from api.query_enriched import (
    ann_filter_where_sql,
    canonical_pathway_label_sql,
    resolve_tax_id_sql,
    resolve_tax_label_sql,
    taxon_filter_where_sql,
)

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"

_LINEAGE_RANKS = TAX_RANK_ORDER
_ANN_ORDER_RANKS = ("superpathway", "pathway")


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


def _rank_totals_cte(*, filtered_alias: str = "f") -> str:
    parts: list[str] = []
    for rank in _LINEAGE_RANKS:
        col = f"{rank}_label"
        parts.append(
            f"SELECT '{rank}' AS anc_rank, {filtered_alias}.{col} AS resolved_label, "
            f"SUM({filtered_alias}.value) AS total "
            f"FROM filtered {filtered_alias} GROUP BY {filtered_alias}.{col}"
        )
    return " UNION ALL ".join(parts)


def _tax_lineage_select(tax_level: str) -> str:
    tax_label = resolve_tax_label_sql(tax_level, prefix="f")
    lineage_cols = ", ".join(
        f"MIN(f.{rank}_label) AS {rank}_label" for rank in _LINEAGE_RANKS
    )
    return f"""
        SELECT
            {tax_label} AS display_label,
            {lineage_cols}
        FROM filtered f
        GROUP BY {tax_label}
    """


def _tax_label_totals_long_sql(tax_level: str) -> str:
    joins: list[str] = []
    for rank in _LINEAGE_RANKS:
        joins.append(
            f"""
            SELECT tl.display_label, '{rank}' AS anc_rank, rt.total AS anc_total
            FROM tax_lineage tl
            JOIN rank_totals rt
              ON rt.anc_rank = '{rank}' AND rt.resolved_label = tl.{rank}_label
            """
        )
    return " UNION ALL ".join(joins)


def _fetch_tax_order(
    conn,
    *,
    tax_level: str,
    where_sql: str,
    params: list,
) -> list[str]:
    tax_lineage_sql = _tax_lineage_select(tax_level)
    sql = f"""
        WITH filtered AS (
            SELECT
                m.value,
                {", ".join(f"m.{rank}_label" for rank in _LINEAGE_RANKS)}
            FROM mart_rpkm_enriched m
            WHERE {where_sql}
        ),
        rank_totals AS (
            {_rank_totals_cte()}
        ),
        tax_lineage AS (
            {tax_lineage_sql}
        ),
        tax_label_totals_long AS (
            {_tax_label_totals_long_sql(tax_level)}
        )
        SELECT display_label
        FROM (
            SELECT *
            FROM tax_label_totals_long
            PIVOT (MAX(anc_total) FOR anc_rank IN (
                'kingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species'
            ))
        )
        ORDER BY
            kingdom DESC NULLS LAST,
            phylum DESC NULLS LAST,
            class DESC NULLS LAST,
            "order" DESC NULLS LAST,
            family DESC NULLS LAST,
            genus DESC NULLS LAST,
            species DESC NULLS LAST,
            display_label
    """
    rows = conn.execute(sql, params).fetchall()
    return [r[0] for r in rows]


def _ann_level_totals_cte(pathway_label_sql: str) -> str:
    parts = [
        f"""
        SELECT 'superpathway' AS pathway_level,
               m.superpathway_name AS ann_label,
               SUM(m.value) AS total
        FROM filtered m
        GROUP BY m.superpathway_name
        """
    ]
    if "pathway" in _ANN_ORDER_RANKS:
        parts.append(
            f"""
            SELECT 'pathway' AS pathway_level,
                   {pathway_label_sql} AS ann_label,
                   SUM(m.value) AS total
            FROM filtered m
            GROUP BY {pathway_label_sql}
            """
        )
    return " UNION ALL ".join(parts)


def _fetch_ann_order(
    conn,
    *,
    tax_level: str,
    ann_level: str,
    where_sql: str,
    params: list,
) -> list[str] | None:
    if ann_level == "pathway_node":
        return None

    pathway_label = canonical_pathway_label_sql(ann_level)

    if ann_level == "superpathway":
        ann_label_totals_long = f"""
            SELECT d.display_label, 'superpathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {pathway_label} AS display_label
                FROM filtered m
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'superpathway' AND lt.ann_label = d.display_label
        """
        pivot_cols = "('superpathway')"
        order_by = "superpathway DESC NULLS LAST, display_label"
    elif ann_level == "pathway":
        ann_label_totals_long = f"""
            SELECT d.display_label, 'superpathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {pathway_label} AS display_label, m.superpathway_name
                FROM filtered m
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'superpathway' AND lt.ann_label = d.superpathway_name
            UNION ALL
            SELECT d.display_label, 'pathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {pathway_label} AS display_label
                FROM filtered m
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'pathway' AND lt.ann_label = d.display_label
        """
        pivot_cols = "('superpathway', 'pathway')"
        order_by = "superpathway DESC NULLS LAST, pathway DESC NULLS LAST, display_label"
    else:
        return None

    pathway_label_pathway = canonical_pathway_label_sql("pathway")
    sql = f"""
        WITH filtered AS (
            SELECT
                m.value,
                m.superpathway_name,
                m.ec_normalized,
                m.pathway_id,
                m.pathway_name,
                {pathway_label} AS ann_display_label
            FROM mart_rpkm_enriched m
            WHERE {where_sql}
        ),
        ann_level_totals AS (
            {_ann_level_totals_cte(pathway_label_pathway)}
        ),
        ann_label_totals_long AS (
            {ann_label_totals_long}
        )
        SELECT display_label
        FROM (
            SELECT *
            FROM ann_label_totals_long
            PIVOT (MAX(anc_total) FOR anc_level IN {pivot_cols})
        )
        ORDER BY {order_by}
    """
    rows = conn.execute(sql, params).fetchall()
    return [r[0] for r in rows]


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
        tax_order = _fetch_tax_order(
            conn, tax_level=tax_level, where_sql=where_sql, params=params
        )
        ann_order = _fetch_ann_order(
            conn,
            tax_level=tax_level,
            ann_level=ann_level,
            where_sql=where_sql,
            params=params,
        )
        return build_chord_matrix(
            pairs, tax_order=tax_order or None, ann_order=ann_order
        )
    finally:
        conn.close()
