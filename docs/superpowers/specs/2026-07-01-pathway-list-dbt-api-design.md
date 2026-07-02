# Pathway List API via dbt Intermediates — Design Spec

> **Status:** Draft (2026-07-01)  
> **Goal:** Reimplement `POST /api/viz/pathway-list` to return pathway names that contribute to the chord count matrix under the selected superpathway, derived from `int_tax_rollup_resolved` in `runs/{sample_id}/sample.duckdb` with the same tax/pathway filters as chord. Express keeps the legacy handler when `?backend=duckdb` is absent; the renderer defaults migrated channels to the FastAPI sidecar.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, `int_tax_rollup_resolved`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — sidecar proxy pattern, envelope, filter normalisation, `chord_prefix_rows`
- `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` — shared `fake_rpkm` fixture and YAML golden pattern
- `docs/superpowers/specs/2026-06-29-overview-dbt-api-design.md` — migration wiring, renderer toggle, golden-test pattern
- `docs/superpowers/specs/2026-06-30-krona-dbt-api-design.md` — sidecar route pattern, error wording

## 1. Context

Metapro Viz renders a clickable pathway grid in the Network pane (`Network.tsx` → `PathwayList`) after the user selects a superpathway in the Chord view. Today the Express handler `parse_pathway_list` (`src/server/data_functions.ts`) calls `get_pathways_in_superpathway` (`src/server/db_functions.ts`), which queries the **bundled SQLite reference DB** for every pathway in the superpathway — regardless of whether the loaded sample has RPKM mapped to those pathways.

**Intended behaviour (locked in):** The pathway grid should list only pathways that **contribute to the chord count matrix** under the currently selected superpathway, using the same sample and filter context as chord (`names`, `tax_level`, `selected_taxon`). This is a deliberate correction over legacy reference-only listing.

The rpkm-transform pipeline already materialises `int_tax_rollup_resolved` with all taxonomy ranks and pathway levels pre-joined — the same table chord queries. Pathway-list is a lighter derivative query: build the same filtered row set chord uses, then return distinct pathway labels at `pathway_level = 'pathway'`.

**Assumption (in scope):** `int_tax_rollup_resolved` is already materialised in `runs/{sample_id}/sample.duckdb` before the pathway-list endpoint is invoked (same as chord/overview).

**Out of scope (this spec):**

- Upload endpoint that ingests RPKM and triggers `dbt build --select stg_rpkm_long+`
- Comparison mode (`names.length > 1`) on the analytics API path
- Updating the legacy Node handler to implement sample-filtered behaviour (documented deviation during migration)
- Retiring the legacy Node implementation
- Shared TypeScript request/response types in the renderer (optional follow-up)

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| API contract | Extended request body; unchanged response type `string[]` + `{ ok, value }` envelope | Sample-aware listing requires chord filter fields |
| FastAPI route | **`POST /api/viz/pathway-list`** — identical path, method, envelope, HTTP 200 as Express | Drop-in replacement when Express is retired |
| Default backend | Legacy Node `parse_pathway_list` | Safe rollout |
| Opt-in backend | `POST /api/viz/pathway-list?backend=duckdb` (Express) or direct on FastAPI `:8001` | Explicit testing switch; mirrors chord/overview/krona |
| Sidecar env var | **`ANALYTICS_API_URL`** (default `http://localhost:8001`) | One FastAPI process serves all viz routes |
| Migration proxy | Shared `src/server/fastapi_sidecar_proxy.ts` | Temporary Express→FastAPI bridge during viz migration |
| Data source | `int_tax_rollup_resolved` + `bridge_ec_pathway` Parquet | Same grain and filters as chord — not `int_rpkm_pathway` or reference `pathway_superpathways` |
| Filter parity | Full chord filter stack: `names`, `tax_level`, `selected_taxon`, plus `superpathway` | Pathway grid reflects filtered chord state |
| Fixed ann level | Server pins `ann_level = 'pathway'` | Pathways are always listed at pathway grain under the parent superpathway |
| Ann filter | `{ level: 'superpathway', name: superpathway }` derived from request | Restricts to pathways under the selected superpathway |
| Inclusion rule | Pathway label included iff `SUM(value) > 0` after chord-equivalent filters | Matches chord matrix ann-axis contributors |
| Label SQL | Reuse chord `PATHWAY_LABEL_SQL` | Display strings match chord `index` labels |
| Ordering | Reuse chord `_fetch_ann_order` at `ann_level = 'pathway'` | Grid order matches chord ann-axis order |
| Payload compatibility | Frontend sends **extended** payload always; legacy **ignores** extra fields | One renderer code path for both backends (see §4.3) |
| Comparison mode | Error when `names.length > 1` | Deferred follow-up (same as chord v1) |
| Error wording | Feature gaps say **"analytics API"**, not "duckdb backend" | Avoid implying DuckDB limitation |
| Verification | Golden tests: `pathway_list_expectations.yaml` + parametrized pytest on `fake_rpkm` | Cross-check against chord ann-axis labels for same filters |
| Renderer backend toggle | Add `'pathway_list'` to `MIGRATED_CHANNELS` in `vizBackend.ts` | Sidecar default for pathway-list |

