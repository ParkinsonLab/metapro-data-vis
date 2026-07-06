import pytest

from api.network_service import load_static_graph

PATHWAY = "Oxidative phosphorylation"


def test_load_static_graph_returns_nodes_and_edges():
    graph = load_static_graph(PATHWAY)
    assert len(graph["nodes"]) > 0
    assert len(graph["edges"]) > 0
    node = graph["nodes"][0]
    assert {"id", "label", "x", "y", "type"} <= set(node.keys())


def test_load_static_graph_unknown_pathway():
    graph = load_static_graph("__no_such_pathway__")
    assert graph == {"nodes": [], "edges": []}
