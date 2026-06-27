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

FOCAL_EC = "1.6.5.9"
FOCAL_TAX_ID = 1280
FALLBACK_TAX_ID = 2
UNKNOWN_TAX_ID = 999999999
FOCAL_SUPERPATHWAY = "Energy metabolism"
TAX_COLUMNS = {
    "col_tax_focal": 1280,
    "col_tax_sibling_genus": 1282,
    "col_tax_cousin_family": 1296,
    "col_tax_cousin_order": 904523,
    "col_tax_cousin_class": 131157,
    "col_tax_cousin_phylum": 865,
    "col_tax_cousin_kingdom": 857891,
    "col_tax_fallback_kingdom": FALLBACK_TAX_ID,
    "col_tax_unknown_header": UNKNOWN_TAX_ID,
}


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
    parser.add_argument(
        "--focal-species-name",
        default="Staphylococcus aureus",
        help="Species label for taxon-filter edge case",
    )
    args = parser.parse_args()

    db = ensure_pipeline_built()
    conn = duckdb.connect(str(db), read_only=True)

    pipeline_doc = {
        "fixture": {
            "sample_id": SAMPLE_ID,
            "tsv": "fake_rpkm.tsv",
            "focal_ec": FOCAL_EC,
            "focal_tax_id": FOCAL_TAX_ID,
            "roles": {
                "fallback_tax_id": FALLBACK_TAX_ID,
                "unknown_tax_id": UNKNOWN_TAX_ID,
                "ec_focal": FOCAL_EC,
                "ec_alt": "1.5.8.1",
                "ec_diff_superpathway": "1.1.1.349",
                "ec_fallback_taxon": "2.1.1.158",
                "focal_superpathway": FOCAL_SUPERPATHWAY,
                **TAX_COLUMNS,
            },
        },
        "rollup_grid": dump_rollup_grid(conn, FOCAL_EC, FOCAL_TAX_ID),
    }
    conn.close()

    unfiltered = [
        dump_chord_case(rank, ann, case_id=f"{rank}_{ann}")
        for rank in RANKS
        for ann in ANN_LEVELS
    ]

    filtered = [
        dump_chord_case(
            "genus",
            "superpathway",
            case_id="taxon_filter_focal_species",
            selected_taxon={"level": "species", "name": args.focal_species_name},
        ),
        dump_chord_case(
            "phylum",
            "superpathway",
            case_id="ann_filter_superpathway",
            selected_ann_cat=FOCAL_SUPERPATHWAY,
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
