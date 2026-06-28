# Stress RPKM Generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local generator that writes two dense, pathway-valid wide RPKM TSVs (`stress_rpkm_1.tsv`, `stress_rpkm_2.tsv`) for dbt pipeline and API stress testing.

**Architecture:** DuckDB loads sorted species + EC pools from reference Parquet; pure-Python `stress_rpkm_lib` handles overlap planning, EC assignment, validation; `generate_stress_rpkm.py` streams TSV rows in chunks and writes a JSON manifest.

**Tech Stack:** Python 3.14, DuckDB, argparse, pytest; reference Parquet at `resources/db/parquet`

**Worktree:** `.worktrees/chord-dbt-api/` on branch `feature/chord-dbt-api`

**Spec:** `docs/superpowers/specs/2026-06-28-stress-rpkm-generator-design.md`

---

## File Map

```
analytics/
├── testing/
│   └── stress_rpkm_lib.py                 # CREATE — pools, overlap, EC, validate (pure + DuckDB)
├── transform/
│   └── scripts/
│       └── generate_stress_rpkm.py          # CREATE — CLI + chunked TSV writer
└── transform/tests/python/
    └── test_generate_stress_rpkm.py         # CREATE — unit + mini e2e tests

.gitignore                                   # MODIFY — explicit stress_rpkm patterns (optional; resources/* already ignores)
```

Outputs (already under `resources/*` gitignore):

```
resources/example_data/stress_rpkm_1.tsv
resources/example_data/stress_rpkm_2.tsv
resources/example_data/stress_rpkm_manifest.json
```

---

### Task 1: Overlap planner (pure Python)

**Files:**
- Create: `analytics/testing/stress_rpkm_lib.py`
- Create: `analytics/transform/tests/python/test_generate_stress_rpkm.py`

- [ ] **Step 1: Write the failing tests**

```python
# analytics/transform/tests/python/test_generate_stress_rpkm.py
from __future__ import annotations

import pytest

from testing.stress_rpkm_lib import (
    DEFAULT_KINGDOM_TAX_IDS,
    OverlapPlan,
    ec_for_row_index,
    plan_overlap,
    sample_tax_columns,
)


def test_plan_overlap_defaults():
    plan = plan_overlap(
        rows_1=425828,
        rows_2=461112,
        tax_cols=100,
        column_overlap=0.75,
        row_overlap=0.47,
    )
    assert plan.n_shared_cols == 75
    assert plan.n_shared_rows == 200139
    assert len(plan.cols_file1) == 100
    assert len(plan.cols_file2) == 100
    assert len(set(plan.cols_file1) & set(plan.cols_file2)) == 75
    assert len(plan.gene_ids_file1) == 425828
    assert len(plan.gene_ids_file2) == 461112
    assert len(set(plan.gene_ids_file1) & set(plan.gene_ids_file2)) == 200139


def test_ec_for_row_index_covers_all_ecs():
    ecs = [f"1.1.1.{i}" for i in range(10)]
    seen = {ec_for_row_index(i, ecs) for i in range(10)}
    assert seen == set(ecs)
    assert ec_for_row_index(10, ecs) == ecs[0]
    assert ec_for_row_index(11, ecs) == ecs[1]


def test_sample_tax_columns_requires_enough_pool():
    pool = list(range(1000))
    cols1, cols2 = sample_tax_columns(
        pool, tax_cols=10, column_overlap=0.75, rng=__import__("random").Random(0)
    )
    assert len(cols1) == 10
    assert len(cols2) == 10
    assert len(set(cols1) & set(cols2)) == 8  # round(0.75 * 10)
    assert len(set(cols1) | set(cols2)) == 18


def test_sample_tax_columns_raises_when_pool_too_small():
    with pytest.raises(ValueError, match="species pool"):
        sample_tax_columns([1, 2, 3], tax_cols=10, column_overlap=0.75, rng=__import__("random").Random(0))


def test_default_kingdom_count():
    assert len(DEFAULT_KINGDOM_TAX_IDS) == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py -v`
Expected: FAIL — `ModuleNotFoundError: testing.stress_rpkm_lib`

- [ ] **Step 3: Write minimal implementation**

```python
# analytics/testing/stress_rpkm_lib.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add analytics/testing/stress_rpkm_lib.py analytics/transform/tests/python/test_generate_stress_rpkm.py
git commit -m "feat(stress-rpkm): add overlap planner and EC assignment helpers"
```

---

### Task 2: DuckDB pool loader

**Files:**
- Modify: `analytics/testing/stress_rpkm_lib.py`
- Modify: `analytics/transform/tests/python/test_generate_stress_rpkm.py`

- [ ] **Step 1: Write the failing test**

Append to `test_generate_stress_rpkm.py`:

