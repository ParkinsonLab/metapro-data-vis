from __future__ import annotations

import duckdb
import pytest

from api.tax_lineage_order import (
    dedupe_preserve_order,
    materialize_tax_metadata_from_ids,
    read_tax_metadata_rows,
    tax_cat_order_from_metadata_rows,
)
from testing.fake_rpkm_fixture import bridges_available, skip_reason


def test_dedupe_preserve_order():
    assert dedupe_preserve_order(["B", "A", "B", "C", "A"]) == ["B", "A", "C"]


def test_tax_cat_order_from_metadata_rows():
    rows = [
        {"display_name": "tax-2", "tax_map_value": "Firmicutes"},
        {"display_name": "tax-1", "tax_map_value": "Actinomycetota"},
        {"display_name": "tax-3", "tax_map_value": "Firmicutes"},
    ]
    assert tax_cat_order_from_metadata_rows(rows) == ["Firmicutes", "Actinomycetota"]


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_read_tax_metadata_rows_preserves_lineage_order(fake_rpkm_db):
    conn = duckdb.connect(fake_rpkm_db, read_only=True)
    try:
        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE ids AS
            SELECT DISTINCT source_tax_id FROM int_rpkm_by_ec_tax
            """
        )
        materialize_tax_metadata_from_ids(
            conn, tax_level="phylum", ids_table="ids", output_table="tax_lineage_metadata"
        )
        ordered = conn.execute(
            """
            SELECT display_name, COALESCE(tax_map_value, '')
            FROM tax_lineage_metadata
            ORDER BY kingdom, phylum, class, "order", family, genus, species, display_name
            """
        ).fetchall()
        read_back = read_tax_metadata_rows(conn, table="tax_lineage_metadata")
        assert read_back == [
            {"display_name": name, "tax_map_value": tax_map_value}
            for name, tax_map_value in ordered
        ]
    finally:
        conn.close()
