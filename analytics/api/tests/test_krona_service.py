import pytest
from types import SimpleNamespace

from api.krona_service import (
    KronaNode,
    Segment,
    build_krona_from_duckdb,
    lineage_segments,
    upsert_segment,
)
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    krona_fixtures_available,
    krona_skip_reason,
    load_krona_expectations,
)


def _taxon(**kwargs):
    return SimpleNamespace(**kwargs)


class TestLineageSegments:
    def test_species_leaf_at_last_rank(self):
        taxon = _taxon(
            name="Staphylococcus aureus",
            phylum="Bacillota",
            genus="Staphylococcus",
            species="Staphylococcus aureus",
        )
        segs = lineage_segments(taxon, ("phylum", "genus", "species"))
        assert [s.id for s in segs] == [
            "Bacillota",
            "Staphylococcus",
            "Staphylococcus aureus",
        ]
        assert segs[-1].is_leaf is True
        assert segs[-1].label == "Staphylococcus aureus"

    def test_early_leaf_when_genus_species_null(self):
        taxon = _taxon(
            name="Bacillota",
            phylum="Bacillota",
            genus=None,
            species=None,
        )
        segs = lineage_segments(taxon, ("phylum", "genus", "species"))
        assert len(segs) == 2
        assert segs[0].id == "Bacillota" and segs[0].is_leaf is False
        assert segs[1].id == "Bacillota"
        assert segs[1].label == "U_Bacillota"
        assert segs[1].is_leaf is True

    def test_orphan_under_root(self):
        taxon = _taxon(name="999999999", phylum=None, genus=None, species=None)
        segs = lineage_segments(taxon, ("phylum", "genus", "species"))
        assert len(segs) == 1
        assert segs[0].label == "U_999999999"


class TestUpsertSegment:
    def test_creates_internal_then_leaf(self):
        root = KronaNode(id="root", label="root", children=[], subtotal=0.0, percentage=1.0)
        grand = 10.0
        n1 = upsert_segment(root, Segment("Bacillota", "Bacillota"), 5.0, grand)
        assert n1.id == "Bacillota"
        n2 = upsert_segment(
            n1, Segment("S. aureus", "S. aureus", is_leaf=True), 5.0, grand
        )
        assert n2.value == 5.0
        assert root.children[0].id == "Bacillota"
        assert root.children[0].children[0].value == 5.0

    def test_merges_duplicate_leaf_ids(self):
        root = KronaNode(id="root", label="root", children=[], subtotal=0.0, percentage=1.0)
        leaf = Segment("dup", "dup", is_leaf=True)
        upsert_segment(root, leaf, 3.0, 10.0)
        upsert_segment(root, leaf, 2.0, 10.0)
        node = root.children[0]
        assert node.value == 5.0
        assert node.percentage == 0.5


def _assert_trees_close(actual: dict, expected: dict, tol: float = 1e-9) -> None:
    """Compare contract fields only; ignore extra keys (e.g. subtotal on internals)."""
    for key in ("id", "label", "percentage"):
        if key == "percentage":
            assert actual[key] == pytest.approx(expected[key], abs=tol)
        else:
            assert actual[key] == expected[key]
    if not expected.get("children"):
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