```python
import os
from pathlib import Path

import pytest

from testing.stress_rpkm_lib import load_pools


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]  # worktree / repo root


def _analytics_dir() -> Path:
    return Path(__file__).resolve().parents[3]


def _parquet_available() -> bool:
    d = _repo_root() / "resources/db/parquet"
    return (d / "parents.parquet").exists() and (d / "pathway_nodes.parquet").exists()


@pytest.mark.skipif(not _parquet_available(), reason="reference parquet missing")
def test_load_pools_returns_expected_sizes():
    parquet_dir = _repo_root() / "resources/db/parquet"
    species, ecs = load_pools(parquet_dir, DEFAULT_KINGDOM_TAX_IDS)
    assert len(species) >= 430_000
    assert len(ecs) == 3867
    assert species == sorted(species)
    assert ecs == sorted(ecs)
    assert all("." in ec for ec in ecs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py::test_load_pools_returns_expected_sizes -v`
Expected: FAIL — `ImportError: cannot import name 'load_pools'`

- [ ] **Step 3: Implement `load_pools`**

Append to `stress_rpkm_lib.py`:

```python
from pathlib import Path

import duckdb

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

    conn = duckdb.connect()
    try:
        conn.execute(
            f"CREATE OR REPLACE VIEW parents AS SELECT * FROM read_parquet('{parents_path}')"
        )
        conn.execute(
            f"CREATE OR REPLACE VIEW pathway_nodes AS SELECT * FROM read_parquet('{nodes_path}')"
        )
        species = [int(r[0]) for r in conn.execute(SPECIES_SQL, [list(kingdom_tax_ids)]).fetchall()]
        ecs = [str(r[0]) for r in conn.execute(EC_SQL).fetchall()]
    finally:
        conn.close()
    return species, ecs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py::test_load_pools_returns_expected_sizes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analytics/testing/stress_rpkm_lib.py analytics/transform/tests/python/test_generate_stress_rpkm.py
git commit -m "feat(stress-rpkm): load species and EC pools from reference parquet"
```

---

### Task 3: Row generation + post-validation helpers

**Files:**
- Modify: `analytics/testing/stress_rpkm_lib.py`
- Modify: `analytics/transform/tests/python/test_generate_stress_rpkm.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_generate_stress_rpkm.py`:

```python
from testing.stress_rpkm_lib import (
    build_row,
    validate_tsv,
    write_tsv_header,
)


def test_build_row_sums_rpkm_and_formats_zeros():
    cols = (100, 200)
    rng = __import__("random").Random(1)
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
  # RPKM equals sum of tax values > 0
    tax_sum = sum(float(row[str(c)]) for c in cols)
    assert float(row["RPKM"]) == pytest.approx(tax_sum)


def test_validate_tsv_mini(tmp_path):
    out = tmp_path / "mini.tsv"
    cols = (1280, 1282)
    with out.open("w", encoding="utf-8", newline="") as f:
        write_tsv_header(f, cols)
        rng = __import__("random").Random(0)
        for i in range(3):
            row = build_row(
                gene_id=f"g{i}",
                ec="1.6.5.9",
                tax_cols=cols,
                density=1.0,
                rng=rng,
            )
            f.write("\t".join(row[c] for c in ["GeneID", "Length", "Reads", "EC#", "RPKM", "Unclassified"] + [str(c) for c in cols]) + "\n")
    report = validate_tsv(out, expected_rows=3, tax_cols=cols, density=1.0, ec_pool={"1.6.5.9"})
    assert report["rows"] == 3
    assert report["distinct_ecs"] == 1
    assert report["nonzero_rate"] == pytest.approx(1.0, abs=0.01)
```

Add helpers to `stress_rpkm_lib.py` imports in test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py::test_build_row_sums_rpkm_and_formats_zeros -v`
Expected: FAIL — `cannot import name 'build_row'`

- [ ] **Step 3: Implement row builder, header writer, validator**

Append to `stress_rpkm_lib.py`:

```python
import csv
import hashlib
import json
from datetime import datetime, timezone


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
    if abs(rate - density) > 0.05 and expected_rows > 100:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py::test_build_row_sums_rpkm_and_formats_zeros transform/tests/python/test_generate_stress_rpkm.py::test_validate_tsv_mini -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analytics/testing/stress_rpkm_lib.py analytics/transform/tests/python/test_generate_stress_rpkm.py
git commit -m "feat(stress-rpkm): add row builder and TSV validation helpers"
```

---

### Task 4: CLI generator script

**Files:**
- Create: `analytics/transform/scripts/generate_stress_rpkm.py`

- [ ] **Step 1: Write the failing mini e2e test**

Append to `test_generate_stress_rpkm.py`:

```python
import subprocess
import sys


