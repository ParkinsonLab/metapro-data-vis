"""Micro unit tests for rpkm ingest (EC normalization + gene SUM via int_rpkm_by_ec_tax)."""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import duckdb
import pytest

ANALYTICS_DIR = Path(__file__).resolve().parents[3]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"


def _write_tsv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.tsv"
    p.write_text(textwrap.dedent(content).lstrip())
    return p


def _run_int_model(
    tsv_path: Path,
    *,
    duckdb_path: Path,
    sample_id: str = "s1",
    expect_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    vars_json = json.dumps({"rpkm_path": str(tsv_path), "sample_id": sample_id})
    env = {**os.environ, "DBT_DUCKDB_PATH": str(duckdb_path)}
    return subprocess.run(
        [
            "uv",
            "run",
            "dbt",
            "run",
            "--select",
            "int_rpkm_by_ec_tax",
            "--project-dir",
            str(TRANSFORM_DIR),
            "--profiles-dir",
            str(TRANSFORM_DIR),
            "--vars",
            vars_json,
        ],
        cwd=ANALYTICS_DIR,
        env=env,
        check=not expect_failure,
        capture_output=True,
        text=True,
    )


def _query_int(db_path: Path, tsv_path: Path, sample_id: str = "s1"):
    _run_int_model(tsv_path, duckdb_path=db_path, sample_id=sample_id)
    conn = duckdb.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT sample_id, ec_normalized, source_tax_id, value FROM int_rpkm_by_ec_tax"
        ).df()
    finally:
        conn.close()


def _query_int_raises(tsv_path: Path, duckdb_path: Path) -> str:
    result = _run_int_model(
        tsv_path,
        duckdb_path=duckdb_path,
        expect_failure=True,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    return output


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "sample.duckdb"


def test_ec_prefix_stripped(db_path, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        """,
    )
    df = _query_int(db_path, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "1.2.3.4"


def test_ec_lower_prefix_stripped(db_path, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tec:5.6.7.8\t1.0\t0\t1.0
        """,
    )
    df = _query_int(db_path, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "5.6.7.8"


def test_ec_none_maps_to_zero(db_path, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tNone\t1.0\t0\t1.0
        """,
    )
    df = _query_int(db_path, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "0.0.0.0"


def test_gene_aggregation_sums(db_path, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t2.0
        gene2\t200\t3\tEC:1.2.3.4\t1.0\t0\t3.0
        """,
    )
    df = _query_int(db_path, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "1.2.3.4"
    assert df["value"].iloc[0] == 5.0


def test_empty_rpkm_rejected(db_path, tmp_path):
    tsv = tmp_path / "empty.tsv"
    tsv.write_text("")
    message = _query_int_raises(tsv, db_path)
    assert "RPKM file is empty" in message


def test_header_only_rpkm_rejected(db_path, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        """,
    )
    message = _query_int_raises(tsv, db_path)
    assert "RPKM file is empty" in message


def test_missing_required_columns_rejected(db_path, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        foo\tbar
        x\ty
        """,
    )
    message = _query_int_raises(tsv, db_path)
    assert "missing required columns" in message
    assert "GeneID" in message
