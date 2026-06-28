from __future__ import annotations

from api.colors import get_color

GAPS = ("gap_1", "gap_2", "gap_3")


def _apply_order(unique_labels: set[str], order_list: list[str] | None) -> list[str]:
    if order_list is None:
        return sorted(unique_labels)
    ordered = [label for label in order_list if label in unique_labels]
    extras = sorted(unique_labels - set(ordered))
    return ordered + extras


def build_chord_matrix(
    pairs: list[tuple[str, str, float]],
    tax_order: list[str] | None = None,
    ann_order: list[str] | None = None,
) -> dict:
    ann_cats = _apply_order({ann for ann, _, _ in pairs}, ann_order)
    tax_cats = _apply_order({tax for _, tax, _ in pairs}, tax_order)
    index = ["gap_1", *ann_cats, "gap_2", *tax_cats, "gap_3"]
    n = len(index)
    pos = {name: i for i, name in enumerate(index)}
    matrix = [[0.0] * n for _ in range(n)]

    for ann, tax, val in pairs:
        if val <= 0:
            continue
        ai, ti = pos.get(ann), pos.get(tax)
        if ai is None or ti is None:
            continue
        matrix[ai][ti] += val
        matrix[ti][ai] += val

    flat_sum = sum(sum(row) for row in matrix)
    for gap_name, div in (("gap_1", 4), ("gap_2", 2), ("gap_3", 4)):
        i = pos[gap_name]
        matrix[i][i] = flat_sum / div

    colors = {
        **{c: get_color(i, len(ann_cats)) for i, c in enumerate(ann_cats)},
        **{c: get_color(i, len(tax_cats)) for i, c in enumerate(tax_cats)},
    }

    return {
        "count_matrix": matrix,
        "index": index,
        "colors": colors,
        "tax_map": {},
        "ann_map": {},
    }
