from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api.config import Settings
from api.datasets.catalog import CatalogStore
from api.datasets.pipeline_runner import (
    PipelineRunner,
    ProgressEvent,
    parse_dbt_json_line,
)

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
        "info": {
            "name": "NodeStart",
            "level": "info",
            "code": "Q024",
        },
    }
)

FIXTURE_NODE_FINISHED = json.dumps(
    {
        "data": {
            "node_info": {
                "node_name": "int_rpkm_by_ec_tax",
                "node_started_at": "2026-07-16T12:00:00.000000",
                "node_finished_at": "2026-07-16T12:00:01.860000",
                "node_status": "success",
            },
            "run_result": {"execution_time": 1.86},
        },
        "info": {
            "name": "NodeFinished",
            "level": "info",
            "code": "Q025",
        },
    }
)

FIXTURE_LOG_TEST_RESULT = json.dumps(
    {
        "data": {
            "name": "not_null_int_rpkm_by_ec_tax_value",
            "status": "pass",
            "index": 2,
            "num_models": 23,
            "execution_time": 0.12,
            "node_info": {"node_name": "not_null_int_rpkm_by_ec_tax_value"},
        },
        "info": {
            "name": "LogTestResult",
            "level": "info",
            "code": "Q007",
        },
    }
)


def _settings(data_root: Path, runs_dir: Path) -> Settings:
    return Settings(
        data_root=data_root.resolve(),
        runs_dir=runs_dir.resolve(),
        reference_parquet_dir=Path("/unused"),
        enable_dev_datasets=False,
    )


def test_parse_node_start_maps_to_progress_event():
    counter = [0]
    event = parse_dbt_json_line(FIXTURE_NODE_START, step_counter=counter)

    assert event == ProgressEvent(
        kind="progress",
        data={"step": 1, "name": "int_rpkm_by_ec_tax", "state": "started"},
    )
    assert counter == [1]


def test_parse_node_finished_maps_to_progress_event():
    event = parse_dbt_json_line(FIXTURE_NODE_FINISHED)

    assert event == ProgressEvent(
        kind="progress",
        data={
            "name": "int_rpkm_by_ec_tax",
            "state": "finished",
            "elapsed_s": 1.86,
        },
    )


def test_parse_log_test_result_maps_to_progress_event():
    event = parse_dbt_json_line(FIXTURE_LOG_TEST_RESULT)

    assert event == ProgressEvent(
        kind="progress",
        data={
            "step": 2,
            "total": 23,
            "name": "not_null_int_rpkm_by_ec_tax_value",
            "state": "pass",
            "elapsed_s": 0.12,
        },
    )


def test_parse_ignores_non_json_and_unrelated_events():
    assert parse_dbt_json_line("not json") is None
    assert parse_dbt_json_line("") is None
    unrelated = json.dumps({"info": {"name": "MainReportVersion"}, "data": {}})
    assert parse_dbt_json_line(unrelated) is None


@pytest.mark.anyio
async def test_pipeline_runner_streams_fixture_lines_and_completes(tmp_path):
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    rpkm.parent.mkdir(parents=True)
    rpkm.write_text("gene\trpkm\n")

    settings = _settings(data_root, runs_dir)
    store = CatalogStore()
    store.refresh(settings)

    runner = PipelineRunner(store, settings)

    stdout_lines = [
        FIXTURE_NODE_START + "\n",
        FIXTURE_NODE_FINISHED + "\n",
        FIXTURE_LOG_TEST_RESULT + "\n",
    ]

    mock_proc = MagicMock()
    mock_proc.stdout = stdout_lines
    mock_proc.stderr = StringIO("")
    mock_proc.wait.return_value = 0
    mock_proc.returncode = 0

    def fake_popen(cmd, **kwargs):
        return mock_proc

    runner._popen = fake_popen  # type: ignore[method-assign]

    await runner.run("proj", rpkm)

    queue = runner.get_queue("proj")
    events: list[ProgressEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0].kind == "progress"
    assert events[0].data["state"] == "started"
    assert events[-1] == ProgressEvent(
        kind="complete",
        data={"status": "ready", "sample_id": "proj"},
    )
    assert store.active_sample_id == "proj"
    assert store.get_entry("proj") is not None
    assert store.get_entry("proj").status != "running"


@pytest.mark.anyio
async def test_pipeline_runner_emits_error_on_nonzero_exit(tmp_path):
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    rpkm.parent.mkdir(parents=True)
    rpkm.write_text("gene\trpkm\n")

    settings = _settings(data_root, runs_dir)
    store = CatalogStore()
    store.refresh(settings)
    store.set_running("proj")

    runner = PipelineRunner(store, settings)

    mock_proc = MagicMock()
    mock_proc.stdout = []
    mock_proc.stderr = StringIO("dbt build failed\n")
    mock_proc.wait.return_value = 1
    mock_proc.returncode = 1

    runner._popen = lambda cmd, **kwargs: mock_proc  # type: ignore[method-assign]

    await runner.run("proj", rpkm)

    queue = runner.get_queue("proj")
    event = queue.get_nowait()
    assert event.kind == "error"
    assert event.data["status"] == "failed"
    assert "dbt build failed" in event.data["message"]
    assert store.active_sample_id is None
    assert store.get_entry("proj").status != "running"
