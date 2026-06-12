#!/usr/bin/env python3
"""Export taxonomy.db tables to Parquet files for version-controlled EDA."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = REPO_ROOT / "resources/db/taxonomy.db"
PARQUET_DIR = REPO_ROOT / "resources/db/parquet"

TABLES = [
    "names",
    "nodes",
    "parents",
    "pathway_nodes",
    "pathway_edges",
    "pathway_superpathways",
    "superpathways",
]


def main() -> None:
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect()
    conn.execute(f"ATTACH '{DB_PATH}' AS db (TYPE SQLITE)")

    for table in TABLES:
        out = PARQUET_DIR / f"{table}.parquet"
        conn.execute(f"COPY db.{table} TO '{out}' (FORMAT PARQUET)")
        row_count = conn.execute(f"SELECT COUNT(*) FROM '{out}'").fetchone()[0]
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"{table}: {row_count:,} rows → {out} ({size_mb:.1f} MB)")

    print("Done.")


if __name__ == "__main__":
    main()
