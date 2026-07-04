from api.colors import get_color, get_sub_color, map_lum


def test_map_lum_deterministic():
    assert map_lum("abc") == map_lum("abc")
    assert 20 <= map_lum("x") <= 100


def test_get_sub_color_changes_luminance():
    base = get_color(0, 3)
    sub = get_sub_color(base, "1.1.1.1")
    assert sub.startswith("hsl(")
    assert sub != base
