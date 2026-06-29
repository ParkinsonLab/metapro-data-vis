"""Unit tests for stg_rpkm_long._transform using synthetic TSV data."""
from __future__ import annotations

import textwrap
from pathlib import Path

import duckdb
import pytest


def _write_tsv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.tsv"
    p.write_text(textwrap.dedent(content).lstrip())
    return p


@pytest.fixture
def conn():
    return duckdb.connect()


def test_unpivot_produces_long_rows(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606\t1234
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t2.0\t0.0
        gene2\t200\t3\tNone\t0.5\t0\t0.0\t4.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    # gene1 has nonzero value only for tax_id 9606
    # gene2 has nonzero value only for tax_id 1234
    assert len(df) == 2
    assert set(df["source_tax_id"].tolist()) == {9606, 1234}


def test_zero_values_excluded(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t0.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    assert len(df) == 0


def test_ec_normalization(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        gene2\t100\t5\tec:5.6.7.8\t1.0\t0\t2.0
        gene3\t100\t5\tNone\t1.0\t0\t3.0
        gene4\t100\t5\t\t1.0\t0\t4.0
        gene5\t100\t5\t9.9.9.9\t1.0\t0\t5.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    ecs = dict(zip(df["gene_id"], df["ec_normalized"]))

    assert ecs["gene1"] == "1.2.3.4"
    assert ecs["gene2"] == "5.6.7.8"
    assert ecs["gene3"] == "0.0.0.0"
    assert ecs["gene4"] == "0.0.0.0"
    assert ecs["gene5"] == "9.9.9.9"


def test_unclassified_column_excluded(conn, tmp_path):
    """'Unclassified' is a KEY_COL — must not appear as source_tax_id."""
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t99.0\t1.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    assert "Unclassified" not in df["source_tax_id"].astype(str).tolist()
    assert len(df) == 1  # only 9606 row


def test_sample_id_column(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "my_sample").df()
    assert df["sample_id"].iloc[0] == "my_sample"


def test_output_columns(conn, tmp_path):
    tsv = _write_tsv(
        tmp_path,
        """\
        GeneID\tLength\tReads\tEC#\tRPKM\tUnclassified\t9606
        gene1\t100\t5\tEC:1.2.3.4\t1.0\t0\t1.0
        """,
    )
    from analytics.transform.scripts.stg_rpkm_long import _transform

    df = _transform(conn, str(tsv), "s1").df()
    assert list(df.columns) == ["sample_id", "gene_id", "ec_normalized", "source_tax_id", "value"]
