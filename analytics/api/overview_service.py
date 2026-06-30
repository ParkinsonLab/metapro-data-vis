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


def _fetch_counts_data(conn) -> OverviewVector:
    raise NotImplementedError


def _fetch_ann_data(conn) -> OverviewVector:
    raise NotImplementedError
