from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import anyio
import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.datasets.pipeline_runner import ProgressEvent
from api.datasets.routes import get_catalog_store, get_pipeline_runner, reset_dataset_services
from api.main import app

FIXTURE_NODE_START = json.dumps(
    {
        "data": {
            "node_info": {
                "node_name": "int_rpkm_by_ec_tax",
                "node_path": "models/int_rpkm_by_ec_tax.sql",
                "resource_type": "model",
                "node_status": "started",
                "unique_id": "model.metapro.int_rpkm_by_ec_tax",
            }
        },
        "info": {"name": "NodeStart", "level": "info", "code": "Q024"},
    }
)


def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def _settings(data_root: Path, runs_dir: Path | None = None, *, dev: bool = False) -> Settings:
    return Settings(
        data_root=data_root.resolve(),
        runs_dir=(runs_dir or data_root / "vis" / "runs").resolve(),
        reference_parquet_dir=Path("/unused"),
        enable_dev_datasets=dev,
    )


def _write_rpkm(path: Path, content: str = "gene\trpkm\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _write_run_context(
    runs_dir: Path,
    sample_id: str,
    *,
    rpkm_path: Path,
    mtime: int,
    size: int,
    overall_status: str = "success",
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
        "run_at": "2026-07-16T12:00:00+00:00",
    }
    (run_dir / "run_context.json").write_text(json.dumps(context))


@pytest.fixture
def dataset_env(tmp_path, monkeypatch, reference_parquet_env):
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("ENABLE_DEV_DATASETS", "0")
    _clear_settings_cache()
    reset_dataset_services()
    settings = _settings(data_root, runs_dir)
    store = get_catalog_store()
    store.refresh(settings)
    runner = get_pipeline_runner()
    with TestClient(app) as client:
        yield client, store, runner, settings, data_root, runs_dir
    reset_dataset_services()
    _clear_settings_cache()


def test_list_datasets_returns_catalog_and_active_sample_id(dataset_env):
    client, store, _runner, settings, data_root, _runs_dir = dataset_env
    rpkm = _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    store.refresh(settings)
    store.set_active("proj")

    res = client.get("/api/datasets")

    assert res.status_code == 200
    body = res.json()
    assert body["active_sample_id"] == "proj"
    assert len(body["datasets"]) == 1
    entry = body["datasets"][0]
    assert entry["sample_id"] == "proj"
    assert entry["path"] == str(rpkm.resolve())
    assert entry["status"] == "discovered"
    assert entry["is_dev_fixture"] is False


def test_refresh_rescans_catalog(dataset_env):
    client, store, _runner, settings, data_root, _runs_dir = dataset_env
    assert client.get("/api/datasets").json()["datasets"] == []

    _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    res = client.post("/api/datasets/refresh")

    assert res.status_code == 200
    body = res.json()
    assert len(body["datasets"]) == 1
    assert body["datasets"][0]["sample_id"] == "proj"
    assert store.get_entry("proj") is not None


def test_select_ready_when_fresh(dataset_env):
    client, store, _runner, settings, data_root, runs_dir = dataset_env
    rpkm = _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
    )
    store.refresh(settings)

    res = client.post("/api/datasets/select", json={"sample_id": "proj"})

    assert res.status_code == 200
    assert res.json() == {"status": "ready"}
    assert store.active_sample_id == "proj"


def test_select_unknown_sample_returns_404(dataset_env):
    client, _store, _runner, _settings, _data_root, _runs_dir = dataset_env

    res = client.post("/api/datasets/select", json={"sample_id": "missing"})

    assert res.status_code == 404


def test_select_conflict_when_another_running_returns_409(dataset_env):
    client, store, _runner, settings, data_root, _runs_dir = dataset_env
    _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    _write_rpkm(data_root / "other" / "RPKM_table.tsv")
    store.refresh(settings)
    store.set_running("proj")

    res = client.post("/api/datasets/select", json={"sample_id": "other"})

    assert res.status_code == 409


def test_select_idempotent_when_same_running(dataset_env):
    client, store, _runner, settings, data_root, _runs_dir = dataset_env
    _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    store.refresh(settings)
    store.set_running("proj")

    res = client.post("/api/datasets/select", json={"sample_id": "proj"})

    assert res.status_code == 200
    assert res.json() == {"status": "running"}


def test_select_stale_starts_pipeline(dataset_env):
    client, store, runner, settings, data_root, runs_dir = dataset_env
    rpkm = _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=1,
        size=2,
    )
    store.refresh(settings)

    mock_proc = MagicMock()
    mock_proc.stdout = [FIXTURE_NODE_START + "\n"]
    mock_proc.stderr = StringIO("")
    mock_proc.wait.return_value = 0
    runner._popen = lambda cmd, **kwargs: mock_proc  # type: ignore[method-assign]

    res = client.post("/api/datasets/select", json={"sample_id": "proj"})

    assert res.status_code == 200
    assert res.json() == {"status": "running", "sample_id": "proj"}


def test_sse_streams_progress_and_complete(dataset_env):
    _client, store, runner, settings, data_root, runs_dir = dataset_env
    rpkm = _write_rpkm(data_root / "proj" / "RPKM_table.tsv")
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=1,
        size=2,
    )
    store.refresh(settings)

    mock_proc = MagicMock()
    mock_proc.stdout = [FIXTURE_NODE_START + "\n"]
    mock_proc.stderr = StringIO("")
    mock_proc.wait.return_value = 0
    runner._popen = lambda cmd, **kwargs: mock_proc  # type: ignore[method-assign]

    events: list[tuple[str, dict]] = []

    async def _run_select_and_stream() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            select_res = await http_client.post(
                "/api/datasets/select",
                json={"sample_id": "proj"},
            )
            assert select_res.status_code == 200

            async with http_client.stream("GET", "/api/datasets/proj/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        kind = None
                        data = None
                        for line in block.splitlines():
                            if line.startswith("event: "):
                                kind = line.removeprefix("event: ")
                            elif line.startswith("data: "):
                                data = json.loads(line.removeprefix("data: "))
                        if kind is not None and data is not None:
                            events.append((kind, data))
                        if events and events[-1][0] in ("complete", "error"):
                            return

    anyio.run(_run_select_and_stream)

    assert events[0][0] == "progress"
    assert events[0][1]["state"] == "started"
    assert events[-1] == (
        "complete",
        {"status": "ready", "sample_id": "proj"},
    )
    assert store.active_sample_id == "proj"
