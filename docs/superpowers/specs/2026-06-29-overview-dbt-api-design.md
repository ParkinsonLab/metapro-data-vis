# Overview API via dbt Intermediates — Design Spec

> **Status:** Approved (2026-06-29; revised 2026-06-30 — exclude unmapped EC from overview vectors)  
> **Goal:** Reimplement `POST /api/viz/overview` to derive overview pie-chart vectors from precomputed dbt intermediate tables (`int_tax_rollup_resolved`) in `runs/{sample_id}/sample.duckdb`, preserving the existing JSON contract. Express keeps legacy handlers when `?backend=duckdb` is absent; the renderer defaults migrated channels to the FastAPI sidecar.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, `int_tax_rollup_resolved`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — sidecar proxy pattern, envelope, sample lookup
- `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` — shared `fake_rpkm` fixture and YAML golden pattern

## 1. Context

Metapro Viz renders two small overview pies (Expression by phylum, Metabolism by superpathway). Today the Express handler `parse_overview` (`src/server/data_functions.ts`) loads wide TSV data in memory and builds `{ counts_data, ann_data }` via `make_count_vector` / `make_ann_vector` (`src/server/parse.ts`) at fixed levels: **phylum** and **superpathway**.

The rpkm-transform pipeline already materialises `int_tax_rollup_resolved` with all 7 taxonomy ranks and 3 pathway levels pre-joined. Overview needs two simple `GROUP BY` aggregations on pinned slices of that table — no runtime rank/level parameters.

**Assumption (in scope):** `int_tax_rollup_resolved` is already materialised in `runs/{sample_id}/sample.duckdb` before the overview endpoint is invoked (same as chord).

**Out of scope (this spec):**

- Upload endpoint that ingests RPKM and triggers `dbt build --select stg_rpkm_long+`
- Comparison mode (`names.length > 1`) on the DuckDB backend
- Retiring the legacy Node implementation
- Shared TypeScript response types in the renderer (optional follow-up)
- Pipeline fix for unknown-header tax_ids (deferred; see §6.2)

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| API contract | Unchanged request body + `{ ok, value }` envelope | No breaking frontend changes |
| FastAPI route | **`POST /api/viz/overview`** — identical path, method, envelope, HTTP 200 as Express | Drop-in replacement when Express is retired |
| Default backend | Legacy Node `parse_overview` | Safe rollout |
| Opt-in backend | `POST /api/viz/overview?backend=duckdb` (Express) or direct on FastAPI `:8001` | Explicit testing switch; mirrors chord |
| Sidecar env var | **`ANALYTICS_API_URL`** (default `http://localhost:8001`); chord handler updated in same PR | One FastAPI process serves all viz routes |
| Migration proxy | Shared `src/server/fastapi_sidecar_proxy.ts` | Temporary Express→FastAPI bridge during viz migration; delete when Express viz routes are retired |
| Data source | Query `int_tax_rollup_resolved` at request time | Consistent with chord; no new dbt mart |
| Pinned dimensions | `requested_rank = 'phylum'`, `pathway_level = 'superpathway'` for both vectors | Avoids 7×3 double-counting; totals invariant across rank at fixed pathway level |
| `counts_data` ordering | Alphabetical by **ancestor name chain** (kingdom → phylum) | Phyla colocated under their kingdom; not flat phylum alphabetical |
| `ann_data` ordering | Alphabetical by superpathway label ASC | Deliberate simplification (legacy uses SQLite EC insertion order) |
| Unmapped EC | **Excluded** — `pathway_key IS NOT NULL` on both vectors | Overview pies show mapped metabolism only; unmapped mass omitted from phylum totals too |
| Comparison mode | Error on duckdb path when `names.length > 1` | Deferred follow-up (same as chord v1) |
| Verification | Golden tests: `overview_expectations.yaml` + parametrized pytest on `fake_rpkm` | Mirrors chord golden pattern |
| Response typing | Pydantic `OverviewResponse` model in Python | Documents contract; used in service return type and tests |
| Renderer backend toggle | **Global** `localStorage` key; **migrated channels only**; **sidecar default**; no dev UI in v1 | FastAPI path unless explicitly opted out; no Vite restart |

