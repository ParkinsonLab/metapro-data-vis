from __future__ import annotations

import pytest

from api.graph_service import build_graph_from_duckdb
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    assert_pairs_close,
    bridges_available,
    extract_graph_inner_index,
    extract_graph_outer_index,
    extract_graph_pairs,
    extract_graph_tax_map,
    load_graph_expectations,
    skip_reason,
)

if bridges_available():
    _graph = load_graph_expectations()
    _unfiltered = _graph["graph_unfiltered"]
    _filtered = _graph["graph_filtered"]
    _edge = _graph["edge_cases"]
else:
    _unfiltered = _filtered = _edge = []


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_graph_from_duckdb_shape(fake_rpkm_db):
    out = build_graph_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        ann_level="superpathway",
        selected_ann_cat={},
        selected_taxon={},
    )
    assert "inner_count_matrix" in out
    assert out["inner_matrix_index"][0] == "gap_1"
    assert len(out["inner_count_matrix"]) == len(out["inner_matrix_index"])
    assert out["tax_map"]


def test_build_graph_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_graph_from_duckdb(
            names=["a.tsv", "b.tsv"],
            tax_level="phylum",
            ann_level="superpathway",
            selected_ann_cat={},
            selected_taxon={},
        )


def _run_case(case: dict) -> dict:
    return build_graph_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        selected_ann_cat=case.get("selected_ann_cat", {}),
        selected_taxon=case.get("selected_taxon", {}),
    )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _unfiltered, ids=lambda c: c["case_id"])
def test_graph_unfiltered_pairs(case, fake_rpkm_db):
    out = _run_case(case)
    assert_pairs_close(extract_graph_pairs(out), case["pairs"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _filtered, ids=lambda c: c["case_id"])
def test_graph_filtered_pairs(case, fake_rpkm_db):
    out = _run_case(case)
    assert_pairs_close(extract_graph_pairs(out), case["pairs"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _edge, ids=lambda c: c["case_id"])
def test_graph_edge_case_pairs(case, fake_rpkm_db):
    out = _run_case(case)
    assert_pairs_close(extract_graph_pairs(out), case["pairs"])
    if case["case_id"] == "unmapped_ec_snapshot":
        assert "999999999" in extract_graph_inner_index(out)


def _all_graph_cases():
    doc = load_graph_expectations()
    for section in ("graph_unfiltered", "graph_filtered", "edge_cases"):
        for case in doc[section]:
            yield pytest.param(case, id=case["case_id"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", list(_all_graph_cases()))
def test_graph_pairs_and_inner_index(case, fake_rpkm_db):
    out = _run_case(case)
    assert_pairs_close(extract_graph_pairs(out), case["pairs"])
    assert extract_graph_inner_index(out) == case["expected_inner_index"]


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", list(_all_graph_cases()))
def test_graph_outer_index_and_tax_map(case, fake_rpkm_db):
    out = _run_case(case)
    assert extract_graph_outer_index(out) == case["expected_outer_index"]
    assert extract_graph_tax_map(out) == case["tax_map"]


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", list(_all_graph_cases()))
def test_graph_index_stateless(case, fake_rpkm_db):
    a = _run_case(case)
    b = _run_case(case)
    assert extract_graph_inner_index(a) == extract_graph_inner_index(b)
    assert extract_graph_outer_index(a) == extract_graph_outer_index(b)
