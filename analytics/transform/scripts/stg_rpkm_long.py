"""Reusable transformation logic for stg_rpkm_long, testable without dbt context."""
from __future__ import annotations

import duckdb

KEY_COLS = ("GeneID", "Length", "Reads", "EC#", "RPKM", "Unclassified")
_EXCLUDE = ", ".join(f'"{c}"' for c in KEY_COLS)


def _escape_sql_str(s: str) -> str:
    """Escape single quotes for safe SQL string embedding."""
    return s.replace("'", "''")


def _transform(
    conn: duckdb.DuckDBPyConnection, rpkm_path: str, sample_id: str
) -> duckdb.DuckDBPyRelation:
    """
    Read wide RPKM TSV at rpkm_path, UNPIVOT tax_id columns, normalize EC#.
    Returns a DuckDB relation with columns:
        sample_id, gene_id, ec_normalized, source_tax_id (BIGINT), value (DOUBLE)
    Filters value > 0; drops rows where source_tax_id is not a valid integer.
    """
    safe_path = _escape_sql_str(rpkm_path)
    safe_sample_id = _escape_sql_str(sample_id)
    return conn.sql(f"""
        WITH wide AS (
            SELECT *
            FROM read_csv(
                '{safe_path}',
                sep = '\t',
                header = true,
                all_varchar = true,
                nullstr = ['', 'NA', 'null', 'NULL', 'None', 'none']
            )
        ),
        unpivoted AS (
            UNPIVOT wide
            ON COLUMNS(* EXCLUDE ({_EXCLUDE}))
            INTO NAME source_tax_id_col VALUE value_str
        ),
        normalized AS (
            SELECT
                '{safe_sample_id}'::VARCHAR                          AS sample_id,
                "GeneID"                                            AS gene_id,
                CASE
                    WHEN "EC#" IS NULL                              THEN '0.0.0.0'
                    WHEN UPPER("EC#") LIKE 'EC:%'                   THEN TRIM(SUBSTRING("EC#", 4))
                    ELSE "EC#"
                END                                                 AS ec_normalized,
                TRY_CAST(source_tax_id_col AS BIGINT)               AS source_tax_id,
                TRY_CAST(value_str AS DOUBLE)                       AS value
            FROM unpivoted
        )
        SELECT sample_id, gene_id, ec_normalized, source_tax_id, value
        FROM normalized
        WHERE value > 0
          AND source_tax_id IS NOT NULL
    """)
