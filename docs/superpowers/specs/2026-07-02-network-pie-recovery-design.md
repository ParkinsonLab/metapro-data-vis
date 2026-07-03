# Network Pie Chart Recovery — Design Spec

> **Status:** Approved (2026-07-02)  
> **Goal:** Restore tax-distribution pie charts in the Network pane list view and detail view, matching behaviour that worked on `upstream/main`, using **Express (legacy) handlers only**.

**Parent context:**

- `docs/superpowers/specs/2026-06-08-electron-to-web-design.md` — web migration removed client-side `parsed_data` aggregation
- `SPEC.md` §6.3 — Network pane two-view model (`PathwayList` / `PathwayDetail`)

## 1. Problem

On `dev`, two pie-chart features that worked on `upstream/main` are missing:

| View | upstream/main | dev (Express) |
|------|---------------|---------------|
| **List** (`PathwayPreview` grid) | Mini tax pie per pathway card | Plain-text `PathwayCard` |
| **Detail** (`PathwayDetail` graph) | Colored pie wedge ring on enzyme nodes | Graph renders; all nodes have `values: []` |

**Scope boundary:** Compare and recover against **Express / legacy mode only**. Analytics API, sidecar proxy, and `?backend=duckdb` are **out of scope**.

## 2. Root Causes

### 2.1 List-view pies

`upstream/main` computed pies client-side from `parsed_data` (chord inner matrix) and `ann_map`. The electron→web migration removed `parsed_data`; `Network.tsx` was rewritten with text-only `PathwayCard` and no replacement data source.

The Express handler `parse_counts` (`POST /api/viz/counts`) already performs the equivalent aggregation when called with `selected_ann_cat: { level: 'pathway', name: '<pathway>' }`, returning `{ index, counts }` at the active `tax_rank`.

### 2.2 Detail-view node pies

`parse_network` (`POST /api/viz/network`) builds per-EC tax pies from `agg_by_ec(filtered_rows)`. The implementation incorrectly treats `agg_by_ec` output as **column-oriented** (`agg_data['EC#']`), but `agg_by_ec` returns a **row array** (confirmed by `src/tests/data_functions.test.ts` `agg_by_ec` suite and `get_tax_map(agg_data, …)` usage in `parse_ec_chord`). The EC→pie map is never populated; every node receives `values: []`.

`parse_counts` for the same pathway/filter returns non-zero totals, proving the underlying data and filters are correct.

## 3. Requirements (Locked In)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Backend | Express only (`/api/viz/counts`, `/api/viz/network`) | User constraint; no analytics changes |
| List pies | Restore `PathwayPreview` d3 mini pies | Parity with upstream/main |
| List data source | `POST /api/viz/counts` per pathway | Reuses existing handler; no new endpoint |
| List fetch pattern | Per-card `fetch` with local React state | Avoids overwriting global `network_preview_data` when N cards mount |
| Detail pies | Fix `parse_network` row iteration | Server bug; no API contract change |
| Filter parity | Same `names`, `tax_rank`, `selected_taxon` as detail view | List and detail pies reflect identical filters |
| Colors (list) | Inline `get_color` helper (same HSL ramp as `Overview.tsx`) | `parse_counts` does not return colors |
| Colors (detail) | Unchanged — `parse_network` returns `colors` map | Existing contract |
| API contracts | No changes to request/response shapes | Drop-in recovery |
| pathway_list | Unchanged | Listing logic is separate from pie rendering |

## 4. Architecture

```
Chord click → selected_ann_cat (superpathway)
                    │
                    ▼
            Network / PathwayList
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
 pathway_list (Express)    PathwayPreview × N
 (unchanged)                     │
                                 │ POST /api/viz/counts  (per pathway)
                                 │ { names, tax_rank, selected_taxon,
                                 │   selected_ann_cat: { level:'pathway', name } }
                                 ▼
                           mini d3 pie + pathway name
                                 │ click
                                 ▼
                         POST /api/viz/network
                                 │
                                 ▼
                    PathwayDetail (nodes + pie wedges)
```

| Component | Location | Role |
|-----------|----------|------|
| `parse_counts` | `src/server/data_functions.ts` | Per-pathway tax rollup for list pies (existing) |
| `parse_network` | `src/server/data_functions.ts` | Per-EC tax pies on graph nodes (fix row iteration) |
| `PathwayPreview` | `src/renderer/src/components/Network.tsx` | Fetch counts + render mini pie; click → network request |
| `PathwayDetail` | `src/renderer/src/components/Network.tsx` | Unchanged renderer; consumes fixed `network_data` |

## 5. Implementation Details

### 5.1 Fix `parse_network` (Express)

Replace the column-format `agg_data['EC#']` loop with row iteration:

```typescript
const agg_rows = agg_by_ec(filtered_rows) as Array<Record<string, number | string>>
if (agg_rows.length > 0) {
  const tax_columns = Object.keys(agg_rows[0]).filter((c) => !key_cols.includes(c))
  const tax_map = get_parents_at_level(tax_columns, tax_level)
  tax_cats = _.uniq(_.sortBy(Object.values(tax_map))) as string[]
  colors = Object.fromEntries(tax_cats.map((cat, i) => [cat, get_color(i, tax_cats.length)]))

  for (const row of agg_rows) {
    const ec = String(row['EC#'])
    const pie = tax_cats.map(() => 0)
    for (const taxon of tax_columns) {
      const cat = tax_map[taxon]
      if (!cat) continue
      const pos = tax_cats.indexOf(cat)
      if (pos < 0) continue
      const value = Number(row[taxon])
      if (Number.isFinite(value)) pie[pos] += value
    }
    ec_to_pie.set(ec, pie)
  }
}
```

Remove the incorrect comment claiming column-format output.

### 5.2 Restore `PathwayPreview` (renderer)

Replace `PathwayCard` with `PathwayPreview`:

1. On mount, `fetch('/api/viz/counts', { method: 'POST', … })` with envelope parsing into local state.
2. Build `pie_data` from `{ index, counts }`.
3. Render d3 pie in `useEffect` (adapt markup from `upstream/main`).
4. On click: `request('network', { names, tax_level: tax_rank, selected_taxon: toApiFilter(selected_taxon), pathway_name, width, height })` and set `selected_pathway`.

Use `toApiFilter(selected_taxon)` for consistency with `pathway_list` fetch in the parent.

### 5.3 Styling

Restore upstream list layout: `svg` + `span.pathway-preview-item-name` below the pie. Remove the bordered flex text-box styling from `PathwayCard`.

Detail label colour (white on dark pies) is optional polish; not required for functional recovery.

## 6. Testing

| Layer | Test |
|-------|------|
| Server | Extend `parse_network` integration test: assert at least one node has `values.some(v => v.value > 0)` for Glycolysis + `test_rpkm_1.tsv` |
| Manual | Load test files → Chord → select superpathway → Network: list pies visible; click pathway → node pie wedges visible |

## 7. Out of Scope

- Analytics API / sidecar / `pathway_list` migration behaviour
- Batch preview endpoint (follow-up if N `counts` calls are too slow)
- `network_preview_data` store cleanup (orphaned but harmless)
- Sample-filtered vs reference-only pathway listing

## 8. Acceptance Criteria

- [ ] Network list grid shows a tax pie chart on each pathway card (Express legacy path).
- [ ] Clicking a pathway opens the detail graph with colored pie wedges on enzyme nodes that have matching EC data.
- [ ] Pies respect the active taxon filter (`selected_taxon`) and `tax_rank`.
- [ ] `npm test` passes, including new `parse_network` pie assertion.
