# Graph Tab Recovery — Design Spec

> **Status:** Draft (2026-07-02)  
> **Goal:** Restore the Graph tab 3D scatter plot (Plotly `scatter3d` of selected ECs × taxonomy × RPKM) on `dev`, matching upstream/main behaviour via **Express (legacy) handlers only**.

**Parent context:**

- `docs/superpowers/specs/2026-06-08-electron-to-web-design.md` — web migration removed client-side `parsed_data`; Graph left unmounted
- `SPEC.md` §6.3 — Graph reads deprecated `parsed_data`; only unmounted pane

## 1. Problem

On `upstream/main`, the Graph tab showed a 3D line plot titled "RPKM for selected ECs":

| Axis | Content |
|------|---------|
| X | EC numbers selected in Network detail view (`selected_annotations`) |
| Y | Taxonomy (grouped by active `tax_rank` category) |
| Z | RPKM |
| Background | Translucent colored surfaces per tax category |

On `dev`, two gaps block this:

| Gap | Detail |
|-----|--------|
| **Component unmounted** | `App.tsx` comments out `{mainState === 'graph' && <Graph />}` |
| **No data source** | `Graph.tsx` reads `parsed_data.{inner_count_matrix, inner_matrix_index, outer_matrix_index, colors, tax_map}` — client `parse_data` was removed and nothing repopulates it |

**Scope boundary:** Express / legacy mode only. Analytics API, sidecar proxy, and `?backend=duckdb` are **out of scope**.

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend | Express only (`POST /api/viz/graph`) | User constraint |
| Data delivery | Full `graph_data` blob (Approach A) | Drop-in for existing `Graph.tsx` plot logic |
| Workflow | Empty until ECs selected in Network (upstream workflow A) | User confirmed; show placeholder copy when `selected_annotations` is empty |
| Orchestration | **Chord-aligned** (not strict `parse_data` port) | Filter-aware matrix via same pipeline as `parse_ec_chord`; refetch on `selected_ann_cat` / `selected_taxon` |
| Matrix builder | Port `parse_data_callback` → `parse_graph_data` | Inner EC × taxon matrix + outer category matrix |
| Fetch pattern | Reactive `request('graph', …)` like Chord/Krona | Replaces upload-time `parse_data` |
| API contracts | New endpoint; response mirrors old `parsed_data` fields Graph consumes | No analytics changes |

### Orchestration note (chord-aligned vs upstream)

Upstream `parse_data` built the matrix from the **full** dataset with **no** chord drill-down filters, refetching only on `tax_rank` / `ann_rank` changes. Graph sliced client-side via `selected_annotations`.

This spec intentionally uses the **`parse_ec_chord` pipeline** instead: subset by `selected_taxon` and `selected_ann_cat`, then aggregate. The matrix reflects active chord filters — a deliberate improvement over strict upstream parity.

## 3. Architecture

```
selected_file_list + tax_rank + ann_rank + selected_ann_cat + selected_taxon
                    │
                    ▼
         POST /api/viz/graph  (Express)
                    │
    subset_data → subset_data_by_ann → agg_by_ec
    ec_map = get_ec_map(selected_ann_cat, ann_level)
    tax_map = get_tax_map(agg_data, tax_level)
                    │
                    ▼
         parse_graph_data → graph_data in Zustand
                    │
     Network: click EC nodes → selected_annotations[]
                    │
                    ▼
              Graph tab (Plotly 3D)
         slice graph_data × selected_annotations
```

| Component | Location | Role |
|-----------|----------|------|
| `parse_graph` | `src/server/data_functions.ts` | Chord-aligned orchestration |
| `parse_graph_data` | `src/server/parse.ts` | Inner + outer matrix build (ported from upstream `parse_data_callback`) |
| `graph` channel | `api.ts`, `App.tsx` | `request('graph', …)` → `graph_data` |
| `Graph.tsx` | renderer | Plot + empty state; reactive fetch `useEffect` |

## 4. Server Implementation

### 4.1 `parse_graph` handler

Register in `vizRoutes` alongside `counts` and `network` (no sidecar proxy).

**Request** (same shape as chord):

```typescript
{
  names: string[]
  tax_level: string
  ann_level: string
  selected_ann_cat: { level: string; name: string }
  selected_taxon: { level: string; name: string }
}
```

**Pipeline:**

```typescript
const raw_data = names_to_data(names)
const filtered = subset_data_by_ann(
  subset_data(raw_data, selected_taxon),
  selected_ann_cat
)
const agg_data = agg_by_ec(filtered)
const ec_map = get_ec_map(selected_ann_cat, ann_level)
const tax_map = get_tax_map(agg_data, tax_level)
return parse_graph_data({ data: agg_data, ec_map, tax_map })
```

### 4.2 `parse_graph_data` (ported from upstream `parse_data_callback`)

