from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class StalenessReason(str, Enum):
    FRESH = "fresh"
    MISSING_ARTIFACTS = "missing_artifacts"
    MTIME_SIZE_MISMATCH = "mtime_size_mismatch"
    SHA256_MISMATCH = "sha256_mismatch"


@dataclass(frozen=True)
class StalenessResult:
    needs_pipeline: bool
    reason: StalenessReason


def _read_run_context(runs_dir: Path, sample_id: str) -> dict | None:
    context_path = runs_dir / sample_id / "run_context.json"
    if not context_path.is_file():
        return None
    return json.loads(context_path.read_text())


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_staleness(
    rpkm_path: Path,
    runs_dir: Path,
    sample_id: str,
) -> StalenessResult:
    db_path = runs_dir / sample_id / "sample.duckdb"
    context = _read_run_context(runs_dir, sample_id)
    if context is None or not db_path.is_file():
        return StalenessResult(
            needs_pipeline=True,
            reason=StalenessReason.MISSING_ARTIFACTS,
        )

    resolved = rpkm_path.resolve()
    stat = resolved.stat()
    mtime = int(stat.st_mtime)
    size = stat.st_size

    ctx_mtime = context.get("rpkm_mtime")
    ctx_size = context.get("rpkm_size")
    if mtime == ctx_mtime and size == ctx_size:
        return StalenessResult(needs_pipeline=False, reason=StalenessReason.FRESH)

    ctx_sha256 = context.get("rpkm_sha256")
    if ctx_sha256 is None:
        return StalenessResult(
            needs_pipeline=True,
            reason=StalenessReason.MTIME_SIZE_MISMATCH,
        )

    current_sha256 = _sha256_file(resolved)
    if current_sha256 == ctx_sha256:
        return StalenessResult(needs_pipeline=False, reason=StalenessReason.FRESH)

    return StalenessResult(
        needs_pipeline=True,
        reason=StalenessReason.SHA256_MISMATCH,
    )
