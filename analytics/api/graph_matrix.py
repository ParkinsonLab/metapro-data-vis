from __future__ import annotations

from functools import cmp_to_key

from api.colors import get_color, get_sub_color
from api.graph_ordering import (
    ann_category_depth,
    compare_tuples,
    lineage_sort_key,
    pathway_sort_key,
    truncate_lineage_tuple,
    truncate_pathway_tuple,
)


def _ann_category(row: dict, ann_level: str) -> str:
    if row.get("ann_category"):
        return row["ann_category"]
    truncated = truncate_pathway_tuple(
        pathway_sort_key(row), ann_category_depth(ann_level)
    )
    return truncated[0]


def _sort_unique_by_tuple(items: list[str], tuple_by_item: dict[str, tuple[str, ...]]) -> list[str]:
    return sorted(
        items,
        key=cmp_to_key(lambda a, b: compare_tuples(tuple_by_item[a], tuple_by_item[b])),
    )


def build_graph_matrix(
    *,
    triples: list[tuple[str, str, float]],
    ec_rows: list[dict],
    tax_rows: list[dict],
    ann_level: str,
    tax_level: str,
) -> dict:
    sorted_ec_rows = sorted(ec_rows, key=pathway_sort_key)
    sorted_tax_rows = sorted(tax_rows, key=lineage_sort_key)

    ec_by_norm = {row["ec_normalized"]: row for row in sorted_ec_rows}
    tax_map = {row["display_name"]: row["tax_map_value"] for row in sorted_tax_rows}

    ec_in_triples = {ec for ec, _, _ in triples}
    tax_in_triples = {tax for _, tax, _ in triples}

    ecs = [
        row["ec_normalized"]
        for row in sorted_ec_rows
        if row["ec_normalized"] in ec_in_triples
    ]
    tax_labels = [
        row["display_name"]
        for row in sorted_tax_rows
        if row["display_name"] in tax_in_triples
    ]

    ann_depth = ann_category_depth(ann_level)
    ann_cat_tuples: dict[str, tuple[str, ...]] = {}
    for row in sorted_ec_rows:
        if row["ec_normalized"] not in ec_in_triples:
            continue
        cat = _ann_category(row, ann_level)
        if cat not in ann_cat_tuples:
            ann_cat_tuples[cat] = truncate_pathway_tuple(pathway_sort_key(row), ann_depth)
    ann_cats = _sort_unique_by_tuple(list(ann_cat_tuples), ann_cat_tuples)

    tax_cat_tuples: dict[str, tuple[str, ...]] = {}
    for row in sorted_tax_rows:
        if row["display_name"] not in tax_in_triples:
            continue
        val = row["tax_map_value"]
        if val not in tax_cat_tuples:
            tax_cat_tuples[val] = truncate_lineage_tuple(row, tax_level)
    tax_cats = _sort_unique_by_tuple(list(tax_cat_tuples), tax_cat_tuples)

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
