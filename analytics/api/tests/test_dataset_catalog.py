import json
import threading
from pathlib import Path

import pytest

from api.config import Settings, get_settings
from api.datasets.catalog import CatalogStore, DatasetEntry, scan_datasets


def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def _settings(data_root: Path, runs_dir: Path | None = None, *, dev: bool = False) -> Settings:
    return Settings(
        data_root=data_root.resolve(),
        runs_dir=(runs_dir or data_root / "vis" / "runs").resolve(),
        reference_parquet_dir=Path("/unused"),
        enable_dev_datasets=dev,
    )


def _write_rpkm(path: Path, content: str = "gene\trpkm\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _write_run_context(
    runs_dir: Path,
    sample_id: str,
    *,
    rpkm_path: Path,
    mtime: int,
    size: int,
    overall_status: str = "success",
    run_at: str = "2026-07-16T12:00:00+00:00",
) -> None:
    run_dir = runs_dir / sample_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "sample.duckdb").write_bytes(b"duckdb")
    context = {
        "sample_id": sample_id,
        "rpkm_path": str(rpkm_path),
        "rpkm_mtime": mtime,
        "rpkm_size": size,
        "overall_status": overall_status,
        "run_at": run_at,
    }
    (run_dir / "run_context.json").write_text(json.dumps(context))


def test_scan_discovers_rpkm_under_data_root(tmp_path):
    data_root = tmp_path / "data"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)

    entries = scan_datasets(_settings(data_root))

    assert len(entries) == 1
    entry = entries[0]
    assert entry.sample_id == "proj"
    assert entry.path == rpkm.resolve()
    assert entry.status == "discovered"
    assert entry.is_dev_fixture is False
    assert entry.last_run_at is None
    assert entry.last_error is None
    assert entry.mtime == int(rpkm.stat().st_mtime)
    assert entry.size == rpkm.stat().st_size


def test_scan_excludes_vis_subtree(tmp_path):
    data_root = tmp_path / "data"
    _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    vis_db = data_root / "vis" / "runs" / "x" / "sample.duckdb"
    vis_db.parent.mkdir(parents=True)
    vis_db.write_bytes(b"duckdb")
    _write_rpkm(data_root / "vis" / "nested" / "RPKM_table.tsv")

    entries = scan_datasets(_settings(data_root))

    assert [e.sample_id for e in entries] == ["proj"]


def test_scan_ready_when_run_context_matches_mtime_size(tmp_path):
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
    )

    entries = scan_datasets(_settings(data_root, runs_dir))

    assert entries[0].status == "ready"
    assert entries[0].last_run_at == "2026-07-16T12:00:00+00:00"
    assert entries[0].last_error is None


def test_scan_stale_when_mtime_or_size_differs(tmp_path):
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=1,
        size=2,
    )

    entries = scan_datasets(_settings(data_root, runs_dir))

    assert entries[0].status == "stale"


def test_scan_failed_when_overall_status_not_success(tmp_path):
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
        overall_status="error",
    )

    entries = scan_datasets(_settings(data_root, runs_dir))

    assert entries[0].status == "failed"


def test_scan_merges_dev_fixtures_when_enabled(tmp_path):
    data_root = tmp_path / "data"
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    fake_rpkm = repo_root / "analytics" / "transform" / "tests" / "fixtures" / "fake_rpkm.tsv"
    if not fake_rpkm.is_file():
        pytest.skip("fake_rpkm.tsv fixture missing")

    entries = scan_datasets(_settings(data_root, dev=True))

    fixture_ids = {e.sample_id for e in entries if e.is_dev_fixture}
    assert "fake_rpkm" in fixture_ids
    assert "test_rpkm_1" in fixture_ids
    assert "test_rpkm_2" in fixture_ids
    fake = next(e for e in entries if e.sample_id == "fake_rpkm")
    assert fake.path == fake_rpkm.resolve()
    assert fake.is_dev_fixture is True


def test_scan_omits_dev_fixtures_when_disabled(tmp_path):
    data_root = tmp_path / "data"

    entries = scan_datasets(_settings(data_root, dev=False))

    assert all(not e.is_dev_fixture for e in entries)


def test_catalog_store_refresh_and_running_override(tmp_path):
    data_root = tmp_path / "data"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    settings = _settings(data_root)
    store = CatalogStore()

    store.refresh(settings)
    assert store.get_entry("proj").status == "discovered"

    store.set_running("proj")
    assert store.get_entry("proj").status == "running"

    store.set_running(None)
    assert store.get_entry("proj").status == "discovered"


def test_catalog_store_active_sample_id(tmp_path):
    data_root = tmp_path / "data"
    _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    store = CatalogStore()
    store.refresh(_settings(data_root))

    assert store.active_sample_id is None
    store.set_active("proj")
    assert store.active_sample_id == "proj"


def test_catalog_store_thread_safe_refresh(tmp_path):
    data_root = tmp_path / "data"
    _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    settings = _settings(data_root)
    store = CatalogStore()
    errors: list[str] = []

    def worker() -> None:
        try:
            for _ in range(20):
                store.refresh(settings)
                store.get_catalog()
        except Exception as exc:  # pragma: no cover
            errors.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(store.get_catalog()) == 1


def test_dataset_entry_is_dataclass():
    entry = DatasetEntry(
        sample_id="proj",
        path=Path("/data/proj/RPKM_table.tsv"),
        status="discovered",
        last_run_at=None,
        last_error=None,
        is_dev_fixture=False,
        mtime=1,
        size=2,
    )
    assert entry.sample_id == "proj"
