"""Generate dense stress RPKM TSVs. See docs/superpowers/specs/2026-06-28-stress-rpkm-generator-design.md"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow `from testing.stress_rpkm_lib import ...` when run as script
_ANALYTICS = Path(__file__).resolve().parents[2]
if str(_ANALYTICS) not in sys.path:
    sys.path.insert(0, str(_ANALYTICS))

from testing.stress_rpkm_lib import (  # noqa: E402
    build_row,
    ec_for_row_index,
    load_pools,
    plan_overlap,
    row_to_tsv_line,
    sample_tax_columns,
    validate_tsv,
    write_manifest,
    write_tsv_header,
)

DEFAULT_OUTPUT = _ANALYTICS.parent / "resources/example_data"


def _write_file(
    path: Path,
    *,
    gene_ids: tuple[str, ...],
    tax_cols: tuple[int, ...],
    ecs_shuffled: list[str],
    density: float,
    rng: random.Random,
    chunk_size: int = 1000,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        write_tsv_header(fp, tax_cols)
        buf: list[str] = []
        for i, gene_id in enumerate(gene_ids):
            ec = ec_for_row_index(i, ecs_shuffled)
            row = build_row(
                gene_id=gene_id,
                ec=ec,
                tax_cols=tax_cols,
                density=density,
                rng=rng,
            )
            buf.append(row_to_tsv_line(row, tax_cols))
            if len(buf) >= chunk_size:
                fp.write("\n".join(buf) + "\n")
                buf.clear()
        if buf:
            fp.write("\n".join(buf) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate stress RPKM TSV pair")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--raw-parquet-dir",
        type=Path,
        default=_ANALYTICS.parent / "resources/db/parquet",
    )
    parser.add_argument("--rows-1", type=int, default=425828)
    parser.add_argument("--rows-2", type=int, default=461112)
    parser.add_argument("--tax-cols", type=int, default=100)
    parser.add_argument("--density", type=float, default=0.95)
    parser.add_argument("--column-overlap", type=float, default=0.75)
    parser.add_argument("--row-overlap", type=float, default=0.47)
    args = parser.parse_args()

    if not 0 < args.density <= 1:
        raise SystemExit("--density must be in (0, 1]")
    if not 0 <= args.column_overlap <= 1:
        raise SystemExit("--column-overlap must be in [0, 1]")
    if not 0 <= args.row_overlap <= 1:
        raise SystemExit("--row-overlap must be in [0, 1]")

    t0 = time.perf_counter()
    rng = random.Random()
    species, ecs = load_pools(args.raw_parquet_dir)
    ecs_shuffled = ecs[:]
    rng.shuffle(ecs_shuffled)

    cols_1, cols_2 = sample_tax_columns(
        species,
        tax_cols=args.tax_cols,
        column_overlap=args.column_overlap,
        rng=rng,
    )
    plan = plan_overlap(
        rows_1=args.rows_1,
        rows_2=args.rows_2,
        tax_cols=args.tax_cols,
        column_overlap=args.column_overlap,
        row_overlap=args.row_overlap,
        cols_file1=cols_1,
        cols_file2=cols_2,
    )

    out1 = args.output_dir / "stress_rpkm_1.tsv"
    out2 = args.output_dir / "stress_rpkm_2.tsv"
    ec_pool = set(ecs)

    _write_file(
        out1,
        gene_ids=plan.gene_ids_file1,
        tax_cols=cols_1,
        ecs_shuffled=ecs_shuffled,
        density=args.density,
        rng=rng,
    )
    _write_file(
        out2,
        gene_ids=plan.gene_ids_file2,
        tax_cols=cols_2,
        ecs_shuffled=ecs_shuffled,
        density=args.density,
        rng=rng,
    )

    rep1 = validate_tsv(
        out1,
        expected_rows=args.rows_1,
        tax_cols=cols_1,
        density=args.density,
        ec_pool=ec_pool,
    )
    rep2 = validate_tsv(
        out2,
        expected_rows=args.rows_2,
        tax_cols=cols_2,
        density=args.density,
        ec_pool=ec_pool,
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.perf_counter() - t0, 2),
        "cli_args": {
            "output_dir": str(args.output_dir),
            "raw_parquet_dir": str(args.raw_parquet_dir),
            "rows_1": args.rows_1,
            "rows_2": args.rows_2,
            "tax_cols": args.tax_cols,
            "density": args.density,
            "column_overlap": args.column_overlap,
            "row_overlap": args.row_overlap,
        },
        "pools": {"species": len(species), "ecs": len(ecs)},
        "overlap": {
            "shared_columns": plan.n_shared_cols,
            "shared_rows": plan.n_shared_rows,
        },
        "files": [
            {"name": out1.name, **rep1},
            {"name": out2.name, **rep2},
        ],
    }
    write_manifest(args.output_dir / "stress_rpkm_manifest.json", manifest)
    print(f"Wrote {out1} and {out2}")
    print(f"Manifest: {args.output_dir / 'stress_rpkm_manifest.json'}")


if __name__ == "__main__":
    main()
