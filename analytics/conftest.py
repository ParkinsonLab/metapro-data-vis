# analytics/conftest.py
from __future__ import annotations

import os
from pathlib import Path

import pytest

from api.config import get_settings
from testing import fake_rpkm_fixture as fixture

_ANALYTICS_DIR = Path(__file__).resolve().parent
_DEFAULT_RUNS_DIR = _ANALYTICS_DIR / "transform" / "runs"


@pytest.fixture(scope="session", autouse=True)
def _runs_dir_env() -> None:
    os.environ["RUNS_DIR"] = str(_DEFAULT_RUNS_DIR)
    get_settings.cache_clear()
    yield
    os.environ.pop("RUNS_DIR", None)
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def fake_rpkm_db() -> str:
    if not fixture.bridges_available():
        pytest.skip(fixture.skip_reason())
    path = fixture.ensure_pipeline_built()
    return str(path)
