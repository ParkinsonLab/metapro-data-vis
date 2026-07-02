from __future__ import annotations

import pytest

from api.chord_service import build_chord_from_duckdb
from api.pathway_list_service import build_pathway_list_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason

SUPERPATHWAY = "Energy metabolism"


def test_pathway_list_rejects_empty_names():
    with pytest.raises(ValueError, match="at least one sample"):
        build_pathway_list_from_duckdb(
            names=[],
            tax_level="phylum",
            selected_ann_cat={"level": "superpathway", "name": SUPERPATHWAY},
            selected_taxon={},
        )


def test_pathway_list_rejects_inactive_ann_cat():
    with pytest.raises(ValueError, match="selected_ann_cat is required"):
        build_pathway_list_from_duckdb(
            names=[f"{SAMPLE_ID}.tsv"],
            tax_level="phylum",
            selected_ann_cat={},
            selected_taxon={},
        )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_pathway_list_alphabetical_and_matches_chord_set(fake_rpkm_db):
    ann_filter = {"level": "superpathway", "name": SUPERPATHWAY}
    names = [f"{SAMPLE_ID}.tsv"]
    tax_level = "phylum"
    selected_taxon = {}

    pathways = build_pathway_list_from_duckdb(
        names=names,
        tax_level=tax_level,
        selected_ann_cat=ann_filter,
        selected_taxon=selected_taxon,
    )
    assert pathways == sorted(pathways)
    assert len(pathways) > 0

    chord = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level=tax_level,
        ann_level="pathway",
        ann_filter=ann_filter,
        taxon_filter=None,
        names=names,
    )
    gap1 = chord["index"].index("gap_1")
    gap2 = chord["index"].index("gap_2")
    chord_pathways = set(chord["index"][gap1 + 1 : gap2])
    assert set(pathways) == chord_pathways
