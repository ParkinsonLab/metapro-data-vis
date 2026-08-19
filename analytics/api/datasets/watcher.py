from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from api.config import Settings
from api.datasets.catalog import CatalogStore

logger = logging.getLogger(__name__)

REQUIRED_REFERENCE_PARQUETS = (
    "bridge_ec_pathway.parquet",
    "bridge_tax_lineage.parquet",
)


def check_reference_parquet(settings: Settings) -> None:
    missing = [
        name
        for name in REQUIRED_REFERENCE_PARQUETS
        if not (settings.reference_parquet_dir / name).is_file()
    ]
    if missing:
        msg = (
            f"Missing reference parquet in {settings.reference_parquet_dir}: "
            f"{', '.join(missing)}. "
            "Run: cd analytics && uv run python transform/scripts/build_reference.py"
        )
        logger.error(msg)
        raise RuntimeError(msg)


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        try:
            path.absolute().relative_to(parent.resolve())
            return True
        except ValueError:
            return False


def event_path_triggers_refresh(event_path: Path, data_root: Path, vis_root: Path) -> bool:
    if not _is_under(event_path, data_root):
        return False
    if _is_under(event_path, vis_root):
        return False
    return True


class Debouncer:
    def __init__(self, delay_seconds: float, callback: Callable[[], None]) -> None:
        self._delay_seconds = delay_seconds
        self._callback = callback
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def trigger(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay_seconds, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
        try:
            self._callback()
        except Exception:
            logger.exception("debounced catalog refresh failed")


class CatalogEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        data_root: Path,
        vis_root: Path,
        debouncer: Debouncer,
    ) -> None:
        super().__init__()
        self._data_root = data_root.resolve()
        self._vis_root = vis_root.resolve()
        self._debouncer = debouncer

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event_path_triggers_refresh(Path(event.src_path), self._data_root, self._vis_root):
            self._debouncer.trigger()


class DatasetWatcher:
    def __init__(
        self,
        store: CatalogStore,
        settings: Settings,
        *,
        debounce_seconds: float = 0.5,
        observer_factory: Callable[[], BaseObserver] | None = None,
    ) -> None:
        self._store = store
        self._settings = settings
        self._debounce_seconds = debounce_seconds
        self._observer_factory = observer_factory or Observer
        self._observer: BaseObserver | None = None
        self._debouncer: Debouncer | None = None

    def start(self) -> None:
        if self._observer is not None:
            return

        data_root = self._settings.data_root.resolve()
        if not data_root.is_dir():
            logger.warning("DATA_ROOT %s does not exist; filesystem watcher not started", data_root)
            return

        vis_root = data_root / "vis"

        def refresh() -> None:
            logger.debug("refreshing dataset catalog after filesystem change")
            self._store.refresh(self._settings)

        self._debouncer = Debouncer(self._debounce_seconds, refresh)
        handler = CatalogEventHandler(data_root, vis_root, self._debouncer)
        observer = self._observer_factory()
        observer.schedule(handler, str(data_root), recursive=True)
        observer.start()
        self._observer = observer
        logger.info("dataset filesystem watcher started on %s", data_root)

    def stop(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
            self._debouncer = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            logger.info("dataset filesystem watcher stopped")
