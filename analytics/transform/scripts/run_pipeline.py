"""
Thin orchestration wrapper for the RPKM transform pipeline.

Usage:
    cd analytics
    uv run python transform/scripts/run_pipeline.py \\
        --sample-id test_rpkm_1 \\
        --rpkm-path ../resources/example_data/test_rpkm_1.tsv \\
        --tax-rank phylum \\
        --pathway-level pathway
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ANALYTICS_DIR = Path(__file__).resolve().parents[2]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
DEFAULT_REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
DEFAULT_RUNS_DIR = TRANSFORM_DIR / "runs"

REQUIRED_BRIDGES = ["bridge_ec_pathway.parquet", "bridge_tax_lineage.parquet"]

_LINEAGE_RANKS = ("kingdom", "phylum", "class", "order", "family", "genus", "species")

INFO_METRICS_SQL = {
    "rpkm_ec_kegg_coverage": """
        SELECT
            COUNT(DISTINCT ec_normalized) FILTER (WHERE pathway_id IS NOT NULL)::DOUBLE
                / NULLIF(COUNT(DISTINCT ec_normalized), 0)
        FROM mart_rpkm_enriched
    """,
    "pathway_join_fanout_rate": """
        SELECT
            COUNT(DISTINCT (ec_normalized, pathway_id)) FILTER (WHERE pathway_id IS NOT NULL)::DOUBLE
                / NULLIF(COUNT(DISTINCT ec_normalized) FILTER (WHERE pathway_id IS NOT NULL), 0)
        FROM mart_rpkm_enriched
    """,
    "unmapped_ec_value_rate": """
        SELECT SUM(value) FILTER (WHERE pathway_id IS NULL) / NULLIF(SUM(value), 0)
        FROM mart_rpkm_enriched
    """,
    "mart_rollup_exact_match_rate": """
        SELECT SUM(value) FILTER (WHERE {tax_rank}_id IS NOT NULL) / NULLIF(SUM(value), 0)
        FROM mart_rpkm_enriched
    """,
    "mart_rollup_fallback_rate": """
        SELECT SUM(value) FILTER (WHERE {fallback_cond}) / NULLIF(SUM(value), 0)
        FROM mart_rpkm_enriched
    """,
    "mart_unclassified_rate": """
        SELECT SUM(value) FILTER (
            WHERE kingdom_id IS NULL AND phylum_id IS NULL AND class_id IS NULL
              AND order_id IS NULL AND family_id IS NULL
              AND genus_id IS NULL AND species_id IS NULL
        ) / NULLIF(SUM(value), 0)
        FROM mart_rpkm_enriched
    """,
}


def _default_runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR", str(DEFAULT_RUNS_DIR))).resolve()


def _default_reference_parquet_dir() -> Path:
    return Path(
        os.environ.get("REFERENCE_PARQUET_DIR", str(DEFAULT_REFERENCE_PARQUET_DIR))
    ).resolve()


def _rollup_fallback_condition(tax_rank: str) -> str:
    try:
        idx = _LINEAGE_RANKS.index(tax_rank)
    except ValueError as exc:
        raise ValueError(f"unknown tax_rank: {tax_rank!r}") from exc
    coarser = _LINEAGE_RANKS[:idx]
    if not coarser:
        return "FALSE"
    parts = [f"{rank}_id IS NOT NULL" for rank in reversed(coarser)]
    return f"({tax_rank}_id IS NULL AND ({' OR '.join(parts)}))"


def _check_bridges(ref_dir: Path) -> None:
    missing = [f for f in REQUIRED_BRIDGES if not (ref_dir / f).exists()]
    if missing:
        print(
            f"ERROR: Missing bridge Parquet files in {ref_dir}: {missing}\n"
            "Run: cd analytics && uv run python transform/scripts/build_reference.py",
            file=sys.stderr,
        )
        sys.exit(1)


def _prepare_sample_db(db_path: Path) -> None:
    """Remove prior sample.duckdb so dbt does not leave orphan tables from retired models."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", ".wal"):
        stale = Path(f"{db_path}{suffix}")
        if stale.exists():
            stale.unlink()


def _rpkm_identity(rpkm_path: Path | str) -> dict[str, int | str]:
    path = Path(rpkm_path)
    stat = path.stat()
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "rpkm_mtime": int(stat.st_mtime),
        "rpkm_size": stat.st_size,
        "rpkm_sha256": sha256,
    }


