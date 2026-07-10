"""SQL helpers for querying mart_rpkm_enriched with dbt macro semantics."""
from __future__ import annotations

from api.filters import TAX_RANK_ORDER, validate_ann_level, validate_tax_level

# Walk from requested rank toward kingdom (coarser), matching resolve_tax_* dbt macros.
_RANKS_FINE_TO_COARSE = tuple(reversed(TAX_RANK_ORDER))


def _lineage_ref(rank: str, suffix: str, prefix: str = "") -> str:
    col = f"{rank}_{suffix}"
    if prefix:
        return f"{prefix}.{col}"
    return col


def _pathway_cols(prefix: str = "") -> dict[str, str]:
    p = f"{prefix}." if prefix else ""
    return {
        "ec_col": f"{p}ec_normalized",
        "pathway_id_col": f"{p}pathway_id",
        "pathway_name_col": f"{p}pathway_name",
        "superpathway_name_col": f"{p}superpathway_name",
    }


def resolve_tax_label_sql(tax_level: str, prefix: str = "") -> str:
    """Mirror resolve_tax_label dbt macro (fallback walk toward kingdom)."""
    validate_tax_level(tax_level)
    start = _RANKS_FINE_TO_COARSE.index(tax_level)
    chain = [_lineage_ref(rank, "label", prefix) for rank in _RANKS_FINE_TO_COARSE[start:]]
    chain.append("'Unclassified'")
    return f"COALESCE({', '.join(chain)})"


def resolve_tax_id_sql(tax_level: str, prefix: str = "") -> str:
    """Mirror resolve_tax_id dbt macro (fallback walk toward kingdom)."""
    validate_tax_level(tax_level)
    start = _RANKS_FINE_TO_COARSE.index(tax_level)
    chain = [_lineage_ref(rank, "id", prefix) for rank in _RANKS_FINE_TO_COARSE[start:]]
    if len(chain) == 1:
        return chain[0]
    return f"COALESCE({', '.join(chain)})"


def canonical_pathway_label_sql(ann_level: str, prefix: str = "") -> str:
    """Mirror canonical_pathway_label dbt macro."""
    validate_ann_level(ann_level)
    cols = _pathway_cols(prefix)
    return f"""CASE
  WHEN {cols["ec_col"]} = '0.0.0.0' OR {cols["pathway_id_col"]} IS NULL THEN 'Unmapped EC'
  WHEN '{ann_level}' = 'pathway_node' THEN {cols["ec_col"]}
  WHEN '{ann_level}' = 'superpathway' THEN {cols["superpathway_name_col"]}
  ELSE {cols["pathway_name_col"]}
END"""


def lineage_order_by_sql() -> str:
    """ORDER BY keys for lineage columns on mart_rpkm_enriched (kingdom → species)."""
    parts = list(TAX_RANK_ORDER) + ["display_name"]
    return ", ".join(f'"{rank}"' if rank == "order" else rank for rank in parts)


def ann_order_by_sql(ann_level: str) -> str:
    """ORDER BY keys for pathway hierarchy on mart_rpkm_enriched."""
    validate_ann_level(ann_level)
    if ann_level == "superpathway":
        return "superpathway_name ASC"
    if ann_level == "pathway":
        return "superpathway_name ASC, pathway_name ASC"
    raise ValueError(f"unsupported ann_level for ann ordering: {ann_level}")


def ann_filter_where_sql(
    ann_filter: dict[str, str] | None,
    ann_level: str,
    prefix: str = "",
) -> tuple[str, list]:
    """WHERE predicate for annotation drill-down on mart_rpkm_enriched."""
    if ann_filter is None:
        return "TRUE", []
    validate_ann_level(ann_level)
    level, name = ann_filter["level"], ann_filter["name"]
    p = f"{prefix}." if prefix else ""

    if ann_level == "superpathway":
        label_sql = canonical_pathway_label_sql("superpathway", prefix=prefix)
        return f"({label_sql}) = ?", [name]

    if ann_level == "pathway_node":
        if level == "pathway":
            return f"{p}pathway_name = ?", [name]
        return f"{p}superpathway_name = ?", [name]

    if level == "pathway":
        return f"{p}pathway_name = ?", [name]
    return f"{p}superpathway_name = ?", [name]


def taxon_filter_where_sql(
    taxon_filter: dict[str, str] | None,
    prefix: str = "",
) -> tuple[str, list]:
    """WHERE predicate for taxon drill-down on mart_rpkm_enriched."""
    if taxon_filter is None:
        return "TRUE", []
    level, name = taxon_filter["level"], taxon_filter["name"]
    label_sql = resolve_tax_label_sql(level, prefix=prefix)
    return f"({label_sql}) = ?", [name]
