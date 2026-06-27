# Chord Reactive Fetch — Design Spec

> **Status:** Approved (2026-06-27)  
> **Goal:** When taxonomy rank, pathway level, or drill-down filters change in the Chord UI, refetch from `POST /api/viz/chord` and redraw the diagram from the response. Normalize filter state on the frontend; do not rely on backend normalisers to patch inconsistent shapes.

**Parent spec:** `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` (DuckDB chord backend — §10 noted frontend re-fetch as follow-up).

**Work isolation:** Branch `feature/chord-dbt-api` in worktree `.worktrees/chord-dbt-api/`.

## 1. Context

The DuckDB chord API accepts `tax_level`, `ann_level`, `selected_ann_cat`, and `selected_taxon` and returns `{ count_matrix, index, colors }`. The backend is ready for runtime rank/level/filter changes without a dbt rebuild.

The frontend has a gap: the chord API is called **once** from `Upload.handleUpdate` with hardcoded defaults. `RankSelector`, arc clicks, and reset buttons update Zustand store only — no refetch. `Krona.tsx` already demonstrates the target pattern (`useEffect` → `request(...)` on store deps).

### Gap summary

| Trigger | Updates store? | Calls chord API? |
|---|---|---|
| Upload "Update" | `selected_file_list` | Yes (hardcoded ranks/filters) |
| Tax / ann rank selector | `tax_rank` / `ann_rank` | No |
| Ann / tax arc click | `selected_ann_cat` / `selected_taxon` (+ `tax_rank` drill) | No |
| Reset buttons | Clears filters | No |
| Navigate to Chord tab | — | No |
| Load test files | `selected_file_list` | No |

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Fetch owner | `Chord.tsx` reactive `useEffect` | Matches Krona / Overview pane pattern (Approach A) |
| Filter preservation | Preserve `selected_ann_cat` and `selected_taxon` on rank/level change | User drill-down intent persists; empty matrix is acceptable |
| Filter UI placement | Chord tab only (v1) | Cross-tab workflow bar deferred to a separate task |
| Frontend filter shape | Always `{}` or `{ level, name }` | Canonical types; backend normaliser is compat only, not a crutch |
| Upload role | Sets `selected_file_list` only | Chord effect owns all chord fetches |
| ChordSVG redraw trigger | `chord_data` only | Avoid highlighting stale matrix before API response |
| Loading UX | Existing global `isLoading` + `LoadingLayer` | Already set by `request()` in `api.ts` |
| Automated frontend tests | Out of scope (v1) | Manual test plan; harness notes in §8 for future |

## 3. State Normalization

### 3.1 Canonical types

Add a shared type (in `AppStore.ts` or `src/renderer/src/chordFilters.ts`):

```typescript
export type ChordFilter = { level: string; name: string }
export type EmptyChordFilter = Record<string, never> // {}
```

| Store field | Empty | Active |
|---|---|---|
| `selected_ann_cat` | `{}` | `{ level: ann_rank, name: string }` |
| `selected_taxon` | `{}` | `{ level: string, name: string }` |

### 3.2 Helpers

```typescript
export const isFilterActive = (f: ChordFilter | EmptyChordFilter): f is ChordFilter =>
  Boolean(f.level?.trim() && f.name?.trim())

export const toApiFilter = (f: ChordFilter | EmptyChordFilter): ChordFilter | EmptyChordFilter =>
  isFilterActive(f) ? f : {}
```

### 3.3 Write sites

| Action | Before | After |
|---|---|---|
| Ann arc click | bare `string` | `{ level: ann_rank, name: clicked_label }` |
| Tax arc click | `{ level: tax_rank, name }` | unchanged |
| Reset ann | `''` | `{}` |
| Reset taxon | `{}` | `{}` (unchanged) |
| `AppStore` type | `object \| string` | `ChordFilter \| EmptyChordFilter` |

### 3.4 Read sites to update

- **`Chord.tsx`** — arc click guard, blue stroke highlight (compare `.name`), filter chips
- **`Network.tsx`** — remove string-branch normalization; read `selected_ann_cat.name` when `isFilterActive`

## 4. Reactive Fetch

### 4.1 Chord `useEffect`

In `Chord` (parent of `ChordSVG`), mirror `Krona.tsx`:

```typescript
useEffect(() => {
  if (selected_file_list.length === 0) return
  request('chord', {
    names: selected_file_list,
    tax_level: tax_rank,
    ann_level: ann_rank,
    selected_ann_cat: toApiFilter(selected_ann_cat),
    selected_taxon: toApiFilter(selected_taxon),
  })
}, [selected_file_list, tax_rank, ann_rank, selected_ann_cat, selected_taxon])
```

**Dependencies:** all five store fields that map to API params. Any change refetches.

**Guard:** skip when `selected_file_list.length === 0`.

### 4.2 Upload simplification

`Upload.handleUpdate` removes `request('chord', …)` and hardcoded `default_settings`. It only:

```typescript
useAppStore.setState({ selected_file_list: names })
```

Selecting files + navigating to Chord (or already being on Chord) triggers fetch via the effect. `load_test` → Chord tab works without an extra Upload click.

### 4.3 Response handling

Unchanged: `App.tsx` channel handler sets `chord_data` from envelope. Global `isLoading` covers the wait.

## 5. ChordSVG Redraw & `draw_chord`

### 5.1 Principle

