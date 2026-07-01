import pytest

from api.krona_service import build_krona_from_duckdb
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    krona_fixtures_available,
    krona_skip_reason,
    load_krona_expectations,
)


def _assert_trees_close(actual: dict, expected: dict, tol: float = 1e-9) -> None:
    """Compare contract fields only; ignore extra keys (e.g. subtotal on internals)."""
    for key in ("id", "label", "percentage"):
        if key == "percentage":
            assert actual[key] == pytest.approx(expected[key], abs=tol)
        else:
            assert actual[key] == expected[key]
    if "value" in expected:
        assert actual.get("value") == pytest.approx(expected["value"], abs=tol)
        assert not actual.get("children")
    else:
        act_children = sorted(actual.get("children") or [], key=lambda n: n["id"])
        exp_children = sorted(expected.get("children") or [], key=lambda n: n["id"])
        assert len(act_children) == len(exp_children)
        for a, e in zip(act_children, exp_children):
            _assert_trees_close(a, e, tol)


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


@pytest.mark.parametrize("case", ["krona_phylum", "krona_genus"])
@pytest.mark.skipif(not krona_fixtures_available(), reason=krona_skip_reason())
def test_krona_tree_matches_golden(case, fake_rpkm_db):
    expected = load_krona_expectations()[case]
    out = build_krona_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_rank=case.replace("krona_", ""),
        selected_taxon={},
    ).model_dump(exclude_none=True)
    _assert_trees_close(out, expected)