Add to `src/server/parse.ts`. Port matrix-building logic from `upstream/main:src/renderer/src/components/parse.tsx`.

**Outer matrix** — annotation categories × tax categories:

- `annotation_cats` = sorted unique values from `ec_map` (flatten `string[]` values)
- `outer_matrix_index` = `['gap_1', ...annotation_cats, 'gap_2', ...tax_cats, 'gap_3']`
- Use existing `make_count_matrix` + `add_filler_value` (same as `parse_ec_data`)

**Inner matrix** — individual EC# × individual taxon columns:

- `all_annotations` = sorted `Object.keys(ec_map)` (EC numbers present after filter)
- `all_taxa` = sorted taxon column names from `tax_map` keys, grouped by category
- `inner_matrix_index` = `['gap_1', ...all_annotations, 'gap_2', ...all_taxa, 'gap_3']`
- New `make_inner_count_matrix(data, matrix_index)` — maps each row's `EC#` directly (no `ann_map` lookup), matching upstream inner-ring call with `ann_map = null`
- Trim zero-sum rows (upstream `idx_to_keep` logic)

**Colors:**

- Category colors via `get_color`
- Per-EC and per-taxon shades via `get_sub_color` — restore in `src/server/utils.ts` (uncomment; `map_lum` already exists)

**Response** (fields `Graph.tsx` consumes):

```typescript
{
  inner_count_matrix: number[][]
  inner_matrix_index: string[]
  outer_matrix_index: string[]
  colors: Record<string, string>
  tax_map: Record<string, string>
  ann_map: Record<string, string[]>  // same as ec_map; Graph does not read this
}
```

Omit `outer_count_matrix` from the response (Graph does not use it).

### 4.3 `sort_by_category`

Port the upstream two-level sort helper used when ordering `all_annotations` and `all_taxa` in the inner index.

## 5. Renderer Implementation

| File | Change |
|------|--------|
| `src/server/index.ts` | Import `parse_graph`; add to `vizRoutes` |
| `src/server/data_functions.ts` | Export `parse_graph` |
| `src/server/parse.ts` | Add `parse_graph_data`, `make_inner_count_matrix`, `sort_by_category` |
| `src/server/utils.ts` | Export `get_sub_color` |
| `src/renderer/src/api.ts` | Add `'graph'` channel → `POST /api/viz/graph` (no `sidecarQuery`) |
| `src/renderer/src/store/AppStore.ts` | Add `graph_data: any`; remove `parsed_data` deprecation |
| `src/renderer/src/App.tsx` | Import `Graph`; register `graph` handler; mount Graph tab |
| `src/renderer/src/components/Graph.tsx` | `parsed_data` → `graph_data`; add `selected_annotations` to `useEffect` deps; empty-state UI; reactive fetch `useEffect` |

### 5.1 Reactive fetch (in `Graph.tsx`)

Mirror Chord deps:

```typescript
useEffect(() => {
  if (selected_file_list.length === 0) return
  request('graph', {
    names: selected_file_list,
    tax_level: tax_rank,
    ann_level: ann_rank,
    selected_ann_cat: toApiFilter(selected_ann_cat),
    selected_taxon: toApiFilter(selected_taxon)
  })
}, [selected_file_list, tax_rank, ann_rank, selected_ann_cat, selected_taxon])
```

### 5.2 Empty state

When `selected_annotations.length === 0`, render placeholder text instead of an empty `<div />`:

> Select ECs in the Network view to plot RPKM.

Plot logic otherwise unchanged (matrix slicing, tax-category y-axis grouping, background surfaces).

## 6. Testing

| Layer | Test |
|-------|------|
| Server | `data_functions.test.ts`: load test fixtures → `parse_graph` with default filters → assert `inner_matrix_index` contains EC labels between `gap_1`/`gap_2`, at least one non-zero cell in `inner_count_matrix`, `colors` non-empty |
| Server | Filter narrowing: call with `selected_ann_cat` set → matrix smaller or different than unfiltered |
| Manual | Load test files → Chord filter → Network → select pathway → click EC nodes → Graph shows 3D lines; clear selections → empty state |

## 7. Out of Scope

- Analytics API / sidecar
- Slim on-demand slice endpoint (Approach B follow-up)
- Cross-tab filter chips on Graph tab
- Plot styling theme changes (dev `Graph.tsx` already uses light theme)
- `parsed_data` store key cleanup beyond replacing with `graph_data`

## 8. Acceptance Criteria

- [ ] Graph tab is mounted and navigable from the nav bar.
- [ ] Empty-state message when no ECs are selected in Network.
- [ ] 3D plot renders after selecting ECs in Network detail view.
- [ ] Plot reflects active chord filters (matrix refetches on filter change).
- [ ] `npm test` passes, including new `parse_graph` integration assertion.
