from __future__ import annotations

import duckdb
import pytest

from api.tax_lineage_order import dedupe_preserve_order, tax_cat_order_from_metadata_rows


def test_dedupe_preserve_order():
    assert dedupe_preserve_order(["B", "A", "B", "C", "A"]) == ["B", "A", "C"]


def test_tax_cat_order_from_metadata_rows():
    rows = [
        {"display_name": "tax-2", "tax_map_value": "Firmicutes"},
        {"display_name": "tax-1", "tax_map_value": "Actinomycetota"},
        {"display_name": "tax-3", "tax_map_value": "Firmicutes"},
    ]
    assert tax_cat_order_from_metadata_rows(rows) == ["Firmicutes", "Actinomycetota"]
