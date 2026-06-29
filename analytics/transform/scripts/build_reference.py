"""Distribution-time reference bridge builder (pure DuckDB SQL — no dbt)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(subprocess.check_output(
    ['git', 'rev-parse', '--show-toplevel'],
    cwd=Path(__file__).parent
).decode().strip())
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"
REFERENCE_PARQUET_DIR = Path(__file__).resolve().parents[1] / "reference/parquet"

RANKS = [
    ("kingdom", 1),
    ("phylum", 2),
    ("class", 3),
    ("order", 4),
    ("family", 5),
    ("genus", 6),
    ("species", 7),
]


def _attach_raw(conn: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    """Register raw parquet tables as views."""
    for tbl in ["names", "parents", "pathway_nodes", "pathway_superpathways", "superpathways"]:
        conn.execute(
            f"CREATE OR REPLACE VIEW {tbl} AS "
            f"SELECT * FROM read_parquet('{raw_dir}/{tbl}.parquet')"
        )


def build_bridge_ec_pathway(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """
    Return a DuckDB relation for bridge_ec_pathway.
    One row per (ec_normalized, pathway_node_id).
    Filters to EC-dotted names (4-segment pattern), excludes 0.0.0.0.
    ORDER BY superpathway_id, pathway_id, ec_normalized for Parquet compression.
    """
    return conn.sql("""
        SELECT
            n.name                              AS ec_normalized,
            n.id                                AS pathway_node_id,
            ps.id                               AS pathway_id,
            ps.name                             AS pathway_name,
            s.id                                AS superpathway_id,
            s.name                              AS superpathway_name
        FROM pathway_nodes n
        JOIN pathway_superpathways ps ON n.pathway = ps.id
        JOIN superpathways         s  ON ps.superpathway = s.id
        WHERE regexp_matches(n.name, '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$')
          AND n.name != '0.0.0.0'
        ORDER BY s.id, ps.id, n.name
    """)


def build_bridge_tax_rank_map(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Build bridge_tax_rank_map as an in-memory DuckDB table.
    One row per (tax_id, rank, rank_tax_id): the ancestor at each rank.
    """
    conn.execute("""
        CREATE OR REPLACE TABLE bridge_tax_rank_map AS
        SELECT DISTINCT tax_id, rank, rank_tax_id
        FROM (
            SELECT tax_id, 'kingdom' AS rank, t_kingdom AS rank_tax_id FROM parents WHERE t_kingdom IS NOT NULL
            UNION ALL
            SELECT tax_id, 'phylum',  t_phylum  FROM parents WHERE t_phylum  IS NOT NULL
            UNION ALL
            SELECT tax_id, 'class',   t_class   FROM parents WHERE t_class   IS NOT NULL
            UNION ALL
            SELECT tax_id, 'order',   t_order   FROM parents WHERE t_order   IS NOT NULL
            UNION ALL
            SELECT tax_id, 'family',  t_family  FROM parents WHERE t_family  IS NOT NULL
            UNION ALL
            SELECT tax_id, 'genus',   t_genus   FROM parents WHERE t_genus   IS NOT NULL
            UNION ALL
            SELECT tax_id, 'species', t_species FROM parents WHERE t_species IS NOT NULL
        )
    """)


def _table_exists(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    result = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ? AND table_schema = 'main'", [name]
    ).fetchone()
    return result[0] > 0


