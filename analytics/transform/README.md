# RPKM Transform Pipeline

dbt + DuckDB pipeline that ingests a wide RPKM/FPKM TSV and produces
`mart_rpkm_enriched` — an EC × taxonomy fact table with denormalized pathway
and lineage dimensions for the viz API.

## Model graph

```
stg_rpkm_long
  → int_rpkm_by_ec_tax
    → dim_sample_taxon   (join bridge_tax_lineage for sample tax_ids)
    → dim_sample_ec      (join bridge_ec_pathway for sample ECs)
      → mart_rpkm_enriched
```

Reference bridges (`bridge_ec_pathway`, `bridge_tax_lineage`) are built once
from taxonomy Parquet and joined at materialization. Tax rank and pathway level
are applied at query time via `aggregate_pathway_tax()` — not pre-fanned into
intermediate tables.

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
`transform/reference/parquet/bridge_tax_lineage.parquet`. These are not
committed; run this step after cloning or whenever raw reference Parquet is
refreshed.

### 3. Run the pipeline on a sample

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id my_sample \
  --rpkm-path /path/to/my_sample.tsv \
  --tax-rank phylum \
  --pathway-level pathway
```

Output in `transform/runs/my_sample/`:
- `sample.duckdb` — all materialised tables (including `mart_rpkm_enriched`)
- `run_context.json` — vars, overall status, info metrics

Each run **replaces** `sample.duckdb` from scratch (any prior tables from retired
models are removed). Do not rely on incremental merges inside the DuckDB file.

## Rebuild triggers

| Model | Rebuilt when |
|---|---|
| `bridge_*` (Parquet) | `build_reference.py` re-run after raw Parquet refresh |
| `stg_rpkm_long` | New/changed RPKM file |
| `int_rpkm_by_ec_tax` | `stg_rpkm_long` rebuilds |
| `dim_sample_taxon` | `int_rpkm_by_ec_tax` rebuilds |
| `dim_sample_ec` | `int_rpkm_by_ec_tax` rebuilds |
| `mart_rpkm_enriched` | Any upstream model rebuilds |

## Design spec

`docs/superpowers/specs/2026-07-08-api-aligned-dbt-model-design.md`

## Analytics API (FastAPI sidecar)

Requires `runs/{sample_id}/sample.duckdb` with `mart_rpkm_enriched`. All six viz
endpoints query `sample.duckdb` only (no reference Parquet reads except network
layout).

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

- `POST /api/viz/chord` — chord matrix
- `POST /api/viz/overview` — overview pie-chart vectors
- `POST /api/viz/pathway-list` — pathway list for drill-down
- `POST /api/viz/krona` — Krona hierarchy
- `POST /api/viz/graph` — graph adjacency matrix
- `POST /api/viz/network` — network layout (reads static pathway layout Parquet)

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
(`chord`, `overview`, `pathway-list`, `krona`, `graph`, `network`). In the
browser console:

```js
localStorage.setItem('vizBackend', 'legacy')    // opt out to Node handlers
localStorage.removeItem('vizBackend')           // reset to sidecar default
```
