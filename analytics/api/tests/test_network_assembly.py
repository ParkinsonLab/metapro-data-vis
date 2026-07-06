from api.network_assembly import (
    apply_layout,
    attach_pies_to_nodes,
    build_category_colors,
    dedupe_preserve_order,
    embed_edges,
)


def test_apply_layout_swaps_and_scales():
    nodes = [{"id": "n1", "label": "1.1.1.1", "type": "rectangle", "x": 1000, "y": 1100}]
    out = apply_layout(nodes, width=900, height=550)
    assert out[0]["x"] == (1100 / 1100) * 900 - 900 / 2 + 100
    assert out[0]["y"] == (1000 / 1000) * 550 - 550 / 2


def test_dedupe_preserve_order():
    assert dedupe_preserve_order(["B", "A", "B", "C"]) == ["B", "A", "C"]


def test_build_category_colors():
    colors = build_category_colors(["Bacillota", "Pseudomonadota"])
    assert colors["Bacillota"] == "hsl(0 75 50)"
    assert colors["Pseudomonadota"] == "hsl(120 75 50)"


def test_attach_pies_by_label_not_id():
    tax_cats = ["Bacillota"]
    ec_values = {"1.1.1.1": [42.0]}
    nodes = [
        {"id": "a", "label": "1.1.1.1", "type": "rectangle", "x": 0, "y": 0},
        {"id": "b", "label": "1.1.1.1", "type": "rectangle", "x": 1, "y": 1},
        {"id": "c", "label": "C00001", "type": "circle", "x": 2, "y": 2},
    ]
    out = attach_pies_to_nodes(nodes, tax_cats=tax_cats, ec_values=ec_values)
    assert out[0]["values"] == [{"id": "Bacillota", "value": 42.0}]
    assert out[1]["values"] == [{"id": "Bacillota", "value": 42.0}]
    assert out[2]["values"] == []


def test_embed_edges_resolves_node_objects():
    nodes = [
        {"id": "s", "label": "A", "type": "rectangle", "x": 0, "y": 0, "values": []},
        {"id": "t", "label": "B", "type": "rectangle", "x": 1, "y": 1, "values": []},
    ]
    edges = embed_edges([{"source": "s", "target": "t"}], nodes)
    assert edges[0]["source"]["id"] == "s"
    assert edges[0]["target"]["label"] == "B"
