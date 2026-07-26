"""Filesystem layout for pipeline run artifacts (local-data/vis/runs)."""
from __future__ import annotations

import os
from pathlib import Path

_ANALYTICS_DIR = Path(__file__).resolve().parent.parent.parent
# Repo-root local-data (same target as dev:fastapi DATA_ROOT=../local-data from analytics/).
DEFAULT_DATA_ROOT = _ANALYTICS_DIR.parent / "local-data"


def default_data_root() -> Path:
    return Path(os.environ.get("DATA_ROOT", str(DEFAULT_DATA_ROOT))).resolve()


def default_runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR", str(default_data_root() / "vis" / "runs"))).resolve()
