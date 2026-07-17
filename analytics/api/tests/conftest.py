from __future__ import annotations

from pathlib import Path

import pytest

from api.config import get_settings
from api.datasets.routes import reset_dataset_services
from api.datasets.watcher import REQUIRED_REFERENCE_PARQUETS


def _write_reference_parquet_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_REFERENCE_PARQUETS:
        (path / name).write_bytes(b"PAR1")


@pytest.fixture(autouse=True)
def reference_parquet_env(monkeypatch, tmp_path):
    ref_dir = tmp_path / "reference_parquet"
    _write_reference_parquet_dir(ref_dir)
    monkeypatch.setenv("REFERENCE_PARQUET_DIR", str(ref_dir))
    get_settings.cache_clear()
    reset_dataset_services()
    yield ref_dir
    reset_dataset_services()
    get_settings.cache_clear()
