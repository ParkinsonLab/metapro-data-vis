# Pathway List Tax Breakdowns — Design Spec

> **Status:** Approved (2026-07-05)  
> **Goal:** Batch per-pathway tax pie data into the DuckDB `pathway-list` response so the Network list view avoids N `/api/viz/counts` calls, while keeping a counts fallback for legacy backend and defensive gaps.

**Parent specs:**

- `docs/superpowers/specs/2026-07-01-pathway-list-dbt-api-design.md` — pathway-list DuckDB migration, filter parity, wrapper infrastructure
- `docs/superpowers/specs/2026-07-02-network-pie-recovery-design.md` — list-view pies via per-card `parse_counts` (deferred batch endpoint)

## 1. Context

The Network pane list view (`Network.tsx` → `PathwayList` → `PathwayPreview`) shows a mini tax-distribution pie on each pathway card. Today each `PathwayPreview` independently calls `POST /api/viz/counts` (Express legacy) with `selected_ann_cat: { level: 'pathway', name }`, returning `{ index, counts }` at the active `tax_rank`.

With pathway-list migrated to the DuckDB analytics API (sidecar default), the list still fires **1 pathway-list + N counts** requests. The pathway-list service already materialises `filtered_rollup_rows` — the same filtered rollup chord uses — so per-pathway tax vectors can be computed in a single additional SQL aggregation without N round-trips.

**Intended behaviour (locked in):** DuckDB pathway-list returns pathway names plus embedded tax breakdowns. The UI uses embedded breakdowns when present and falls back to per-card counts calls otherwise. Legacy Express pathway-list is updated to return a minimal wrapper object so both backends share one renderer code path.

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Breakdown source | DuckDB analytics API only | Reuses `filtered_rollup_rows`; no duplicate Node aggregation |
| Legacy pathway-list | Returns `{ pathways: string[] }` (no `breakdowns` key) | Uniform object shape for UI; avoids `string[]` vs object union detection |
| DuckDB pathway-list | Returns `{ pathways: string[], breakdowns: Record<string, OverviewVector> }` | Batch all pie data in one response |
| `OverviewVector` | Reuse existing `{ index: string[], counts: number[] }` | Same shape as `parse_counts` and overview |
| UI data priority | Embedded `breakdowns[pathway]` first; per-card counts fallback | Works on legacy and for any missing key |
| Tax index ordering | Alphabetical by `resolved_tax_label` within each pathway | Matches legacy `make_count_vector` (`_.sortBy` on tax categories) |
| Pathway ordering | Alphabetical by display label ASC | Unchanged from pathway-list spec |
| Inclusion rule | Pathway in `pathways` iff `SUM(value) > 0` after filters | Unchanged |
| Label SQL | Reuse `PATHWAY_LABEL_SQL` | Display strings match chord / counts labels |
| Request body | Unchanged (`PathwayListRequest`) | No new query params |
| `/api/viz/counts` | Unchanged; not migrated to DuckDB | Fallback only |
| Legacy breakdowns | Not computed in Node | Counts fallback covers legacy pies |

## 3. Architecture

```
Chord click → selected_ann_cat (superpathway)
                    │
                    ▼
            Network / PathwayList
                    │
        POST /api/viz/pathway-list
        (legacy or ?backend=duckdb)
                    │
        ┌───────────┴───────────────────────┐
        ▼                                   ▼
  Legacy Express                      DuckDB analytics
  { pathways: [...] }               { pathways: [...],
                                        breakdowns: { name → vector } }
        │                                   │
        └───────────┬───────────────────────┘
                    ▼
           normalize → store
           pathway_list + pathway_tax_breakdowns
                    │
                    ▼
           PathwayPreview × N
                    │
        breakdowns[p] present? ──yes──► render pie (no fetch)
                    │
                   no
                    ▼
           POST /api/viz/counts (per card)
```

