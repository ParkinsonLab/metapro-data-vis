from pathlib import Path

import duckdb
import pytest

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

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(),
    reason="taxonomy.db not present locally",
)


def test_parquet_row_counts_match_sqlite():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import export_parquet

    export_parquet.main()

    conn = duckdb.connect()
    conn.execute(f"ATTACH '{DB_PATH}' AS db (TYPE SQLITE)")
    for table in TABLES:
        sqlite_count = conn.execute(f"SELECT COUNT(*) FROM db.{table}").fetchone()[0]
        parquet_count = conn.execute(
            f"SELECT COUNT(*) FROM '{PARQUET_DIR / f'{table}.parquet'}'"
        ).fetchone()[0]
        assert parquet_count == sqlite_count, f"{table}: {parquet_count} != {sqlite_count}"