## 3. Architecture

```
┌─────────────┐     POST /api/viz/overview         ┌──────────────┐
│   React     │ ────────────────────────────────► │   Express    │
│  (unchanged)│     (no query param = legacy)      │   :3001      │
└─────────────┘                                    └──────┬───────┘
                                                          │
                        ?backend=duckdb                   │
                        ───────────────────────────────►│ proxy ──────┐
                                                          │  (same path) │
                                                          ▼             ▼
                                                 legacy in-process   ┌──────────────────────────┐
                                                                     │   FastAPI  :8001         │
                                                                     │   POST /api/viz/overview │
                                                                     └──────────────┬───────────┘
                                                                                    │
                                                                                    ▼
                                                                         runs/{sample_id}/sample.duckdb
                                                                         int_tax_rollup_resolved
```

| Component | Location | Role |
|---|---|---|
| Migration proxy | `src/server/fastapi_sidecar_proxy.ts` | `createSidecarProxyHandler({ legacyHandler, apiPath, label })` — forwards `?backend=duckdb` to FastAPI; temporary until Express retirement |
| Express routes | `src/server/index.ts` | Overview uses sidecar proxy; chord refactored to same helper |
| Env var | `ANALYTICS_API_URL` | Default `http://localhost:8001`; replaces `CHORD_API_URL` |
| FastAPI route | `analytics/api/main.py` | `POST /api/viz/overview` |
| Service | `analytics/api/overview_service.py` | DuckDB queries + vector assembly |
| Schemas | `analytics/api/schemas.py` | `OverviewRequest`, `OverviewVector`, `OverviewResponse` |
| Renderer toggle | `src/renderer/src/vizBackend.ts` + `api.ts` | Reads global `localStorage` at request time; appends `?backend=duckdb` for migrated channels only |

**Route parity (required):** FastAPI exposes `POST /api/viz/overview` (not a shortened internal path) so future cutover is a host/port change only.

### 3.1 Express sidecar proxy behaviour

**Naming:** `fastapi_sidecar_proxy.ts` (not `duckdb_proxy`) — the proxy targets the **FastAPI analytics server**, not DuckDB directly. DuckDB is an implementation detail inside Python. This module is a **temporary migration bridge**; delete it when Express viz routes are retired and the UI talks to FastAPI directly.

When `?backend=duckdb` is present:

1. Forward method, path (`/api/viz/overview`), query string, and JSON body unchanged to FastAPI.
2. Return FastAPI's JSON envelope to the client unchanged.
3. On connection failure, return `{ ok: false, error: "overview duckdb backend unavailable: ..." }` with HTTP 200.

### 3.2 Renderer backend toggle (v1)

During migration, developers switch between legacy Node handlers and the FastAPI sidecar **at runtime** — no Vite restart and no source edits.

| Decision | Choice |
|---|---|
| Scope | **Global** — one setting for all migrated viz channels |
| Channels affected | **Migrated endpoints only** (`chord`, `overview` initially; extend set as routes migrate) |
| Unaffected | `handshake`, `load`, `load_test`, `counts`, `krona`, `network`, `pathway_list` — always legacy Express |
| Storage | `localStorage` key `vizBackend`: `'sidecar'` (default) or `'legacy'` |
| Dev UI | **Deferred** — console/localStorage only in v1 |

**Module:** `src/renderer/src/vizBackend.ts`

```typescript
const STORAGE_KEY = 'vizBackend'
const MIGRATED_CHANNELS = new Set<Channel>(['chord', 'overview'])

export type VizBackend = 'legacy' | 'sidecar'

export function getVizBackend(): VizBackend {
  return localStorage.getItem(STORAGE_KEY) === 'legacy' ? 'legacy' : 'sidecar'
}

export function sidecarQuery(channel: Channel): string {
  return MIGRATED_CHANNELS.has(channel) && getVizBackend() === 'sidecar'
    ? '?backend=duckdb'
    : ''
}
```

**`api.ts`:** remove hardcoded `CHORD_BACKEND_QUERY`; use `sidecarQuery(channel)` in `endpointFor()`.

