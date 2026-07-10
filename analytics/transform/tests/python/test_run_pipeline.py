from __future__ import annotations

from pathlib import Path

import duckdb

from transform.scripts.run_pipeline import _prepare_sample_db


def test_prepare_sample_db_removes_existing_file_and_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.duckdb"
    wal_path = Path(f"{db_path}.wal")
    db_path.write_text("stub")
    wal_path.write_text("stub")

    _prepare_sample_db(db_path)

    assert not db_path.exists()
    assert not wal_path.exists()


def test_prepare_sample_db_creates_parent_dir(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "sample.duckdb"
    _prepare_sample_db(db_path)
    assert db_path.parent.is_dir()


def test_prepare_sample_db_allows_fresh_duckdb_write(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE legacy_orphan AS SELECT 1 AS x")
    conn.close()

    _prepare_sample_db(db_path)

    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE current_model AS SELECT 2 AS y")
    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    conn.close()

    assert tables == {"current_model"}
