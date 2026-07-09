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

_PATHWAY = {"level": "pathway", "name": "Oxidative phosphorylation"}

if bridges_available():
    _cases = load_graph_expectations()["cases"]
else:
    _cases = []


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_graph_from_duckdb_shape(fake_rpkm_db):
    out = build_graph_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        selected_ann_cat=_PATHWAY,
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
            selected_ann_cat=_PATHWAY,
            selected_taxon={},
        )


@pytest.mark.parametrize(
    "selected_ann_cat",
    [
        {},
        {"level": "superpathway", "name": "Energy metabolism"},
        {"level": "pathway", "name": ""},
    ],
)
def test_build_graph_requires_pathway_filter(selected_ann_cat):
    with pytest.raises(ValueError, match="graph requires selected_ann_cat"):
        build_graph_from_duckdb(
            names=[f"{SAMPLE_ID}.tsv"],
            tax_level="phylum",
            selected_ann_cat=selected_ann_cat,
            selected_taxon={},
        )


def _run_case(case: dict) -> dict:
    return build_graph_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level=case["tax_level"],
        selected_ann_cat=case["selected_ann_cat"],
        selected_taxon=case.get("selected_taxon", {}),
    )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _cases, ids=lambda c: c["case_id"])
def test_graph_golden(case, fake_rpkm_db):
    out = _run_case(case)
    assert_pairs_close(extract_graph_pairs(out), case["pairs"])
    assert extract_graph_inner_index(out) == case["expected_inner_index"]
    assert extract_graph_outer_index(out) == case["expected_outer_index"]
    assert extract_graph_tax_map(out) == case["tax_map"]


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_graph_golden_stateless(fake_rpkm_db):
    case = _cases[0]
    a = _run_case(case)
    b = _run_case(case)
    assert extract_graph_inner_index(a) == extract_graph_inner_index(b)
    assert extract_graph_outer_index(a) == extract_graph_outer_index(b)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_graph_baseline_includes_unknown_tax_id(fake_rpkm_db):
    case = next(c for c in _cases if c["case_id"] == "pathway_phylum_baseline")
    out = _run_case(case)
    assert "999999999" in extract_graph_inner_index(out)
    assert "Unclassified" in extract_graph_outer_index(out)
