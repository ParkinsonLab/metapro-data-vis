from __future__ import annotations

import duckdb
import pytest

from testing.enriched_query import count_rollup_cells, fetch_rollup_cell
from testing.fake_rpkm_fixture import (
    bridges_available,
    load_pipeline_expectations,
    skip_reason,
)

pytestmark = pytest.mark.skipif(not bridges_available(), reason=skip_reason())

if bridges_available():
    _expectations = load_pipeline_expectations()
    _fixture = _expectations["fixture"]
    _rollup_rows = _expectations["rollup_grid"]
else:
    _fixture = {"focal_ec": "", "focal_tax_id": 0}
    _rollup_rows = []


@pytest.mark.parametrize(
    "row",
    _rollup_rows,
    ids=lambda r: f"{r['requested_rank']}-{r['pathway_level']}",
)
def test_rollup_grid_row(row, fake_rpkm_db):
    conn = duckdb.connect(fake_rpkm_db, read_only=True)
    try:
        result = fetch_rollup_cell(
            conn,
            ec=_fixture["focal_ec"],
            tax_id=_fixture["focal_tax_id"],
            tax_level=row["requested_rank"],
            ann_level=row["pathway_level"],
        )
    finally:
        conn.close()

    assert result is not None, f"missing row: {row}"
    pathway_label, resolved_tax_label, value = result
    assert pathway_label == row["pathway_label"]
    assert resolved_tax_label == row["resolved_tax_label"]
    assert float(value) == pytest.approx(float(row["value"]))


def test_rollup_grid_row_count(fake_rpkm_db):
    conn = duckdb.connect(fake_rpkm_db, read_only=True)
    try:
        n = count_rollup_cells(
            conn,
            ec=_fixture["focal_ec"],
            tax_id=_fixture["focal_tax_id"],
        )
    finally:
        conn.close()
    assert n == 21
