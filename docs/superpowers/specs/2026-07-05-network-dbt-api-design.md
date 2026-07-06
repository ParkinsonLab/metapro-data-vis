# Network API via dbt Intermediates — Design Spec

> **Status:** Approved (2026-07-05)  
> **Goal:** Reimplement `POST /api/viz/network` on the FastAPI analytics sidecar, returning the per-pathway graph (`nodes`, `edges`, `colors`) with EC-node tax pies from `int_rpkm_by_ec_tax` in `runs/{sample_id}/sample.duckdb` and static topology from reference Parquet. Express keeps the legacy handler when `?backend=duckdb` is absent; the renderer adds `'network'` to migrated channels.

**Parent specs:**

- `docs/superpowers/specs/2026-07-02-network-pie-recovery-design.md` — Express `parse_network` pie fix, renderer wiring (legacy only)
- `docs/superpowers/specs/2026-07-04-graph-dbt-api-design.md` — `int_rpkm_by_ec_tax` value triples, tax metadata PIVOT, lineage-ordered category colors
- `docs/superpowers/specs/2026-07-01-pathway-list-dbt-api-design.md` — sidecar migration pattern, Network pane context
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — sidecar proxy, envelope, filter normalisation
- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, reference Parquet

## 1. Context

Metapro Viz renders a per-pathway network graph in the Network pane detail view (`Network.tsx` → `PathwayDetail`). The Express handler `parse_network` (`src/server/data_functions.ts`) does two things:

1. **Static pathway graph** — nodes and edges from bundled SQLite `pathway_nodes` / `pathway_edges` via `get_pathway_info(pathway_name)`, with server-side x/y rescaling from client `width` / `height`.
2. **EC pie decoration** — filters sample rows to the pathway and `selected_taxon`, aggregates by EC, rolls tax columns up to `tax_level`, and attaches `values: [{ id, value }]` on enzyme nodes whose `label` matches the EC, plus a `colors` map keyed by tax category.

`POST /api/viz/network` is one of two remaining legacy viz routes (`counts` is the other). Pathway-list, graph, chord, krona, and overview are already on the FastAPI sidecar.

**Assumption (in scope):** `int_rpkm_by_ec_tax` is materialised in `runs/{sample_id}/sample.duckdb` before the network endpoint is invoked (same pipeline run as graph/krona/chord).

**Out of scope (this spec):**

- `POST /api/viz/counts` migration (list-view `PathwayPreview` mini pies stay on legacy)
- Upload endpoint / pipeline trigger integration
- Comparison mode (`names.length > 1`) on the analytics API path
- Retiring the legacy Node `parse_network` handler
- Strict cross-backend golden parity (legacy vs DuckDB byte match on pie values or category order)
- Network tab UI changes beyond `sidecarQuery('network')` wiring
- Shared module extraction from `graph_service.py` (standalone `network_service.py`; share only `filters.py`, `colors.py`, envelope)
- Leaf-level pie granularity or `get_sub_color` on pie wedges (pies remain at `tax_level` category grain)

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Parity bar | **Contract parity** — same response fields/shape; Network detail view renders correctly on both backends; ordering/color deviations acceptable | Matches graph migration bar |
| Python architecture | **Standalone** `network_service.py`; share only `filters.py`, `colors.py`, envelope | Network and graph may diverge; no coupling to `graph_matrix` or `rollup_query` |
| Value source | **`int_rpkm_by_ec_tax`** — canonical `(ec_normalized, source_tax_id, value)` grain | Same rationale as graph; avoids rollup double-counting |
| Static graph source | **Reference Parquet** (`pathway_superpathways`, `pathway_nodes`, `pathway_edges`) | Mirrors bundled SQLite; topology independent of sample |
| Pathway filter | **`pathway_name` on request body** — maps to `bridge_ec.pathway_name` EXISTS | No renderer payload refactor; differs from graph's `selected_ann_cat` |
| Taxon filter | `normalise_taxon_filter(selected_taxon)` via `bridge_tax_rollup` EXISTS | Same as graph |
| Tax category order | **Lineage first-seen dedupe** — distinct `tax_map_value` in SQL lineage row order | Graph-aligned; not legacy alphabetical `_.sortBy` |
| Tax colors | **Category hues** via `get_color(i, len(tax_cats))` on lineage-ordered categories | Graph outer-band model; no `get_sub_color` (pies are category-granular) |
| EC → node match | `node.label == ec_normalized` | Legacy behaviour; pies keyed by EC label, not `node.id` — see §4.4 |
| API contract | Request: `names`, `tax_level`, `selected_taxon`, `pathway_name`, `width`, `height`; response: `{ nodes, edges, colors }` + envelope | Unchanged from Express |
| FastAPI route | **`POST /api/viz/network`** — identical path, method, envelope, HTTP 200 as Express | Drop-in sidecar replacement |
| Default backend | Legacy Node `parse_network` | Safe rollout |
| Opt-in backend | `POST /api/viz/network?backend=duckdb` (Express) or direct on FastAPI `:8001` | Mirrors other migrated channels |
| Sidecar env var | **`ANALYTICS_API_URL`** (default `http://localhost:8001`) | Shared FastAPI process |
| Migration proxy | Shared `src/server/fastapi_sidecar_proxy.ts` | Temporary Express→FastAPI bridge |
| Renderer toggle | Add `'network'` to `MIGRATED_CHANNELS` in `vizBackend.ts` | Sidecar default for network detail |
| Comparison mode | Error when `names.length > 1` | Deferred follow-up (same as graph v1) |

