import pytest

from api.overview_service import build_overview_from_duckdb
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    bridges_available,
    load_overview_expectations,
    skip_reason,
)


def test_overview_rejects_empty_names():
    with pytest.raises(ValueError, match="at least one sample"):
        build_overview_from_duckdb(names=[])


def test_overview_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_overview_from_duckdb(names=["a.tsv", "b.tsv"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_overview_from_duckdb_shape(fake_rpkm_db):
    out = build_overview_from_duckdb(names=[f"{SAMPLE_ID}.tsv"])
    assert len(out.counts_data.index) == len(out.counts_data.counts)
    assert len(out.ann_data.index) == len(out.ann_data.counts)
    assert len(out.counts_data.index) > 0
    assert len(out.ann_data.index) > 0


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_overview_vectors_match_golden(fake_rpkm_db):
    expected = load_overview_expectations()["overview"]
    out = build_overview_from_duckdb(names=[f"{SAMPLE_ID}.tsv"])
    assert out.counts_data.model_dump() == expected["counts_data"]
    assert out.ann_data.model_dump() == expected["ann_data"]
    assert "Unmapped EC" not in out.ann_data.index
