from __future__ import annotations

import pytest

from api.graph_service import build_graph_from_duckdb
from api.network_service import build_network_from_duckdb
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    bridges_available,
    load_graph_expectations,
    load_network_expectations,
    skip_reason,
)


def _graph_tax_cats(out: dict) -> list[str]:
    return [x for x in out["outer_matrix_index"] if not x.startswith("gap_")]


def _network_tax_cats(out: dict) -> list[str]:
    return list(out["colors"].keys())


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize(
    "case",
    load_graph_expectations()["cases"] if bridges_available() else [],
    ids=lambda c: c["case_id"],
)
def test_graph_and_network_share_tax_cat_order(case, fake_rpkm_db):
    if case["case_id"] == "unknown_pathway":
        pytest.skip("graph cases do not include unknown pathway")

    pathway_name = case["selected_ann_cat"]["name"]
    names = [f"{SAMPLE_ID}.tsv"]
    taxon = case.get("selected_taxon", {})

    graph = build_graph_from_duckdb(
        names=names,
        tax_level=case["tax_level"],
        selected_ann_cat=case["selected_ann_cat"],
        selected_taxon=taxon,
    )
    network = build_network_from_duckdb(
        names=names,
        tax_level=case["tax_level"],
        selected_taxon=taxon,
        pathway_name=pathway_name,
        width=900,
        height=550,
    )

    assert _graph_tax_cats(graph) == _network_tax_cats(network)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_network_expectations_align_with_graph_tax_order(fake_rpkm_db):
    for case in load_network_expectations()["cases"]:
        if case["case_id"] == "unknown_pathway":
            continue
        names = [f"{SAMPLE_ID}.tsv"]
        taxon = case.get("selected_taxon", {})
        pathway = {"level": "pathway", "name": case["pathway_name"]}

        graph = build_graph_from_duckdb(
            names=names,
            tax_level=case["tax_level"],
            selected_ann_cat=pathway,
            selected_taxon=taxon,
        )
        network = build_network_from_duckdb(
            names=names,
            tax_level=case["tax_level"],
            selected_taxon=taxon,
            pathway_name=case["pathway_name"],
            width=case.get("width", 900),
            height=case.get("height", 550),
        )
        assert _graph_tax_cats(graph) == _network_tax_cats(network)
