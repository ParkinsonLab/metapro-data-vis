# Graph API via dbt Intermediates — Design Spec

> **Status:** Draft (2026-07-04)  
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
| Index membership | **Inner joins** — EC and taxon labels derived only from filtered triples joined to bridges; no reference-only rows | Avoids legacy index/reference mismatch; no zero-row trim on DuckDB path |
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
| Query + metadata | `analytics/api/graph_service.py` | Value triples, `ec_map`, `tax_map`, lineage/pathway sort keys |
| Matrix builder | `analytics/api/graph_matrix.py` | Inner matrix, outer index, colors |
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

### 5.1 Value triples and index membership

Query `int_rpkm_by_ec_tax` directly — one row per `(ec_normalized, source_tax_id)`. The pipeline already drops `value <= 0` in `stg_rpkm_long`, so triples are strictly positive.

**Inner joins define index membership.** EC and taxon labels come only from triples that survive filters — not from a full reference scan. This avoids the legacy mismatch where `ec_map` could list reference ECs absent from filtered data (which forced zero-row trim in `parse_graph_data`).

```sql
SELECT
    r.ec_normalized,
    r.source_tax_id,
    r.value,
    b.superpathway_name,
    b.pathway_name
FROM int_rpkm_by_ec_tax r
INNER JOIN bridge_ec_pathway b ON r.ec_normalized = b.ec_normalized
INNER JOIN bridge_tax_rollup t
    ON r.source_tax_id = t.source_tax_id
   AND t.requested_rank = ?   -- tax_level, for taxon filter + tax_map
WHERE r.value > 0
  AND <ann_filter_predicate>
  AND <taxon_filter_predicate>
```

Ann/taxon filter predicates reuse the same normalisation helpers as chord (`normalise_ann_filter`, `normalise_taxon_filter`) but are implemented in graph_service — not delegated to `rollup_query.py`.

Distinct EC labels and taxon display names for the matrix index are derived from this result set (plus `names` / lineage PIVOT for tax display labels). No separate reference query that could introduce zero-sum rows.

**Precedent:** krona reads `int_rpkm_by_ec_tax` directly (`krona_service.py`).

**Legacy note:** Express `parse_graph_data` still zero-row-trims because `Object.keys(ec_map)` can include reference ECs not present in filtered `agg_data`. The DuckDB path does not replicate that pattern.

### 5.2 `ec_map` (metadata — not used for values)

`ec_map: Record<ec_normalized, list[category_label]>` maps each EC to its annotation category at `ann_level` (superpathway name, pathway name, etc.).

Built via **INNER JOIN** from filtered triples to `bridge_ec_pathway` — one entry per EC present in data, not the full bridge. Used by `graph_matrix.py` for:

1. EC ordering (pathway hierarchy sort keys)
2. Outer index annotation categories (at `ann_level` depth — see §5.4)
3. Per-EC line colors (`get_sub_color` from category color)

Values in the matrix come from triples, not from `ec_map`.

### 5.3 `tax_map` (metadata)

`tax_map: Record<display_name, category_at_tax_level>` maps each taxon column label to its category at `tax_level`.

Built from the same inner-joined triple rows: display name from finest-rank / `names` lookup; category from `bridge_tax_rollup` at `requested_rank = tax_level`. Used by `Graph.tsx` for y-axis background surface grouping.

### 5.4 Lineage and pathway sort keys

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
| ECs | Full pathway tuple `(superpathway_name, pathway_name, ec_normalized)` (§5.4), lexicographic |
| Taxa | Full lineage tuple (§5.4), lexicographic |

Index members are exactly the distinct EC and taxon labels from filtered triples (§5.1) — no zero-sum rows by construction.

### 6.2 Outer matrix index

```
outer_matrix_index = ['gap_1', ...sorted_ann_cats..., 'gap_2', ...sorted_tax_cats..., 'gap_3']
```

| Segment | Derivation | Sort key |
|---|---|---|
| Ann categories | Distinct category labels at `ann_level` present in filtered data | Pathway tuple **truncated** to category depth (§5.4), lexicographic |
| Tax categories | Distinct `tax_map` values (categories at `tax_level`) | Lineage tuple **truncated** to `tax_level` depth, lexicographic |

**Example (tax):** When `tax_level = phylum`, each phylum category `"Bacillota"` sorts by `(kingdom_label, "Bacillota")` — the first two segments of the lineage tuple for any taxon in that phylum. When `tax_level = genus`, category sort uses `(kingdom, phylum, class, order, family, genus_label)`.

**Example (pathway):** When `ann_level = superpathway`, category `"Amino acid metabolism"` sorts by `("Amino acid metabolism",)`. When `ann_level = pathway`, category `"Glycolysis"` sorts by `(superpathway_name, "Glycolysis")`.

Implementation: compute sort keys once per leaf; derive category keys as prefix truncation; deduplicate and sort categories independently but with the same tuple comparison function.

### 6.3 Colors

Category colors via `get_color(i, n)` on the **sorted** category lists (same index order as outer segments).

Per-EC and per-taxon shades via `get_sub_color(category_color, label)` — port `map_lum` + `get_sub_color` from `src/server/utils.ts` into `analytics/api/colors.py`.

Color assignment order follows the unified sort order above (not legacy abundance order).

## 7. Matrix Builder (`graph_matrix.py`)

Port core logic from `parse_graph_data` / `make_inner_count_matrix` / `add_filler_value` in `src/server/parse.ts`:

1. Build sorted `inner_matrix_index` from distinct EC and taxon labels in filtered triples (§5.1)
2. Fill symmetric inner matrix from triples `(ec, display_tax_label, value)`
3. Apply gap fillers on `gap_1`, `gap_2`, `gap_3`
4. Build `outer_matrix_index` from sorted category lists (§6.2)
5. Assign colors (§6.3)

**No zero-row trim** on the DuckDB path — index membership is enforced by inner joins in `graph_service`, not by post-hoc matrix pruning. (Legacy Express still trims; see §5.1.)

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
| Unit | `test_graph_matrix.py` — matrix shape, gap fillers, unified ordering, colors present; all index labels have ≥1 non-zero cell |
| Unit | `test_graph_ordering.py` — lineage tuple sort, pathway tuple sort, category prefix truncation |
| Service | `test_graph_service.py` — shape on `fake_rpkm` fixture; filter narrowing; comparison-mode rejection; `int_rpkm_by_ec_tax` missing error |
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
| `ec_map` source | SQLite EC reference (can include ECs absent from filtered data) | `bridge_ec_pathway` via inner join on filtered triples |
| Zero-row trim | `idx_to_keep` in `parse_graph_data` | Not needed — index from inner joins only |

These are acceptable under contract parity (B). Graph tab must render correctly; index order need not match legacy byte-for-byte.

## 12. Acceptance Criteria

- [ ] `POST /api/viz/graph` on FastAPI returns valid graph blob on `fake_rpkm` fixture
- [ ] Value query reads `int_rpkm_by_ec_tax` with inner joins — no double-counting, no reference-only index rows
- [ ] Inner and outer indices use unified hierarchical alphabetical ordering (§6)
- [ ] Express sidecar proxy forwards graph requests when `?backend=duckdb`
- [ ] Graph tab renders 3D plot in sidecar mode with EC selections from Network
- [ ] Legacy mode unchanged when `vizBackend=legacy`
- [ ] `pytest analytics/api/tests/test_graph_*.py` and `npm test` pass
