import os
from pathlib import Path

from api.config import db_path, get_settings


def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_defaults(monkeypatch):
    monkeypatch.delenv("DATA_ROOT", raising=False)
    monkeypatch.delenv("RUNS_DIR", raising=False)
    _clear_settings_cache()
    s = get_settings()
    assert s.data_root.name  # Path exists conceptually
    assert s.runs_dir == s.data_root / "vis" / "runs"


def test_runs_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "custom-runs"))
    _clear_settings_cache()
    s = get_settings()
    assert s.runs_dir == (tmp_path / "custom-runs").resolve()


def test_reference_parquet_dir_default_resolves_from_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("REFERENCE_PARQUET_DIR", raising=False)
    _clear_settings_cache()
    expected = (
        Path(__file__).resolve().parent.parent.parent
        / "transform"
        / "reference"
        / "parquet"
    )
    original = os.getcwd()
    os.chdir(tmp_path)
    try:
        s = get_settings()
        assert s.reference_parquet_dir == expected.resolve()
    finally:
        os.chdir(original)
        _clear_settings_cache()


def test_enable_dev_datasets(monkeypatch):
    monkeypatch.setenv("ENABLE_DEV_DATASETS", "1")
    _clear_settings_cache()
    assert get_settings().enable_dev_datasets is True

    monkeypatch.setenv("ENABLE_DEV_DATASETS", "0")
    _clear_settings_cache()
    assert get_settings().enable_dev_datasets is False

    monkeypatch.delenv("ENABLE_DEV_DATASETS", raising=False)
    _clear_settings_cache()
    assert get_settings().enable_dev_datasets is False


def test_db_path(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    _clear_settings_cache()
    assert db_path("proj1__run2") == (tmp_path / "runs" / "proj1__run2" / "sample.duckdb").resolve()
