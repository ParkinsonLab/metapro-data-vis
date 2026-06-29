# RPKM Transform Pipeline

dbt + DuckDB pipeline that ingests a wide RPKM/FPKM TSV and produces
`mart_pathway_taxonomy_long` — a configurable pathway × taxonomy long table.

## Quick start

### 1. Prerequisites

```bash
# Install dependencies (Python 3.14 required)
cd analytics && uv sync

# Export raw reference Parquet (once, from taxonomy.db)
uv run python exploration/scripts/export_parquet.py
```

### 2. Build reference bridges (distribution step — run once per DB refresh)

```bash
cd analytics
uv run python transform/scripts/build_reference.py
```

Outputs `transform/reference/parquet/bridge_ec_pathway.parquet` and
`transform/reference/parquet/bridge_tax_rollup.parquet`. These are not committed;
run this step after cloning or whenever raw reference Parquet is refreshed.

### 3. Run the pipeline on a sample

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id my_sample \
  --rpkm-path /path/to/my_sample.tsv \
  --tax-rank phylum \
  --pathway-level pathway \
  --export-mart
```

Output in `transform/runs/my_sample/`:
- `sample.duckdb` — all materialised tables
- `run_context.json` — vars, overall status, info metrics
- `mart_pathway_taxonomy_long.parquet` — mart export (with `--export-mart`)

### 4. Change tax_rank or pathway_level (fast re-run)

Intermediates are pre-computed for all parameter combinations. Only the mart's
WHERE filter changes — rebuild takes seconds:

```bash
DBT_DUCKDB_PATH=transform/runs/my_sample/sample.duckdb \
  uv run dbt build --project-dir transform --profiles-dir transform \
  --select mart_pathway_taxonomy_long \
  --vars '{"sample_id": "my_sample", "tax_rank": "class", "pathway_level": "superpathway", "reference_parquet_dir": "transform/reference/parquet"}'
```

## Rebuild triggers

| Model | Rebuilt when |
|---|---|
| `bridge_*` (Parquet) | `build_reference.py` re-run after raw Parquet refresh |
| `stg_rpkm_long` | New/changed RPKM file |
| `int_rpkm_by_ec_tax` | `stg_rpkm_long` rebuilds |
| `int_rpkm_pathway` | `int_rpkm_by_ec_tax` rebuilds (all 3 levels pre-computed) |
| `int_tax_rollup_resolved` | `int_rpkm_pathway` rebuilds (all 7 ranks pre-joined) |
| `mart_pathway_taxonomy_long` | Upstream rebuild **or** `tax_rank`/`pathway_level` change |

## Design spec

`docs/superpowers/specs/2026-06-15-rpkm-transform-design.md`

## Chord API (FastAPI sidecar)

Requires `runs/{sample_id}/sample.duckdb` with `int_tax_rollup_resolved`.

Run the chord API in a third terminal alongside `npm run dev` (Express + Vite):

```bash
# Terminal A — chord FastAPI sidecar (or: npm run dev:chord-api)
cd analytics && uv run uvicorn api.main:app --port 8001

# Terminal B — Express proxy
curl -X POST 'http://localhost:3001/api/viz/chord?backend=duckdb' ...
```
