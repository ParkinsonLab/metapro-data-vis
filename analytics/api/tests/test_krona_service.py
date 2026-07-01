import pytest

from api.krona_service import build_krona_from_duckdb


def test_krona_rejects_empty_names():
    with pytest.raises(ValueError, match="at least one sample"):
        build_krona_from_duckdb(names=[], tax_rank="phylum", selected_taxon={})


def test_krona_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode not supported on analytics API"):
        build_krona_from_duckdb(names=["a.tsv", "b.tsv"], tax_rank="phylum", selected_taxon={})


def test_krona_rejects_taxon_filter():
    with pytest.raises(ValueError, match="taxon filter not supported on analytics API"):
        build_krona_from_duckdb(
            names=["fake_rpkm.tsv"],
            tax_rank="phylum",
            selected_taxon={"level": "phylum", "name": "Bacillota"},
        )
