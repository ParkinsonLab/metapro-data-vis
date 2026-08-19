from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api.config import Settings
from api.datasets.catalog import CatalogStore
from api.datasets.watcher import (
    CatalogEventHandler,
    DatasetWatcher,
    Debouncer,
    check_reference_parquet,
    event_path_triggers_refresh,
)


def _settings(data_root: Path, ref_dir: Path) -> Settings:
    return Settings(
        data_root=data_root.resolve(),
        runs_dir=(data_root / "vis" / "runs").resolve(),
        reference_parquet_dir=ref_dir.resolve(),
        enable_dev_datasets=False,
    )


def test_event_path_triggers_refresh_outside_vis(tmp_path):
    data_root = tmp_path / "data"
    vis_root = data_root / "vis"
    data_root.mkdir()
    vis_root.mkdir(parents=True)

    assert event_path_triggers_refresh(data_root / "proj" / "RPKM_table.tsv", data_root, vis_root)
    assert not event_path_triggers_refresh(vis_root / "runs" / "x" / "sample.duckdb", data_root, vis_root)
    assert not event_path_triggers_refresh(tmp_path / "outside.txt", data_root, vis_root)


def test_check_reference_parquet_raises_when_missing(tmp_path):
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    settings = _settings(tmp_path / "data", ref_dir)

    with pytest.raises(RuntimeError, match="bridge_ec_pathway.parquet"):
        check_reference_parquet(settings)


def test_check_reference_parquet_passes_when_present(tmp_path):
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "bridge_ec_pathway.parquet").write_bytes(b"x")
    (ref_dir / "bridge_tax_lineage.parquet").write_bytes(b"x")
    settings = _settings(tmp_path / "data", ref_dir)

    check_reference_parquet(settings)


def test_debouncer_coalesces_rapid_triggers():
    calls: list[int] = []

    def callback() -> None:
        calls.append(1)

    debouncer = Debouncer(0.05, callback)
    debouncer.trigger()
    debouncer.trigger()
    debouncer.trigger()
    time.sleep(0.15)
    debouncer.cancel()

    assert len(calls) == 1


def test_debouncer_cancel_prevents_callback():
    calls: list[int] = []

    debouncer = Debouncer(0.05, lambda: calls.append(1))
    debouncer.trigger()
    debouncer.cancel()
    time.sleep(0.1)

    assert calls == []


def test_catalog_event_handler_triggers_debouncer(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    calls: list[int] = []
    debouncer = Debouncer(0.01, lambda: calls.append(1))
    handler = CatalogEventHandler(data_root, data_root / "vis", debouncer)

    class Event:
        src_path = str(data_root / "proj" / "RPKM_table.tsv")
        is_directory = False

    handler.on_any_event(Event())
    time.sleep(0.05)
    debouncer.cancel()
    assert calls == [1]


def test_catalog_event_handler_skips_vis_events(tmp_path):
    data_root = tmp_path / "data"
    vis_root = data_root / "vis"
    vis_root.mkdir(parents=True)
    calls: list[int] = []
    debouncer = Debouncer(0.01, lambda: calls.append(1))
    handler = CatalogEventHandler(data_root, vis_root, debouncer)

    class Event:
        src_path = str(vis_root / "runs" / "x" / "sample.duckdb")
        is_directory = False

    handler.on_any_event(Event())
    time.sleep(0.05)
    debouncer.cancel()

    assert calls == []


def test_dataset_watcher_start_stop_with_mock_observer(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "bridge_ec_pathway.parquet").write_bytes(b"x")
    (ref_dir / "bridge_tax_lineage.parquet").write_bytes(b"x")

    observer = MagicMock()
    store = CatalogStore()
    settings = _settings(data_root, ref_dir)
    watcher = DatasetWatcher(store, settings, observer_factory=lambda: observer)

    watcher.start()
    observer.schedule.assert_called_once()
    observer.start.assert_called_once()

    watcher.stop()
    observer.stop.assert_called_once()
    observer.join.assert_called_once()


def test_dataset_watcher_debounced_refresh_calls_store(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "bridge_ec_pathway.parquet").write_bytes(b"x")
    (ref_dir / "bridge_tax_lineage.parquet").write_bytes(b"x")

    rpkm = data_root / "proj" / "RPKM_table.tsv"
    rpkm.parent.mkdir(parents=True)
    rpkm.write_text("gene\trpkm\n")

    store = CatalogStore()
    settings = _settings(data_root, ref_dir)
    watcher = DatasetWatcher(
        store,
        settings,
        debounce_seconds=0.05,
        observer_factory=lambda: MagicMock(),
    )

    watcher.start()
    try:
        handler = watcher._observer.schedule.call_args[0][0]
        handler.on_any_event(
            type("Event", (), {"src_path": str(rpkm), "is_directory": False})()
        )
        time.sleep(0.15)
        catalog = store.get_catalog()
        assert len(catalog) == 1
        assert catalog[0].sample_id == "proj"
    finally:
        watcher.stop()