## 3. Architecture

```
┌─────────────┐     POST /api/viz/pathway-list     ┌──────────────┐
│   React     │ ─────────────────────────────────► │   Express    │
│  (extended  │     (no query param = legacy)     │   :3001      │
│   payload)  │                                    └──────┬───────┘
└─────────────┘                                           │
                       ?backend=duckdb                    │
                       ──────────────────────────────────►│ proxy ──────┐
                                                          │  (same path) │
                                                          ▼             ▼
                                                 legacy in-process   ┌──────────────────────────────┐
                                                                   │   FastAPI  :8001             │
                                                                   │   POST /api/viz/pathway-list │
                                                                   └──────────────┬───────────────┘
                                                                                  │
                                                                                  ▼
                                                                       runs/{sample_id}/sample.duckdb
                                                                       int_tax_rollup_resolved
                                                                       + bridge_ec_pathway (Parquet)
```

| Component | Location | Role |
|---|---|---|
| Migration proxy | `src/server/fastapi_sidecar_proxy.ts` | `createSidecarProxyHandler({ legacyHandler, apiPath, label: 'pathway_list' })` |
| Express routes | `src/server/index.ts` | Move pathway-list from `vizRoutes` → `sidecarRoutes` |
| FastAPI route | `analytics/api/main.py` | `POST /api/viz/pathway-list` |
| Shared prefix builder | `analytics/api/chord_prefix.py` (extracted) | Build `chord_prefix_rows` temp table — shared by chord and pathway-list |
| Service | `analytics/api/pathway_list_service.py` | Distinct pathway labels + ordering |
| Schemas | `analytics/api/schemas.py` | `PathwayListRequest` |
| Renderer request | `src/renderer/src/components/Network.tsx` | Send extended payload with chord-aligned deps |
| Renderer toggle | `src/renderer/src/vizBackend.ts` | Add `'pathway_list'` to `MIGRATED_CHANNELS` |

**Route parity (required):** FastAPI exposes `POST /api/viz/pathway-list` (not a shortened internal path) so future cutover is a host/port change only.

### 3.1 Express sidecar proxy behaviour

When `?backend=duckdb` is present:

1. Forward method, path (`/api/viz/pathway-list`), query string, and JSON body unchanged to FastAPI.
2. Return FastAPI's JSON envelope to the client unchanged.
3. On connection failure, return `{ ok: false, error: "pathway_list analytics API unavailable: ..." }` with HTTP 200.

### 3.2 Renderer backend toggle

Add `'pathway_list'` to `MIGRATED_CHANNELS` in `vizBackend.ts` (alongside `'chord'`, `'overview'`, `'krona'`). Update `api.ts` to append `sidecarQuery('pathway_list')`.

## 4. Request / Response Contract

### 4.1 Request (extended JSON body)

```json
{
  "names": ["fake_rpkm.tsv"],
  "tax_level": "phylum",
  "selected_taxon": {},
  "superpathway": "Carbohydrate metabolism"
}
```

| Field | Analytics API semantics |
|---|---|
| `names` | Single sample only; `sample_id = strip_extension(names[0])` → `runs/{sample_id}/sample.duckdb` |
| `names.length > 1` | `{ ok: false, error: "comparison mode not supported on analytics API" }` |
| `names` empty | `{ ok: false, error: "names must contain at least one sample" }` |
| `tax_level` | One of 7 ranks; validated via `validate_tax_level()` — same as chord |
| `selected_taxon` | Normalised via `normalise_taxon_filter()` — same as chord; empty `{}` = no filter |
| `superpathway` | Required non-empty string; parent superpathway name from `selected_ann_cat` in Network |

**Server-derived (not in request):**

| Field | Value |
|---|---|
| `ann_level` | Always `'pathway'` |
| `ann_filter` | `{ level: 'superpathway', name: superpathway }` |

### 4.2 Response `value` (unchanged type)

```json
{
  "ok": true,
  "value": ["Glycolysis / Gluconeogenesis", "Citrate cycle (TCA cycle)", "..."]
}
```

