from __future__ import annotations

import pytest

from api.chord_service import build_chord_from_duckdb
from api.filters import normalise_ann_filter, normalise_taxon_filter
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    assert_pairs_close,
    bridges_available,
    extract_chord_pairs,
    load_chord_expectations,
    skip_reason,
)

if bridges_available():
    _chord = load_chord_expectations()
    _unfiltered = _chord["chord_unfiltered"]
    _filtered = _chord["chord_filtered"]
    _edge = _chord["edge_cases"]
else:
    _unfiltered = _filtered = _edge = []


def test_build_chord_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_chord_from_duckdb(
            sample_id=SAMPLE_ID,
            tax_level="phylum",
            ann_level="superpathway",
            ann_filter=None,
            taxon_filter=None,
            names=["a.tsv", "b.tsv"],
        )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_chord_from_duckdb_shape(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
    )
    assert "count_matrix" in out
    assert out["index"][0] == "gap_1"
    assert len(out["count_matrix"]) == len(out["index"])


def _run_case(case: dict) -> list[tuple[str, str, float]]:
    ann = normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"])
    tax = normalise_taxon_filter(case.get("selected_taxon"))
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=ann,
        taxon_filter=tax,
    )
    return extract_chord_pairs(out)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _unfiltered, ids=lambda c: c["case_id"])
def test_chord_unfiltered_pairs(case, fake_rpkm_db):
    assert_pairs_close(_run_case(case), case["pairs"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _filtered, ids=lambda c: c["case_id"])
def test_chord_filtered_pairs(case, fake_rpkm_db):
    assert_pairs_close(_run_case(case), case["pairs"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _edge, ids=lambda c: c["case_id"])
def test_chord_edge_case_pairs(case, fake_rpkm_db):
    actual = _run_case(case)
    assert_pairs_close(actual, case["pairs"])
    if case["case_id"] == "unmapped_ec_snapshot":
        assert any(p[0] == "Unmapped EC" for p in actual)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(c, id=c["case_id"])
        for c in load_chord_expectations()["chord_unfiltered"]
        if c["case_id"] in ("species_pathway", "phylum_superpathway")
    ],
)
def test_chord_pairs_unchanged_after_prefix_refactor(case, fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"]),
        taxon_filter=normalise_taxon_filter(case.get("selected_taxon")),
    )
    assert_pairs_close(extract_chord_pairs(out), case["pairs"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_phylum_rank_tax_order_by_abundance_not_alphabetical(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    tax_labels = out["index"][gap2 + 1 : -1]
    # Alphabetical would start with Actinomycetota; abundance sort puts Bacillota first
    assert tax_labels[0] == "Bacillota"
    assert tax_labels != sorted(tax_labels)
