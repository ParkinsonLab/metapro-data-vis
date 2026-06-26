# analytics/conftest.py
from __future__ import annotations

import pytest

from testing import fake_rpkm_fixture as fixture


@pytest.fixture(scope="session")
def fake_rpkm_db() -> str:
    if not fixture.bridges_available():
        pytest.skip(fixture.skip_reason())
    path = fixture.ensure_pipeline_built()
    return str(path)