## 3. Architecture

```
┌─────────────┐     POST /api/viz/network         ┌──────────────┐
│   React     │ ────────────────────────────────► │   Express    │
│ Network.tsx │     (no query param = legacy)   │   :3001      │
└─────────────┘                                   └──────┬───────┘
                                                         │
                       ?backend=duckdb                   │
                       ─────────────────────────────────►│ proxy ──────┐
                                                         │  (same path) │
                                                         ▼             ▼
                                                legacy in-process   ┌──────────────────────────┐
                                                                    │   FastAPI  :8001         │
                                                                    │   POST /api/viz/network  │
                                                                    └──────────────┬───────────┘
                                                                                   │
              reference parquet (pathway_nodes/edges)  +  int_rpkm_by_ec_tax        │
              network_service: static graph + filtered triples + pie assembly     │
                                                                                   ▼
                                                                    runs/{sample_id}/sample.duckdb
```

| Component | Location | Role |
|---|---|---|
| Sidecar route | `src/server/index.ts` | Move network from `vizRoutes` → `sidecarRoutes` |
| FastAPI endpoint | `analytics/api/main.py` | `POST /api/viz/network` |
| Service | `analytics/api/network_service.py` | Reference graph load, filtered triples, tax metadata, pie aggregation, layout transform, edge embedding |
| Colors | `analytics/api/colors.py` | `get_color` on lineage-ordered tax categories (existing) |
| Schema | `analytics/api/schemas.py` | `NetworkRequest` |
| Renderer | `vizBackend.ts`, `api.ts` | `'network'` in `MIGRATED_CHANNELS`; `sidecarQuery('network')` |

**Do not use `build_filtered_rollup_rows` or `int_tax_rollup_resolved` for network values.** Network needs per-EC tax breakdown at canonical grain; rollup fans out across pathway levels and ranks (same rejection rationale as graph spec §3).

## 4. Request / Response Contract

### 4.1 Request (unchanged)

```json
{
  "names": ["test_rpkm_1.tsv"],
  "tax_level": "phylum",
  "selected_taxon": { "level": "phylum", "name": "Bacillota" },
  "pathway_name": "Glycolysis",
  "width": 900,
  "height": 550
}
```

| Field | DuckDB semantics |
|---|---|
| `names` | Single sample only; `sample_id = strip_extension(names[0])` |
| `tax_level` | Rank for pie category grouping (`tax_map_value` at this rank) |
| `selected_taxon` | Optional `source_tax_id` subset filter via `bridge_tax_rollup` EXISTS |
| `pathway_name` | **Required** — resolves static graph and pathway EXISTS filter on value triples |
| `width` / `height` | Client viewBox; server applies legacy x/y flip + rescale |

