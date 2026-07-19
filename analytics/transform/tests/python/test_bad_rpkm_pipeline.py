"""Integration tests: run_pipeline.py with invalid RPKM fixtures."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from testing.bad_rpkm_fixtures import BAD_RPKM_EMPTY
from testing.fake_rpkm_fixture import ANALYTICS_DIR, bridges_available, skip_reason

pytestmark = pytest.mark.skipif(not bridges_available(), reason=skip_reason())


def _run_pipeline(
    *,
    sample_id: str,
    rpkm_path: Path,
    runs_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "python",
            "transform/scripts/run_pipeline.py",
            "--sample-id",
            sample_id,
            "--rpkm-path",
            str(rpkm_path.resolve()),
            "--runs-dir",
            str(runs_dir),
            "--tax-rank",
            "phylum",
            "--pathway-level",
            "pathway",
        ],
        cwd=ANALYTICS_DIR,
        capture_output=True,
        text=True,
    )


def test_run_pipeline_empty_rpkm_fails(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    sample_id = "bad_empty"

    result = _run_pipeline(
        sample_id=sample_id,
        rpkm_path=BAD_RPKM_EMPTY,
        runs_dir=runs_dir,
    )

    assert result.returncode != 0

    context_path = runs_dir / sample_id / "run_context.json"
    assert context_path.is_file()
    context = json.loads(context_path.read_text())
    assert context["overall_status"] == "failed"
    assert context["rpkm_size"] == 0
    assert context.get("last_error") == "RPKM file is empty"
