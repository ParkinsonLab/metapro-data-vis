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

FIXTURE_LOG_START_LINE = json.dumps(
    {
        "data": {
            "description": "sql table model main.int_rpkm_by_ec_tax",
            "index": 1,
            "total": 23,
            "node_info": {
                "node_name": "int_rpkm_by_ec_tax",
                "resource_type": "model",
                "node_status": "started",
                "node_started_at": "2026-07-17T14:43:13.892217",
                "node_finished_at": "",
            },
        },
        "info": {
            "name": "LogStartLine",
            "level": "info",
            "code": "Q011",
        },
    }
)

FIXTURE_LOG_MODEL_RESULT = json.dumps(
    {
        "data": {
            "description": "sql table model main.int_rpkm_by_ec_tax",
            "execution_time": 0.049499035,
            "index": 1,
            "node_info": {
                "node_name": "int_rpkm_by_ec_tax",
                "resource_type": "model",
                "node_status": "success",
            },
            "status": "OK",
            "total": 23,
        },
        "info": {
            "name": "LogModelResult",
            "level": "info",
            "code": "Q012",
        },
    }
)

FIXTURE_LOG_MODEL_RESULT_ERROR = json.dumps(
    {
        "data": {
            "description": "sql table model main.broken_model",
            "execution_time": 0.01,
            "index": 1,
            "node_info": {"node_name": "broken_model", "resource_type": "model"},
            "status": "error",
            "total": 1,
        },
        "info": {"name": "LogModelResult", "level": "error", "code": "Q012"},
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

FIXTURE_RUN_RESULT_ERROR = json.dumps(
    {
        "data": {
            "msg": (
                "Runtime Error in model int_rpkm_by_ec_tax "
                "(models/intermediate/int_rpkm_by_ec_tax.sql)\n"
                "  Invalid Input Error: RPKM file is empty"
            ),
            "node_info": {"node_name": "int_rpkm_by_ec_tax", "resource_type": "model"},
        },
        "info": {
            "name": "RunResultError",
            "level": "error",
            "code": "Z024",
            "msg": (
                "  Runtime Error in model int_rpkm_by_ec_tax "
                "(models/intermediate/int_rpkm_by_ec_tax.sql)\n"
                "  Invalid Input Error: RPKM file is empty"
            ),
        },
    }
)


FIXTURE_RESULT_EVENTS = Path(__file__).parent / "fixtures" / "dbt_fake_rpkm_result_events.jsonl"
FIXTURE_START_EVENTS = Path(__file__).parent / "fixtures" / "dbt_fake_rpkm_start_events.jsonl"
FIXTURE_PROGRESS_EVENTS = Path(__file__).parent / "fixtures" / "dbt_fake_rpkm_progress_events.jsonl"


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


def test_parse_log_start_line_maps_to_progress_event():
    event = parse_dbt_json_line(FIXTURE_LOG_START_LINE)

    assert event == ProgressEvent(
        kind="progress",
        data={
            "step": 1,
            "total": 23,
            "name": "int_rpkm_by_ec_tax",
            "state": "started",
        },
    )


def test_parse_log_model_result_maps_to_progress_event():
    event = parse_dbt_json_line(FIXTURE_LOG_MODEL_RESULT)

    assert event == ProgressEvent(
        kind="progress",
        data={
            "step": 1,
            "total": 23,
            "name": "int_rpkm_by_ec_tax",
            "state": "OK",
            "elapsed_s": 0.049499035,
        },
    )


def test_parse_log_model_result_error_status():
    event = parse_dbt_json_line(FIXTURE_LOG_MODEL_RESULT_ERROR)

    assert event == ProgressEvent(
        kind="progress",
        data={
            "step": 1,
            "total": 1,
            "name": "broken_model",
            "state": "error",
            "elapsed_s": 0.01,
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


def test_parse_fixture_jsonl_forwards_all_start_lines():
    events: list[ProgressEvent] = []
    with FIXTURE_START_EVENTS.open() as handle:
        for line in handle:
            event = parse_dbt_json_line(line)
            if event is not None:
                events.append(event)

    assert len(events) == 23
    assert [event.data["step"] for event in events] == list(range(1, 24))
    assert all(event.data["state"] == "started" for event in events)
    assert all(event.data["total"] == 23 for event in events)


def test_parse_fixture_jsonl_forwards_all_model_and_test_results():
    events: list[ProgressEvent] = []
    with FIXTURE_RESULT_EVENTS.open() as handle:
        for line in handle:
            event = parse_dbt_json_line(line)
            if event is not None:
                events.append(event)

    assert len(events) == 23
    steps = [event.data["step"] for event in events]
    assert steps == list(range(1, 24))
    assert all(event.data["total"] == 23 for event in events)

    model_names = {
        "int_rpkm_by_ec_tax",
        "dim_sample_ec",
        "dim_sample_taxon",
        "mart_rpkm_enriched",
    }
    assert {event.data["name"] for event in events if event.data["state"] == "OK"} == model_names
    assert sum(1 for event in events if event.data["state"] == "pass") == 18
    assert sum(1 for event in events if event.data["state"] == "warn") == 1


def test_parse_fixture_jsonl_forwards_start_and_result_events():
    events: list[ProgressEvent] = []
    with FIXTURE_PROGRESS_EVENTS.open() as handle:
        for line in handle:
            event = parse_dbt_json_line(line)
            if event is not None:
                events.append(event)

    assert len(events) == 46
    started = [event for event in events if event.data["state"] == "started"]
    finished = [event for event in events if event.data["state"] != "started"]
    assert len(started) == 23
    assert len(finished) == 23
    assert {event.data["step"] for event in started} == set(range(1, 24))
    assert {event.data["step"] for event in finished} == set(range(1, 24))


def test_parse_ignores_non_json_and_unrelated_events():
    assert parse_dbt_json_line("not json") is None
    assert parse_dbt_json_line("") is None
    unrelated = json.dumps({"info": {"name": "MainReportVersion"}, "data": {}})
    assert parse_dbt_json_line(unrelated) is None


def test_parse_run_result_error_collects_message():
    errors: list[str] = []
    event = parse_dbt_json_line(FIXTURE_RUN_RESULT_ERROR, error_messages=errors)

    assert event is None
    assert errors == ["RPKM file is empty"]


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
        FIXTURE_LOG_START_LINE + "\n",
        FIXTURE_LOG_MODEL_RESULT + "\n",
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
    assert events[0].data["name"] == "int_rpkm_by_ec_tax"
    assert events[0].data["state"] == "started"
    assert events[1].data["state"] == "OK"
    assert events[2].data["state"] == "pass"
    assert events[-1] == ProgressEvent(
        kind="complete",
        data={"status": "Ready", "sample_id": "proj"},
    )
    assert store.active_sample_id == "proj"
    assert store.get_entry("proj") is not None
    assert store.get_entry("proj").status != "Processing"


@pytest.mark.anyio
async def test_pipeline_runner_forwards_all_fixture_progress_events(tmp_path):
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
        line if line.endswith("\n") else line + "\n"
        for line in FIXTURE_PROGRESS_EVENTS.read_text().splitlines()
        if line.strip()
    ]

    mock_proc = MagicMock()
    mock_proc.stdout = stdout_lines
    mock_proc.stderr = StringIO("")
    mock_proc.wait.return_value = 0
    runner._popen = lambda cmd, **kwargs: mock_proc  # type: ignore[method-assign]

    await runner.run("proj", rpkm)

    queue = runner.get_queue("proj")
    events: list[ProgressEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    progress_events = [event for event in events if event.kind == "progress"]
    assert len(progress_events) == 46
    assert progress_events[0].data["state"] == "started"
    assert progress_events[1].data["state"] == "OK"
    assert events[-1].kind == "complete"


@pytest.mark.anyio
async def test_pipeline_runner_forwards_all_fixture_result_events(tmp_path):
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
        line if line.endswith("\n") else line + "\n"
        for line in FIXTURE_RESULT_EVENTS.read_text().splitlines()
        if line.strip()
    ]

    mock_proc = MagicMock()
    mock_proc.stdout = stdout_lines
    mock_proc.stderr = StringIO("")
    mock_proc.wait.return_value = 0
    runner._popen = lambda cmd, **kwargs: mock_proc  # type: ignore[method-assign]

    await runner.run("proj", rpkm)

    queue = runner.get_queue("proj")
    events: list[ProgressEvent] = []
    while not queue.empty():
        events.append(queue.get_nowait())

    progress_events = [event for event in events if event.kind == "progress"]
    assert len(progress_events) == 23
    assert progress_events[0].data["name"] == "int_rpkm_by_ec_tax"
    assert progress_events[0].data["state"] == "OK"
    assert events[-1].kind == "complete"


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
    assert event.data["status"] == "Failed"
    assert "dbt build failed" in event.data["message"]
    assert store.active_sample_id is None
    assert store.get_entry("proj").status != "Processing"


@pytest.mark.anyio
async def test_pipeline_runner_prefers_run_result_error_over_stderr(tmp_path):
    data_root = tmp_path / "data"
    runs_dir = data_root / "vis" / "runs"
    rpkm = data_root / "proj" / "RPKM_table.tsv"
    rpkm.parent.mkdir(parents=True)
    rpkm.write_text("gene\trpkm\n")

    settings = _settings(data_root, runs_dir)
    store = CatalogStore()
    store.refresh(settings)
    runner = PipelineRunner(store, settings)

    mock_proc = MagicMock()
    mock_proc.stdout = [FIXTURE_RUN_RESULT_ERROR + "\n"]
    mock_proc.stderr = StringIO("run_context.json written to /tmp/run_context.json\n")
    mock_proc.wait.return_value = 1
    mock_proc.returncode = 1

    runner._popen = lambda cmd, **kwargs: mock_proc  # type: ignore[method-assign]

    await runner.run("proj", rpkm)

    queue = runner.get_queue("proj")
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert events[-1].kind == "error"
    assert events[-1].data["message"] == "RPKM file is empty"
