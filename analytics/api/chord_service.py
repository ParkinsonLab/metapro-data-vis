from __future__ import annotations

from pathlib import Path

import duckdb

from api.chord_matrix import build_chord_matrix
from api.filters import ann_levels_up_to, ranks_up_to, validate_ann_level, validate_tax_level

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"

PATHWAY_LABEL_SQL = (
    "CASE "
    "WHEN t.ec_normalized = '0.0.0.0' OR t.pathway_key IS NULL THEN 'Unmapped EC' "
    "ELSE COALESCE(t.pathway_label, t.ec_normalized) "
    "END"
)


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


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
        FROM chord_prefix_rows
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
            FROM chord_prefix_rows
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


def _ann_predicate(ann_filter: dict[str, str] | None, ann_level: str) -> tuple[str, list]:
    if ann_filter is None:
        return "TRUE", []
    level, name = ann_filter["level"], ann_filter["name"]
    if ann_level == "superpathway":
        return f"{PATHWAY_LABEL_SQL} = ?", [name]
    if ann_level == "pathway_node":
        if level == "pathway":
            return (
                "t.pathway_key IN ("
                "  SELECT pathway_node_id FROM bridge_ec WHERE pathway_name = ?"
                ")",
                [name],
            )
        return (
            "t.pathway_key IN ("
            "  SELECT pathway_node_id FROM bridge_ec WHERE superpathway_name = ?"
            ")",
            [name],
        )
    if level == "pathway":
        return (
            "t.pathway_key IN ("
            "  SELECT CAST(pathway_id AS VARCHAR) FROM bridge_ec "
            "  WHERE pathway_name = ?"
            ")",
            [name],
        )
    return (
        "t.pathway_key IN ("
        "  SELECT CAST(pathway_id AS VARCHAR) FROM bridge_ec "
        "  WHERE superpathway_name = ?"
        ")",
        [name],
    )


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

        rank_in = _sql_in_list(ranks_up_to(tax_level))
        level_in = _sql_in_list(ann_levels_up_to(ann_level))

        if BRIDGE_EC_PATH.exists():
            conn.execute(
                f"CREATE TEMP TABLE bridge_ec AS "
                f"SELECT * FROM read_parquet('{BRIDGE_EC_PATH.as_posix()}')"
            )

        tax_subquery = "TRUE"
        params: list = []
        if taxon_filter:
            tax_subquery = (
                "t.source_tax_id IN ("
                "  SELECT DISTINCT source_tax_id FROM int_tax_rollup_resolved"
                "  WHERE requested_rank = ? AND resolved_tax_label = ?"
                ")"
            )
            params.extend([taxon_filter["level"], taxon_filter["name"]])

        ann_sql, ann_params = _ann_predicate(ann_filter, ann_level)

        conn.execute(
            f"""
            CREATE TEMP TABLE chord_prefix_rows AS
            SELECT
                t.source_tax_id,
                t.requested_rank,
                t.resolved_tax_label,
                t.resolved_tax_id,
                t.pathway_key,
                t.pathway_level,
                t.pathway_label,
                t.ec_normalized,
                t.value
            FROM int_tax_rollup_resolved t
            WHERE t.requested_rank IN ({rank_in})
              AND t.pathway_level IN ({level_in})
              AND ({tax_subquery})
              AND ({ann_sql})
            """,
            params + ann_params,
        )

        pair_sql = f"""
            SELECT
                {PATHWAY_LABEL_SQL} AS pathway_label,
                t.resolved_tax_label,
                SUM(t.value) AS value
            FROM chord_prefix_rows t
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
        return build_chord_matrix(pairs, tax_order=tax_order or None)
    finally:
        conn.close()
