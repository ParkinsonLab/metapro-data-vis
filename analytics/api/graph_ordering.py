from __future__ import annotations

from api.filters import TAX_RANK_ORDER

TAX_RANKS = TAX_RANK_ORDER


def compare_tuples(a: tuple[str, ...], b: tuple[str, ...]) -> int:
    for x, y in zip(a, b):
        if x < y:
            return -1
        if x > y:
            return 1
    if len(a) < len(b):
        return -1
    if len(a) > len(b):
        return 1
    return 0


def pathway_sort_key(row: dict) -> tuple[str, str, str]:
    return (
        row.get("superpathway_name") or "",
        row.get("pathway_name") or "",
        row.get("ec_normalized") or "",
    )


def lineage_sort_key(row: dict) -> tuple[str, ...]:
    return tuple(row.get(r) or "" for r in TAX_RANKS) + (row["display_name"],)


def ann_category_depth(ann_level: str) -> int:
    if ann_level == "superpathway":
        return 1
    return 2


def truncate_pathway_tuple(key: tuple[str, str, str], depth: int) -> tuple[str, ...]:
    if depth == 1:
        return (key[0],)
    return (key[0], key[1])


def truncate_lineage_tuple(row: dict, tax_level: str) -> tuple[str, ...]:
    idx = TAX_RANKS.index(tax_level) + 1
    return lineage_sort_key(row)[:idx]
