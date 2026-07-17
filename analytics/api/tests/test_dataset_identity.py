from pathlib import Path

import pytest

from api.datasets.identity import dev_fixture_sample_id, sample_id_from_path


def test_sample_id_nested_path(tmp_path):
    data_root = tmp_path / "data"
    rpkm = data_root / "proj1" / "run2" / "RPKM_table.tsv"
    assert sample_id_from_path(data_root, rpkm) == "proj1__run2"


def test_sample_id_single_segment(tmp_path):
    data_root = tmp_path / "data"
    rpkm = data_root / "run1" / "RPKM_table.tsv"
    assert sample_id_from_path(data_root, rpkm) == "run1"


def test_sample_id_root_level(tmp_path):
    data_root = tmp_path / "data"
    rpkm = data_root / "RPKM_table.tsv"
    assert sample_id_from_path(data_root, rpkm) == "_root"


def test_sample_id_root_absolute():
    data_root = Path("/data")
    rpkm = Path("/data/RPKM_table.tsv")
    assert sample_id_from_path(data_root, rpkm) == "_root"


def test_sample_id_nested_absolute():
    data_root = Path("/data")
    rpkm = Path("/data/proj1/run2/RPKM_table.tsv")
    assert sample_id_from_path(data_root, rpkm) == "proj1__run2"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("test_rpkm_1.tsv", "test_rpkm_1"),
        ("test_rpkm_2.tsv", "test_rpkm_2"),
        ("fake_rpkm.tsv", "fake_rpkm"),
        ("stress_rpkm_1.tsv", "stress_rpkm_1"),
    ],
)
def test_dev_fixture_sample_id(filename, expected):
    assert dev_fixture_sample_id(filename) == expected


def test_dev_fixture_sample_id_accepts_path():
    assert dev_fixture_sample_id(Path("test_rpkm_1.tsv")) == "test_rpkm_1"
