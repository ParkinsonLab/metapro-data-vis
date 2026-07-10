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
COMPILED_SQL = (
    TRANSFORM_DIR
    / "target/compiled/rpkm_transform/models/intermediate/int_rpkm_by_ec_tax.sql"
)


def _write_tsv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.tsv"
    p.write_text(textwrap.dedent(content).lstrip())
    return p


def _query_int(
    conn: duckdb.DuckDBPyConnection, tsv_path: Path, sample_id: str = "s1"
):
    vars_json = json.dumps({"rpkm_path": str(tsv_path), "sample_id": sample_id})
    env = {**os.environ, "DBT_DUCKDB_PATH": ":memory:"}
    subprocess.run(
        [
            "uv",
            "run",
            "dbt",
            "compile",
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
        check=True,
        capture_output=True,
        text=True,
    )
    sql = COMPILED_SQL.read_text()
    return conn.execute(sql).df()


@pytest.fixture
def conn():
    return duckdb.connect()


def test_ec_prefix_stripped(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        """,
    )
    df = _query_int(conn, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "1.2.3.4"


def test_ec_lower_prefix_stripped(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tec:5.6.7.8\t1.0\t0\t1.0
        """,
    )
    df = _query_int(conn, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "5.6.7.8"


def test_ec_none_maps_to_zero(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tNone\t1.0\t0\t1.0
        """,
    )
    df = _query_int(conn, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "0.0.0.0"


def test_gene_aggregation_sums(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t2.0
        gene2\t200\t3\tEC:1.2.3.4\t1.0\t0\t3.0
        """,
    )
    df = _query_int(conn, tsv)
    assert len(df) == 1
    assert df["ec_normalized"].iloc[0] == "1.2.3.4"
    assert df["value"].iloc[0] == 5.0