No `selected_ann_cat`, no `ann_level`.

### 4.2 Response (unchanged — fields `PathwayDetail` consumes)

```json
{
  "ok": true,
  "value": {
    "nodes": [
      {
        "id": "…",
        "label": "1.1.1.1",
        "type": "rectangle",
        "x": 123.4,
        "y": -56.7,
        "values": [
          { "id": "Bacillota", "value": 42.0 },
          { "id": "Pseudomonadota", "value": 0 }
        ]
      }
    ],
    "edges": [
      { "source": { "id": "…", "label": "…", "x": 0, "y": 0, "type": "…", "values": [] }, "target": { "…": "…" } }
    ],
    "colors": { "Bacillota": "hsl(0 75 50)", "Pseudomonadota": "hsl(90 75 50)" }
  }
}
```

| Field | Semantics |
|---|---|
| `nodes` | All pathway nodes from reference graph; layout coords transformed; nodes whose `label` matches an EC in filtered data carry `values`, others get `values: []` |
| `edges` | `source` / `target` are **embedded node objects** (legacy lodash `_.find` pattern), not bare ids |
| `colors` | One HSL color per tax category in `values[].id`; `{}` when no pie data |
| `values` | Dense array — one entry per distinct tax category across the pathway, **zeros included**, order aligned to lineage-derived `tax_cats` |

### 4.3 Edge cases (match legacy)

| Condition | Response |
|---|---|
| Unknown `pathway_name` | `{ nodes: [], edges: [], colors: {} }` |
| Taxon filter matches nothing | Static graph renders; all `values: []`; `colors: {}` |
| Duplicate EC labels on multiple nodes (same pathway) | Same pie attached to each (keyed by `node.label`, not `node.id`) |
| Compound/circle nodes (non-EC labels) | `values: []` |

### 4.4 Duplicate EC labels within a pathway

`pathway_nodes.name` is **not unique within a single pathway** — KEGG KGML can place the same EC on multiple rectangles in one map (distinct `id`, `x`, `y`; same `name`). This is separate from the same EC appearing across different pathways.

Measured on `resources/db/taxonomy.db`:

- **1,460** `(pathway, name)` groups have duplicates within the same pathway (any name)
- **1,034** for EC-dotted names only
- Example: **Fatty acid biosynthesis** has **33** nodes all labeled `2.3.1.85`; **Metabolism of xenobiotics by cytochrome P450** has **27** nodes labeled `1.14.14.1`

Legacy `parse_network` builds `ec_to_pie` keyed by EC string, then looks up `ec_to_pie.get(node.label)` per node — so all copies in a pathway share one pie. The DuckDB path must preserve this.

## 5. Data Query (`network_service.py`)

`network_service` has **three data sources**. Only one separation rule is strict:

| Role | Grain | Source | Purpose |
|---|---|---|---|
| **Static graph** | 1 row per pathway node/edge | Reference Parquet | Topology + raw layout coords (sample-independent) |
| **Triples** | 1 row = `(ec_normalized, source_tax_id, value)` | `int_rpkm_by_ec_tax` | Pie cell values; **must never fan out** |
| **Tax metadata** | 1 row per distinct `source_tax_id` in triples | Bridges + lineage PIVOT + `names` | `tax_map_value` at `tax_level`, lineage sort order |

**Hard rule (triples creation):** do not join `bridge_ec` (or any bridge) on the `int_rpkm_by_ec_tax` scan — use `EXISTS` filters only. A join can fan out rows and double-count `SUM(value)` (graph spec §5.1).

**Soft rule (metadata + aggregation):** tax metadata may be materialised as a temp table (graph pattern) or inlined — either is fine. Joining `filtered_triples` → tax metadata on `source_tax_id` for pie aggregation is **1:1** and expected (same as `graph_service._fetch_labeled_triples`). Static graph loading stays separate from sample queries.

### 5.1 Static graph (reference Parquet)

Parquet files under `analytics/transform/reference/parquet/`:

