from __future__ import annotations

import random

import pytest

from testing.stress_rpkm_lib import (
    DEFAULT_KINGDOM_TAX_IDS,
    ec_for_row_index,
    plan_overlap,
    sample_tax_columns,
)


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
