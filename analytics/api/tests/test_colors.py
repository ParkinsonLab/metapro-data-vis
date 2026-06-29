from api.colors import get_color


def test_get_color_matches_node_formula():
    assert get_color(0, 3) == "hsl(0 75 50)"
    assert get_color(1, 3) == "hsl(90 75 50)"
    assert get_color(2, 3) == "hsl(180 75 50)"
