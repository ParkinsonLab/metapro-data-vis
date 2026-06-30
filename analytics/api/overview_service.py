from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import sample_id_from_names
from api.schemas import OverviewResponse, OverviewVector

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def build_overview_from_duckdb(*, names: list[str]) -> OverviewResponse:
    if len(names) == 0:
        raise ValueError("names must contain at least one sample")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on duckdb backend")

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
    if not BRIDGE_TAX_PATH.exists():
        raise FileNotFoundError(f"bridge parquet missing: {BRIDGE_TAX_PATH}")
    bridge = BRIDGE_TAX_PATH.as_posix()
    rows = conn.execute(
        f"""
        WITH phylum_totals AS (
            SELECT resolved_tax_label AS phylum_label, SUM(value) AS total
            FROM int_tax_rollup_resolved
            WHERE requested_rank = 'phylum'
              AND pathway_level = 'superpathway'
            GROUP BY resolved_tax_label
        ),
        phylum_map AS (
            SELECT DISTINCT source_tax_id, resolved_tax_label AS phylum_label
            FROM read_parquet('{bridge}')
            WHERE requested_rank = 'phylum'
        ),
        kingdom_map AS (
            SELECT source_tax_id, resolved_tax_label AS kingdom_label
            FROM read_parquet('{bridge}')
            WHERE requested_rank = 'kingdom'
        ),
        phylum_to_kingdom AS (
            SELECT p.phylum_label, MIN(k.kingdom_label) AS kingdom_label
            FROM phylum_map p
            JOIN kingdom_map k USING (source_tax_id)
            GROUP BY p.phylum_label
        )
        SELECT p.phylum_label, p.total
        FROM phylum_totals p
        LEFT JOIN phylum_to_kingdom k ON k.phylum_label = p.phylum_label
        ORDER BY COALESCE(k.kingdom_label, ''), p.phylum_label ASC
        """
    ).fetchall()
    return _rows_to_vector(rows)


def _fetch_ann_data(conn) -> OverviewVector:
    rows = conn.execute(
        """
        SELECT
            CASE WHEN pathway_key IS NULL THEN 'Unmapped EC' ELSE pathway_label END AS label,
            SUM(value) AS total
        FROM int_tax_rollup_resolved
        WHERE requested_rank = 'phylum'
          AND pathway_level = 'superpathway'
        GROUP BY 1
        ORDER BY label ASC
        """
    ).fetchall()
    return _rows_to_vector(rows)