**Console usage (no page reload required for next fetch):**

```javascript
localStorage.setItem('vizBackend', 'legacy')    // opt out to Node handlers for chord + overview
localStorage.removeItem('vizBackend')           // reset to sidecar default
```

Re-fetch by navigating tabs or changing filters — e.g. revisit Overview or change chord rank. A soft page reload also works.

**Follow-up (out of scope v1):** dev-only UI control bound to the same `localStorage` key.

### 3.3 Future Express retirement (out of scope v1)

```
Today:     React → Express :3001 /api/viz/overview?backend=duckdb → FastAPI :8001 /api/viz/overview
Future:    React → FastAPI :8080 /api/viz/overview   (Express removed)
```

## 4. Request / Response Contract

### 4.1 Request (unchanged JSON body)

```json
{ "names": ["fake_rpkm.tsv"] }
```

| Field | DuckDB semantics |
|---|---|
| `names` | Single sample only; `sample_id = strip_extension(names[0])` → `runs/{sample_id}/sample.duckdb` |
| `names.length > 1` | `{ ok: false, error: "comparison mode not supported on duckdb backend" }` |
| `names` empty | `{ ok: false, error: "names must contain at least one sample" }` |

### 4.2 Response `value` (unchanged shape)

```json
{
  "counts_data": { "index": ["Actinobacteria", "Firmicutes"], "counts": [120.5, 340.2] },
  "ann_data":      { "index": ["Amino acid metabolism", "Energy metabolism"], "counts": [50.0, 200.0] }
}
```

| Block | Semantics | Index ordering |
|---|---|---|
| `counts_data` | Total RPKM per **phylum** (all ECs, all tax columns) | Alphabetical by ancestor names coarse→fine: `kingdom_label ASC`, then `phylum_label ASC` |
| `ann_data` | Total RPKM per **superpathway** (row-wise sum per EC, grouped) | Alphabetical by `pathway_label` ASC |

Frontend (`Overview.tsx`) consumes `counts_data.index`, `counts_data.counts`, `ann_data.index`, `ann_data.counts` only. Pie colors are index-position-based (`get_color(i, n)`), so `ann_data` slice order will differ from legacy when toggling backends — accepted for v1.

### 4.3 Pydantic models

```python
class OverviewVector(BaseModel):
    index: list[str]
    counts: list[float]

class OverviewResponse(BaseModel):
    counts_data: OverviewVector
    ann_data: OverviewVector

class OverviewRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
```

FastAPI endpoint does not set `response_model` on the route (envelope wraps value), but `build_overview_from_duckdb()` returns `OverviewResponse` and tests validate against it.

### 4.4 Errors (duckdb path)

| Condition | HTTP | `{ ok: false, error }` |
|---|---|---|
| `names` empty | 200 | `"names must contain at least one sample"` |
| `names.length > 1` | 200 | `"comparison mode not supported on duckdb backend"` |
| DuckDB file missing | 200 | `"sample not found: {sample_id}"` |
| `int_tax_rollup_resolved` missing | 200 | `"int_tax_rollup_resolved not materialized for sample: {sample_id}"` |
| FastAPI unreachable (Express proxy) | 200 | `"overview duckdb backend unavailable: ..."` |

## 5. Data Flow

### 5.1 Pipeline

```
int_tax_rollup_resolved
  → counts: WHERE requested_rank='phylum' AND pathway_level='superpathway' AND pathway_key IS NOT NULL
            GROUP BY resolved_tax_label (int_tax_rollup_resolved)
            ORDER BY kingdom/phylum labels from bridge_tax_rollup Parquet only
  → ann:    WHERE requested_rank='phylum' AND pathway_level='superpathway' AND pathway_key IS NOT NULL
            GROUP BY pathway_label → ORDER BY pathway_label ASC
  → OverviewResponse
```

Both vectors pin the same `(requested_rank, pathway_level)` pair. Totals are invariant across `requested_rank` at a fixed `pathway_level` because each `(ec_normalized, source_tax_id)` carries the same `value` at every rank.

### 5.2 SQL details

