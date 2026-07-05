from __future__ import annotations

from api.colors import get_color, get_sub_color
from api.graph_ordering import ann_category_depth, pathway_sort_key, truncate_pathway_tuple


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _ann_category(row: dict, ann_level: str) -> str:
    if row.get("ann_category"):
        return row["ann_category"]
    truncated = truncate_pathway_tuple(
        pathway_sort_key(row), ann_category_depth(ann_level)
    )
    return truncated[0]


def build_graph_matrix(
    *,
    triples: list[tuple[str, str, float]],
    ec_rows: list[dict],
    tax_rows: list[dict],
    ann_level: str,
    tax_level: str,
) -> dict:
    # ec_rows / tax_rows are pre-ordered by graph_service metadata queries.
    ec_by_norm = {row["ec_normalized"]: row for row in ec_rows}
    tax_map = {row["display_name"]: row["tax_map_value"] for row in tax_rows}

    ec_in_triples = {ec for ec, _, _ in triples}
    tax_in_triples = {tax for _, tax, _ in triples}

    ecs = [
        row["ec_normalized"]
        for row in ec_rows
        if row["ec_normalized"] in ec_in_triples
    ]
    tax_labels = [
        row["display_name"]
        for row in tax_rows
        if row["display_name"] in tax_in_triples
    ]

    ann_cats = _dedupe_preserve_order(
        [_ann_category(ec_by_norm[ec], ann_level) for ec in ecs]
    )
    tax_cats = _dedupe_preserve_order([tax_map[tax] for tax in tax_labels])

    inner_matrix_index = ["gap_1", *ecs, "gap_2", *tax_labels, "gap_3"]
    outer_matrix_index = ["gap_1", *ann_cats, "gap_2", *tax_cats, "gap_3"]

    n = len(inner_matrix_index)
    pos = {name: i for i, name in enumerate(inner_matrix_index)}
    matrix = [[0.0] * n for _ in range(n)]

    for ec, tax, val in triples:
        if val <= 0:
            continue
        ei, ti = pos.get(ec), pos.get(tax)
        if ei is None or ti is None:
            continue
        matrix[ei][ti] += val
        matrix[ti][ei] += val

    flat_sum = sum(sum(row) for row in matrix)
    for gap_name, div in (("gap_1", 4), ("gap_2", 2), ("gap_3", 4)):
        i = pos[gap_name]
        matrix[i][i] = flat_sum / div

    cat_colors = {
        **{c: get_color(i, len(ann_cats)) for i, c in enumerate(ann_cats)},
        **{c: get_color(i, len(tax_cats)) for i, c in enumerate(tax_cats)},
    }
    sub_colors = {
        **{
            ec: get_sub_color(
                cat_colors[_ann_category(ec_by_norm[ec], ann_level)], ec
            )
            for ec in ecs
        },
        **{tax: get_sub_color(cat_colors[tax_map[tax]], tax) for tax in tax_labels},
    }
    colors = {**sub_colors, **cat_colors}

    return {
        "inner_count_matrix": matrix,
        "inner_matrix_index": inner_matrix_index,
        "outer_matrix_index": outer_matrix_index,
        "colors": colors,
        "tax_map": tax_map,
    }
