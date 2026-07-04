from __future__ import annotations

import duckdb
import pytest

from api.graph_service import _fetch_triples, build_graph_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_graph_from_duckdb_shape(fake_rpkm_db):
    out = build_graph_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level="phylum",
        ann_level="superpathway",
        selected_ann_cat={},
        selected_taxon={},
    )
    assert "inner_count_matrix" in out
    assert out["inner_matrix_index"][0] == "gap_1"
    assert len(out["inner_count_matrix"]) == len(out["inner_matrix_index"])
    assert out["tax_map"]


def test_build_graph_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_graph_from_duckdb(
            names=["a.tsv", "b.tsv"],
            tax_level="phylum",
            ann_level="superpathway",
            selected_ann_cat={},
            selected_taxon={},
        )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_graph_triples_no_fanout(fake_rpkm_db):
    conn = duckdb.connect(fake_rpkm_db, read_only=True)
    try:
        triples = _fetch_triples(
            conn, ann_filter=None, taxon_filter=None, ann_level="superpathway"
        )
        pairs = {(ec, tax_id) for ec, tax_id, _ in triples}
        assert len(triples) == len(pairs)
        raw = conn.execute(
            """
            SELECT ec_normalized, source_tax_id
            FROM int_rpkm_by_ec_tax
            WHERE value > 0
            """
        ).fetchall()
        assert len(triples) == len(set(raw))
    finally:
        conn.close()