**Unmapped EC filter (both vectors):** Rows with `pathway_key IS NULL` (ECs absent from `bridge_ec_pathway`) are **excluded**. Overview does not surface an `'Unmapped EC'` slice or include that mass in phylum expression totals.

**ann_data:** Aggregate at `pathway_level = 'superpathway'` using `pathway_label` directly (always non-null when `pathway_key IS NOT NULL`).

**counts_data:**

Aggregate phylum totals from sample data; resolve kingdom sort keys from **reference bridge only** (no sample values in the hierarchy lookup):

```sql
WITH phylum_totals AS (
    SELECT resolved_tax_label AS phylum_label, SUM(value) AS total
    FROM int_tax_rollup_resolved
    WHERE requested_rank = 'phylum'
      AND pathway_level = 'superpathway'
      AND pathway_key IS NOT NULL
    GROUP BY resolved_tax_label
),
phylum_map AS (
    SELECT DISTINCT source_tax_id, resolved_tax_label AS phylum_label
    FROM read_parquet('<bridge_tax_rollup>')
    WHERE requested_rank = 'phylum'
),
kingdom_map AS (
    SELECT source_tax_id, resolved_tax_label AS kingdom_label
    FROM read_parquet('<bridge_tax_rollup>')
    WHERE requested_rank = 'kingdom'
),
phylum_to_kingdom AS (
    SELECT p.phylum_label, MIN(k.kingdom_label) AS kingdom_label
    FROM phylum_map p
    JOIN kingdom_map k USING (source_tax_id)
    GROUP BY p.phylum_label
)
SELECT p.phylum_label, p.total
FROM phylum_totals p
LEFT JOIN phylum_to_kingdom k ON k.phylum_label = p.phylum_label
ORDER BY COALESCE(k.kingdom_label, ''), p.phylum_label ASC
```

`phylum_to_kingdom` is reference-sized (taxonomy only); `phylum_totals` is the only query that touches sample mass.

`'Unclassified'` phylum labels sort under `COALESCE(kingdom_label, '')` then their phylum label.

**ann_data:**

```sql
SELECT pathway_label AS label, SUM(value) AS total
FROM int_tax_rollup_resolved
WHERE requested_rank = 'phylum'
  AND pathway_level = 'superpathway'
  AND pathway_key IS NOT NULL
GROUP BY pathway_label
ORDER BY label ASC
```

**Assembly:**

```python
def _build_vector(rows: list[tuple[str, float]]) -> OverviewVector:
    return OverviewVector(
        index=[r[0] for r in rows],
        counts=[float(r[1]) for r in rows],
    )
```

### 5.3 Sample lookup

`sample_id = sample_id_from_names(body.names)` — reuses `api/filters.py` helper (strip `.tsv` extension).

## 6. Documented Deviations from Legacy

| Area | Legacy (Node) | DuckDB path |
|---|---|---|
| Tax rollup | `get_parents_at_level` — exact rank only | `bridge_tax_rollup` — exact → coarser fallback → `'Unclassified'` |
| Unmapped ECs | Included via `0.0.0.0` / SQLite pathway map (may appear in totals) | **Excluded** — `pathway_key IS NOT NULL` filter on both vectors |
| Comparison mode | `get_delta` for two files | Not supported (v1) |
| `counts_data` index order | Flat alphabetical on phylum label (`_.sortBy`) | Hierarchical: kingdom name, then phylum name |
| `ann_data` index order | First-encounter order from SQLite `pathway_nodes` scan | Alphabetical by superpathway label ASC |
| Unknown-header tax_ids | Column included in wide-matrix sums | Mass excluded from `WHERE requested_rank = 'phylum'` (NULL bridge join) |
| TSV `Unclassified` column | Included as KEY_COL in wide matrix | Excluded from pipeline unpivot (unchanged) |

### 6.1 `'Unclassified'` label semantics

Three distinct concepts:

