from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import ann_levels_from_root_to, ranks_from_root_to

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"

PATHWAY_LABEL_SQL = (
    "CASE "
    "WHEN t.ec_normalized = '0.0.0.0' OR t.pathway_key IS NULL THEN 'Unmapped EC' "
    "ELSE COALESCE(t.pathway_label, t.ec_normalized) "
    "END"
)


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


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


def build_filtered_rollup_rows(
    conn: duckdb.DuckDBPyConnection,
    *,
    tax_level: str,
    ann_level: str,
    ann_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
) -> None:
    rank_in = _sql_in_list(ranks_from_root_to(tax_level))
    level_in = _sql_in_list(ann_levels_from_root_to(ann_level))

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
        CREATE TEMP TABLE filtered_rollup_rows AS
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
