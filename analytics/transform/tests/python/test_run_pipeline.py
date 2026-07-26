from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from transform.lib.paths import DEFAULT_DATA_ROOT
from transform.scripts.run_pipeline import (
    _default_runs_dir,
    _parse_last_error,
    _parse_overall_status,
    _prepare_sample_db,
    _rpkm_identity,
    _run_dbt,
)


def test_prepare_sample_db_removes_existing_file_and_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.duckdb"
    wal_path = Path(f"{db_path}.wal")
    db_path.write_text("stub")
    wal_path.write_text("stub")

    _prepare_sample_db(db_path)

    assert not db_path.exists()
    assert not wal_path.exists()


def test_prepare_sample_db_creates_parent_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "sample.duckdb"
    _prepare_sample_db(db_path)
    assert db_path.parent.is_dir()


def test_prepare_sample_db_allows_fresh_duckdb_write(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE legacy_orphan AS SELECT 1 AS x")
    conn.close()

    _prepare_sample_db(db_path)

    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE current_model AS SELECT 2 AS y")
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    conn.close()

    assert tables == {"current_model"}


def test_default_runs_dir_prefers_env(monkeypatch, tmp_path):
    custom = tmp_path / "custom-runs"
    monkeypatch.setenv("RUNS_DIR", str(custom))
    assert _default_runs_dir() == custom.resolve()


def test_default_runs_dir_falls_back_to_local_data_vis_runs(monkeypatch):
    monkeypatch.delenv("RUNS_DIR", raising=False)
    monkeypatch.delenv("DATA_ROOT", raising=False)
    runs_dir = _default_runs_dir()
    assert runs_dir == (DEFAULT_DATA_ROOT / "vis" / "runs").resolve()


def test_rpkm_identity_includes_mtime_size_sha256(tmp_path):
    rpkm = tmp_path / "sample.tsv"
    rpkm.write_text("gene\trpkm\n1\t2.5\n")

    identity = _rpkm_identity(rpkm)

    stat = rpkm.stat()
    assert identity["rpkm_mtime"] == int(stat.st_mtime)
    assert identity["rpkm_size"] == stat.st_size
    assert len(identity["rpkm_sha256"]) == 64


def test_parse_overall_status_marks_dbt_test_fail_as_failed(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "run_results.json").write_text(
        json.dumps(
            {
                "results": [
                    {"status": "success"},
                    {"status": "fail"},
                    {"status": "warn"},
                ]
            }
        )
    )
    assert _parse_overall_status(tmp_path) == "failed"


def test_parse_last_error_includes_failed_test_name(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "run_results.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "status": "fail",
                        "unique_id": "test.rpkm_transform.assert_mart_nonempty",
                        "message": "Got 1 result, configured to fail if != 0",
                    }
                ]
            }
        )
    )
    assert _parse_last_error(tmp_path) == "Assertion failed: assert_mart_nonempty"


def test_run_dbt_adds_json_log_format_when_requested(tmp_path):
    runs_dir = tmp_path / "runs"
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("Result", (), {"returncode": 0})()

    with patch("transform.scripts.run_pipeline.subprocess.run", fake_run):
        _run_dbt(
            "sample_a",
            str(tmp_path / "input.tsv"),
            "phylum",
            "pathway",
            runs_dir=runs_dir,
            reference_parquet_dir=tmp_path / "reference",
            json_logs=True,
        )

    assert "--log-format" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--log-format") + 1] == "json"


def test_main_writes_rpkm_identity_to_run_context(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    rpkm = tmp_path / "sample.tsv"
    rpkm.write_text("gene\trpkm\n")

    monkeypatch.chdir(Path(__file__).resolve().parents[3])
    monkeypatch.setattr(
        "transform.scripts.run_pipeline._check_bridges",
        lambda ref_dir: None,
    )
    monkeypatch.setattr(
        "transform.scripts.run_pipeline._run_dbt",
        lambda *args, **kwargs: {
            "returncode": 0,
            "db_path": str(runs_dir / "sample_a" / "sample.duckdb"),
        },
    )
    monkeypatch.setattr(
        "transform.scripts.run_pipeline._parse_overall_status",
        lambda transform_dir: "success",
    )
    monkeypatch.setattr(
        "transform.scripts.run_pipeline._compute_info_metrics",
        lambda db_path, tax_rank: {},
    )

    from transform.scripts import run_pipeline

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_pipeline.py",
            "--sample-id",
            "sample_a",
            "--rpkm-path",
            str(rpkm),
            "--runs-dir",
            str(runs_dir),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        run_pipeline.main()
    assert exc.value.code == 0

    context = json.loads((runs_dir / "sample_a" / "run_context.json").read_text())
    identity = _rpkm_identity(rpkm)
    assert context["rpkm_mtime"] == identity["rpkm_mtime"]
    assert context["rpkm_size"] == identity["rpkm_size"]
    assert context["rpkm_sha256"] == identity["rpkm_sha256"]
