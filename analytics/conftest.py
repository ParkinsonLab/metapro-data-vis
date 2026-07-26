# analytics/conftest.py
from __future__ import annotations

import pytest

from api.config import get_settings
from testing import fake_rpkm_fixture as fixture


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """get_settings() is cached; tests that monkeypatch env must not leak Settings."""
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def fake_rpkm_db() -> str:
    if not fixture.bridges_available():
        pytest.skip(fixture.skip_reason())
    path = fixture.ensure_pipeline_built()
    return str(path)
