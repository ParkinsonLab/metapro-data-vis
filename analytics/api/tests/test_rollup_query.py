import pytest
from api.chord_service import build_chord_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_chord_matrix_unchanged_after_rollup_extraction(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
        names=[f"{SAMPLE_ID}.tsv"],
    )
    assert len(out["index"]) > 0
    assert len(out["count_matrix"]) == len(out["index"])
