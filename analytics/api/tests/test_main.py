from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.chord_service import TRANSFORM_DIR

client = TestClient(app)
FIXTURE_DB = TRANSFORM_DIR / "runs/test_rpkm_1/sample.duckdb"


@pytest.mark.skipif(not FIXTURE_DB.exists(), reason="fixture not built")
def test_chord_endpoint_envelope():
    res = client.post(
        "/api/viz/chord",
        json={
            "names": ["test_rpkm_1.tsv"],
            "tax_level": "phylum",
            "ann_level": "superpathway",
            "selected_ann_cat": {},
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "count_matrix" in body["value"]


def test_chord_comparison_error_envelope():
    res = client.post(
        "/api/viz/chord",
        json={
            "names": ["a.tsv", "b.tsv"],
            "tax_level": "phylum",
            "ann_level": "superpathway",
            "selected_ann_cat": {},
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "comparison mode" in body["error"]
