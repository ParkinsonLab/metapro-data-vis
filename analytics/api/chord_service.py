from __future__ import annotations

from pathlib import Path

import duckdb

from api.chord_matrix import build_chord_matrix
from api.filters import validate_ann_level, validate_tax_level
from api.rollup_query import PATHWAY_LABEL_SQL, build_filtered_rollup_rows

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _fetch_tax_order(conn, tax_level: str, ann_level: str) -> list[str]:
    if not BRIDGE_TAX_PATH.exists():
        return []

    conn.execute(
        f"CREATE TEMP TABLE bridge_tax AS "
        f"SELECT source_tax_id, requested_rank, resolved_tax_label "
        f"FROM read_parquet('{BRIDGE_TAX_PATH.as_posix()}')"
    )
    conn.execute(
        """
        CREATE TEMP TABLE rank_totals AS
        SELECT requested_rank, resolved_tax_label, SUM(value) AS total
        FROM filtered_rollup_rows
        GROUP BY requested_rank, resolved_tax_label
        """
    )
    conn.execute(
        f"""
        CREATE TEMP TABLE tax_label_totals_long AS
        SELECT
            d.display_label,
            b.requested_rank AS anc_rank,
            rt.total AS anc_total
        FROM (
            SELECT DISTINCT source_tax_id, resolved_tax_label AS display_label
            FROM filtered_rollup_rows
            WHERE requested_rank = ?
              AND pathway_level = ?
        ) d
        JOIN bridge_tax b ON b.source_tax_id = d.source_tax_id
        JOIN rank_totals rt
          ON rt.requested_rank = b.requested_rank
         AND rt.resolved_tax_label = b.resolved_tax_label
        """,
        [tax_level, ann_level],
    )
    rows = conn.execute(
        """
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
    ).fetchall()
    return [r[0] for r in rows]


def _fetch_ann_order(conn, tax_level: str, ann_level: str) -> list[str] | None:
    if ann_level == "pathway_node":
        return None

    if not BRIDGE_EC_PATH.exists():
        return None

    conn.execute(
        """
        CREATE TEMP TABLE ann_level_totals AS
        SELECT pathway_level, """
        + PATHWAY_LABEL_SQL.replace("t.", "cf.")
        + """ AS ann_label, SUM(value) AS total
        FROM filtered_rollup_rows cf
        GROUP BY pathway_level, """
        + PATHWAY_LABEL_SQL.replace("t.", "cf.")
    )

    label_sql = PATHWAY_LABEL_SQL.replace("t.", "cf.")

    if ann_level == "superpathway":
        conn.execute(
            f"""
            CREATE TEMP TABLE ann_label_totals_long AS
            SELECT d.display_label, 'superpathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {label_sql} AS display_label
                FROM filtered_rollup_rows cf
                WHERE cf.pathway_level = 'superpathway'
                  AND cf.requested_rank = ?
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'superpathway' AND lt.ann_label = d.display_label
            """,
            [tax_level],
        )
    elif ann_level == "pathway":
        conn.execute(
            f"""
            CREATE TEMP TABLE ann_label_totals_long AS
            SELECT d.display_label, 'superpathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {label_sql} AS display_label, b.superpathway_name
                FROM filtered_rollup_rows cf
                LEFT JOIN bridge_ec b ON cf.ec_normalized = b.ec_normalized
                WHERE cf.pathway_level = 'pathway' AND cf.requested_rank = ?
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'superpathway' AND lt.ann_label = d.superpathway_name
            UNION ALL
            SELECT d.display_label, 'pathway' AS anc_level, lt.total AS anc_total
            FROM (
                SELECT DISTINCT {label_sql} AS display_label
                FROM filtered_rollup_rows cf
                WHERE cf.pathway_level = 'pathway' AND cf.requested_rank = ?
            ) d
            JOIN ann_level_totals lt
              ON lt.pathway_level = 'pathway' AND lt.ann_label = d.display_label
            """,
            [tax_level, tax_level],
        )
    else:
        return None

    rows = conn.execute(
        """
        SELECT display_label
        FROM (
            SELECT *
            FROM ann_label_totals_long
            PIVOT (MAX(anc_total) FOR anc_level IN ('superpathway', 'pathway'))
        )
        ORDER BY superpathway DESC NULLS LAST, pathway DESC NULLS LAST, display_label
        """
    ).fetchall()
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
        if "int_tax_rollup_resolved" not in tables:
            raise RuntimeError(
                f"int_tax_rollup_resolved not materialized for sample: {sample_id}"
            )

        build_filtered_rollup_rows(
            conn,
            tax_level=tax_level,
            ann_level=ann_level,
            ann_filter=ann_filter,
            taxon_filter=taxon_filter,
        )

        pair_sql = f"""
            SELECT
                {PATHWAY_LABEL_SQL} AS pathway_label,
                t.resolved_tax_label,
                SUM(t.value) AS value
            FROM filtered_rollup_rows t
            WHERE t.requested_rank = ?
              AND t.pathway_level = ?
            GROUP BY t.pathway_key, t.resolved_tax_id,
                     {PATHWAY_LABEL_SQL},
                     t.resolved_tax_label
            HAVING SUM(t.value) > 0
        """
        rows = conn.execute(pair_sql, [tax_level, ann_level]).fetchall()
        pairs = [(r[0], r[1], float(r[2])) for r in rows]
        tax_order = _fetch_tax_order(conn, tax_level, ann_level)
        ann_order = _fetch_ann_order(conn, tax_level, ann_level)
        return build_chord_matrix(
            pairs, tax_order=tax_order or None, ann_order=ann_order
        )
    finally:
        conn.close()
