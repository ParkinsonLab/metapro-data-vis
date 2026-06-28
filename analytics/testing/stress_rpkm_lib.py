# analytics/testing/stress_rpkm_lib.py
from __future__ import annotations

import csv
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

import duckdb

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

SPECIES_SQL = """
    SELECT p.tax_id
    FROM parents p
    WHERE p.t_kingdom IN (SELECT unnest(?::BIGINT[]))
      AND p.t_species = p.tax_id
    ORDER BY p.tax_id
"""

EC_SQL = """
    SELECT DISTINCT n.name AS ec_normalized
    FROM pathway_nodes n
    WHERE regexp_matches(n.name, '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$')
      AND n.name != '0.0.0.0'
    ORDER BY ec_normalized
"""


def load_pools(
    raw_parquet_dir: Path,
    kingdom_tax_ids: tuple[int, ...] = DEFAULT_KINGDOM_TAX_IDS,
) -> tuple[list[int], list[str]]:
    parents_path = raw_parquet_dir / "parents.parquet"
    nodes_path = raw_parquet_dir / "pathway_nodes.parquet"
    if not parents_path.exists():
        raise FileNotFoundError(f"missing {parents_path}")
    if not nodes_path.exists():
        raise FileNotFoundError(f"missing {nodes_path}")

    parents_sql = parents_path.as_posix().replace("'", "''")
    nodes_sql = nodes_path.as_posix().replace("'", "''")

    conn = duckdb.connect()
    try:
        conn.execute(
            f"CREATE OR REPLACE VIEW parents AS SELECT * FROM read_parquet('{parents_sql}')"
        )
        conn.execute(
            f"CREATE OR REPLACE VIEW pathway_nodes AS SELECT * FROM read_parquet('{nodes_sql}')"
        )
        species = [
            int(r[0])
            for r in conn.execute(SPECIES_SQL, [list(kingdom_tax_ids)]).fetchall()
        ]
        ecs = [str(r[0]) for r in conn.execute(EC_SQL).fetchall()]
    finally:
        conn.close()
    return species, ecs


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
    if rows_1 <= 0 or rows_2 <= 0:
        raise ValueError("rows_1 and rows_2 must be positive")
    if not (0 <= column_overlap <= 1):
        raise ValueError("column_overlap must be between 0 and 1")
    if not (0 <= row_overlap <= 1):
        raise ValueError("row_overlap must be between 0 and 1")

    n_shared_cols = round(column_overlap * tax_cols)
    n_shared_rows = round(row_overlap * rows_1)
    if n_shared_rows > rows_1 or n_shared_rows > rows_2:
        raise ValueError("n_shared_rows exceeds row counts")

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
    if tax_cols <= 0:
        raise ValueError("tax_cols must be positive")
    if not (0 <= column_overlap <= 1):
        raise ValueError("column_overlap must be between 0 and 1")

    n_shared = round(column_overlap * tax_cols)
    if n_shared > tax_cols:
        raise ValueError("n_shared exceeds tax_cols")
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


def write_tsv_header(fp, tax_cols: tuple[int, ...]) -> None:
    header = list(FIXED_COLUMNS) + [str(t) for t in tax_cols]
    fp.write("\t".join(header) + "\n")


def build_row(
    *,
    gene_id: str,
    ec: str,
    tax_cols: tuple[int, ...],
    density: float,
    rng: random.Random,
) -> dict[str, str]:
    row: dict[str, str] = {
        "GeneID": gene_id,
        "Length": str(rng.randint(50, 2000)),
        "Reads": str(rng.randint(1, 50)),
        "EC#": ec,
        "Unclassified": "0.000000",
    }
    tax_sum = 0.0
    for tax_id in tax_cols:
        key = str(tax_id)
        if rng.random() < density:
            val = rng.uniform(0.01, 10.0)
            row[key] = f"{val:.6f}"
            tax_sum += val
        else:
            row[key] = "0.000000"
    row["RPKM"] = f"{tax_sum:.6f}"
    return row


def row_to_tsv_line(row: dict[str, str], tax_cols: tuple[int, ...]) -> str:
    fields = [row[c] for c in FIXED_COLUMNS] + [row[str(t)] for t in tax_cols]
    return "\t".join(fields)


def validate_tsv(
    path: Path,
    *,
    expected_rows: int,
    tax_cols: tuple[int, ...],
    density: float,
    ec_pool: set[str],
) -> dict:
    nonzero = 0
    total_cells = 0
    distinct_ecs: set[str] = set()
    rows = 0
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        header_tax = [h for h in reader.fieldnames or [] if h not in FIXED_COLUMNS]
        if tuple(int(h) for h in header_tax) != tax_cols:
            raise ValueError(f"tax column mismatch in {path}")
        for record in reader:
            rows += 1
            ec = record["EC#"]
            distinct_ecs.add(ec)
            if ec not in ec_pool:
                raise ValueError(f"unmapped EC {ec!r} in {path}")
            for h in header_tax:
                total_cells += 1
                if float(record[h]) > 0:
                    nonzero += 1
    if rows != expected_rows:
        raise ValueError(f"expected {expected_rows} rows, got {rows}")
    rate = nonzero / total_cells if total_cells else 0.0
    if expected_rows > 100 and abs(rate - density) > 0.05:
        raise ValueError(f"nonzero rate {rate:.3f} outside tolerance for density {density}")
    body = path.read_bytes()
    return {
        "rows": rows,
        "distinct_ecs": len(distinct_ecs),
        "nonzero_rate": rate,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def write_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
