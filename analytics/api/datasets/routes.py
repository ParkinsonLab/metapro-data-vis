from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.datasets.catalog import CatalogStore, DatasetEntry
from api.datasets.pipeline_runner import PipelineRunner
from api.datasets.staleness import verify_staleness
from api.datasets import status as dataset_status

router = APIRouter()

_catalog_store: CatalogStore | None = None
_pipeline_runner: PipelineRunner | None = None


def get_catalog_store() -> CatalogStore:
    global _catalog_store
    if _catalog_store is None:
        _catalog_store = CatalogStore()
    return _catalog_store


def get_pipeline_runner() -> PipelineRunner:
    global _pipeline_runner
    if _pipeline_runner is None:
        _pipeline_runner = PipelineRunner(get_catalog_store(), get_settings())
    return _pipeline_runner


def reset_dataset_services() -> None:
    global _catalog_store, _pipeline_runner
    _catalog_store = None
    _pipeline_runner = None


class SelectRequest(BaseModel):
    sample_id: str


def _entry_to_dict(entry: DatasetEntry) -> dict[str, Any]:
    return {
        "sample_id": entry.sample_id,
        "path": str(entry.path),
        "status": entry.status,
        "last_run_at": entry.last_run_at,
        "last_error": entry.last_error,
        "is_dev_fixture": entry.is_dev_fixture,
        "mtime": entry.mtime,
        "size": entry.size,
    }


def _catalog_response(store: CatalogStore) -> dict[str, Any]:
    return {
        "datasets": [_entry_to_dict(e) for e in store.get_catalog()],
        "active_sample_id": store.active_sample_id,
    }


def _refresh_catalog(settings: Settings) -> dict[str, Any]:
    store = get_catalog_store()
    store.refresh(settings)
    return _catalog_response(store)


@router.get("")
def list_datasets() -> dict[str, Any]:
    return _catalog_response(get_catalog_store())


@router.post("/refresh")
def refresh_datasets() -> dict[str, Any]:
    return _refresh_catalog(get_settings())


@router.post("/select")
async def select_dataset(body: SelectRequest) -> dict[str, Any]:
    store = get_catalog_store()
    settings = get_settings()
    runner = get_pipeline_runner()

    entry = store.get_entry(body.sample_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown sample_id")

    running = store.running_sample_id
    if running is not None:
        if running == body.sample_id:
            return {"status": dataset_status.PROCESSING}
        raise HTTPException(
            status_code=409, detail="Another dataset is already processing"
        )

    staleness = verify_staleness(entry.path, settings.runs_dir, body.sample_id)
    if not staleness.needs_pipeline:
        store.set_active(body.sample_id)
        return {"status": dataset_status.READY}

    store.set_running(body.sample_id)
    try:
        asyncio.create_task(runner.run(body.sample_id, entry.path))
    except Exception:
        store.set_running(None)
        raise
    return {"status": dataset_status.PROCESSING, "sample_id": body.sample_id}


async def event_stream(sample_id: str) -> Any:
    queue = get_pipeline_runner().get_queue(sample_id)
    while True:
        event = await queue.get()
        yield f"event: {event.kind}\ndata: {json.dumps(event.data)}\n\n"
        if event.kind in ("complete", "error"):
            break


@router.get("/{sample_id}/events")
async def dataset_events(sample_id: str) -> StreamingResponse:
    return StreamingResponse(
        event_stream(sample_id),
        media_type="text/event-stream",
    )
