from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PARQUET_DIR = REPO_ROOT / "resources/db/parquet"
PATHWAY_SUPERPATHWAYS = RAW_PARQUET_DIR / "pathway_superpathways.parquet"
PATHWAY_NODES = RAW_PARQUET_DIR / "pathway_nodes.parquet"
PATHWAY_EDGES = RAW_PARQUET_DIR / "pathway_edges.parquet"


def _require_pathway_parquet() -> None:
    for path in (PATHWAY_SUPERPATHWAYS, PATHWAY_NODES, PATHWAY_EDGES):
        if not path.exists():
            raise FileNotFoundError(f"reference parquet missing: {path}")


def load_static_graph(pathway_name: str) -> dict:
    _require_pathway_parquet()
    conn = duckdb.connect()
    try:
        psp = PATHWAY_SUPERPATHWAYS.as_posix()
        nodes_p = PATHWAY_NODES.as_posix()
        edges_p = PATHWAY_EDGES.as_posix()
        row = conn.execute(
            f"SELECT id FROM read_parquet('{psp}') WHERE name = ?",
            [pathway_name],
        ).fetchone()
        if row is None:
            return {"nodes": [], "edges": []}
        pathway_id = row[0]
        nodes = conn.execute(
            f"""
            SELECT id, name AS label, x, y, type
            FROM read_parquet('{nodes_p}')
            WHERE pathway = ?
            """,
            [pathway_id],
        ).fetchdf()
        edges = conn.execute(
            f"""
            SELECT source, target
            FROM read_parquet('{edges_p}')
            WHERE pathway = ?
            """,
            [pathway_id],
        ).fetchdf()
        return {
            "nodes": nodes.to_dict(orient="records"),
            "edges": edges.to_dict(orient="records"),
        }
    finally:
        conn.close()
