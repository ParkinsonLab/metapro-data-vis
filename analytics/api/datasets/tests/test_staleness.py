import hashlib
import json
from pathlib import Path

from api.datasets.staleness import StalenessReason, verify_staleness


def _write_rpkm(path: Path, content: str = "gene\trpkm\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_run_context(
    runs_dir: Path,
    sample_id: str,
    *,
    rpkm_path: Path,
    mtime: int,
    size: int,
    rpkm_sha256: str | None = None,
    overall_status: str = "success",
) -> None:
    run_dir = runs_dir / sample_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "sample.duckdb").write_bytes(b"duckdb")
    context = {
        "sample_id": sample_id,
        "rpkm_path": str(rpkm_path),
        "rpkm_mtime": mtime,
        "rpkm_size": size,
        "overall_status": overall_status,
        "run_at": "2026-07-16T12:00:00+00:00",
    }
    if rpkm_sha256 is not None:
        context["rpkm_sha256"] = rpkm_sha256
    (run_dir / "run_context.json").write_text(json.dumps(context))


def test_verify_staleness_missing_run_context(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.MISSING_ARTIFACTS


def test_verify_staleness_missing_sample_duckdb(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    run_dir = runs_dir / "proj"
    run_dir.mkdir(parents=True)
    (run_dir / "run_context.json").write_text(
        json.dumps(
            {
                "sample_id": "proj",
                "rpkm_path": str(rpkm),
                "rpkm_mtime": int(stat.st_mtime),
                "rpkm_size": stat.st_size,
            }
        )
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.MISSING_ARTIFACTS


def test_verify_staleness_fresh_when_mtime_and_size_match(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
        rpkm_sha256=_sha256(rpkm),
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is False
    assert result.reason == StalenessReason.FRESH


def test_verify_staleness_stale_when_mtime_size_match_but_sha_missing(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.SHA256_MISMATCH


def test_verify_staleness_sha256_mismatch_when_mtime_size_match(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
        rpkm_sha256="0" * 64,
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.SHA256_MISMATCH


def test_verify_staleness_mtime_size_mismatch_without_sha256(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime) - 100,
        size=stat.st_size,
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.MTIME_SIZE_MISMATCH


def test_verify_staleness_stale_when_mtime_differs_even_if_sha256_matches(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime) - 100,
        size=stat.st_size,
        rpkm_sha256=_sha256(rpkm),
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.MTIME_SIZE_MISMATCH


def test_verify_staleness_failed_run_when_overall_status_not_success(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
        overall_status="failed",
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.FAILED_RUN


def test_verify_staleness_fresh_when_success_with_warnings(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm)
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime),
        size=stat.st_size,
        rpkm_sha256=_sha256(rpkm),
        overall_status="success_with_warnings",
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is False
    assert result.reason == StalenessReason.FRESH


def test_verify_staleness_stale_when_mtime_size_changed(tmp_path):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "proj" / "RPKM_table.tsv"
    _write_rpkm(rpkm, "gene\trpkm\nversion-a\n")
    stat = rpkm.stat()
    _write_run_context(
        runs_dir,
        "proj",
        rpkm_path=rpkm,
        mtime=int(stat.st_mtime) - 100,
        size=stat.st_size,
        rpkm_sha256="0" * 64,
    )

    result = verify_staleness(rpkm, runs_dir, "proj")

    assert result.needs_pipeline is True
    assert result.reason == StalenessReason.MTIME_SIZE_MISMATCH
