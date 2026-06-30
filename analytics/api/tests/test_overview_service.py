import pytest

from api.overview_service import build_overview_from_duckdb


def test_overview_rejects_empty_names():
    with pytest.raises(ValueError, match="at least one sample"):
        build_overview_from_duckdb(names=[])


def test_overview_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_overview_from_duckdb(names=["a.tsv", "b.tsv"])
