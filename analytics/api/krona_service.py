from __future__ import annotations

from dataclasses import dataclass

from api.schemas import KronaNode


@dataclass
class Segment:
    id: str
    label: str
    is_leaf: bool = False


def _taxon_get(taxon, key: str):
    try:
        return taxon[key]
    except (TypeError, KeyError):
        return getattr(taxon, key, None)


def lineage_segments(taxon, levels: tuple[str, ...]) -> list[Segment]:
    segments: list[Segment] = []
    for i, rank in enumerate(levels):
        is_last = i == len(levels) - 1
        if is_last:
            name = _taxon_get(taxon, "name")
            return segments + [Segment(name, name, is_leaf=True)]

        rank_val = _taxon_get(taxon, rank)
        rank_label = rank_val if rank_val else f"Unclassified {_taxon_get(taxon, 'name')}"
        if _taxon_get(taxon, levels[i + 1]) is None:
            if rank_val:
                segments.append(Segment(rank_label, rank_label))
            name = _taxon_get(taxon, "name")
            return segments + [Segment(name, f"U_{name}", is_leaf=True)]

        segments.append(Segment(rank_label, rank_label))

    raise RuntimeError("unreachable")


def upsert_segment(
    parent: KronaNode, seg: Segment, taxon_value: float, grand_total: float
) -> KronaNode:
    existing = next(
        (c for c in (parent.children or []) if c.id == seg.id), None
    )

    if seg.is_leaf:
        if existing is not None:
            existing.value += taxon_value
            existing.percentage = existing.value / grand_total
            return existing
        child = KronaNode(
            id=seg.id,
            label=seg.label,
            value=taxon_value,
            percentage=taxon_value / grand_total,
        )
    else:
        if existing is not None:
            existing.subtotal += taxon_value
            existing.percentage = existing.subtotal / grand_total
            return existing
        child = KronaNode(
            id=seg.id,
            label=seg.label,
            children=[],
            subtotal=taxon_value,
            percentage=taxon_value / grand_total,
        )

    if parent.children is None:
        parent.children = []
    parent.children.append(child)
    return child


def build_tree_from_taxa(taxa, levels: tuple[str, ...]) -> KronaNode:
    grand_total = sum(float(t.total) for t in taxa)
    root = KronaNode(
        id="root",
        label="root",
        children=[],
        subtotal=grand_total,
        percentage=1.0,
    )
    for taxon in taxa:
        segments = lineage_segments(taxon, levels)
        node = root
        for seg in segments:
            node = upsert_segment(node, seg, float(taxon.total), grand_total)
    return root
