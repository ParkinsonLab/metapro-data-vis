# Graph API via dbt Intermediates — Design Spec

> **Status:** Approved (2026-07-04; PR #12 review incorporated)  
> **Goal:** Reimplement `POST /api/viz/graph` on the FastAPI analytics sidecar, returning the graph blob (`inner_count_matrix`, `inner_matrix_index`, `outer_matrix_index`, `colors`, `tax_map`) from `int_rpkm_by_ec_tax` in `runs/{sample_id}/sample.duckdb`. Express keeps the legacy handler when `?backend=duckdb` is absent; the renderer adds `'graph'` to migrated channels.

**Parent specs:**

- `docs/superpowers/specs/2026-07-02-graph-tab-recovery-design.md` — Express graph endpoint, `parse_graph_data`, renderer wiring
- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, `int_rpkm_by_ec_tax`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — sidecar proxy pattern, envelope, filter normalisation
- `docs/superpowers/specs/2026-06-30-krona-dbt-api-design.md` — `int_rpkm_by_ec_tax` as canonical value source; bridge_tax PIVOT pattern

## 1. Context

Metapro Viz renders a 3D RPKM scatter plot on the Graph tab (`Graph.tsx`). The Express handler `parse_graph` (`src/server/data_functions.ts`) loads wide TSV data, applies tax/pathway filters, aggregates by EC, and builds an inner EC × taxon matrix via `parse_graph_data` (`src/server/parse.ts`).

Graph and chord share the same request body and filter semantics today, but **must remain independent modules** — they may diverge in ordering and query strategy later (chord ordering migration is explicitly out of scope).

The graph-tab-recovery spec (`2026-07-02`) scoped analytics out. This spec adds the DuckDB backend following the established sidecar migration pattern (overview, krona, chord, pathway-list).

**Assumption (in scope):** `int_rpkm_by_ec_tax` is materialised in `runs/{sample_id}/sample.duckdb` before the graph endpoint is invoked (same pipeline run as krona/chord).

**Out of scope (this spec):**

- Upload endpoint / pipeline trigger integration
- Comparison mode (`names.length > 1`) on the analytics API path
- Retiring the legacy Node `parse_graph` handler
- Chord ordering migration to hierarchical alphabetical
- Strict cross-backend matrix golden parity (legacy vs DuckDB byte match)
- Graph tab UI changes beyond `sidecarQuery('graph')` wiring
- Shared code between `graph_service.py` and `chord_service.py` beyond `filters.py` and `colors.py`

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Parity bar | **Contract parity (B)** — same response fields/shape; Graph tab renders correctly on both backends. **Functional-only (C)** acceptable when justified, provided frontend stays backend-agnostic. | Design decision |
| Python architecture | **Standalone** `graph_service.py` + `graph_matrix.py`; share only `filters.py`, `colors.py`, envelope | Graph and chord may diverge; no coupling to `chord_service` or `rollup_query` |
| Value source | **`int_rpkm_by_ec_tax`** — canonical `(ec_normalized, source_tax_id, value)` grain | No pathway-level or rank duplication (unlike `int_tax_rollup_resolved`) |
| Index membership | **Distinct keys from filtered triples** — index/metadata from separate bridge queries; no reference-only rows | Avoids legacy index/reference mismatch; no zero-row trim on DuckDB path |
| Tax display label | Finest resolved rank display name per `source_tax_id`; fallback `COALESCE(names.name, CAST(source_tax_id AS VARCHAR))` | Matches krona name fallback |
| EC ordering | Hierarchical alphabetical: `(superpathway_name, pathway_name, ec_normalized)` tuple, lexicographic — **always full tuple** | Design decision |
| Taxon ordering | Hierarchical alphabetical: full lineage tuple `(kingdom, phylum, class, order, family, genus, species, display_name)` lexicographic | Design decision |
| Outer index ordering | **Same tuple rules as inner leaves** — categories are prefix segments; `ann_level` controls outer ann-axis depth only | Design decision |
| API contract | Unchanged request body (identical to chord) + graph response blob + `{ ok, value }` envelope | No `Graph.tsx` plot logic changes |
| FastAPI route | **`POST /api/viz/graph`** — identical path, method, envelope, HTTP 200 as Express | Drop-in sidecar replacement |
| Default backend | Legacy Node `parse_graph` | Safe rollout |
| Opt-in backend | `POST /api/viz/graph?backend=duckdb` (Express) or direct on FastAPI `:8001` | Mirrors other migrated channels |
| Sidecar env var | **`ANALYTICS_API_URL`** (default `http://localhost:8001`) | Shared FastAPI process |
| Migration proxy | Shared `src/server/fastapi_sidecar_proxy.ts` | Temporary Express→FastAPI bridge |
| Renderer toggle | Add `'graph'` to `MIGRATED_CHANNELS` in `vizBackend.ts` | Sidecar default for graph |
| Comparison mode | Error when `names.length > 1` | Deferred follow-up (same as chord v1) |

## 3. Architecture

```
┌─────────────┐     POST /api/viz/graph          ┌──────────────┐
│   React     │ ────────────────────────────────► │   Express    │
│  Graph.tsx  │     (no query param = legacy)   │   :3001      │
└─────────────┘                                   └──────┬───────┘
                                                         │
                       ?backend=duckdb                   │
                       ─────────────────────────────────►│ proxy ──────┐
                                                         │  (same path) │
                                                         ▼             ▼
                                                legacy in-process   ┌──────────────────────────┐
                                                                    │   FastAPI  :8001         │
                                                                    │   POST /api/viz/graph    │
                                                                    └──────────────┬───────────┘
                                                                                   │
                                         int_rpkm_by_ec_tax + bridge parquets      │
                                         graph_service → graph_matrix              │
                                                                                   ▼
                                                                    runs/{sample_id}/sample.duckdb
```

| Component | Location | Role |
|---|---|---|
| Sidecar route | `src/server/index.ts` | Move graph from `vizRoutes` → `sidecarRoutes` |
| FastAPI endpoint | `analytics/api/main.py` | `POST /api/viz/graph` |
| Query + metadata | `analytics/api/graph_service.py` | `filtered_triples` temp table; SQL-ordered EC/tax metadata; labeled triples join |
| Matrix builder | `analytics/api/graph_matrix.py` | Assembles pre-ordered indices, symmetric matrix, outer categories, colors (no SQL, no Python sort) |
| Colors | `analytics/api/colors.py` | Add `map_lum`, `get_sub_color` (port from `src/server/utils.ts`) |
| Schema | `analytics/api/schemas.py` | `GraphRequest` (= chord request fields) |
| Renderer | `vizBackend.ts`, `api.ts` | `'graph'` in `MIGRATED_CHANNELS`; `sidecarQuery('graph')` |

**Do not use `build_filtered_rollup_rows` or `int_tax_rollup_resolved` for graph values.** That table duplicates each underlying RPKM up to 21× (3 pathway levels × 7 tax ranks). Chord avoids double-counting by pinning `pathway_level = ann_level` and `requested_rank = tax_level` in its final aggregation; graph reads the canonical grain directly.

## 4. Request / Response Contract

### 4.1 Request (unchanged — identical to chord)

```json
{
  "names": ["test_rpkm_1.tsv"],
  "tax_level": "phylum",
  "ann_level": "superpathway",
  "selected_ann_cat": {},
  "selected_taxon": {}
}
```

| Field | DuckDB semantics |
|---|---|
| `names` | Single sample only; `sample_id = strip_extension(names[0])` |
| `tax_level` | Rank used for `tax_map` category grouping and outer tax-axis categories |
| `ann_level` | Pathway rank for `ec_map` category label and **outer ann-axis category depth** (does not shorten EC leaf sort tuple) |
| `selected_ann_cat` | EC subset filter via `bridge_ec_pathway` (same normalisation as chord) |
| `selected_taxon` | `source_tax_id` subset filter via `bridge_tax_rollup` |

### 4.2 Response (unchanged — fields `Graph.tsx` consumes)

```json
{
  "ok": true,
  "value": {
    "inner_count_matrix": [[...]],
    "inner_matrix_index": ["gap_1", "1.1.1.1", "...", "gap_2", "Bacillus subtilis", "...", "gap_3"],
    "outer_matrix_index": ["gap_1", "Amino acid metabolism", "...", "gap_2", "Bacillota", "...", "gap_3"],
    "colors": { "1.1.1.1": "hsl(...)", "Bacillota": "hsl(...)" },
    "tax_map": { "Bacillus subtilis": "Bacillota" }
  }
}
```

Omit `ann_map` and `outer_count_matrix`. Frontend plot logic in `Graph.tsx` is unchanged.

## 5. Data Query (`graph_service.py`)

`graph_service` runs **two query roles** — values and index/metadata — that must not be combined:

| Role | Grain | Bridge joins | Purpose |
|---|---|---|---|
| **Triples** (§5.1) | 1 row = `(ec_normalized, source_tax_id, value)` | **None** — filters via `EXISTS` only | Matrix cell values; must never fan out |
| **Index / metadata** (§5.2) | 1 row per distinct EC or `source_tax_id` in triples | Bridges + lineage PIVOT | Sort keys, `ec_map`, `tax_map`, display labels |

### 5.1 Value triples

Query `int_rpkm_by_ec_tax` directly — one row per `(ec_normalized, source_tax_id)`. The pipeline already drops `value <= 0` in `stg_rpkm_long`, so triples are strictly positive.

**No bridge joins on the triples query.** Joining `bridge_ec_pathway` (one row per `pathway_node_id`) or `bridge_tax_rollup` (seven rows per taxon) would fan out and risk double-counting values. Filters are applied via `EXISTS` subqueries only. Ann filters use a materialised `bridge_ec_long` temp table (one row per `(ec_normalized, filter_level, filter_name)`) so EXISTS predicates stay simple; taxon filters use `bridge_tax_rollup` parquet directly.

Results are stored in a `filtered_triples` temp table (same pattern as chord's `filtered_rollup_rows`) and reused by all downstream metadata queries:

```sql
CREATE TEMP TABLE filtered_triples AS
SELECT r.ec_normalized, r.source_tax_id, r.value
FROM int_rpkm_by_ec_tax r
WHERE r.value > 0
  AND EXISTS (
    SELECT 1 FROM bridge_ec_long b
    WHERE b.ec_normalized = r.ec_normalized
      AND b.filter_level = ? AND b.filter_name = ?
  )
  AND EXISTS (
    SELECT 1 FROM bridge_tax_rollup t
    WHERE t.source_tax_id = r.source_tax_id
      AND t.requested_rank = ? AND t.resolved_tax_label = ?
  )
```

Ann/taxon filter predicates reuse the same normalisation helpers as chord (`normalise_ann_filter`, `normalise_taxon_filter`) but are implemented in graph_service — not delegated to `rollup_query.py`.

**Precedent:** krona reads `int_rpkm_by_ec_tax` directly (`krona_service.py`).

**Legacy note:** Express `parse_graph_data` zero-row-trims because `Object.keys(ec_map)` can include reference ECs not present in filtered `agg_data`. The DuckDB path builds the index from distinct keys in filtered triples only (§5.2) — no equivalent mismatch.

### 5.2 Index and metadata queries

Run **after** `filtered_triples` is materialised. Operate on distinct keys from that temp table — bridge fan-out here affects metadata only, not summed values.

**EC axis** — distinct `ec_normalized` from `filtered_triples`, joined to deduped bridge for pathway sort keys, **ordered in SQL**:

```sql
SELECT b.ec_normalized, b.superpathway_name, b.pathway_name
FROM (SELECT DISTINCT ec_normalized FROM filtered_triples) t
JOIN bridge_ec_dedup b ON b.ec_normalized = t.ec_normalized
ORDER BY b.superpathway_name, b.pathway_name, b.ec_normalized
```

`bridge_ec_dedup` is one row per `ec_normalized` (lexicographically smallest `(superpathway_name, pathway_name)` when an EC maps to multiple pathway nodes).

From this result build in Python:

- Sorted EC label list (inner index ann segment) — **order preserved from SQL**
- `ann_category` per EC at `ann_level` depth (`superpathway_name` or `pathway_name`)
- Pathway sort keys (§5.5) — implicit in SQL `ORDER BY`

**Tax axis** — distinct `source_tax_id` from `filtered_triples`, joined to lineage PIVOT + `names`, materialised as `graph_tax_metadata` temp table, **ordered in SQL**:

```sql
CREATE TEMP TABLE graph_tax_metadata AS
WITH ids AS (SELECT DISTINCT source_tax_id FROM filtered_triples),
     bridge_wide AS (<bridge_tax PIVOT all 7 ranks — krona pattern>)
SELECT
    d.source_tax_id,
    w.kingdom, w.phylum, w.class, w."order", w.family, w.genus, w.species,
    COALESCE(n.name, CAST(d.source_tax_id AS VARCHAR)) AS display_name,
    COALESCE(w.<tax_level>, '') AS tax_map_value
FROM ids d
LEFT JOIN bridge_wide w USING (source_tax_id)
LEFT JOIN names n ON n.tax_id = d.source_tax_id
ORDER BY kingdom, phylum, class, "order", family, genus, species, display_name
```

No second `bridge_tax_rollup` join is needed. The PIVOT already exposes `resolved_tax_label` at each rank as a column (`w.kingdom`, `w.phylum`, …). Derive metadata in Python from the ordered result:

- **`tax_map`:** `display_name → tax_map_value` (PIVOT column at `tax_level`)
- **Inner sort key:** full lineage tuple `(w.kingdom, …, w.species, display_name)` (§5.5) — implicit in SQL `ORDER BY`
- **Outer tax categories:** first-seen dedupe of `tax_map_value` in tax row order (§6.2)

Labeled triples for the matrix join `filtered_triples` to `graph_tax_metadata` on `source_tax_id` (INNER JOIN — every filtered triple has metadata by construction).

### 5.3 `ec_map` (metadata — not used for values)

`ec_map: Record<ec_normalized, list[category_label]>` maps each EC to its annotation category at `ann_level` (superpathway name, pathway name, etc.).

Built from the **EC metadata query** (§5.2) — one entry per EC present in filtered triples, not the full bridge. Each `ec_rows` dict includes `ann_category` at `ann_level` depth. Used by `graph_matrix.py` for:

1. Outer index annotation categories (first-seen dedupe of `ann_category` in EC row order — §6.2)
2. Per-EC line colors (`get_sub_color` from category color)

EC leaf ordering is enforced by SQL `ORDER BY` in `graph_service` (§5.2), not in `graph_matrix.py`.

Values in the matrix come from triples (§5.1), not from `ec_map`.

### 5.4 `tax_map` (metadata)

`tax_map: Record<display_name, category_at_tax_level>` maps each taxon column label to its category at `tax_level`.

Built from the **tax metadata query** (§5.2): `display_name → w.<tax_level>` using the lineage PIVOT column at the active rank. Used by `Graph.tsx` for y-axis background surface grouping.

### 5.5 Lineage and pathway sort keys

**Pathway tuple** per EC — **always** `(superpathway_name, pathway_name, ec_normalized)`, lexicographic. `ann_level` does **not** shorten this tuple; it only controls outer ann-axis category depth (§6.2).

| `ann_level` | EC leaf sort tuple (always) | Outer ann-axis category depth |
|---|---|---|
| `superpathway` | `(superpathway_name, pathway_name, ec_normalized)` | 1 segment: `superpathway_name` |
| `pathway` | `(superpathway_name, pathway_name, ec_normalized)` | 2 segments: through `pathway_name` |
| `pathway_node` | `(superpathway_name, pathway_name, ec_normalized)` | 2 segments: through `pathway_name` (EC label is `ec_normalized`) |

**Taxonomy tuple** per taxon (PIVOT `bridge_tax_rollup` + `names`, same pattern as krona `_fetch_taxa`):

```
(kingdom, phylum, class, order, family, genus, species, display_name)
```

Each element compared alphabetically left-to-right (lexicographic sort).

## 6. Unified Ordering Model

Inner leaves and outer categories share one ordering philosophy: **hierarchical alphabetical on prefix tuples**. Categories are the first *N* segments of the same hierarchy that leaves use.

### 6.1 Inner matrix index

```
inner_matrix_index = ['gap_1', ...sorted_ecs..., 'gap_2', ...sorted_taxa..., 'gap_3']
```

| Segment | Sort key |
|---|---|
| ECs | Full pathway tuple `(superpathway_name, pathway_name, ec_normalized)` (§5.5), lexicographic |
| Taxa | Full lineage tuple (§5.5), lexicographic |

Index members are the distinct EC and taxon labels from filtered triples (§5.1), with sort keys and maps from metadata queries (§5.2) — no zero-sum rows by construction.

### 6.2 Outer matrix index

```
outer_matrix_index = ['gap_1', ...sorted_ann_cats..., 'gap_2', ...sorted_tax_cats..., 'gap_3']
```

| Segment | Derivation | Sort key |
|---|---|---|
| Ann categories | Distinct `ann_category` labels in EC row order | First-seen dedupe of ordered inner EC categories (§7) |
| Tax categories | Distinct `tax_map_value` labels in tax row order | First-seen dedupe of ordered inner tax categories (§7) |

**Example (tax):** When `tax_level = phylum`, each phylum category `"Bacillota"` sorts by `(kingdom_label, "Bacillota")` — the first two segments of the lineage tuple for any taxon in that phylum. When `tax_level = genus`, category sort uses `(kingdom, phylum, class, order, family, genus_label)`.

**Example (pathway):** When `ann_level = superpathway`, category `"Amino acid metabolism"` appears in outer index when the first EC in that superpathway appears in the SQL-ordered EC list. Category order follows first appearance among sorted EC leaves, not a separate category sort pass.

Implementation: **inner leaves sorted in SQL** (`graph_service.py`); **outer categories** derived in `graph_matrix.py` by first-seen dedupe (`_dedupe_preserve_order`) on the ordered inner category labels. Because inner leaves are sorted by full pathway/lineage tuple, category order matches prefix-truncated tuple sort in practice.

### 6.3 Colors

Category colors via `get_color(i, n)` on the **sorted** category lists (same index order as outer segments).

Per-EC and per-taxon shades via `get_sub_color(category_color, label)` — port `map_lum` + `get_sub_color` from `src/server/utils.ts` into `analytics/api/colors.py`.

Color assignment order follows the unified sort order above (not legacy abundance order).

## 7. Matrix Builder (`graph_matrix.py`)

Port core logic from `parse_graph_data` / `make_inner_count_matrix` / `add_filler_value` in `src/server/parse.ts`. **`graph_matrix.py` receives pre-ordered triples + metadata from `graph_service` — it does not run SQL, join bridges, or sort rows.**

1. Build `inner_matrix_index` from pre-ordered `ec_rows` and `tax_rows`: `['gap_1', *ecs, 'gap_2', *tax_labels, 'gap_3']` — EC/tax lists are the SQL-ordered row sequences as-is (§6.1)
2. Build `outer_matrix_index` by first-seen dedupe of `ann_category` (EC rows) and `tax_map_value` (tax rows) in that same order (§6.2)
3. Fill symmetric inner matrix by keyed lookup: for each triple `(ec_normalized, display_tax_label, value)`, place `value` at the corresponding matrix positions
4. Apply gap fillers on `gap_1`, `gap_2`, `gap_3`
5. Assign colors (§6.3)

**No zero-row trim** on the DuckDB path — `ec_rows` and `tax_rows` are built from distinct keys in `filtered_triples`; labeled triples join the same metadata. Every index label has a corresponding triple by construction. (Legacy Express still trims; see §5.1 legacy note.)

Return `{ inner_count_matrix, inner_matrix_index, outer_matrix_index, colors, tax_map }`.

## 8. Express + Renderer Wiring

```typescript
// index.ts — move graph from vizRoutes to sidecarRoutes
{ path: '/api/viz/graph', label: 'graph', legacyHandler: parse_graph }

// vizBackend.ts
const MIGRATED_CHANNELS = new Set([..., 'graph'])

// api.ts
graph: { method: 'POST', url: `/api/viz/graph${sidecarQuery('graph')}` }
```

Default backend: legacy. Sidecar mode (localStorage default) appends `?backend=duckdb`.

## 9. Testing

| Layer | Coverage |
|---|---|
| Unit | `test_graph_matrix.py` — matrix shape, gap fillers, pre-ordered EC/tax indices, outer category dedupe, colors present |
| Service | `test_graph_service.py` — triples query has no bridge joins (row count = unique `(ec, source_tax_id)` pairs); SQL-ordered metadata on distinct keys; shape on `fake_rpkm` fixture; filter narrowing; comparison-mode rejection |
| Proxy | Extend or mirror `fastapi_sidecar_proxy.test.ts` for graph route |
| Cross-backend | **Not required v1** — optional smoke that both backends return valid shapes |
| Manual | Graph tab 3D plot in legacy and sidecar modes; EC selection from Network |

No YAML golden matrix dump for v1 (that would be strict A-parity).

## 10. Error Handling

| Condition | Response |
|---|---|
| `names.length > 1` | `{ ok: false, error: "comparison mode not supported on analytics API" }` |
| Sample DB missing | `{ ok: false, error: "sample not found: …" }` |
| `int_rpkm_by_ec_tax` not materialised | `{ ok: false, error: "int_rpkm_by_ec_tax not materialized for sample: …" }` |
| Bridge Parquet missing | `{ ok: false, error: "reference parquet missing: …" }` |
| FastAPI unreachable | `{ ok: false, error: "graph duckdb backend unavailable: …" }` |

All HTTP 200 with envelope (consistent with other migrated endpoints).

## 11. Documented Deviations from Legacy (Expected)

| Area | Legacy (Express) | Analytics API |
|---|---|---|
| Index ordering | Abundance-based category sort + `sort_by_category` within category | Hierarchical alphabetical (pathway tuple + lineage tuple) |
| Outer category order | Derived from `ec_map` / `tax_map` with legacy sort | Prefix-truncated tuple sort (§6.2) |
| Value source | Wide TSV in memory | `int_rpkm_by_ec_tax` in sample DuckDB |
| Query structure | Single in-memory pipeline (`agg_by_ec` + `parse_graph_data`) | **Separate triples query** (no bridge joins) + **metadata queries** on distinct triple keys (§5.1–§5.2) |
| `ec_map` source | SQLite EC reference (can include ECs absent from filtered data) | `bridge_ec_pathway` on distinct EC keys from triples (metadata query) |
| Zero-row trim | `idx_to_keep` in `parse_graph_data` — trims reference ECs absent from data | Not needed — inner index built from distinct triple keys only |

These are acceptable under contract parity (B). Graph tab must render correctly; index order need not match legacy byte-for-byte.

## 12. Acceptance Criteria

- [ ] `POST /api/viz/graph` on FastAPI returns valid graph blob on `fake_rpkm` fixture
- [ ] Triples query reads `int_rpkm_by_ec_tax` with `EXISTS` filters only — no bridge joins, no double-counting
- [ ] Index/metadata from separate queries on distinct triple keys (§5.2)
- [ ] Inner and outer indices use unified hierarchical alphabetical ordering (§6)
- [ ] Express sidecar proxy forwards graph requests when `?backend=duckdb`
- [ ] Graph tab renders 3D plot in sidecar mode with EC selections from Network
- [ ] Legacy mode unchanged when `vizBackend=legacy`
- [ ] `pytest analytics/api/tests/test_graph_*.py` and `npm test` pass
