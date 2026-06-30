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

## Analytics API (FastAPI sidecar)

Requires `runs/{sample_id}/sample.duckdb` with `int_tax_rollup_resolved`.

Express proxies migrated viz routes to the FastAPI sidecar when the request
includes `?backend=duckdb`. Set `ANALYTICS_API_URL` (default
`http://localhost:8001`) to point Express at the sidecar.

Run the analytics API in a third terminal alongside `npm run dev` (Express + Vite):

```bash
# Terminal A — FastAPI sidecar (or: npm run dev:chord-api)
cd analytics && uv run uvicorn api.main:app --port 8001

# Terminal B — Express + Vite
npm run dev
```

Endpoints served by the sidecar:

- `POST /api/viz/chord` — chord matrix from DuckDB intermediates
- `POST /api/viz/overview` — overview pie-chart vectors from DuckDB intermediates

Via Express proxy (`?backend=duckdb`):

```bash
curl -X POST 'http://localhost:3001/api/viz/chord?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{"names": ["fake_rpkm.tsv"], "tax_level": "phylum", "ann_level": "superpathway"}'

curl -X POST 'http://localhost:3001/api/viz/overview?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{"names": ["fake_rpkm.tsv"]}'
```

**Renderer backend toggle:** the UI defaults to the sidecar for migrated channels
(`chord`, `overview`). In the browser console:

```js
localStorage.setItem('vizBackend', 'legacy')    // opt out to Node handlers
localStorage.removeItem('vizBackend')           // reset to sidecar default
```