```sql
-- resolve pathway_name → pathway_id
SELECT id FROM pathway_superpathways WHERE name = ?

-- nodes
SELECT id, name AS label, x, y, type
FROM pathway_nodes
WHERE pathway = ?

-- edges (ids only before assembly)
SELECT source, target
FROM pathway_edges
WHERE pathway = ?
```

If `pathway_name` does not resolve → return `{ nodes: [], edges: [], colors: {} }` immediately (no sample DB access required).

### 5.2 Value triples

Same pattern as `graph_service._materialize_filtered_triples`. **No bridge joins on the triples query** — filters via `EXISTS` only:

```sql
CREATE TEMP TABLE filtered_triples AS
SELECT r.ec_normalized, r.source_tax_id, r.value
FROM int_rpkm_by_ec_tax r
WHERE r.value > 0
  AND EXISTS (
    SELECT 1 FROM bridge_ec b
    WHERE b.ec_normalized = r.ec_normalized
      AND b.pathway_name = ?
  )
  AND EXISTS (
    SELECT 1 FROM read_parquet(?) t
    WHERE t.source_tax_id = r.source_tax_id
      AND t.requested_rank = ?
      AND t.resolved_tax_label = ?
  )  -- or TRUE when no taxon filter
```

`pathway_name` from the request maps directly to `bridge_ec.pathway_name`. Materialise `bridge_ec` from `bridge_ec_pathway.parquet` when the pathway filter is active (always, since `pathway_name` is required).

### 5.3 Tax metadata

Materialise `network_tax_metadata` (or an equivalent CTE) using the same SQL pattern as `graph_service._materialize_tax_metadata` (PIVOT `bridge_tax_rollup` + `names`, `ORDER BY` full lineage tuple). A separate temp table is optional — implementation may inline metadata into the §5.4 aggregation query as long as lineage ordering for `tax_cats` is preserved. Derive:

- **`tax_map_value`** — PIVOT column at `tax_level`, falling back to `display_name`
- **`tax_cats`** — first-seen dedupe of `tax_map_value` in lineage row order

### 5.4 Pie aggregation

1. Join `filtered_triples` → `network_tax_metadata` on `source_tax_id`
2. `GROUP BY ec_normalized, tax_map_value` → `SUM(value)`
3. Build `ec_to_values: dict[str, list[float]]` — dense array aligned to `tax_cats`
4. Attach to nodes: `values = [{ id: cat, value: v } for cat, v in zip(tax_cats, ec_to_values.get(node.label, zeros))]`

### 5.5 Layout transform

Port from legacy `parse_network` — applied server-side so both backends return identical coordinates:

```python
x = (node.y / 1100) * width - width / 2 + 100
y = (node.x / 1000) * height - height / 2
```

The pathway-graph layout was authored with x/y swapped relative to SVG axes; the renderer stays generic.

### 5.6 Edge assembly

For each edge, resolve `source` and `target` ids to full node objects from the placed `nodes` list (same as legacy `_.find(new_nodes, n => n.id === edge.source)`).

## 6. Colors

Network pies are **category-granular** (`values[].id` = tax category at `tax_level`), so use graph's **category** color pipeline only — not leaf-level `get_sub_color`.

| Step | Rule |
|---|---|
| Category list | `tax_cats` = first-seen dedupe of `tax_map_value` in lineage-sorted tax metadata row order |
| `colors` map | `{ category: get_color(i, len(tax_cats)) for i, category in enumerate(tax_cats) }` |
| `values` order | Dense array aligned to `tax_cats` order |

`PathwayDetail` fills pie wedges via `colors[d.data.id]` where `d.data.id` is the category name.

**Deviation from legacy (acceptable under contract parity):** category order and therefore hue assignment follows lineage-derived order (graph-aligned), not legacy `_.uniq(_.sortBy(Object.values(tax_map)))` alphabetical order.

## 7. Express + Renderer Wiring

```typescript
// index.ts — move network from vizRoutes to sidecarRoutes
{ path: '/api/viz/network', label: 'network', legacyHandler: parse_network }

// vizBackend.ts
const MIGRATED_CHANNELS = new Set([..., 'network'])

// api.ts
network: { method: 'POST', url: `/api/viz/network${sidecarQuery('network')}` }
```