`value` is a `string[]` of pathway display labels — the same strings chord places on the ann axis when `ann_level = 'pathway'` and the superpathway filter is active.

Empty superpathway with no matching rows → `[]`.

### 4.3 Payload compatibility (legacy vs migrated)

The renderer will send the **extended** payload (§4.1) on every pathway-list request, regardless of backend.

| Direction | Compatible? | Notes |
|---|---|---|
| Extended payload → **legacy** Express handler | **Yes** | `parse_pathway_list` destructures only `{ superpathway }`; extra JSON keys (`names`, `tax_level`, `selected_taxon`) are ignored |
| Minimal payload `{ superpathway }` → **analytics API** | **No** | Analytics API requires `names` and `tax_level`; missing fields produce validation or runtime errors |
| Extended payload → **analytics API** | **Yes** | Full filter context available |
| Response shape | **Yes** | Both return `{ ok, value: string[] }` |
| Response **contents** | **No** (intentional) | Legacy returns all reference ontology pathways; analytics API returns sample-filtered chord contributors only |

**Rollout rule:** The renderer always sends the extended payload. Legacy ignores the new fields and continues returning the reference list until retired. Users on the sidecar path get the corrected sample-filtered list. No dual code paths in the renderer for payload shape.

### 4.4 Pydantic model

```python
class PathwayListRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_level: str
    selected_taxon: Any = Field(default_factory=dict)
    superpathway: str
```

FastAPI endpoint does not set `response_model` on the route (envelope wraps value), but `build_pathway_list_from_duckdb()` returns `list[str]` and tests validate against it.

### 4.5 Errors (analytics API path)

| Condition | HTTP | `{ ok: false, error }` |
|---|---|---|
| `names` empty | 200 | `"names must contain at least one sample"` |
| `names.length > 1` | 200 | `"comparison mode not supported on analytics API"` |
| `superpathway` empty / whitespace | 200 | `"superpathway is required"` |
| Invalid `tax_level` | 200 | `"invalid tax_level: {value}"` |
| DuckDB file missing | 200 | `"sample not found: {sample_id}"` |
| `int_tax_rollup_resolved` missing | 200 | `"int_tax_rollup_resolved not materialized for sample: {sample_id}"` |
| Bridge Parquet missing | 200 | `"reference parquet missing: ..."` |
| FastAPI unreachable (Express proxy) | 200 | `"pathway_list analytics API unavailable: ..."` |

## 5. Data Flow

### 5.1 Pipeline

```
int_tax_rollup_resolved
  → build_chord_prefix_rows (shared with chord)
      tax_level, ann_level='pathway',
      ann_filter={level:'superpathway', name:superpathway},
      taxon_filter=normalise(selected_taxon)
  → SELECT DISTINCT pathway_label
      WHERE pathway_level = 'pathway'
        AND requested_rank = tax_level
      GROUP BY pathway_key, pathway_label
      HAVING SUM(value) > 0
  → ORDER BY chord ann_order
  → string[]
```

### 5.2 Shared chord prefix builder (extracted)

Extract from `chord_service.py` into `analytics/api/chord_prefix.py`:

```python
def build_chord_prefix_rows(
    conn: duckdb.DuckDBPyConnection,
    *,
    tax_level: str,
    ann_level: str,
    ann_filter: dict[str, str] | None,
    taxon_filter: dict[str, str] | None,
) -> None:
    """CREATE TEMP TABLE chord_prefix_rows — same SQL as chord_service today."""
```

`chord_service.build_chord_from_duckdb()` and `pathway_list_service.build_pathway_list_from_duckdb()` both call this helper. Filter predicates (`_ann_predicate`, tax subquery, `PATHWAY_LABEL_SQL`) remain in one module to prevent drift.

### 5.3 Pathway-list SQL

After `build_chord_prefix_rows`:

```sql
SELECT DISTINCT
    <PATHWAY_LABEL_SQL> AS display_label
FROM chord_prefix_rows cf
WHERE cf.requested_rank = ?
  AND cf.pathway_level = 'pathway'
GROUP BY cf.pathway_key, <PATHWAY_LABEL_SQL>
HAVING SUM(cf.value) > 0
```

Ordering: call existing `_fetch_ann_order(conn, tax_level, 'pathway')` on the populated `chord_prefix_rows`, then filter/order the distinct labels to match that list. Labels not in ann_order (should not occur if SQL is consistent) append at end in alphabetical order.

### 5.4 Sample lookup

`sample_id = sample_id_from_names(body.names)` — reuses `api/filters.py` helper (strip `.tsv` extension).

### 5.5 Why not other tables?

