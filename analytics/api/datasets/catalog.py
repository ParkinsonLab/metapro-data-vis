from __future__ import annotations

import json
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from api.config import Settings
from api.datasets.identity import sample_id_from_path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_RPKM_FILENAME = "RPKM_table.tsv"

_DEV_FIXTURE_PATHS: tuple[tuple[str, str], ...] = (
    ("resources/example_data/test_rpkm_1.tsv", "test_rpkm_1"),
    ("resources/example_data/test_rpkm_2.tsv", "test_rpkm_2"),
    ("analytics/transform/tests/fixtures/fake_rpkm.tsv", "fake_rpkm"),
    ("resources/example_data/stress_rpkm_1.tsv", "stress_rpkm_1"),
    ("resources/example_data/stress_rpkm_2.tsv", "stress_rpkm_2"),
)


@dataclass(frozen=True)
class DatasetEntry:
    sample_id: str
    path: Path
    status: str
    last_run_at: str | None
    last_error: str | None
    is_dev_fixture: bool
    mtime: int
    size: int


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _dev_fixtures() -> list[tuple[Path, str]]:
    fixtures: list[tuple[Path, str]] = []
    for rel_path, sample_id in _DEV_FIXTURE_PATHS:
        path = (_REPO_ROOT / rel_path).resolve()
        if path.is_file():
            fixtures.append((path, sample_id))
    return fixtures


def _read_run_context(runs_dir: Path, sample_id: str) -> dict | None:
    context_path = runs_dir / sample_id / "run_context.json"
    if not context_path.is_file():
        return None
    return json.loads(context_path.read_text())


def _derive_status(
    rpkm_path: Path,
    runs_dir: Path,
    sample_id: str,
    mtime: int,
    size: int,
) -> tuple[str, str | None, str | None]:
    db_path = runs_dir / sample_id / "sample.duckdb"
    context = _read_run_context(runs_dir, sample_id)
    if context is None or not db_path.is_file():
        return "discovered", None, None

    last_run_at = context.get("run_at")
    overall_status = context.get("overall_status")
    if overall_status not in ("success", "success_with_warnings"):
        last_error = context.get("last_error") or f"pipeline status: {overall_status}"
        return "failed", last_run_at, last_error

    ctx_mtime = context.get("rpkm_mtime")
    ctx_size = context.get("rpkm_size")
    if ctx_mtime is None or ctx_size is None:
        return "stale", last_run_at, None

    if mtime != ctx_mtime or size != ctx_size:
        return "stale", last_run_at, None

    return "ready", last_run_at, None


def _entry_from_rpkm(
    rpkm_path: Path,
    settings: Settings,
    *,
    sample_id: str | None = None,
    is_dev_fixture: bool = False,
) -> DatasetEntry:
    resolved = rpkm_path.resolve()
    stat = resolved.stat()
    mtime = int(stat.st_mtime)
    size = stat.st_size
    sid = sample_id or sample_id_from_path(settings.data_root, resolved)
    status, last_run_at, last_error = _derive_status(
        resolved, settings.runs_dir, sid, mtime, size
    )
    return DatasetEntry(
        sample_id=sid,
        path=resolved,
        status=status,
        last_run_at=last_run_at,
        last_error=last_error,
        is_dev_fixture=is_dev_fixture,
        mtime=mtime,
        size=size,
    )


def scan_datasets(settings: Settings) -> list[DatasetEntry]:
    entries: dict[str, DatasetEntry] = {}
    data_root = settings.data_root.resolve()
    vis_root = data_root / "vis"

    if data_root.is_dir():
        for rpkm_path in data_root.rglob(_RPKM_FILENAME):
            if _is_under(rpkm_path, vis_root):
                continue
            entry = _entry_from_rpkm(rpkm_path, settings)
            entries[entry.sample_id] = entry

    if settings.enable_dev_datasets:
        for fixture_path, sample_id in _dev_fixtures():
            entry = _entry_from_rpkm(
                fixture_path,
                settings,
                sample_id=sample_id,
                is_dev_fixture=True,
            )
            entries[sample_id] = entry

    return sorted(entries.values(), key=lambda e: (e.is_dev_fixture, e.sample_id))


class CatalogStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, DatasetEntry] = {}
        self._running_sample_id: str | None = None
        self._active_sample_id: str | None = None

    def _with_running_overlay(self, entry: DatasetEntry) -> DatasetEntry:
        if entry.sample_id == self._running_sample_id:
            return replace(entry, status="running")
        return entry

    @property
    def active_sample_id(self) -> str | None:
        with self._lock:
            return self._active_sample_id

    @property
    def running_sample_id(self) -> str | None:
        with self._lock:
            return self._running_sample_id

    def refresh(self, settings: Settings) -> list[DatasetEntry]:
        scanned = {e.sample_id: e for e in scan_datasets(settings)}
        with self._lock:
            self._entries = scanned
            return [self._with_running_overlay(e) for e in self._entries.values()]

    def get_catalog(self) -> list[DatasetEntry]:
        with self._lock:
            return sorted(
                (self._with_running_overlay(e) for e in self._entries.values()),
                key=lambda e: (e.is_dev_fixture, e.sample_id),
            )

    def get_entry(self, sample_id: str) -> DatasetEntry | None:
        with self._lock:
            entry = self._entries.get(sample_id)
            if entry is None:
                return None
            return self._with_running_overlay(entry)

    def set_running(self, sample_id: str | None) -> None:
        with self._lock:
            self._running_sample_id = sample_id

    def set_active(self, sample_id: str | None) -> None:
        with self._lock:
            self._active_sample_id = sample_id