| Component | Location | Role |
|---|---|---|
| `build_pathway_list_from_duckdb` | `analytics/api/pathway_list_service.py` | Pathway names + batched tax breakdowns |
| `parse_pathway_list` | `src/server/data_functions.ts` | Wrap legacy `string[]` as `{ pathways }` |
| `normalizePathwayListResponse` | `src/renderer/src/` (small helper) | Parse envelope value into store fields |
| `pathway_tax_breakdowns` | `AppStore` | `Record<string, CountsData>` keyed by pathway name |
| `PathwayPreview` | `Network.tsx` | Optional `tax_counts` prop; counts fetch fallback |

## 4. API Contract

### 4.1 Response shapes

All responses use the existing `{ ok, value }` envelope.

| Backend | `value` shape |
|---|---|
| Legacy Express | `{ pathways: string[] }` |
| DuckDB analytics | `{ pathways: string[], breakdowns: Record<string, OverviewVector> }` |

`breakdowns` keys are pathway display labels (same strings as `pathways` entries). A pathway listed in `pathways` has a corresponding `breakdowns` entry when the DuckDB backend is used; legacy omits `breakdowns` entirely.

### 4.2 Pydantic schemas

```python
class PathwayListResponse(BaseModel):
    pathways: list[str]
    breakdowns: dict[str, OverviewVector] = Field(default_factory=dict)
```

DuckDB service always populates `breakdowns`. Legacy Node handler returns `{ pathways: names }` without a `breakdowns` key (empty dict after normalisation).

### 4.3 Legacy handler change

`parse_pathway_list` currently returns `string[]`. Change to:

```typescript
return { pathways: get_pathways_in_superpathway(sp).map((p) => p.name) }
```

Update `src/tests/data_functions.test.ts` expectations from `string[]` to `{ pathways: string[] }`.

## 5. DuckDB Implementation

### 5.1 SQL

After `build_filtered_rollup_rows` (unchanged), run pathway-name query as today, plus:

```sql
SELECT
  {label_sql} AS display_label,
  cf.resolved_tax_label,
  SUM(cf.value) AS value
FROM filtered_rollup_rows cf
WHERE cf.requested_rank = ?
  AND cf.pathway_level = 'pathway'
GROUP BY cf.pathway_key, {label_sql}, cf.resolved_tax_label
HAVING SUM(cf.value) > 0
ORDER BY display_label ASC, resolved_tax_label ASC
```

`label_sql` is `PATHWAY_LABEL_SQL` with `t.` → `cf.` (same as existing pathway-list query).

### 5.2 Building vectors

Group SQL rows by `display_label`. For each pathway, collect distinct `resolved_tax_label` values in encounter order (already sorted alphabetically by SQL `ORDER BY`). Emit:

```python
OverviewVector(index=[...], counts=[...])
```

Return `PathwayListResponse(pathways=pathway_names, breakdowns=breakdown_map)`.

### 5.3 Parity target

For each pathway in golden fixtures, `breakdowns[name]` must match the vector produced by legacy `parse_counts` with:

```json
{
  "names": ["<sample>"],
  "tax_rank": "<tax_level>",
  "selected_taxon": "<filter>",
  "selected_ann_cat": { "level": "pathway", "name": "<pathway>" }
}
```

## 6. Renderer Implementation

### 6.1 Store

Add to `AppStore`:

```typescript
pathway_tax_breakdowns: Record<string, CountsData>  // default {}
```

### 6.2 Normaliser

```typescript
type PathwayListValue = {
  pathways: string[]
  breakdowns?: Record<string, CountsData>
}

function normalizePathwayListResponse(value: unknown): PathwayListValue {
  if (typeof value === 'object' && value !== null && 'pathways' in value) {
    const v = value as PathwayListValue
    return { pathways: v.pathways, breakdowns: v.breakdowns ?? {} }
  }
  // Defensive: accept bare string[] during any transitional window
  if (Array.isArray(value)) return { pathways: value, breakdowns: {} }
  return { pathways: [], breakdowns: {} }
}
```

