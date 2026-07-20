"""Integration tests: dataset pipeline failure on invalid RPKM input."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from api.config import Settings, get_settings
from api.datasets.catalog import CatalogStore
from api.datasets.pipeline_runner import PipelineRunner
from api.datasets.routes import reset_dataset_services
from testing.bad_rpkm_fixtures import BAD_RPKM_EMPTY, BAD_RPKM_EMPTY_MART
from testing.fake_rpkm_fixture import REFERENCE_PARQUET_DIR, bridges_available, skip_reason

pytestmark = pytest.mark.skipif(not bridges_available(), reason=skip_reason())


@pytest.fixture
def real_reference_parquet(monkeypatch):
    monkeypatch.setenv("REFERENCE_PARQUET_DIR", str(REFERENCE_PARQUET_DIR))
    get_settings.cache_clear()
    reset_dataset_services()
    yield REFERENCE_PARQUET_DIR
    reset_dataset_services()
    get_settings.cache_clear()


def _settings(data_root: Path, runs_dir: Path) -> Settings:
    return Settings(
        data_root=data_root.resolve(),
        runs_dir=runs_dir.resolve(),
        reference_parquet_dir=REFERENCE_PARQUET_DIR.resolve(),
        enable_dev_datasets=False,
    )


@pytest.mark.anyio
async def test_pipeline_runner_empty_rpkm_emits_error_and_catalog_failed(
    tmp_path: Path,
    real_reference_parquet,
) -> None:
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    rpkm.parent.mkdir(parents=True)
    shutil.copy(BAD_RPKM_EMPTY, rpkm)

    settings = _settings(data_root, runs_dir)
    store = CatalogStore()
    store.refresh(settings)
    runner = PipelineRunner(store, settings)

    await runner.run("proj", rpkm)

    queue = runner.get_queue("proj")
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert events
    assert events[-1].kind == "error"
    assert events[-1].data["status"] == "failed"
    assert "RPKM file is empty" in events[-1].data["message"]

    entry = store.get_entry("proj")
    assert entry is not None
    assert entry.status == "failed"
    assert entry.last_error is not None
    assert "RPKM file is empty" in entry.last_error
    assert store.active_sample_id is None
    assert store.running_sample_id is None


@pytest.mark.anyio
async def test_pipeline_runner_empty_mart_rpkm_fails_assertion(
    tmp_path: Path,
    real_reference_parquet,
) -> None:
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    rpkm.parent.mkdir(parents=True)
    shutil.copy(BAD_RPKM_EMPTY_MART, rpkm)

    settings = _settings(data_root, runs_dir)
    store = CatalogStore()
    store.refresh(settings)
    runner = PipelineRunner(store, settings)

    await runner.run("proj", rpkm)

    queue = runner.get_queue("proj")
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert events[-1].kind == "error"
    assert events[-1].data["message"] == "Assertion failed: assert_mart_nonempty"

    entry = store.get_entry("proj")
    assert entry is not None
    assert entry.status == "failed"
    assert entry.last_error == "Assertion failed: assert_mart_nonempty"
