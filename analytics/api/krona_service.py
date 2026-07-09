from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import duckdb

from api.filters import krona_levels, sample_id_from_names
from api.schemas import KronaNode

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"


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


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _order_by_clause(levels: tuple[str, ...]) -> str:
    if len(levels) == 1:
        return f"COALESCE({levels[0]}_label, display_name)"
    parts: list[str] = []
    for i, rank in enumerate(levels):
        col = f"{rank}_label"
        if i == 0:
            parts.append(f"COALESCE({col}, 'Unclassified ' || display_name)")
        elif i == len(levels) - 1:
            parts.append("COALESCE(species_label, display_name)")
        else:
            parts.append(f"COALESCE({col}, '')")
    return ",\n    ".join(parts)


def _fetch_taxa(conn, *, levels: tuple[str, ...]) -> list:
    lineage_cols = ", ".join(f"{rank}_label AS {rank}" for rank in levels)
    group_cols = ", ".join(f"{rank}_label" for rank in levels)
    order_by = _order_by_clause(levels)
    sql = f"""
    SELECT
        display_name,
        SUM(value) AS total,
        {lineage_cols}
    FROM mart_rpkm_enriched
    GROUP BY source_tax_id, display_name, {group_cols}
    HAVING SUM(value) > 0
    ORDER BY
        {order_by}
    """
    return conn.execute(sql).fetchall()


def _row_to_taxon(row, levels: tuple[str, ...]):
    attrs = {"name": row[0], "total": row[1]}
    for i, rank in enumerate(levels):
        attrs[rank] = row[2 + i]
    return SimpleNamespace(**attrs)


def build_krona_from_duckdb(
    *, names: list[str], tax_rank: str, selected_taxon: dict
) -> KronaNode:
    if len(names) == 0:
        raise ValueError("names must contain at least one sample")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")
    if isinstance(selected_taxon, dict):
        level = str(selected_taxon.get("level") or "").strip()
        name = str(selected_taxon.get("name") or "").strip()
        if level and name:
            raise ValueError("taxon filter not supported on analytics API")

    levels = krona_levels(tax_rank)
    sample_id = sample_id_from_names(names)
    db_file = _db_path(sample_id)
    if not db_file.exists():
        raise FileNotFoundError(f"sample not found: {sample_id}")

    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "mart_rpkm_enriched" not in tables:
            raise RuntimeError(
                f"mart_rpkm_enriched not materialized for sample: {sample_id}"
            )
        rows = _fetch_taxa(conn, levels=levels)
        taxa = [_row_to_taxon(r, levels) for r in rows]
        return build_tree_from_taxa(taxa, levels)
    finally:
        conn.close()
