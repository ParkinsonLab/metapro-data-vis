import pytest
from fastapi.testclient import TestClient

from api.config import db_path
from api.main import app
from testing.fake_rpkm_fixture import bridges_available, skip_reason


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


FIXTURE_DB = db_path("test_rpkm_1")


@pytest.mark.skipif(not FIXTURE_DB.exists(), reason="fixture not built")
def test_chord_endpoint_envelope(client):
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


def test_chord_comparison_error_envelope(client):
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


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_overview_endpoint_envelope(client, fake_rpkm_db):
    res = client.post("/api/viz/overview", json={"names": ["fake_rpkm.tsv"]})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "counts_data" in body["value"]
    assert "ann_data" in body["value"]


def test_overview_comparison_error_envelope(client):
    res = client.post("/api/viz/overview", json={"names": ["a.tsv", "b.tsv"]})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "comparison mode" in body["error"]


def test_krona_endpoint_envelope(client, fake_rpkm_db):
    res = client.post(
        "/api/viz/krona",
        json={"names": ["fake_rpkm.tsv"], "tax_rank": "phylum", "selected_taxon": {}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["value"]["id"] == "root"
    assert "children" in body["value"]


def test_krona_comparison_error_envelope(client):
    res = client.post(
        "/api/viz/krona",
        json={"names": ["a.tsv", "b.tsv"], "tax_rank": "phylum", "selected_taxon": {}},
    )
    body = res.json()
    assert body["ok"] is False
    assert "comparison mode" in body["error"]


def test_pathway_list_endpoint_ok(client, fake_rpkm_db):
    if not bridges_available():
        pytest.skip(skip_reason())
    res = client.post(
        "/api/viz/pathway-list",
        json={
            "names": ["fake_rpkm.tsv"],
            "tax_level": "phylum",
            "selected_ann_cat": {"level": "superpathway", "name": "Energy metabolism"},
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    value = body["value"]
    assert isinstance(value, dict)
    assert "pathways" in value
    assert "breakdowns" in value
    assert isinstance(value["pathways"], list)
    assert len(value["pathways"]) > 0
    assert value["pathways"][0] in value["breakdowns"]


def test_pathway_list_missing_ann_cat_error_envelope(client):
    res = client.post(
        "/api/viz/pathway-list",
        json={
            "names": ["fake_rpkm.tsv"],
            "tax_level": "phylum",
            "selected_ann_cat": {},
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "selected_ann_cat is required" in body["error"]


def test_graph_endpoint_envelope(client, fake_rpkm_db):
    if not bridges_available():
        pytest.skip(skip_reason())
    res = client.post(
        "/api/viz/graph",
        json={
            "names": ["fake_rpkm.tsv"],
            "tax_level": "phylum",
            "selected_ann_cat": {
                "level": "pathway",
                "name": "Oxidative phosphorylation",
            },
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "inner_count_matrix" in body["value"]


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_network_endpoint(client, fake_rpkm_db):
    res = client.post(
        "/api/viz/network",
        json={
            "names": ["fake_rpkm.tsv"],
            "tax_level": "phylum",
            "selected_taxon": {},
            "pathway_name": "Oxidative phosphorylation",
            "width": 900,
            "height": 550,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["value"]["nodes"]
