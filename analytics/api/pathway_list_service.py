from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import (
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
    validate_tax_level,
)
from api.rollup_query import PATHWAY_LABEL_SQL, build_filtered_rollup_rows

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
) -> list[str]:
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

        label_sql = PATHWAY_LABEL_SQL.replace("t.", "cf.")
        rows = conn.execute(
            f"""
            SELECT
                {label_sql} AS display_label
            FROM filtered_rollup_rows cf
            WHERE cf.requested_rank = ?
              AND cf.pathway_level = 'pathway'
            GROUP BY cf.pathway_key, {label_sql}
            HAVING SUM(cf.value) > 0
            ORDER BY display_label ASC
            """,
            [tax_level],
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()
