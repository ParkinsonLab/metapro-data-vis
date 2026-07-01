import pytest
from api.filters import krona_levels, validate_tax_level


def test_krona_levels_phylum():
    assert krona_levels("phylum") == ("phylum", "genus", "species")


def test_krona_levels_genus():
    assert krona_levels("genus") == ("genus", "species")


def test_krona_levels_species():
    assert krona_levels("species") == ("species",)


def test_krona_levels_dedupes_when_tax_rank_is_species():
    assert krona_levels("species") == ("species",)


def test_krona_levels_invalid_rank():
    with pytest.raises(ValueError, match="invalid tax_level"):
        krona_levels("not_a_rank")
