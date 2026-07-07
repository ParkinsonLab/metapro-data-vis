from __future__ import annotations

from api.colors import get_color


def apply_layout(nodes: list[dict], *, width: float, height: float) -> list[dict]:
    placed = []
    for node in nodes:
        placed.append({
            **node,
            "x": (node["y"] / 1100) * width - width / 2 + 100,
            "y": (node["x"] / 1000) * height - height / 2,
        })
    return placed


def build_category_colors(tax_cats: list[str]) -> dict[str, str]:
    return {cat: get_color(i, len(tax_cats)) for i, cat in enumerate(tax_cats)}


def attach_pies_to_nodes(
    nodes: list[dict],
    *,
    tax_cats: list[str],
    ec_values: dict[str, list[float]],
) -> list[dict]:
    out = []
    for node in nodes:
        pie = ec_values.get(node["label"])
        values = (
            [{"id": cat, "value": v} for cat, v in zip(tax_cats, pie)]
            if pie is not None
            else []
        )
        out.append({**node, "values": values})
    return out


def embed_edges(edges: list[dict], nodes: list[dict]) -> list[dict]:
    by_id = {n["id"]: n for n in nodes}
    return [
        {"source": by_id.get(e["source"]), "target": by_id.get(e["target"])}
        for e in edges
    ]