Do **not** put `selected_ann_cat` / `selected_taxon` in the redraw effect deps. Redrawing the old matrix with new highlight strokes before the API responds is misleading.

**Redraw effect deps:** `[chord_data]` only.

### 5.2 `draw_chord` and `useCallback`

Use `useCallback` for `draw_chord` with dependency **`[chord_data]`** only. Read filter values for highlight strokes via **`useAppStore.getState()`** inside the callback at draw time — not from a stale render closure and not as `useCallback` deps:

```typescript
const draw_chord = useCallback(() => {
  const { selected_ann_cat, selected_taxon, tax_rank } = useAppStore.getState()
  // ... d3 draw using chord_data + filters for stroke highlight and arc click handlers
}, [chord_data])

useEffect(() => {
  if (chord_data != null && !_.isEmpty(chord_data)) {
    draw_chord()
  }
}, [chord_data, draw_chord])
```

**Why `getState()` inside the callback:** When `chord_data` updates after a filter change, the same render produces a new `draw_chord` (because `chord_data` changed). `getState()` ensures highlight strokes reflect the filters that triggered that fetch, even if React batching reorders updates.

**Why not filter deps on `useCallback`:** That would recreate `draw_chord` on every filter click and, if wired to the effect, redraw the stale matrix immediately.

**Locked in (2026-06-27):** `useCallback` + `getState()` — satisfies exhaustive-deps and avoids premature redraw simultaneously.

### 5.3 Arc click handler

`handle_arc_click` inside `draw_chord` attaches per draw. It continues to `setState` filters (and drill `tax_rank` on tax side). Store update → fetch effect → new `chord_data` → redraw. No direct `request()` in click handlers.

## 6. Filter UI (Chord tab only)

Replace flanking rotate-left reset buttons with filter chips in `#chord-top-bar` (below rank selectors):

```
[kingdom phylum class ...]  [pathway superpathway]
Pathway: Glycolysis (superpathway) ×    Taxon: Firmicutes (phylum) ×
```

- Render a chip only when `isFilterActive(filter)`
- Label: `{name} ({level})`
- `×` sets that filter to `{}` (triggers refetch via §4.1)
- Remove `#chord-inner-container` reset buttons

**Deferred:** Global workflow context bar visible on Network / Graph tabs (§10).

## 7. File Changes

| File | Change |
|---|---|
| `src/renderer/src/chordFilters.ts` | New: types, `isFilterActive`, `toApiFilter` |
| `src/renderer/src/store/AppStore.ts` | Tighten `selected_ann_cat` type |
| `src/renderer/src/components/Chord.tsx` | Reactive fetch, filter chips, normalized arc clicks, `draw_chord` refactor |
| `src/renderer/src/components/Upload.tsx` | Remove chord request; set `selected_file_list` only |
| `src/renderer/src/components/Network.tsx` | Simplify `selected_ann_cat` read |

No backend changes in v1.

## 8. Testing

### 8.1 Manual test plan (v1)

- [ ] Load test files → Chord tab → chart loads without Upload "Update"
- [ ] Change tax rank → spinner → chart labels re-aggregate
- [ ] Toggle pathway / superpathway → chart re-aggregates
- [ ] Click ann arc → chip appears → chart narrows
- [ ] Click tax arc → chip appears + rank drills → chart narrows
- [ ] Change rank with active filter → chip preserved → chart refetches filtered
- [ ] Clear chip → chart widens
- [ ] Network tab still reads `selected_ann_cat.name` after normalization

### 8.2 Future automated frontend harness (not v1)

Existing stack: Vitest for server only. Would additionally need:

- DOM environment (`jsdom` or `happy-dom`) in Vitest config
- `@testing-library/react` + `@testing-library/user-event`
- Vitest alias resolution matching `tsconfig.web.json` (`@renderer/...`)
- `fetch` stub or MSW for chord envelope fixtures
- Zustand store reset between tests
- SVG/D3 assertions via DOM queries (path counts, label text)

E2E (Playwright against `npm run dev`) is a separate investment.

## 9. Success Criteria

- [ ] Rank selector changes trigger chord API call and chart update
- [ ] Ann level changes trigger chord API call and chart update
- [ ] Arc drill-down and reset trigger refetch; filters sent as `{ level, name }` or `{}`
- [ ] Filters preserved across rank/level changes
- [ ] Filter chips visible on Chord tab with clear affordance
- [ ] ChordSVG does not redraw on filter-only store changes before `chord_data` updates
- [ ] Upload no longer duplicates chord fetch logic

## 10. Future Considerations

- **Cross-tab filter visibility:** Workflow context bar in `App.tsx` (evolve `DataInfoBar`) visible on Chord / Network / Graph when filters active — separate spec
- **Krona sharing `selected_taxon`:** Krona currently passes `selected_taxon: {}` always
- **Backend normaliser removal:** Once frontend is canonical, simplify `filters.py` in a later cleanup
- **Request deduplication / abort:** Guard against stale responses if user clicks rapidly (out of scope v1)
- **Chord-specific loading state:** Global `isLoading` may flash for unrelated requests (pre-existing)

## 11. References

- `src/renderer/src/components/Krona.tsx` — reactive fetch pattern
- `src/renderer/src/components/Upload.tsx` — current sole chord caller (to remove)
- `src/renderer/src/api.ts` — `request()`, `isLoading`
- `analytics/api/filters.py` — backend normaliser (compat reference)
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — API contract §4
