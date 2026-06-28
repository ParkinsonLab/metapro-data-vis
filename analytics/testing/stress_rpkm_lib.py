from __future__ import annotations

import random
from dataclasses import dataclass

DEFAULT_KINGDOM_TAX_IDS: tuple[int, ...] = (
    1783272,   # Bacillati
    3384189,   # Fusobacteriati
    3379134,   # Pseudomonadati
    3384194,   # Thermotogati
    3366610,   # Methanobacteriati
    1783276,   # Nanobdellati
    1935183,   # Promethearchaeati
    1783275,   # Thermoproteati
)

FIXED_COLUMNS: tuple[str, ...] = (
    "GeneID",
    "Length",
    "Reads",
    "EC#",
    "RPKM",
    "Unclassified",
)


@dataclass(frozen=True)
class OverlapPlan:
    n_shared_cols: int
    n_shared_rows: int
    cols_file1: tuple[int, ...]
    cols_file2: tuple[int, ...]
    gene_ids_file1: tuple[str, ...]
    gene_ids_file2: tuple[str, ...]


def plan_overlap(
    *,
    rows_1: int,
    rows_2: int,
    tax_cols: int,
    column_overlap: float,
    row_overlap: float,
    cols_file1: tuple[int, ...],
    cols_file2: tuple[int, ...],
) -> OverlapPlan:
    n_shared_cols = round(column_overlap * tax_cols)
    n_shared_rows = round(row_overlap * rows_1)
    if len(cols_file1) != tax_cols or len(cols_file2) != tax_cols:
        raise ValueError("cols_file1/cols_file2 must each have length tax_cols")
    if len(set(cols_file1) & set(cols_file2)) != n_shared_cols:
        raise ValueError("column sets do not match expected shared count")

    shared_genes = tuple(f"stress_g_{i:09d}" for i in range(n_shared_rows))
    genes_1_only = tuple(
        f"stress_g1_{i:09d}" for i in range(rows_1 - n_shared_rows)
    )
    genes_2_only = tuple(
        f"stress_g2_{i:09d}" for i in range(rows_2 - n_shared_rows)
    )
    return OverlapPlan(
        n_shared_cols=n_shared_cols,
        n_shared_rows=n_shared_rows,
        cols_file1=cols_file1,
        cols_file2=cols_file2,
        gene_ids_file1=shared_genes + genes_1_only,
        gene_ids_file2=shared_genes + genes_2_only,
    )


def sample_tax_columns(
    species_pool: list[int],
    *,
    tax_cols: int,
    column_overlap: float,
    rng: random.Random,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    n_shared = round(column_overlap * tax_cols)
    n_unique = 2 * tax_cols - n_shared
    if len(species_pool) < n_unique:
        raise ValueError(
            f"species pool too small: need {n_unique}, got {len(species_pool)}"
        )
    picked = rng.sample(species_pool, n_unique)
    shared = sorted(picked[:n_shared])
    only_1 = sorted(picked[n_shared : n_shared + (tax_cols - n_shared)])
    only_2 = sorted(picked[n_shared + (tax_cols - n_shared) :])
    cols_1 = tuple(shared + only_1)
    cols_2 = tuple(shared + only_2)
    return cols_1, cols_2


def ec_for_row_index(row_index: int, ecs_shuffled: list[str]) -> str:
    n = len(ecs_shuffled)
    if n == 0:
        raise ValueError("ecs_shuffled must not be empty")
    if row_index < n:
        return ecs_shuffled[row_index]
    return ecs_shuffled[(row_index - n) % n]