Default backend: legacy. Sidecar mode (localStorage default) appends `?backend=duckdb`.

`Network.tsx` request payload is unchanged — still sends `pathway_name`, not `selected_ann_cat`.

## 8. Testing

| Layer | Coverage |
|---|---|
| Unit | `test_network_service.py` — pie aggregation, layout transform, edge embedding, unknown pathway, empty taxon filter |
| Golden | `network_expectations.yaml` + parametrized pytest on `fake_rpkm` fixture |
| Proxy | Extend or mirror `fastapi_sidecar_proxy.test.ts` for network route |
| Manual | Network detail view: node pie wedges + colors in sidecar mode; taxon filter clears pies |

### 8.1 Network golden YAML (`network_expectations.yaml`)

Hand-picked scenarios on `fake_rpkm`. Regenerate via `dump_fake_rpkm_expectations.py --network` (add flag during implementation).

| `case_id` | What it locks |
|---|---|
| `pathway_phylum_baseline` | Default request: pathway + phylum `tax_level`; at least one EC node with non-zero pie values |
| `pathway_species_tax_rank` | Finest tax category grouping |
| `pathway_kingdom_tax_rank` | Coarsest tax category grouping |
| `pathway_and_taxon_filter` | Pathway + `selected_taxon` EXISTS filter → empty pies when no match |
| `pathway_methane_metabolism` | Alternate pathway → different EC pie subset |
| `unknown_pathway` | Empty graph response |

Each case asserts `nodes` shape, selected EC `values` pairs (tolerance), `colors` keys, and layout coords for a fixed `width`/`height`.

## 9. Error Handling

| Condition | Response |
|---|---|
| Missing / empty `pathway_name` | `{ ok: false, error: "pathway_name is required" }` |
| `names.length === 0` | `{ ok: false, error: "names must contain at least one sample" }` |
| `names.length > 1` | `{ ok: false, error: "comparison mode not supported on analytics API" }` |
| Sample DB missing | `{ ok: false, error: "sample not found: …" }` |
| `int_rpkm_by_ec_tax` not materialised | `{ ok: false, error: "int_rpkm_by_ec_tax not materialized for sample: …" }` |
| Reference Parquet missing | `{ ok: false, error: "reference parquet missing: …" }` |
| FastAPI unreachable | `{ ok: false, error: "network analytics API unavailable: …" }` |

All HTTP 200 with envelope (consistent with other migrated endpoints). Feature gaps say **"analytics API"**, not "duckdb backend".

## 10. Documented Deviations from Legacy (Expected)

| Area | Legacy (Express) | Analytics API |
|---|---|---|
| Tax category order | Alphabetical (`_.sortBy` on tax_map values) | Lineage first-seen dedupe (graph-aligned) |
| Category hues | `get_color(i, n)` on alphabetical `tax_cats` | `get_color(i, n)` on lineage-ordered `tax_cats` |
| Value source | Wide TSV in memory (`agg_by_ec`) | `int_rpkm_by_ec_tax` in sample DuckDB |
| Static graph source | Bundled SQLite | Reference Parquet |
| Query structure | Single in-memory pipeline | Separate triples query (no bridge joins) + tax metadata + reference graph load |

These are acceptable under contract parity. Network detail view must render correctly; category order and exact pie values need not match legacy byte-for-byte.

## 11. Acceptance Criteria

- [ ] `POST /api/viz/network` on FastAPI returns valid `{ nodes, edges, colors }` on `fake_rpkm` fixture
- [ ] Triples query reads `int_rpkm_by_ec_tax` with `EXISTS` filters only — no bridge joins, no double-counting
- [ ] Static graph loaded from reference Parquet; layout transform matches legacy formula
- [ ] EC nodes with matching data carry non-empty `values`; taxon filter respected
- [ ] `colors` keyed by tax category at `tax_level`; lineage-derived category order
- [ ] Express sidecar proxy forwards network requests when `?backend=duckdb`
- [ ] Network detail view renders pie wedges in sidecar mode
- [ ] Legacy mode unchanged when `vizBackend=legacy`
- [ ] `pytest analytics/api/tests/test_network_*.py` and `npm test` pass