def _run_dbt(
    sample_id: str,
    rpkm_path: str,
    tax_rank: str,
    pathway_level: str,
    *,
    runs_dir: Path,
    reference_parquet_dir: Path,
    json_logs: bool = False,
) -> dict:
    db_path = runs_dir / sample_id / "sample.duckdb"
    _prepare_sample_db(db_path)

    vars_dict = {
        "rpkm_path": rpkm_path,
        "sample_id": sample_id,
        "tax_rank": tax_rank,
        "pathway_level": pathway_level,
        "reference_parquet_dir": str(reference_parquet_dir),
    }
    vars_json = json.dumps(vars_dict)

    env = {**os.environ, "DBT_DUCKDB_PATH": str(db_path)}

    cmd = [
        "uv", "run", "dbt", "build",
        "--select", "int_rpkm_by_ec_tax+",
        "--project-dir", str(TRANSFORM_DIR),
        "--profiles-dir", str(TRANSFORM_DIR),
        "--vars", vars_json,
    ]
    if json_logs:
        cmd.extend(["--log-format", "json"])

    result = subprocess.run(
        cmd,
        cwd=str(ANALYTICS_DIR),
        env=env,
        capture_output=False,
    )
    return {"returncode": result.returncode, "db_path": str(db_path)}


def _normalize_dbt_error_message(msg: str) -> str:
    stripped = msg.strip()
    for prefix in ("Invalid Input Error: ", "Binder Error: ", "Catalog Error: "):
        if prefix in stripped:
            return stripped.split(prefix, 1)[-1].strip()
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    return lines[-1] if lines else stripped


def _parse_last_error(transform_dir: Path) -> str | None:
    results_path = transform_dir / "target/run_results.json"
    if not results_path.exists():
        return None
    try:
        data = json.loads(results_path.read_text())
        for result in data.get("results", []):
            if result.get("status") == "error":
                message = result.get("message")
                if message:
                    return _normalize_dbt_error_message(message)
    except Exception:
        return None
    return None


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
    fallback_cond = _rollup_fallback_condition(tax_rank)
    for name, sql in INFO_METRICS_SQL.items():
        try:
            value = conn.execute(
                sql.format(tax_rank=tax_rank, fallback_cond=fallback_cond)
            ).fetchone()[0]
            metrics[name] = round(float(value), 6) if value is not None else None
        except Exception as e:
            metrics[name] = f"error: {e}"
    conn.close()
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RPKM transform pipeline")
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--rpkm-path", required=True)
    parser.add_argument("--tax-rank", default="phylum")
    parser.add_argument("--pathway-level", default="pathway")
    parser.add_argument(
        "--runs-dir",
        default=str(_default_runs_dir()),
        help="Output directory for per-sample run artifacts (default: RUNS_DIR env or transform/runs)",
    )
    parser.add_argument(
        "--json-logs",
        action="store_true",
        help="Pass --log-format json to dbt for machine-readable stdout",
    )
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir).resolve()
    reference_parquet_dir = _default_reference_parquet_dir()
    rpkm_identity = _rpkm_identity(args.rpkm_path)

    _check_bridges(reference_parquet_dir)

    dbt_result = _run_dbt(
        args.sample_id,
        args.rpkm_path,
        args.tax_rank,
        args.pathway_level,
        runs_dir=runs_dir,
        reference_parquet_dir=reference_parquet_dir,
        json_logs=args.json_logs,
    )

    overall_status = _parse_overall_status(TRANSFORM_DIR)
    last_error = _parse_last_error(TRANSFORM_DIR) if overall_status == "failed" else None
    info_metrics = _compute_info_metrics(dbt_result["db_path"], args.tax_rank)

    context = {
        "sample_id": args.sample_id,
        "rpkm_path": args.rpkm_path,
        **rpkm_identity,
        "tax_rank": args.tax_rank,
        "pathway_level": args.pathway_level,
        "reference_parquet_dir": str(reference_parquet_dir),
        "dbt_artifacts": str(TRANSFORM_DIR / "target"),
        "overall_status": overall_status,
        "info_metrics": info_metrics,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }
    if last_error is not None:
        context["last_error"] = last_error

    context_path = runs_dir / args.sample_id / "run_context.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps(context, indent=2))
    print(f"\nrun_context.json written to {context_path}", file=sys.stderr)
    print(f"overall_status: {overall_status}", file=sys.stderr)

    sys.exit(0 if dbt_result["returncode"] == 0 else 1)


if __name__ == "__main__":
    main()
