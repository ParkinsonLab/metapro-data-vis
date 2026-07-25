"""Distribution-time reference bridge builder (pure DuckDB SQL — no dbt)."""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[3]
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


def build_bridge_tax_lineage(conn: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """
    Return a DuckDB relation for bridge_tax_lineage.
    One row per tax_id with kingdom..species id/label columns.
    ORDER BY tax_id for Parquet compression.
    """
    if not _table_exists(conn, "bridge_tax_rank_map"):
        build_bridge_tax_rank_map(conn)

    return conn.sql("""
        WITH base AS (
            SELECT DISTINCT tax_id FROM bridge_tax_rank_map
            UNION
            SELECT DISTINCT tax_id FROM parents
        ),
        lineage AS (
            SELECT
                p.tax_id,
                p.t_kingdom AS kingdom_id, p.t_phylum AS phylum_id,
                p.t_class AS class_id, p.t_order AS order_id,
                p.t_family AS family_id, p.t_genus AS genus_id,
                p.t_species AS species_id
            FROM parents p
            JOIN base b ON b.tax_id = p.tax_id
        )
        SELECT
            l.tax_id,
            COALESCE(n_self.name, CAST(l.tax_id AS VARCHAR)) AS display_name,
            l.kingdom_id, nk.name AS kingdom_label,
            l.phylum_id,  np.name AS phylum_label,
            l.class_id,   nc.name AS class_label,
            l.order_id,   no.name AS order_label,
            l.family_id,  nf.name AS family_label,
            l.genus_id,   ng.name AS genus_label,
            l.species_id, ns.name AS species_label
        FROM lineage l
        LEFT JOIN names n_self ON n_self.tax_id = l.tax_id
        LEFT JOIN names nk ON nk.tax_id = l.kingdom_id
        LEFT JOIN names np ON np.tax_id = l.phylum_id
        LEFT JOIN names nc ON nc.tax_id = l.class_id
        LEFT JOIN names no ON no.tax_id = l.order_id
        LEFT JOIN names nf ON nf.tax_id = l.family_id
        LEFT JOIN names ng ON ng.tax_id = l.genus_id
        LEFT JOIN names ns ON ns.tax_id = l.species_id
        ORDER BY l.tax_id
    """)


def _assert_bridge_ec_pathway(conn: duckdb.DuckDBPyConnection, out_path: Path) -> None:
    zero_rows = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{out_path}') WHERE ec_normalized = '0.0.0.0'"
    ).fetchone()[0]
    assert zero_rows == 0, f"bridge_ec_pathway contains {zero_rows} rows with ec_normalized='0.0.0.0'"
    total = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    assert total > 0, "bridge_ec_pathway is empty"
    print(f"  bridge_ec_pathway: {total:,} rows, 0.0.0.0 check passed")


def _assert_bridge_tax_lineage(conn: duckdb.DuckDBPyConnection, out_path: Path) -> None:
    total = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    assert total > 0, "bridge_tax_lineage is empty"
    cols = conn.execute(f"DESCRIBE SELECT * FROM read_parquet('{out_path}')").fetchall()
    col_names = {row[0] for row in cols}
    for rank in RANKS:
        assert f"{rank[0]}_label" in col_names, f"missing {rank[0]}_label column"
    print(f"  bridge_tax_lineage: {total:,} rows, 7 rank label columns confirmed")


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

    print("Building bridge_tax_lineage…")
    tax_path = out_dir / "bridge_tax_lineage.parquet"
    conn.execute(
        "CREATE OR REPLACE TABLE _bridge_tax_lineage AS (" + build_bridge_tax_lineage(conn).sql_query() + ")"
    )
    conn.execute(f"COPY _bridge_tax_lineage TO '{tax_path}' (FORMAT PARQUET)")
    _assert_bridge_tax_lineage(conn, tax_path)

    print("Done.")


if __name__ == "__main__":
    main()
