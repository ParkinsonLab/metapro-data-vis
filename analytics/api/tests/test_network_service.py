import pytest

from api.network_service import build_network_from_duckdb, load_static_graph
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    assert_pairs_close,
    bridges_available,
    extract_network_ec_values,
    load_network_expectations,
    skip_reason,
)

PATHWAY = "Oxidative phosphorylation"
WIDTH, HEIGHT = 900, 550

if bridges_available():
    _network_cases = load_network_expectations()["cases"]
else:
    _network_cases = []


def test_load_static_graph_returns_nodes_and_edges():
    graph = load_static_graph(PATHWAY)
    assert len(graph["nodes"]) > 0
    assert len(graph["edges"]) > 0
    node = graph["nodes"][0]
    assert {"id", "label", "x", "y", "type"} <= set(node.keys())


def test_load_static_graph_unknown_pathway():
    graph = load_static_graph("__no_such_pathway__")
    assert graph == {"nodes": [], "edges": []}


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_network_from_duckdb_shape(fake_rpkm_db):
    out = build_network_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        selected_taxon={},
        pathway_name=PATHWAY,
        width=WIDTH,
        height=HEIGHT,
    )
    assert "nodes" in out and "edges" in out and "colors" in out
    assert len(out["nodes"]) > 0
    with_pie = [n for n in out["nodes"] if any(v["value"] > 0 for v in n["values"])]
    assert len(with_pie) > 0
    assert out["edges"][0]["source"] is not None
    assert isinstance(out["edges"][0]["source"], dict)


def test_build_network_requires_pathway_name():
    with pytest.raises(ValueError, match="pathway_name is required"):
        build_network_from_duckdb(
            names=["fake_rpkm.tsv"],
            tax_level="phylum",
            selected_taxon={},
            pathway_name="",
            width=WIDTH,
            height=HEIGHT,
        )


def test_build_network_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_network_from_duckdb(
            names=["a.tsv", "b.tsv"],
            tax_level="phylum",
            selected_taxon={},
            pathway_name=PATHWAY,
            width=WIDTH,
            height=HEIGHT,
        )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_network_empty_pies_on_impossible_taxon_filter(fake_rpkm_db):
    out = build_network_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        selected_taxon={"level": "phylum", "name": "__no_such_phylum__"},
        pathway_name=PATHWAY,
        width=WIDTH,
        height=HEIGHT,
    )
    assert len(out["nodes"]) > 0
    assert out["colors"] == {}
    for n in out["nodes"]:
        assert n["values"] == []


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _network_cases, ids=[c["case_id"] for c in _network_cases])
def test_network_golden(case, fake_rpkm_db):
    out = build_network_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level=case["tax_level"],
        selected_taxon=case.get("selected_taxon", {}),
        pathway_name=case["pathway_name"],
        width=case.get("width", WIDTH),
        height=case.get("height", HEIGHT),
    )
    if case["case_id"] == "unknown_pathway":
        assert out == {"nodes": [], "edges": [], "colors": {}}
        return

    assert set(out["colors"].keys()) == set(case["expected_color_keys"])
    assert_pairs_close(
        extract_network_ec_values(out, case["focal_ec"]),
        case["expected_values"],
    )
    layout = next(n for n in out["nodes"] if n["label"] == case["focal_ec"])
    expected = case["expected_layout"]
    assert layout["label"] == expected["label"]
    assert layout["x"] == pytest.approx(expected["x"])
    assert layout["y"] == pytest.approx(expected["y"])