def build_bridge_tax_rollup(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """
    Return a DuckDB relation for bridge_tax_rollup.
    One row per (source_tax_id, requested_rank): pre-resolved ancestry.
    Exact → coarser fallback → Unclassified (NULL key + 'Unclassified' label).
    ORDER BY requested_rank, source_tax_id for Parquet compression.
    """
    if not _table_exists(conn, "bridge_tax_rank_map"):
        build_bridge_tax_rank_map(conn)

    ranks_values = ", ".join(f"('{r}', {o})" for r, o in RANKS)

    return conn.sql(f"""
        WITH ranks(requested_rank, rank_order) AS (
            VALUES {ranks_values}
        ),
        all_combos AS (
            SELECT DISTINCT
                m.tax_id   AS source_tax_id,
                r.requested_rank,
                r.rank_order AS requested_order
            FROM bridge_tax_rank_map m
            CROSS JOIN ranks r
        ),
        with_match AS (
            SELECT
                c.source_tax_id,
                c.requested_rank,
                m.rank          AS resolved_tax_rank,
                m.rank_tax_id   AS resolved_tax_id,
                ROW_NUMBER() OVER (
                    PARTITION BY c.source_tax_id, c.requested_rank
                    ORDER BY rr.rank_order DESC
                ) AS rn
            FROM all_combos c
            JOIN bridge_tax_rank_map m  ON m.tax_id = c.source_tax_id
            JOIN ranks rr               ON rr.requested_rank = m.rank
            WHERE rr.rank_order <= c.requested_order
        ),
        best AS (
            SELECT source_tax_id, requested_rank, resolved_tax_rank, resolved_tax_id
            FROM with_match WHERE rn = 1
        ),
        final AS (
            SELECT
                c.source_tax_id,
                c.requested_rank,
                b.resolved_tax_id,
                b.resolved_tax_rank,
                COALESCE(n.name, 'Unclassified') AS resolved_tax_label
            FROM all_combos c
            LEFT JOIN best b ON c.source_tax_id = b.source_tax_id
                             AND c.requested_rank = b.requested_rank
            LEFT JOIN names n ON b.resolved_tax_id = n.tax_id
        )
        SELECT source_tax_id, requested_rank, resolved_tax_id, resolved_tax_rank, resolved_tax_label
        FROM final
        ORDER BY requested_rank, source_tax_id
    """)


def _assert_bridge_ec_pathway(conn: duckdb.DuckDBPyConnection, out_path: Path) -> None:
    zero_rows = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{out_path}') WHERE ec_normalized = '0.0.0.0'"
    ).fetchone()[0]
    assert zero_rows == 0, f"bridge_ec_pathway contains {zero_rows} rows with ec_normalized='0.0.0.0'"
    total = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    assert total > 0, "bridge_ec_pathway is empty"
    print(f"  bridge_ec_pathway: {total:,} rows, 0.0.0.0 check passed")


def _assert_bridge_tax_rollup(conn: duckdb.DuckDBPyConnection, out_path: Path) -> None:
    n_ranks = conn.execute(
        f"SELECT COUNT(DISTINCT requested_rank) FROM read_parquet('{out_path}')"
    ).fetchone()[0]
    assert n_ranks == 7, f"bridge_tax_rollup has {n_ranks} distinct requested_rank values (expected 7)"
    total = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    assert total > 0, "bridge_tax_rollup is empty"
    print(f"  bridge_tax_rollup: {total:,} rows, 7 ranks confirmed")


def main() -> None:
    raw_dir = RAW_PARQUET_DIR
    out_dir = REFERENCE_PARQUET_DIR

    if not raw_dir.exists():
        print(
            f"ERROR: {raw_dir} not found. Run analytics/exploration/scripts/export_parquet.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect()
    _attach_raw(conn, raw_dir)

    print("Building bridge_ec_pathway…")
    ec_path = out_dir / "bridge_ec_pathway.parquet"
    conn.execute(
        "CREATE OR REPLACE TABLE _bridge_ec_pathway AS (" + build_bridge_ec_pathway(conn).sql_query() + ")"
    )
    conn.execute(f"COPY _bridge_ec_pathway TO '{ec_path}' (FORMAT PARQUET)")
    _assert_bridge_ec_pathway(conn, ec_path)

    print("Building bridge_tax_rank_map…")
    build_bridge_tax_rank_map(conn)

    print("Building bridge_tax_rollup (may take ~1 min for ~20M rows)…")
    tax_path = out_dir / "bridge_tax_rollup.parquet"
    conn.execute(
        "CREATE OR REPLACE TABLE _bridge_tax_rollup AS (" + build_bridge_tax_rollup(conn).sql_query() + ")"
    )
    conn.execute(f"COPY _bridge_tax_rollup TO '{tax_path}' (FORMAT PARQUET)")
    _assert_bridge_tax_rollup(conn, tax_path)

    print("Done.")


if __name__ == "__main__":
    main()
