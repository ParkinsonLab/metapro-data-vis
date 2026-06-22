"""
Thin orchestration wrapper for the RPKM transform pipeline.

Usage:
    cd analytics
    uv run python transform/scripts/run_pipeline.py \\
        --sample-id test_rpkm_1 \\
        --rpkm-path ../resources/example_data/test_rpkm_1.tsv \\
        --tax-rank phylum \\
        --pathway-level pathway \\
        [--export-mart]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ANALYTICS_DIR = Path(__file__).resolve().parents[2]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"

REQUIRED_BRIDGES = ["bridge_ec_pathway.parquet", "bridge_tax_rollup.parquet"]

INFO_METRICS_SQL = {
    "rpkm_ec_kegg_coverage": """
        SELECT
            COUNT(DISTINCT ec_normalized) FILTER (
                WHERE pathway_key IS NOT NULL AND pathway_level = 'pathway_node'
            )::DOUBLE / NULLIF(COUNT(DISTINCT ec_normalized), 0)
        FROM int_rpkm_pathway
    """,
    "pathway_join_fanout_rate": """
        SELECT
            COUNT(*) FILTER (
                WHERE pathway_level = 'pathway_node' AND pathway_key IS NOT NULL
            )::DOUBLE /
            NULLIF(COUNT(DISTINCT (ec_normalized, source_tax_id)) FILTER (
                WHERE pathway_key IS NOT NULL
            ), 0)
        FROM int_rpkm_pathway
    """,
    "unmapped_ec_value_rate": """
        SELECT SUM(value) FILTER (WHERE pathway_key IS NULL) / NULLIF(SUM(value), 0)
        FROM mart_pathway_taxonomy_long
    """,
    "mart_rollup_exact_match_rate": """
        SELECT
            SUM(value) FILTER (
                WHERE resolved_tax_rank = '{tax_rank}'
                  AND resolved_tax_label != 'Unclassified'
            ) / NULLIF(SUM(value), 0)
        FROM mart_pathway_taxonomy_long
    """,
    "mart_rollup_fallback_rate": """
        SELECT
            SUM(value) FILTER (
                WHERE resolved_tax_rank != '{tax_rank}'
                  AND resolved_tax_label != 'Unclassified'
                  AND resolved_tax_id IS NOT NULL
            ) / NULLIF(SUM(value), 0)
        FROM mart_pathway_taxonomy_long
    """,
    "mart_unclassified_rate": """
        SELECT SUM(value) FILTER (WHERE resolved_tax_label = 'Unclassified') / NULLIF(SUM(value), 0)
        FROM mart_pathway_taxonomy_long
    """,
}


def _check_bridges(ref_dir: Path) -> None:
    missing = [f for f in REQUIRED_BRIDGES if not (ref_dir / f).exists()]
    if missing:
        print(
            f"ERROR: Missing bridge Parquet files in {ref_dir}: {missing}\n"
            "Run: cd analytics && uv run python transform/scripts/build_reference.py",
            file=sys.stderr,
        )
        sys.exit(1)


def _run_dbt(sample_id: str, rpkm_path: str, tax_rank: str, pathway_level: str) -> dict:
    db_path = TRANSFORM_DIR / f"runs/{sample_id}/sample.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    vars_dict = {
        "rpkm_path": rpkm_path,
        "sample_id": sample_id,
        "tax_rank": tax_rank,
        "pathway_level": pathway_level,
        "reference_parquet_dir": str(REFERENCE_PARQUET_DIR),
    }
    vars_json = json.dumps(vars_dict)

    env = {**os.environ, "DBT_DUCKDB_PATH": str(db_path)}

    result = subprocess.run(
        [
            "uv", "run", "dbt", "build",
            "--select", "stg_rpkm_long+",
            "--project-dir", str(TRANSFORM_DIR),
            "--profiles-dir", str(TRANSFORM_DIR),
            "--vars", vars_json,
        ],
        cwd=str(ANALYTICS_DIR),
        env=env,
        capture_output=False,  # stream output to terminal
    )
    return {"returncode": result.returncode, "db_path": str(db_path)}


def _parse_overall_status(transform_dir: Path) -> str:
    results_path = transform_dir / "target/run_results.json"
    if not results_path.exists():
        return "unknown"
    try:
        data = json.loads(results_path.read_text())
        statuses = [r.get("status", "") for r in data.get("results", [])]
        if any("error" in s for s in statuses):
            return "failed"
        if any("warn" in s for s in statuses):
            return "success_with_warnings"
        return "success"
    except Exception:
        return "unknown"


def _compute_info_metrics(db_path: str, tax_rank: str) -> dict:
    metrics = {}
    conn = duckdb.connect(db_path, read_only=True)
    for name, sql in INFO_METRICS_SQL.items():
        try:
            value = conn.execute(sql.format(tax_rank=tax_rank)).fetchone()[0]
            metrics[name] = round(float(value), 6) if value is not None else None
        except Exception as e:
            metrics[name] = f"error: {e}"
    return metrics


def _export_mart(db_path: str, sample_id: str) -> str:
    out_path = str(TRANSFORM_DIR / f"runs/{sample_id}/mart_pathway_taxonomy_long.parquet")
    conn = duckdb.connect(db_path)
    conn.execute(
        f"COPY mart_pathway_taxonomy_long TO '{out_path}' (FORMAT PARQUET)"
    )
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RPKM transform pipeline")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--rpkm-path", required=True)
    parser.add_argument("--tax-rank", default="phylum")
    parser.add_argument("--pathway-level", default="pathway")
    parser.add_argument("--export-mart", action="store_true")
    args = parser.parse_args()

    _check_bridges(REFERENCE_PARQUET_DIR)

    dbt_result = _run_dbt(
        args.sample_id, args.rpkm_path, args.tax_rank, args.pathway_level
    )

    overall_status = _parse_overall_status(TRANSFORM_DIR)
    info_metrics = _compute_info_metrics(dbt_result["db_path"], args.tax_rank)

    context = {
        "sample_id": args.sample_id,
        "rpkm_path": args.rpkm_path,
        "tax_rank": args.tax_rank,
        "pathway_level": args.pathway_level,
        "reference_parquet_dir": str(REFERENCE_PARQUET_DIR),
        "dbt_artifacts": str(TRANSFORM_DIR / "target"),
        "overall_status": overall_status,
        "info_metrics": info_metrics,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }

    context_path = TRANSFORM_DIR / f"runs/{args.sample_id}/run_context.json"
    context_path.write_text(json.dumps(context, indent=2))
    print(f"\nrun_context.json written to {context_path}")
    print(f"overall_status: {overall_status}")

    if args.export_mart:
        mart_path = _export_mart(dbt_result["db_path"], args.sample_id)
        print(f"mart exported to {mart_path}")

    sys.exit(0 if dbt_result["returncode"] == 0 else 1)


if __name__ == "__main__":
    main()
