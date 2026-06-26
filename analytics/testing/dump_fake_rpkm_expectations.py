"""Generate golden YAML from built fake_rpkm DuckDB. Run once after TSV is final."""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import yaml

from api.chord_service import build_chord_from_duckdb
from api.filters import normalise_ann_filter, normalise_taxon_filter
from testing.fake_rpkm_fixture import (
    ANN_LEVELS,
    CHORD_YAML,
    PIPELINE_YAML,
    RANKS,
    SAMPLE_ID,
    ensure_pipeline_built,
    extract_chord_pairs,
)


def dump_rollup_grid(conn, focal_ec: str, focal_tax_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT requested_rank, pathway_level, pathway_label,
               resolved_tax_label, value
        FROM int_tax_rollup_resolved
        WHERE ec_normalized = ? AND source_tax_id = ?
        ORDER BY requested_rank, pathway_level
        """,
        [focal_ec, focal_tax_id],
    ).fetchall()
    if len(rows) != 21:
        raise RuntimeError(f"expected 21 rollup rows, got {len(rows)}")
    return [
        {
            "requested_rank": r[0],
            "pathway_level": r[1],
            "pathway_label": r[2] or "Unmapped EC",
            "resolved_tax_label": r[3],
            "value": float(r[4]),
        }
        for r in rows
    ]


def dump_chord_case(tax_level: str, ann_level: str, **filters) -> dict:
    ann = normalise_ann_filter(filters.get("selected_ann_cat"), ann_level)
    tax = normalise_taxon_filter(filters.get("selected_taxon"))
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level=tax_level,
        ann_level=ann_level,
        ann_filter=ann,
        taxon_filter=tax,
    )
    pairs = extract_chord_pairs(out)
    case = {
        "case_id": filters.get("case_id", f"{tax_level}_{ann_level}"),
        "tax_level": tax_level,
        "ann_level": ann_level,
        "pairs": [[a, t, v] for a, t, v in pairs],
    }
    for key in ("selected_ann_cat", "selected_taxon"):
        if key in filters:
            case[key] = filters[key]
    return case


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focal-ec", required=True)
    parser.add_argument("--focal-tax-id", type=int, required=True)
    parser.add_argument("--fallback-tax-id", type=int, required=True)
    parser.add_argument("--sibling-genus-name", required=True)
    parser.add_argument("--ann-superpathway-name", required=True)
    args = parser.parse_args()

    db = ensure_pipeline_built()
    conn = duckdb.connect(str(db), read_only=True)

    pipeline_doc = {
        "fixture": {
            "sample_id": SAMPLE_ID,
            "tsv": "fake_rpkm.tsv",
            "focal_ec": args.focal_ec,
            "focal_tax_id": args.focal_tax_id,
            "roles": {
                "fallback_tax_id": args.fallback_tax_id,
                "unknown_tax_id": 999999999,
            },
        },
        "rollup_grid": dump_rollup_grid(conn, args.focal_ec, args.focal_tax_id),
    }
    conn.close()

    unfiltered = [
        dump_chord_case(rank, ann, case_id=f"{rank}_{ann}")
        for rank in RANKS
        for ann in ANN_LEVELS
    ]

    filtered = [
        dump_chord_case(
            "phylum",
            "superpathway",
            case_id="taxon_filter_sibling_genus",
            selected_taxon={"level": "genus", "name": args.sibling_genus_name},
        ),
        dump_chord_case(
            "phylum",
            "superpathway",
            case_id="ann_filter_superpathway",
            selected_ann_cat=args.ann_superpathway_name,
        ),
    ]

    edge_cases = [
        dump_chord_case("phylum", "superpathway", case_id="unmapped_ec_snapshot"),
        dump_chord_case("phylum", "superpathway", case_id="unclassified_tax_snapshot"),
        dump_chord_case("species", "superpathway", case_id="fallback_species_request"),
    ]

    chord_doc = {
        "sample_id": SAMPLE_ID,
        "chord_unfiltered": unfiltered,
        "chord_filtered": filtered,
        "edge_cases": edge_cases,
    }

    PIPELINE_YAML.write_text(yaml.safe_dump(pipeline_doc, sort_keys=False), encoding="utf-8")
    CHORD_YAML.parent.mkdir(parents=True, exist_ok=True)
    CHORD_YAML.write_text(yaml.safe_dump(chord_doc, sort_keys=False), encoding="utf-8")
    print(f"Wrote {PIPELINE_YAML}")
    print(f"Wrote {CHORD_YAML}")


if __name__ == "__main__":
    main()
