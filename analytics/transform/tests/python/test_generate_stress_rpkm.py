from __future__ import annotations

import random
from pathlib import Path

import pytest

from testing.stress_rpkm_lib import (
    DEFAULT_KINGDOM_TAX_IDS,
    build_row,
    ec_for_row_index,
    load_pools,
    plan_overlap,
    row_to_tsv_line,
    sample_tax_columns,
    validate_tsv,
    write_tsv_header,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _parquet_available() -> bool:
    d = _repo_root() / "resources/db/parquet"
    return (d / "parents.parquet").exists() and (d / "pathway_nodes.parquet").exists()


def test_plan_overlap_defaults():
    rng = random.Random(0)
    pool = list(range(10000))
    cols1, cols2 = sample_tax_columns(
        pool, tax_cols=100, column_overlap=0.75, rng=rng
    )
    plan = plan_overlap(
        rows_1=425828,
        rows_2=461112,
        tax_cols=100,
        column_overlap=0.75,
        row_overlap=0.47,
        cols_file1=cols1,
        cols_file2=cols2,
    )
    assert plan.n_shared_cols == 75
    assert plan.n_shared_rows == 200139
    assert len(plan.cols_file1) == 100
    assert len(plan.cols_file2) == 100
    assert len(set(plan.cols_file1) & set(plan.cols_file2)) == 75
    assert len(plan.gene_ids_file1) == 425828
    assert len(plan.gene_ids_file2) == 461112
    assert len(set(plan.gene_ids_file1) & set(plan.gene_ids_file2)) == 200139


def test_plan_overlap_raises_on_wrong_column_lengths():
    with pytest.raises(ValueError, match="cols_file1/cols_file2"):
        plan_overlap(
            rows_1=10,
            rows_2=10,
            tax_cols=5,
            column_overlap=0.5,
            row_overlap=0.5,
            cols_file1=(1, 2, 3),
            cols_file2=(1, 2, 3, 4, 5),
        )


def test_plan_overlap_raises_when_row_overlap_too_high_for_rows_2():
    rng = random.Random(0)
    cols1, cols2 = sample_tax_columns(
        list(range(100)), tax_cols=10, column_overlap=0.5, rng=rng
    )
    with pytest.raises(ValueError, match="n_shared_rows exceeds row counts"):
        plan_overlap(
            rows_1=100,
            rows_2=10,
            tax_cols=10,
            column_overlap=0.5,
            row_overlap=0.9,
            cols_file1=cols1,
            cols_file2=cols2,
        )


def test_ec_for_row_index_covers_all_ecs():
    ecs = [f"1.1.1.{i}" for i in range(10)]
    seen = {ec_for_row_index(i, ecs) for i in range(10)}
    assert seen == set(ecs)
    assert ec_for_row_index(10, ecs) == ecs[0]
    assert ec_for_row_index(11, ecs) == ecs[1]


def test_ec_for_row_index_raises_on_empty_ecs():
    with pytest.raises(ValueError, match="ecs_shuffled must not be empty"):
        ec_for_row_index(0, [])


def test_sample_tax_columns_requires_enough_pool():
    pool = list(range(1000))
    cols1, cols2 = sample_tax_columns(
        pool, tax_cols=10, column_overlap=0.75, rng=random.Random(0)
    )
    assert len(cols1) == 10
    assert len(cols2) == 10
    assert len(set(cols1) & set(cols2)) == 8  # round(0.75 * 10)
    assert len(set(cols1) | set(cols2)) == 12  # 2 * tax_cols - n_shared


def test_sample_tax_columns_raises_when_pool_too_small():
    with pytest.raises(ValueError, match="species pool"):
        sample_tax_columns(
            [1, 2, 3],
            tax_cols=10,
            column_overlap=0.75,
            rng=random.Random(0),
        )


def test_sample_tax_columns_raises_when_column_overlap_too_high():
    with pytest.raises(ValueError, match="column_overlap must be between 0 and 1"):
        sample_tax_columns(
            list(range(100)),
            tax_cols=10,
            column_overlap=1.5,
            rng=random.Random(0),
        )


def test_default_kingdom_count():
    assert len(DEFAULT_KINGDOM_TAX_IDS) == 8


def test_build_row_sums_rpkm_and_formats_zeros():
    cols = (100, 200)
    rng = random.Random(1)
    row = build_row(
        gene_id="stress_g_000000001",
        ec="1.6.5.9",
        tax_cols=cols,
        density=0.5,
        rng=rng,
    )
    assert row["GeneID"] == "stress_g_000000001"
    assert row["EC#"] == "1.6.5.9"
    assert row["Unclassified"] == "0.000000"
    tax_sum = sum(float(row[str(c)]) for c in cols)
    assert float(row["RPKM"]) == pytest.approx(tax_sum)


def test_validate_tsv_mini(tmp_path):
    out = tmp_path / "mini.tsv"
    cols = (1280, 1282)
    with out.open("w", encoding="utf-8", newline="") as f:
        write_tsv_header(f, cols)
        rng = random.Random(0)
        for i in range(3):
            row = build_row(
                gene_id=f"g{i}",
                ec="1.6.5.9",
                tax_cols=cols,
                density=1.0,
                rng=rng,
            )
            f.write(row_to_tsv_line(row, cols) + "\n")
    report = validate_tsv(
        out, expected_rows=3, tax_cols=cols, density=1.0, ec_pool={"1.6.5.9"}
    )
    assert report["rows"] == 3
    assert report["distinct_ecs"] == 1
    assert report["nonzero_rate"] == pytest.approx(1.0, abs=0.01)


@pytest.mark.skipif(not _parquet_available(), reason="reference parquet missing")
def test_load_pools_returns_expected_sizes():
    parquet_dir = _repo_root() / "resources/db/parquet"
    species, ecs = load_pools(parquet_dir, DEFAULT_KINGDOM_TAX_IDS)
    assert len(species) >= 430_000
    assert len(ecs) == 3867
    assert species == sorted(species)
    assert ecs == sorted(ecs)
    assert all("." in ec for ec in ecs)
