from __future__ import annotations

import duckdb
import pytest

from api.chord_service import build_chord_from_duckdb
from api.pathway_list_service import build_pathway_list_from_duckdb
from api.rollup_query import build_filtered_rollup_rows
from api.schemas import PathwayListResponse
from api.tax_lineage_order import tax_cat_order_for_ids_table
from testing.fake_rpkm_fixture import (
    DB_PATH,
    SAMPLE_ID,
    bridges_available,
    load_pathway_list_expectations,
    skip_reason,
)

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

    out = build_pathway_list_from_duckdb(
        names=names,
        tax_level=tax_level,
        selected_ann_cat=ann_filter,
        selected_taxon=selected_taxon,
    )
    assert isinstance(out, PathwayListResponse)
    pathways = out.pathways
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
    assert out.breakdowns
    for name in pathways:
        assert name in out.breakdowns
        vec = out.breakdowns[name]
        assert len(vec.index) == len(vec.counts)
        assert sum(vec.counts) > 0


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_pathway_breakdown_tax_index_respects_lineage_order(fake_rpkm_db):
    ann_filter = {"level": "superpathway", "name": SUPERPATHWAY}
    tax_level = "phylum"
    out = build_pathway_list_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level=tax_level,
        selected_ann_cat=ann_filter,
        selected_taxon={},
    )
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        build_filtered_rollup_rows(
            conn,
            tax_level=tax_level,
            ann_level="pathway",
            ann_filter=ann_filter,
            taxon_filter=None,
        )
        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE pathway_tax_ids AS
            SELECT DISTINCT source_tax_id
            FROM filtered_rollup_rows
            WHERE requested_rank = ?
              AND pathway_level = 'pathway'
            """,
            [tax_level],
        )
        tax_cat_order = tax_cat_order_for_ids_table(
            conn, tax_level=tax_level, ids_table="pathway_tax_ids"
        )
    finally:
        conn.close()

    pos = {cat: i for i, cat in enumerate(tax_cat_order)}
    for pathway, vec in out.breakdowns.items():
        for i in range(len(vec.index) - 1):
            assert pos[vec.index[i]] < pos[vec.index[i + 1]]


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.skip(reason="Task 5 updates YAML")
@pytest.mark.parametrize(
    "case_key",
    list(load_pathway_list_expectations()["pathway_list"].keys()),
)
def test_pathway_list_matches_golden(fake_rpkm_db, case_key):
    cases = load_pathway_list_expectations()["pathway_list"]
    case = cases[case_key]
    out = build_pathway_list_from_duckdb(
        names=case["names"],
        tax_level=case["tax_level"],
        selected_ann_cat=case["selected_ann_cat"],
        selected_taxon=case["selected_taxon"],
    )
    assert out.model_dump() == case["expected"]
    for pathway in out.pathways:
        assert sum(out.breakdowns[pathway].counts) > 0
