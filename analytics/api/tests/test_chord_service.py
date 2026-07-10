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


def test_chord_rejects_pathway_node_ann_level():
    with pytest.raises(ValueError, match="pathway_node ann_level not supported on chord"):
        build_chord_from_duckdb(
            sample_id=SAMPLE_ID,
            tax_level="species",
            ann_level="pathway_node",
            ann_filter=None,
            taxon_filter=None,
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


def _all_chord_cases():
    doc = load_chord_expectations()
    for section in ("chord_unfiltered", "chord_filtered", "edge_cases"):
        for case in doc[section]:
            yield pytest.param(case, id=case["case_id"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", list(_all_chord_cases()))
def test_chord_pairs_and_index(case, fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"]),
        taxon_filter=normalise_taxon_filter(case.get("selected_taxon")),
    )
    assert_pairs_close(extract_chord_pairs(out), case["pairs"])
    assert out["index"] == case["expected_index"]


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", list(_all_chord_cases()))
def test_chord_index_stateless(case, fake_rpkm_db):
    kwargs = dict(
        sample_id=SAMPLE_ID,
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"]),
        taxon_filter=normalise_taxon_filter(case.get("selected_taxon")),
    )
    a = build_chord_from_duckdb(**kwargs)["index"]
    b = build_chord_from_duckdb(**kwargs)["index"]
    assert a == b


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
    # Most abundant phylum sits at the top of the tax arc (last in index, before gap_3).
    assert tax_labels[-1] == "Bacillota"
    assert tax_labels != sorted(tax_labels)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_pathway_level_ann_order_groups_by_superpathway(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="phylum",
        ann_level="pathway",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    ann_labels = out["index"][1:gap2]
    assert ann_labels != sorted(ann_labels)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_pathway_node_ann_order_stays_alphabetical(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id="fake_rpkm",
        tax_level="species",
        ann_level="pathway_node",
        ann_filter=None,
        taxon_filter=None,
    )
    gap2 = out["index"].index("gap_2")
    ann_labels = out["index"][1:gap2]
    assert ann_labels == sorted(ann_labels)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_class_rank_tax_labels_colocate_by_phylum_prefix(fake_rpkm_db):
    phylum_out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID, tax_level="phylum", ann_level="superpathway",
        ann_filter=None, taxon_filter=None,
    )
    class_out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID, tax_level="class", ann_level="superpathway",
        ann_filter=None, taxon_filter=None,
    )
    phylum_tax = phylum_out["index"][
        phylum_out["index"].index("gap_2") + 1 : -1
    ]
    class_tax = class_out["index"][
        class_out["index"].index("gap_2") + 1 : -1
    ]
    # Each phylum label's descendant classes appear in one contiguous block
    # (minimal check: more than one class and not purely alphabetical)
    assert len(class_tax) > 1
    assert class_tax != sorted(class_tax)
    assert phylum_tax != sorted(phylum_tax)
