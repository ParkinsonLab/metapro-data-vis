from pathlib import Path

import pytest

from api.chord_service import TRANSFORM_DIR, build_chord_from_duckdb

FIXTURE_DB = TRANSFORM_DIR / "runs/test_rpkm_1/sample.duckdb"
pytestmark = pytest.mark.skipif(
    not FIXTURE_DB.exists(), reason="run_pipeline.py fixture not built"
)


def test_build_chord_from_duckdb_shape():
    out = build_chord_from_duckdb(
        sample_id="test_rpkm_1",
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
    )
    assert "count_matrix" in out
    assert out["index"][0] == "gap_1"
    assert len(out["count_matrix"]) == len(out["index"])


def test_build_chord_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_chord_from_duckdb(
            sample_id="test_rpkm_1",
            tax_level="phylum",
            ann_level="superpathway",
            ann_filter=None,
            taxon_filter=None,
            names=["a.tsv", "b.tsv"],
        )
