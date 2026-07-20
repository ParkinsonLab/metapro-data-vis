from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from api.config import Settings
from api.datasets.catalog import CatalogStore

_ANALYTICS_DIR = Path(__file__).resolve().parent.parent.parent
_RUN_PIPELINE_SCRIPT = _ANALYTICS_DIR / "transform" / "scripts" / "run_pipeline.py"


@dataclass(frozen=True)
class ProgressEvent:
    kind: str
    data: dict[str, Any]


def _node_result_progress(
    data: dict[str, Any],
    *,
    name: str | None,
    status: str | None,
    total: int | None,
) -> ProgressEvent:
    progress: dict[str, Any] = {
        "step": data.get("index"),
        "total": total,
        "name": name,
        "state": status,
    }
    elapsed = data.get("execution_time")
    if elapsed is not None:
        progress["elapsed_s"] = elapsed
    return ProgressEvent(kind="progress", data=progress)


from testing.dbt_failure_messages import format_dbt_failure_message


def _node_start_progress(data: dict[str, Any]) -> ProgressEvent:
    node_info = data.get("node_info") or {}
    return _node_result_progress(
        data,
        name=node_info.get("node_name"),
        status="started",
        total=data.get("total"),
    )


def parse_dbt_json_line(
    line: str,
    *,
    step_counter: list[int] | None = None,
    error_messages: list[str] | None = None,
) -> ProgressEvent | None:
    stripped = line.strip()
    if not stripped or not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None

    info = payload.get("info") or {}
    event_name = info.get("name")
    data = payload.get("data") or {}

    if event_name == "NodeStart":
        node_info = data.get("node_info") or {}
        progress: dict[str, Any] = {
            "name": node_info.get("node_name"),
            "state": "started",
        }
        if step_counter is not None:
            step_counter[0] += 1
            progress["step"] = step_counter[0]
        return ProgressEvent(kind="progress", data=progress)

    if event_name == "NodeFinished":
        node_info = data.get("node_info") or {}
        run_result = data.get("run_result") or {}
        elapsed = run_result.get("execution_time")
        progress = {
            "name": node_info.get("node_name"),
            "state": "finished",
        }
        if elapsed is not None:
            progress["elapsed_s"] = elapsed
        return ProgressEvent(kind="progress", data=progress)

    if event_name == "LogStartLine":
        return _node_start_progress(data)

    if event_name == "LogModelResult":
        node_info = data.get("node_info") or {}
        return _node_result_progress(
            data,
            name=node_info.get("node_name"),
            status=data.get("status"),
            total=data.get("total"),
        )

    if event_name == "LogTestResult":
        return _node_result_progress(
            data,
            name=data.get("name"),
            status=data.get("status"),
            total=data.get("num_models"),
        )

    if event_name == "RunResultError":
        raw_msg = data.get("msg") or info.get("msg")
        if raw_msg and error_messages is not None:
            node_info = data.get("node_info") or {}
            message = format_dbt_failure_message(
                unique_id=node_info.get("unique_id", ""),
                node_name=node_info.get("node_name"),
                message=raw_msg,
            )
            error_messages.append(message)
        return None

    return None


class PipelineRunner:
    def __init__(self, catalog: CatalogStore, settings: Settings) -> None:
        self._catalog = catalog
        self._settings = settings
        self._queues: dict[str, asyncio.Queue[ProgressEvent]] = {}
        self._popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen

    def get_queue(self, sample_id: str) -> asyncio.Queue[ProgressEvent]:
        if sample_id not in self._queues:
            self._queues[sample_id] = asyncio.Queue()
        return self._queues[sample_id]

    def _pipeline_cmd(self, sample_id: str, rpkm_path: Path) -> list[str]:
        return [
            "uv",
            "run",
            "python",
            str(_RUN_PIPELINE_SCRIPT),
            "--sample-id",
            sample_id,
            "--rpkm-path",
            str(rpkm_path),
            "--runs-dir",
            str(self._settings.runs_dir),
            "--json-logs",
        ]

    def _pipeline_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["RUNS_DIR"] = str(self._settings.runs_dir)
        env["REFERENCE_PARQUET_DIR"] = str(self._settings.reference_parquet_dir)
        return env

    async def run(self, sample_id: str, rpkm_path: Path) -> None:
        queue = self.get_queue(sample_id)
        self._catalog.set_running(sample_id)
        loop = asyncio.get_running_loop()

        def _execute() -> tuple[int, str, list[str]]:
            proc = self._popen(
                self._pipeline_cmd(sample_id, rpkm_path),
                cwd=str(_ANALYTICS_DIR),
                env=self._pipeline_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert proc.stdout is not None
            step_counter = [0]
            error_messages: list[str] = []
            for line in proc.stdout:
                event = parse_dbt_json_line(
                    line,
                    step_counter=step_counter,
                    error_messages=error_messages,
                )
                if event is not None:
                    future = asyncio.run_coroutine_threadsafe(queue.put(event), loop)
                    future.result()
            stderr = ""
            if proc.stderr is not None:
                stderr = proc.stderr.read()
            returncode = proc.wait()
            return returncode, stderr, error_messages

        returncode, stderr, error_messages = await asyncio.to_thread(_execute)

        self._catalog.set_running(None)
        self._catalog.refresh(self._settings)

        if returncode == 0:
            self._catalog.set_active(sample_id)
            await queue.put(
                ProgressEvent(
                    kind="complete",
                    data={"status": "ready", "sample_id": sample_id},
                )
            )
            return

        if error_messages:
            message = error_messages[-1]
        else:
            message = stderr.strip() or f"pipeline exited with code {returncode}"
        await queue.put(
            ProgressEvent(
                kind="error",
                data={"status": "failed", "message": message},
            )
        )