def test_cli_mini_generation(tmp_path):
    if not _parquet_available():
        pytest.skip("reference parquet missing")
    parquet_dir = _repo_root() / "resources/db/parquet"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    script = _analytics_dir() / "transform/scripts/generate_stress_rpkm.py"
    cmd = [
        sys.executable,
        str(script),
        "--output-dir",
        str(out_dir),
        "--raw-parquet-dir",
        str(parquet_dir),
        "--rows-1",
        "50",
        "--rows-2",
        "60",
        "--tax-cols",
        "10",
        "--density",
        "0.5",
        "--column-overlap",
        "0.75",
        "--row-overlap",
        "0.47",
    ]
    result = subprocess.run(cmd, cwd=_analytics_dir(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (out_dir / "stress_rpkm_1.tsv").exists()
    assert (out_dir / "stress_rpkm_2.tsv").exists()
    assert (out_dir / "stress_rpkm_manifest.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py::test_cli_mini_generation -v`
Expected: FAIL — script missing or nonzero exit

- [ ] **Step 3: Implement `generate_stress_rpkm.py`**

```python
# analytics/transform/scripts/generate_stress_rpkm.py
"""Generate dense stress RPKM TSVs. See docs/superpowers/specs/2026-06-28-stress-rpkm-generator-design.md"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow `from testing.stress_rpkm_lib import ...` when run as script
_ANALYTICS = Path(__file__).resolve().parents[2]
if str(_ANALYTICS) not in sys.path:
    sys.path.insert(0, str(_ANALYTICS))

from testing.stress_rpkm_lib import (  # noqa: E402
    build_row,
    ec_for_row_index,
    load_pools,
    plan_overlap,
    row_to_tsv_line,
    sample_tax_columns,
    validate_tsv,
    write_manifest,
    write_tsv_header,
)

DEFAULT_OUTPUT = _ANALYTICS.parent / "resources/example_data"


def _write_file(
    path: Path,
    *,
    gene_ids: tuple[str, ...],
    tax_cols: tuple[int, ...],
    ecs_shuffled: list[str],
    density: float,
    rng: random.Random,
    chunk_size: int = 1000,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        write_tsv_header(fp, tax_cols)
        buf: list[str] = []
        for i, gene_id in enumerate(gene_ids):
            ec = ec_for_row_index(i, ecs_shuffled)
            row = build_row(
                gene_id=gene_id,
                ec=ec,
                tax_cols=tax_cols,
                density=density,
                rng=rng,
            )
            buf.append(row_to_tsv_line(row, tax_cols))
            if len(buf) >= chunk_size:
                fp.write("\n".join(buf) + "\n")
                buf.clear()
        if buf:
            fp.write("\n".join(buf) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate stress RPKM TSV pair")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-parquet-dir", type=Path, default=_ANALYTICS.parent / "resources/db/parquet")
    parser.add_argument("--rows-1", type=int, default=425828)
    parser.add_argument("--rows-2", type=int, default=461112)
    parser.add_argument("--tax-cols", type=int, default=100)
    parser.add_argument("--density", type=float, default=0.95)
    parser.add_argument("--column-overlap", type=float, default=0.75)
    parser.add_argument("--row-overlap", type=float, default=0.47)
    args = parser.parse_args()

    if not 0 < args.density <= 1:
        raise SystemExit("--density must be in (0, 1]")
    if not 0 <= args.column_overlap <= 1:
        raise SystemExit("--column-overlap must be in [0, 1]")
    if not 0 <= args.row_overlap <= 1:
        raise SystemExit("--row-overlap must be in [0, 1]")

    t0 = time.perf_counter()
    rng = random.Random()
    species, ecs = load_pools(args.raw_parquet_dir)
    ecs_shuffled = ecs[:]
    rng.shuffle(ecs_shuffled)

    cols_1, cols_2 = sample_tax_columns(
        species,
        tax_cols=args.tax_cols,
        column_overlap=args.column_overlap,
        rng=rng,
    )
    plan = plan_overlap(
        rows_1=args.rows_1,
        rows_2=args.rows_2,
        tax_cols=args.tax_cols,
        column_overlap=args.column_overlap,
        row_overlap=args.row_overlap,
        cols_file1=cols_1,
        cols_file2=cols_2,
    )

    out1 = args.output_dir / "stress_rpkm_1.tsv"
    out2 = args.output_dir / "stress_rpkm_2.tsv"
    ec_pool = set(ecs)

    _write_file(out1, gene_ids=plan.gene_ids_file1, tax_cols=cols_1, ecs_shuffled=ecs_shuffled, density=args.density, rng=rng)
    _write_file(out2, gene_ids=plan.gene_ids_file2, tax_cols=cols_2, ecs_shuffled=ecs_shuffled, density=args.density, rng=rng)

    rep1 = validate_tsv(out1, expected_rows=args.rows_1, tax_cols=cols_1, density=args.density, ec_pool=ec_pool)
    rep2 = validate_tsv(out2, expected_rows=args.rows_2, tax_cols=cols_2, density=args.density, ec_pool=ec_pool)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
        "cli_args": {
            "output_dir": str(args.output_dir),
            "raw_parquet_dir": str(args.raw_parquet_dir),
            "rows_1": args.rows_1,
            "rows_2": args.rows_2,
            "tax_cols": args.tax_cols,
            "density": args.density,
            "column_overlap": args.column_overlap,
            "row_overlap": args.row_overlap,
        },
        "pools": {"species": len(species), "ecs": len(ecs)},
        "overlap": {
            "shared_columns": plan.n_shared_cols,
            "shared_rows": plan.n_shared_rows,
        },
        "files": [
            {"name": out1.name, **rep1},
            {"name": out2.name, **rep2},
        ],
    }
    write_manifest(args.output_dir / "stress_rpkm_manifest.json", manifest)
    print(f"Wrote {out1} and {out2}")
    print(f"Manifest: {args.output_dir / 'stress_rpkm_manifest.json'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run mini e2e test**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py::test_cli_mini_generation -v`
Expected: PASS

- [ ] **Step 5: Run full unit suite**

Run: `cd analytics && uv run pytest transform/tests/python/test_generate_stress_rpkm.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add analytics/transform/scripts/generate_stress_rpkm.py analytics/transform/tests/python/test_generate_stress_rpkm.py
git commit -m "feat(stress-rpkm): add CLI generator for stress RPKM TSV pair"
```

---

### Task 5: Gitignore documentation

**Files:**
- Modify: `.gitignore` (repo root)

- [ ] **Step 1: Add explicit patterns** (clarity; `resources/*` already ignores outputs)

Append to repo root `.gitignore`:

```
# stress RPKM generator outputs (also under resources/*)
resources/example_data/stress_rpkm_*.tsv
resources/example_data/stress_rpkm_manifest.json
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore stress RPKM generator outputs"
```

---

### Task 6: Manual verification (full-size)

**Not automated** — run locally after implementation.

- [ ] **Step 1: Generate full stress files**

```bash
cd .worktrees/chord-dbt-api/analytics
uv run python transform/scripts/generate_stress_rpkm.py
```

Expected: ~2–5 min per file; manifest shows `distinct_ecs: 3867`, `nonzero_rate` ≈ 0.95

- [ ] **Step 2: Run pipeline on stress_rpkm_1**

```bash
uv run python transform/scripts/build_reference.py   # if bridges missing
uv run python transform/scripts/run_pipeline.py \
  --sample-id stress_rpkm_1 \
  --rpkm-path ../../resources/example_data/stress_rpkm_1.tsv
```

Expected: exit 0; `transform/runs/stress_rpkm_1/sample.duckdb` exists

- [ ] **Step 3: Smoke chord API** (bridges + DB present)

```bash
uv run python -c "
from api.chord_service import build_chord_from_duckdb
out = build_chord_from_duckdb(sample_id='stress_rpkm_1', tax_level='phylum', ann_level='superpathway')
assert 'index' in out and 'count_matrix' in out
print('pairs', len(out['index']))
"
```

Expected: prints pair count without error

- [ ] **Step 4: Confirm fake_rpkm tests still pass**

```bash
uv run pytest transform/tests/python/test_fake_rpkm_pipeline.py api/tests/test_chord_service.py -q --ignore=api/tests/test_chord_service.py::test_phylum_rank_tax_order_by_abundance_not_alphabetical
```

Or full chord tests if bridges built:

```bash
uv run pytest transform/tests/python/test_fake_rpkm_pipeline.py -q
```

Expected: golden tests unaffected

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| Generator script only, gitignored outputs | Task 4, 5 |
| Two files, default row counts | Task 4 CLI defaults |
| 100 tax cols, uniform species sampling | Task 1 `sample_tax_columns`, Task 2 |
| 8 kingdom allowlist | Task 2 `DEFAULT_KINGDOM_TAX_IDS` |
| Configurable density / overlaps | Task 4 argparse |
| Pathway-mapped ECs only, max distinct | Task 1 `ec_for_row_index`, Task 3 validator |
| Shared row/col overlap semantics | Task 1 `plan_overlap`, `sample_tax_columns` |
| Manifest JSON | Task 3 `write_manifest`, Task 4 |
| Post-generation validation | Task 3 `validate_tsv` |
| Mini pytest suite | Tasks 1–4 |
| No fake_rpkm changes | — |
| `--seed` deferred | — |
| Manual pipeline/API workflow | Task 6 |

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-28-stress-rpkm-generator.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