### 6.3 Channel handler

```typescript
pathway_list: (value) => {
  const { pathways, breakdowns } = normalizePathwayListResponse(value)
  useAppStore.setState({ pathway_list: pathways, pathway_tax_breakdowns: breakdowns })
}
```

### 6.4 PathwayList / PathwayPreview

- `PathwayList` reads `pathway_tax_breakdowns` from store.
- Pass `tax_counts={pathway_tax_breakdowns[p]}` to each `PathwayPreview`.
- `PathwayPreview` accepts optional `tax_counts?: CountsData`:
  - If defined → use directly in existing pie `useEffect` (skip fetch `useEffect`).
  - If undefined → existing `fetch('/api/viz/counts', …)` fallback unchanged.

Clear `pathway_tax_breakdowns` when superpathway or filter deps change (same `useEffect` as pathway-list request in `Network.tsx`).

## 7. Error Handling

| Case | Behaviour |
|---|---|
| Legacy response `{ pathways }` only | `breakdowns = {}` → all cards use counts fallback |
| DuckDB response, pathway missing from `breakdowns` | That card falls back to counts (defensive) |
| `breakdowns[pathway]` with empty `index` | Render empty pie; no fallback |
| Filter / superpathway change | Re-fetch pathway-list; store fields replaced atomically |
| Comparison mode (`names.length > 1`) | Unchanged error from pathway-list service |
| FastAPI unreachable (sidecar proxy) | Falls back to legacy `{ pathways }` via proxy; pies via counts |

## 8. Testing

| Layer | Test |
|---|---|
| `pathway_list_service.py` | Golden YAML extended with `breakdowns`; per-pathway parity vs `parse_counts` on `fake_rpkm` |
| `test_main.py` | Assert wrapper shape with `pathways` and `breakdowns` keys |
| `data_functions.test.ts` | `parse_pathway_list` returns `{ pathways }` object |
| Renderer | Unit test for `normalizePathwayListResponse` (object, bare array, empty) |
| Manual | Sidecar: list pies render; DevTools shows 1 pathway-list call, 0 counts calls. Legacy: pies render via counts fallback |

## 9. Out of Scope

- Migrating `/api/viz/counts` to DuckDB
- Computing breakdowns in legacy `parse_pathway_list`
- Detail-view node pies (`parse_network`)
- Opt-in query param to omit breakdowns from DuckDB response
- Shared TypeScript response types package

## 10. Acceptance Criteria

- [ ] DuckDB `POST /api/viz/pathway-list` returns `{ pathways, breakdowns }` with per-pathway vectors matching `parse_counts` parity.
- [ ] Legacy `parse_pathway_list` returns `{ pathways: string[] }`.
- [ ] Network list pies render from embedded breakdowns on sidecar (no per-card counts traffic).
- [ ] Network list pies still render on legacy backend via counts fallback.
- [ ] `pytest` and `npm test` pass, including updated golden fixtures.

## 11. File Touch List

| File | Change |
|---|---|
| `analytics/api/schemas.py` | Add `PathwayListResponse` |
| `analytics/api/pathway_list_service.py` | Return wrapper with breakdowns |
| `analytics/api/main.py` | Return `.model_dump()` |
| `analytics/api/tests/fixtures/pathway_list_expectations.yaml` | Add `breakdowns` per case |
| `analytics/api/tests/test_pathway_list_service.py` | Assert breakdown parity |
| `analytics/api/tests/test_main.py` | Assert wrapper shape |
| `src/server/data_functions.ts` | `parse_pathway_list` → `{ pathways }` |
| `src/tests/data_functions.test.ts` | Update expectations |
| `src/renderer/src/store/AppStore.ts` | Add `pathway_tax_breakdowns` |
| `src/renderer/src/App.tsx` | Normaliser in channel handler |
| `src/renderer/src/components/Network.tsx` | Pass `tax_counts` prop; conditional fetch |
