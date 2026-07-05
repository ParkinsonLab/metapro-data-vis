"""Generate golden YAML from built fake_rpkm DuckDB. Run once after TSV is final."""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import yaml

from api.chord_service import build_chord_from_duckdb
from api.filters import normalise_ann_filter, normalise_taxon_filter
from api.graph_service import build_graph_from_duckdb
from api.krona_service import build_krona_from_duckdb
from api.overview_service import build_overview_from_duckdb
from testing.fake_rpkm_fixture import (
    ANN_LEVELS,
    CHORD_YAML,
    GRAPH_YAML,
    KRONA_YAML,
    OVERVIEW_YAML,
    PIPELINE_YAML,
    RANKS,
    SAMPLE_ID,
    ensure_pipeline_built,
    extract_chord_index,
    extract_chord_pairs,
    extract_graph_inner_index,
    extract_graph_outer_index,
    extract_graph_pairs,
    extract_graph_tax_map,
)

FOCAL_EC = "1.6.5.9"
EC_SAME_PATHWAY = "2.7.4.1"
EC_ALT = "1.5.8.1"
EC_DIFF_SP = "1.1.1.349"
FOCAL_TAX_ID = 1280
FALLBACK_TAX_ID = 2
UNKNOWN_TAX_ID = 999999999
FOCAL_SUPERPATHWAY = "Energy metabolism"
FOCAL_PATHWAY = "Oxidative phosphorylation"
FOCAL_PATHWAY_ALT = "Methane metabolism"
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


def dump_krona_case(tax_rank: str) -> dict:
    return build_krona_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_rank=tax_rank,
        selected_taxon={},
    ).model_dump(exclude_none=True)


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
    case["expected_index"] = extract_chord_index(out)
    for key in ("selected_ann_cat", "selected_taxon"):
        if key in filters:
            case[key] = filters[key]
    return case


def dump_graph_case(tax_level: str, **filters) -> dict:
    selected_ann_cat = filters.get("selected_ann_cat")
    if selected_ann_cat is None:
        raise ValueError(f"{filters.get('case_id', tax_level)}: selected_ann_cat required")
    out = build_graph_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level=tax_level,
        selected_ann_cat=selected_ann_cat,
        selected_taxon=filters.get("selected_taxon", {}),
    )
    pairs = extract_graph_pairs(out)
    case = {
        "case_id": filters.get("case_id", tax_level),
        "tax_level": tax_level,
        "selected_ann_cat": selected_ann_cat,
        "pairs": [[ec, tax, v] for ec, tax, v in pairs],
        "expected_inner_index": extract_graph_inner_index(out),
        "expected_outer_index": extract_graph_outer_index(out),
        "tax_map": extract_graph_tax_map(out),
    }
    if "selected_taxon" in filters:
        case["selected_taxon"] = filters["selected_taxon"]
    return case


def dump_graph_expectations(focal_species_name: str) -> None:
    """Hand-picked graph scenarios — pathway filter required."""
    ensure_pipeline_built()
    pathway = {"level": "pathway", "name": FOCAL_PATHWAY}
    pathway_alt = {"level": "pathway", "name": FOCAL_PATHWAY_ALT}
    cases = [
        dump_graph_case(
            "phylum",
            case_id="pathway_phylum_baseline",
            selected_ann_cat=pathway,
        ),
        dump_graph_case(
            "species",
            case_id="pathway_species_tax_rank",
            selected_ann_cat=pathway,
        ),
        dump_graph_case(
            "kingdom",
            case_id="pathway_kingdom_tax_rank",
            selected_ann_cat=pathway,
        ),
        dump_graph_case(
            "genus",
            case_id="pathway_and_taxon_filter",
            selected_ann_cat=pathway,
            selected_taxon={"level": "species", "name": focal_species_name},
        ),
        dump_graph_case(
            "phylum",
            case_id="pathway_methane_metabolism",
            selected_ann_cat=pathway_alt,
        ),
    ]
    graph_doc = {
        "sample_id": SAMPLE_ID,
        "cases": cases,
    }
    GRAPH_YAML.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_YAML.write_text(yaml.safe_dump(graph_doc, sort_keys=False), encoding="utf-8")
    print(f"Wrote {GRAPH_YAML}")


def dump_krona_expectations() -> None:
    ensure_pipeline_built()
    krona_doc = {
        "sample_id": SAMPLE_ID,
        "krona_phylum": dump_krona_case("phylum"),
        "krona_genus": dump_krona_case("genus"),
    }
    KRONA_YAML.parent.mkdir(parents=True, exist_ok=True)
    KRONA_YAML.write_text(yaml.safe_dump(krona_doc, sort_keys=False), encoding="utf-8")
    print(f"Wrote {KRONA_YAML}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--focal-species-name",
        default="Staphylococcus aureus",
        help="Species label for taxon-filter edge case",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Write graph_expectations.yaml only",
    )
    parser.add_argument(
        "--krona",
        action="store_true",
        help="Write krona_expectations.yaml only",
    )
    args = parser.parse_args()

    if args.graph:
        dump_graph_expectations(args.focal_species_name)
        return

    if args.krona:
        dump_krona_expectations()
        return

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
                "ec_same_pathway": EC_SAME_PATHWAY,
                "ec_alt": EC_ALT,
                "ec_diff_superpathway": EC_DIFF_SP,
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

    overview_out = build_overview_from_duckdb(names=[f"{SAMPLE_ID}.tsv"])
    overview_doc = {
        "sample_id": SAMPLE_ID,
        "overview": {
            "counts_data": overview_out.counts_data.model_dump(),
            "ann_data": overview_out.ann_data.model_dump(),
        },
    }

    graph_doc = {
        "sample_id": SAMPLE_ID,
        "graph_unfiltered": [
            dump_graph_case(rank, ann, case_id=f"{rank}_{ann}")
            for rank in RANKS
            for ann in ANN_LEVELS
        ],
        "graph_filtered": [
            dump_graph_case(
                "genus",
                "superpathway",
                case_id="taxon_filter_focal_species",
                selected_taxon={"level": "species", "name": args.focal_species_name},
            ),
            dump_graph_case(
                "phylum",
                "superpathway",
                case_id="ann_filter_superpathway",
                selected_ann_cat=FOCAL_SUPERPATHWAY,
            ),
        ],
        "edge_cases": [
            dump_graph_case("phylum", "superpathway", case_id="unmapped_ec_snapshot"),
            dump_graph_case("phylum", "superpathway", case_id="unclassified_tax_snapshot"),
            dump_graph_case("species", "superpathway", case_id="fallback_species_request"),
        ],
    }

    PIPELINE_YAML.write_text(yaml.safe_dump(pipeline_doc, sort_keys=False), encoding="utf-8")
    CHORD_YAML.parent.mkdir(parents=True, exist_ok=True)
    CHORD_YAML.write_text(yaml.safe_dump(chord_doc, sort_keys=False), encoding="utf-8")
    OVERVIEW_YAML.write_text(
        yaml.safe_dump(overview_doc, sort_keys=False), encoding="utf-8"
    )
    GRAPH_YAML.write_text(yaml.safe_dump(graph_doc, sort_keys=False), encoding="utf-8")
    print(f"Wrote {PIPELINE_YAML}")
    print(f"Wrote {CHORD_YAML}")
    print(f"Wrote {OVERVIEW_YAML}")
    print(f"Wrote {GRAPH_YAML}")


if __name__ == "__main__":
    main()