1. **TSV `Unclassified` column** — fixed metadata column (`KEY_COLS`), not a taxon label; excluded from unpivot.
2. **Bridge `'Unclassified'`** — `source_tax_id` is in `bridge_tax_rollup` but has no ancestor at the requested rank (`resolved_tax_id IS NULL`, `resolved_tax_label = 'Unclassified'`). Rare when reference ancestors are complete.
3. **Unknown header tax_id** — column header absent from `bridge_tax_rollup` (e.g. `999999999` in `fake_rpkm.tsv`). Produces NULL bridge columns, not `'Unclassified'`; excluded from rank-filtered queries. Deferred pipeline fix per `2026-06-22-chord-golden-tests-design.md` §12.

## 7. Repository Layout (additions)

```
analytics/
├── api/
│   ├── main.py                     # add POST /api/viz/overview
│   ├── overview_service.py         # build_overview_from_duckdb()
│   ├── schemas.py                  # add OverviewRequest/Vector/Response
│   └── tests/
│       ├── fixtures/
│       │   └── overview_expectations.yaml
│       └── test_overview_service.py
└── testing/
    └── dump_fake_rpkm_expectations.py   # extend to dump overview goldens

src/server/
├── fastapi_sidecar_proxy.ts        # temporary Express→FastAPI migration proxy (chord + overview)
├── chord_handler.ts                # thin wrapper or removed in favour of sidecar proxy
└── index.ts                        # wire overview sidecar route

src/renderer/src/
├── vizBackend.ts                   # localStorage global toggle; migrated channel set
└── api.ts                          # sidecarQuery(channel) in endpointFor()
```

## 8. Testing

### 8.1 Golden tests

Reuse shared `fake_rpkm` fixture (`analytics/conftest.py`, `testing/fake_rpkm_fixture.py`):

| Asset | Purpose |
|---|---|
| `overview_expectations.yaml` | Expected `counts_data` and `ann_data` vectors for `fake_rpkm` sample |
| `test_overview_service.py` | Parametrized pytest via `build_overview_from_duckdb()` |
| `dump_fake_rpkm_expectations.py` | Regenerate YAML after fixture or SQL changes |

Tests skip when bridges/sample.duckdb unavailable (same guard as chord).

### 8.2 Express sidecar proxy tests

Extend `src/tests/chord_handler.test.ts` or add `fastapi_sidecar_proxy.test.ts`:

- Default (no query param) → legacy handler
- `?backend=duckdb` → fetch to `ANALYTICS_API_URL` + route path
- Fetch failure → error envelope with route-specific prefix (`chord` / `overview`)

### 8.3 Node integration test

Existing `API /api/viz/overview` test in `src/tests/server.test.ts` continues to exercise legacy path (no query param).

## 9. Development Workflow

### 9.1 Prerequisites

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id fake_rpkm \
  --rpkm-path transform/tests/fixtures/fake_rpkm.tsv \
  --tax-rank phylum \
  --pathway-level superpathway
```

### 9.2 Running locally

```bash
# Terminal 1 — FastAPI sidecar
cd analytics && uv run uvicorn api.main:app --port 8001

# Terminal 2 — Express + Vite
npm run dev

# Browser console — opt out to legacy Node (migrated channels: chord, overview)
localStorage.setItem('vizBackend', 'legacy')

# Via Express proxy (duckdb backend) — curl equivalent
curl -X POST 'http://localhost:3001/api/viz/overview?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{"names": ["fake_rpkm.tsv"]}'
```

## 10. Implementation Checklist

- [ ] `analytics/api/overview_service.py` — `build_overview_from_duckdb()`
- [ ] `analytics/api/schemas.py` — `OverviewRequest`, `OverviewVector`, `OverviewResponse`
- [ ] `analytics/api/main.py` — `POST /api/viz/overview`
- [ ] `overview_expectations.yaml` + `test_overview_service.py`
- [ ] `src/server/fastapi_sidecar_proxy.ts` — temporary migration proxy; refactor chord to use it
- [ ] `src/server/index.ts` — overview route with proxy
- [ ] `ANALYTICS_API_URL` env var (update chord, docs, README)
- [ ] `src/renderer/src/vizBackend.ts` — global `localStorage` toggle; migrated channel set
- [ ] `src/renderer/src/api.ts` — remove `CHORD_BACKEND_QUERY`; use `sidecarQuery(channel)`
- [ ] Proxy unit tests
