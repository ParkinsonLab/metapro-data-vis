from __future__ import annotations

from pathlib import Path

import duckdb

from api.chord_matrix import build_chord_matrix
from api.filters import validate_ann_level, validate_tax_level

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


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


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

        if BRIDGE_EC_PATH.exists():
            conn.execute(
                f"CREATE TEMP TABLE bridge_ec AS "
                f"SELECT * FROM read_parquet('{BRIDGE_EC_PATH.as_posix()}')"
            )

        tax_subquery = "TRUE"
        params: list = [tax_level, ann_level]
        if taxon_filter:
            tax_subquery = (
                "t.source_tax_id IN ("
                "  SELECT DISTINCT source_tax_id FROM int_tax_rollup_resolved"
                "  WHERE requested_rank = ? AND resolved_tax_label = ?"
                ")"
            )
            params.extend([taxon_filter["level"], taxon_filter["name"]])

        ann_sql, ann_params = _ann_predicate(ann_filter, ann_level)

        sql = f"""
            SELECT
                {PATHWAY_LABEL_SQL} AS pathway_label,
                t.resolved_tax_label AS resolved_tax_label,
                SUM(t.value) AS value
            FROM int_tax_rollup_resolved t
            WHERE t.requested_rank = ?
              AND t.pathway_level = ?
              AND ({tax_subquery})
              AND ({ann_sql})
            GROUP BY t.pathway_key, t.resolved_tax_id,
                     {PATHWAY_LABEL_SQL},
                     t.resolved_tax_label
            HAVING SUM(t.value) > 0
        """
        rows = conn.execute(sql, params + ann_params).fetchall()
    finally:
        conn.close()

    pairs = [(r[0], r[1], float(r[2])) for r in rows]
    return build_chord_matrix(pairs)
