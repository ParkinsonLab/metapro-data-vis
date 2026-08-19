# Legacy Express + upload development

The original Metapro Viz stack: Express backend, browser file upload, and direct queries against `taxonomy.db`. Kept for **comparison and migration** while the product path ([FastAPI + dbt](../README.md#development)) ships.

This stack does **not** match mounted-data processing, dbt, or `sample.duckdb` artifacts.

## Prerequisites

Same as the main [Contributing prerequisites](../README.md#contributing-prerequisites), plus:

- `resources/db/taxonomy.db` — **required**; not in git (see below)

## Build `taxonomy.db`

Express reads SQLite directly. There is no script to rebuild it from committed Parquet.

- Notebooks and scripts: `resources/scripts/`
- Exploration workflow: [analytics/exploration/README.md](../analytics/exploration/README.md)

## Start the app

**Together** (recommended):

```bash
npm run dev:legacy    # Express + Vite, Upload tab
```

**Separate processes** (do not run together with `npm run dev:legacy`):

```bash
npm run dev:api       # Express only
npm run dev:web       # Vite only; default upload mode unless VITE_DATA_MODE=upload
```

Set `VITE_DATA_MODE=upload` when starting `dev:web` to default to the **Upload** tab. The in-app toggle persists the choice in `localStorage`.

Open [http://localhost:5173](http://localhost:5173).

## Tests and production build

```bash
npm test                        # vitest (Node handlers)
npm run build && npm start      # legacy Express production build on :8080
```

## Reference data used

| Layer | Location | Used by Express |
| --- | --- | --- |
| `taxonomy.db` | `resources/db/` | Taxonomy and pathway layout queries |
| Raw Parquet | `resources/db/parquet/` | Not used |
| Bridge Parquet | `analytics/transform/reference/parquet/` | Not used |

Updating reference tables for the product path is documented in [Refreshing reference data](../README.md#refreshing-reference-data).
