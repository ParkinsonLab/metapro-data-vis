from __future__ import annotations
from typing import Any

VALID_TAX_RANKS = frozenset({"kingdom", "phylum", "class", "order", "family", "genus", "species"})
VALID_ANN_LEVELS = frozenset({"superpathway", "pathway", "pathway_node"})

TAX_RANK_ORDER = (
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
)
ANN_LEVEL_ORDER = ("superpathway", "pathway", "pathway_node")


def ranks_up_to(tax_level: str) -> tuple[str, ...]:
    validate_tax_level(tax_level)
    idx = TAX_RANK_ORDER.index(tax_level)
    return TAX_RANK_ORDER[: idx + 1]


def ann_levels_up_to(ann_level: str) -> tuple[str, ...]:
    validate_ann_level(ann_level)
    idx = ANN_LEVEL_ORDER.index(ann_level)
    return ANN_LEVEL_ORDER[: idx + 1]


def sample_id_from_names(names: list[str]) -> str:
    base = names[0]
    if base.endswith(".tsv"):
        return base[:-4]
    return base


def normalise_ann_filter(raw: Any, ann_level: str) -> dict[str, str] | None:
    if not raw:
        return None
    if isinstance(raw, str):
        name = raw.strip()
        if not name:
            return None
        level = "superpathway" if ann_level in ("pathway", "pathway_node") else ann_level
        return {"level": level, "name": name}
    if isinstance(raw, dict):
        level = str(raw.get("level") or "").strip()
        name = str(raw.get("name") or "").strip()
        if level and name:
            return {"level": level, "name": name}
    return None


def normalise_taxon_filter(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    level = str(raw.get("level") or "").strip()
    name = str(raw.get("name") or "").strip()
    if level and name:
        return {"level": level, "name": name}
    return None


def validate_tax_level(tax_level: str) -> None:
    if tax_level not in VALID_TAX_RANKS:
        raise ValueError(f"invalid tax_level: {tax_level}")


def validate_ann_level(ann_level: str) -> None:
    if ann_level not in VALID_ANN_LEVELS:
        raise ValueError(f"invalid ann_level: {ann_level}")
