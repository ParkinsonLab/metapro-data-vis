from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import (
    TAX_RANK_ORDER,
    normalise_ann_filter,
    normalise_taxon_filter,
    sample_id_from_names,
    validate_ann_level,
    validate_tax_level,
)
from api.graph_matrix import build_graph_matrix

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_EC_PATH = REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"
REPO_ROOT = ANALYTICS_DIR.parent
NAMES_PATH = REPO_ROOT / "resources/db/parquet/names.parquet"


def _db_path(sample_id: str) -> Path:
    return TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _lineage_order_by_sql() -> str:
    parts = [f"COALESCE(w.{rank}, '')" for rank in TAX_RANK_ORDER]
    parts.append("display_name")
    return ", ".join(parts)


def _ann_filter_key(ann_filter: dict[str, str], ann_level: str) -> tuple[str, str]:
    level, name = ann_filter["level"], ann_filter["name"]
    if ann_level == "superpathway":
        return "superpathway_label", name
    if ann_level == "pathway_node":
        if level == "pathway":
            return "pathway", name
        return "superpathway", name
    if level == "pathway":
        return "pathway", name
    return "superpathway", name


def _ensure_bridge_ec(conn: duckdb.DuckDBPyConnection) -> None:
    if conn.execute(
        "SELECT 1 FROM duckdb_tables() WHERE table_name = 'bridge_ec_long'"
    ).fetchone():
        return
    if not BRIDGE_EC_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_EC_PATH}")

    path = BRIDGE_EC_PATH.as_posix()
    conn.execute(f"CREATE TEMP TABLE bridge_ec AS SELECT * FROM read_parquet('{path}')")
    conn.execute(
        """
        CREATE TEMP TABLE bridge_ec_long AS
        SELECT DISTINCT
            ec_normalized,
            'superpathway_label' AS filter_level,
            CASE
                WHEN ec_normalized = '0.0.0.0' THEN 'Unmapped EC'
                ELSE COALESCE(superpathway_name, ec_normalized)
            END AS filter_name
        FROM bridge_ec
        UNION ALL
        SELECT DISTINCT ec_normalized, 'pathway', pathway_name
        FROM bridge_ec
        WHERE pathway_name IS NOT NULL
        UNION ALL
        SELECT DISTINCT ec_normalized, 'superpathway', superpathway_name
        FROM bridge_ec
        WHERE superpathway_name IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE TEMP TABLE bridge_ec_dedup AS
        SELECT ec_normalized, superpathway_name, pathway_name
        FROM (
            SELECT
                ec_normalized,
                superpathway_name,
                pathway_name,
                ROW_NUMBER() OVER (
                    PARTITION BY ec_normalized
                    ORDER BY superpathway_name, pathway_name
                ) AS rn
            FROM bridge_ec
        )
        WHERE rn = 1
        """
    )


def _ann_exists_clause(ann_filter: dict[str, str] | None, ann_level: str) -> tuple[str, list]:
    if ann_filter is None:
        return "TRUE", []
    filter_level, filter_name = _ann_filter_key(ann_filter, ann_level)
    return (
        "EXISTS ("
        "  SELECT 1 FROM bridge_ec_long b"
        "  WHERE b.ec_normalized = r.ec_normalized"
        "    AND b.filter_level = ? AND b.filter_name = ?"
        ")",
        [filter_level, filter_name],
    )


def _taxon_exists_predicate(taxon_filter: dict[str, str] | None) -> tuple[str, list]:
    if taxon_filter is None:
        return "TRUE", []
    return (
        "EXISTS ("
        "  SELECT 1 FROM read_parquet(?) t"
        "  WHERE t.source_tax_id = r.source_tax_id"
        "    AND t.requested_rank = ?"
        "    AND t.resolved_tax_label = ?"
        ")",
        [
            BRIDGE_TAX_PATH.as_posix(),
            taxon_filter["level"],
            taxon_filter["name"],
        ],
    )


def _fetch_triples(
    conn: duckdb.DuckDBPyConnection,
    *,
    ann_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
    ann_level: str,
) -> list[tuple[str, int, float]]:
    ann_clause, ann_params = _ann_exists_clause(ann_filter, ann_level)
    tax_clause, tax_params = _taxon_exists_predicate(taxon_filter)
    rows = conn.execute(
        f"""
        SELECT r.ec_normalized, r.source_tax_id, r.value
        FROM int_rpkm_by_ec_tax r
        WHERE r.value > 0
          AND ({ann_clause})
          AND ({tax_clause})
        """,
        ann_params + tax_params,
    ).fetchall()
    return [(str(ec), int(tax_id), float(value)) for ec, tax_id, value in rows]


def _ann_category(superpathway_name: str | None, pathway_name: str | None, ann_level: str) -> str:
    if ann_level == "superpathway":
        return superpathway_name or ""
    return pathway_name or ""