| Table | Rejected because |
|---|---|
| `pathway_superpathways` + `superpathways` (SQLite / raw Parquet) | Reference-only; ignores sample RPKM — legacy behaviour, not intended |
| `bridge_ec_pathway` alone | No sample values; would list all mapped pathways regardless of RPKM |
| `int_rpkm_pathway` | EC grain without tax rollup ranks; tax filter would not match chord's `int_tax_rollup_resolved` path |

## 6. Documented Deviations from Legacy

| Area | Legacy (Node) | Analytics API path |
|---|---|---|
| Data source | SQLite `pathway_superpathways` | `int_tax_rollup_resolved` in sample DuckDB |
| Sample context | None — `{ superpathway }` only | Requires `names` (+ chord filters) |
| Pathway set | All pathways in superpathway (ontology) | Pathways with `SUM(value) > 0` under chord filters |
| Taxon filter | Ignored | Honoured — same as chord |
| Ordering | `pathway_superpathways.id` row order | Chord ann-axis order |
| Payload | `{ superpathway }` accepted | Extended payload required; legacy accepts superset |

## 7. Repository Layout (additions)

```
analytics/
├── api/
│   ├── chord_prefix.py              # extracted build_chord_prefix_rows + shared predicates
│   ├── chord_service.py             # refactored to use chord_prefix
│   ├── pathway_list_service.py      # build_pathway_list_from_duckdb()
│   ├── main.py                      # add POST /api/viz/pathway-list
│   ├── schemas.py                   # add PathwayListRequest
│   └── tests/
│       ├── fixtures/
│       │   └── pathway_list_expectations.yaml
│       └── test_pathway_list_service.py

src/server/
└── index.ts                         # move pathway-list to sidecarRoutes

src/renderer/src/
├── vizBackend.ts                    # add 'pathway_list' to MIGRATED_CHANNELS
├── api.ts                           # sidecarQuery('pathway_list')
└── components/Network.tsx           # extended request payload + deps
```

## 8. Testing

### 8.1 Golden tests

Reuse shared `fake_rpkm` fixture (`analytics/conftest.py`):

| Asset | Purpose |
|---|---|
| `pathway_list_expectations.yaml` | Expected pathway name lists for `fake_rpkm` at 1–2 superpathways and tax/filter combos |
| `test_pathway_list_service.py` | Parametrized pytest via `build_pathway_list_from_duckdb()` |
| Cross-check | For each case, assert result equals distinct ann-axis labels from `build_chord_from_duckdb()` with `ann_level='pathway'` and matching filters |

Tests skip when bridges/sample.duckdb unavailable (same guard as chord/overview/krona).

### 8.2 Express sidecar proxy tests

Extend `fastapi_sidecar_proxy.test.ts`:

- Default (no query param) → legacy handler
- `?backend=duckdb` → fetch to `ANALYTICS_API_URL` + route path
- Fetch failure → error envelope with `"pathway_list analytics API unavailable"` prefix

### 8.3 Node integration test

Existing `parse_pathway_list` tests in `src/tests/data_functions.test.ts` continue to exercise legacy path (reference list). Add a note that extended-payload compatibility is covered by the handler ignoring extra fields (no test change required unless legacy is updated later).

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

# Browser console — opt out to legacy Node (migrated channels: chord, overview, krona, pathway_list)
localStorage.setItem('vizBackend', 'legacy')

# Via Express proxy
curl -X POST 'http://localhost:3001/api/viz/pathway-list?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{
    "names": ["fake_rpkm.tsv"],
    "tax_level": "phylum",
    "selected_taxon": {},
    "superpathway": "Carbohydrate metabolism"
  }'
```

## 10. Implementation Checklist

- [ ] `analytics/api/chord_prefix.py` — extract `build_chord_prefix_rows` + shared predicates from `chord_service.py`
- [ ] `analytics/api/chord_service.py` — refactor to use `chord_prefix`
- [ ] `analytics/api/pathway_list_service.py` — `build_pathway_list_from_duckdb()`
- [ ] `analytics/api/schemas.py` — `PathwayListRequest`
- [ ] `analytics/api/main.py` — `POST /api/viz/pathway-list`
- [ ] `pathway_list_expectations.yaml` + `test_pathway_list_service.py` (cross-check vs chord ann labels)
- [ ] `src/server/index.ts` — pathway-list sidecar route
- [ ] `src/renderer/src/vizBackend.ts` — add `'pathway_list'` to `MIGRATED_CHANNELS`
- [ ] `src/renderer/src/api.ts` — `sidecarQuery('pathway_list')`
- [ ] `src/renderer/src/components/Network.tsx` — extended payload + re-fetch on chord-aligned deps
- [ ] Proxy unit tests (pathway_list label)