def _fetch_ec_metadata(
    conn: duckdb.DuckDBPyConnection,
    ec_keys: list[str],
    *,
    ann_level: str,
) -> list[dict]:
    if not ec_keys:
        return []
    _ensure_bridge_ec(conn)

    placeholders = ", ".join("?" for _ in ec_keys)
    rows = conn.execute(
        f"""
        SELECT ec_normalized, superpathway_name, pathway_name
        FROM bridge_ec_dedup
        WHERE ec_normalized IN ({placeholders})
        ORDER BY superpathway_name, pathway_name, ec_normalized
        """,
        ec_keys,
    ).fetchall()
    return [
        {
            "ec_normalized": ec,
            "superpathway_name": superpathway or "",
            "pathway_name": pathway or "",
            "ann_category": _ann_category(superpathway, pathway, ann_level),
        }
        for ec, superpathway, pathway in rows
    ]


def _fetch_tax_metadata(
    conn: duckdb.DuckDBPyConnection,
    tax_ids: list[int],
    *,
    tax_level: str,
) -> list[dict]:
    if not tax_ids:
        return []
    if not BRIDGE_TAX_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_TAX_PATH}")
    if not NAMES_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {NAMES_PATH}")

    rank_in = _sql_in_list(TAX_RANK_ORDER)
    pivot_cols = ", ".join(f"w.{rank}" for rank in TAX_RANK_ORDER)
    order_by = _lineage_order_by_sql()
    placeholders = ", ".join("?" for _ in tax_ids)
    bridge = BRIDGE_TAX_PATH.as_posix()
    names = NAMES_PATH.as_posix()
    rows = conn.execute(
        f"""
        WITH ids AS (
            SELECT unnest(ARRAY[{placeholders}])::BIGINT AS source_tax_id
        ),
        bridge_gated AS (
            SELECT
                source_tax_id,
                requested_rank,
                CASE
                    WHEN resolved_tax_rank = requested_rank
                    THEN resolved_tax_label
                END AS label
            FROM read_parquet('{bridge}')
            WHERE requested_rank IN ({rank_in})
        ),
        bridge_wide AS (
            SELECT *
            FROM (
                SELECT source_tax_id, requested_rank, label
                FROM bridge_gated
            )
            PIVOT (MAX(label) FOR requested_rank IN ({rank_in}))
        )
        SELECT
            d.source_tax_id,
            {pivot_cols},
            COALESCE(n.name, CAST(d.source_tax_id AS VARCHAR)) AS display_name
        FROM ids d
        LEFT JOIN bridge_wide w USING (source_tax_id)
        LEFT JOIN read_parquet('{names}') n ON d.source_tax_id = n.tax_id
        ORDER BY {order_by}
        """,
        tax_ids,
    ).fetchall()

    out: list[dict] = []
    for row in rows:
        source_tax_id = int(row[0])
        rank_values = row[1 : 1 + len(TAX_RANK_ORDER)]
        display_name = row[1 + len(TAX_RANK_ORDER)]
        tax_map_idx = TAX_RANK_ORDER.index(tax_level)
        tax_map_value = rank_values[tax_map_idx] or ""
        item = {
            "source_tax_id": source_tax_id,
            "display_name": display_name,
            "tax_map_value": tax_map_value,
        }
        for rank, value in zip(TAX_RANK_ORDER, rank_values):
            item[rank] = value or ""
        out.append(item)
    return out


def build_graph_from_duckdb(
    *,
    names: list[str],
    tax_level: str,
    ann_level: str,
    selected_ann_cat: dict | str,
    selected_taxon: dict,
) -> dict:
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")

    validate_tax_level(tax_level)
    validate_ann_level(ann_level)

    ann_filter = normalise_ann_filter(selected_ann_cat, ann_level)
    taxon_filter = normalise_taxon_filter(selected_taxon)
    sample_id = sample_id_from_names(names)
    db_file = _db_path(sample_id)
    if not db_file.exists():
        raise FileNotFoundError(f"sample not found: {sample_id}")

    conn = duckdb.connect(str(db_file), read_only=True)
    try:
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "int_rpkm_by_ec_tax" not in tables:
            raise RuntimeError(
                f"int_rpkm_by_ec_tax not materialized for sample: {sample_id}"
            )

        _ensure_bridge_ec(conn)
        triples_raw = _fetch_triples(
            conn,
            ann_filter=ann_filter,
            taxon_filter=taxon_filter,
            ann_level=ann_level,
        )
        ec_keys = sorted({ec for ec, _, _ in triples_raw})
        tax_ids = sorted({tax_id for _, tax_id, _ in triples_raw})

        ec_rows = _fetch_ec_metadata(conn, ec_keys, ann_level=ann_level)
        tax_rows = _fetch_tax_metadata(conn, tax_ids, tax_level=tax_level)
        display_by_tax_id = {row["source_tax_id"]: row["display_name"] for row in tax_rows}

        triples = [
            (ec, display_by_tax_id[tax_id], value)
            for ec, tax_id, value in triples_raw
            if tax_id in display_by_tax_id
        ]

        return build_graph_matrix(
            triples=triples,
            ec_rows=ec_rows,
            tax_rows=tax_rows,
            ann_level=ann_level,
            tax_level=tax_level,
        )
    finally:
        conn.close()
