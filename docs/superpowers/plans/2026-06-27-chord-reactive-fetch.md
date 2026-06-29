# Chord Reactive Fetch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refetch `POST /api/viz/chord` whenever rank, level, or drill-down filters change; redraw the diagram from `chord_data` only; normalize filter state on the frontend.

**Architecture:** Shared `chordFilters.ts` helpers define canonical `{ level, name } | {}` shapes. `Chord` parent owns a reactive fetch `useEffect` (mirrors `Krona.tsx`). `ChordSVG` draws via `useCallback(..., [chord_data])` reading filters from `useAppStore.getState()` at draw time. Filter chips live in the Chord top bar.

**Tech Stack:** React 19, Zustand, Vitest (unit tests for pure helpers), existing Express/FastAPI chord API

**Worktree:** `.worktrees/chord-dbt-api/` on branch `feature/chord-dbt-api`

**Spec:** `docs/superpowers/specs/2026-06-27-chord-reactive-fetch-design.md`

---

## File Map

```
src/renderer/src/
├── chordFilters.ts              # CREATE: types, isFilterActive, toApiFilter, filterName
├── store/AppStore.ts            # MODIFY: tighten selected_ann_cat type
├── components/
│   ├── Chord.tsx                # MODIFY: fetch effect, draw_chord refactor, filter chips
│   ├── Upload.tsx               # MODIFY: remove chord request
│   └── Network.tsx              # MODIFY: use isFilterActive + filterName
└── App.css                      # MODIFY: filter chip styles; drop reset-button layout deps

src/tests/
└── chord_filters.test.ts        # CREATE: unit tests for chordFilters helpers
```

---

### Task 1: `chordFilters` helpers

**Files:**
- Create: `src/renderer/src/chordFilters.ts`
- Create: `src/tests/chord_filters.test.ts`

- [ ] **Step 1: Write the failing tests**

```typescript
// src/tests/chord_filters.test.ts
import { describe, it, expect } from 'vitest'
import {
  isFilterActive,
  toApiFilter,
  filterName,
  type ChordFilter
} from '@renderer/chordFilters'

describe('isFilterActive', () => {
  it('returns false for empty object', () => {
    expect(isFilterActive({})).toBe(false)
  })

  it('returns false when level or name missing', () => {
    expect(isFilterActive({ level: 'phylum', name: '' })).toBe(false)
    expect(isFilterActive({ level: '', name: 'Firmicutes' })).toBe(false)
  })

  it('returns true for populated filter', () => {
    const f: ChordFilter = { level: 'superpathway', name: 'Glycolysis' }
    expect(isFilterActive(f)).toBe(true)
  })
})

describe('toApiFilter', () => {
  it('returns {} when inactive', () => {
    expect(toApiFilter({})).toEqual({})
    expect(toApiFilter({ level: '', name: '' })).toEqual({})
  })

  it('returns filter when active', () => {
    const f: ChordFilter = { level: 'phylum', name: 'Firmicutes' }
    expect(toApiFilter(f)).toEqual(f)
  })
})

describe('filterName', () => {
  it('returns empty string when inactive', () => {
    expect(filterName({})).toBe('')
  })

  it('returns name when active', () => {
    expect(filterName({ level: 'superpathway', name: 'Glycolysis' })).toBe('Glycolysis')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/tests/chord_filters.test.ts`
Expected: FAIL — module `@renderer/chordFilters` not found

- [ ] **Step 3: Implement helpers**

```typescript
// src/renderer/src/chordFilters.ts
export type ChordFilter = { level: string; name: string }
export type EmptyChordFilter = Record<string, never>

export type ChordFilterValue = ChordFilter | EmptyChordFilter

export const isFilterActive = (f: ChordFilterValue): f is ChordFilter =>
  Boolean(f.level?.trim() && f.name?.trim())

export const toApiFilter = (f: ChordFilterValue): ChordFilter | EmptyChordFilter =>
  isFilterActive(f) ? f : {}

export const filterName = (f: ChordFilterValue): string =>
  isFilterActive(f) ? f.name : ''
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/tests/chord_filters.test.ts`
Expected: PASS (3 test suites, all green)

- [ ] **Step 5: Commit**

```bash
git add src/renderer/src/chordFilters.ts src/tests/chord_filters.test.ts
git commit -m "feat(chord): add canonical filter helpers with unit tests"
```

---

### Task 2: Tighten `AppStore` types

**Files:**
- Modify: `src/renderer/src/store/AppStore.ts`

- [ ] **Step 1: Import types and update interface**

At top of `AppStore.ts`:

```typescript
import type { ChordFilterValue } from '../chordFilters'
```

Replace:

```typescript
selected_ann_cat: object | string
selected_taxon: object // {level: string, name: string}
```

With:

```typescript
selected_ann_cat: ChordFilterValue
selected_taxon: ChordFilterValue
```

Defaults stay `{}` for both (lines 41–42).

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck:web`
Expected: May report errors in `Chord.tsx` / `Network.tsx` — fixed in Tasks 3–5. No new errors in unrelated files.

- [ ] **Step 3: Commit**

```bash
git add src/renderer/src/store/AppStore.ts
git commit -m "refactor(store): use ChordFilterValue for drill-down filters"
```

---

### Task 3: Simplify Upload

**Files:**
- Modify: `src/renderer/src/components/Upload.tsx`

- [ ] **Step 1: Remove chord fetch from `DataSelector`**

Remove `default_settings` object entirely.

Remove `request` import if no longer used (`load` and `load_test` still need it).

Replace `handleUpdate`:

```typescript
const handleUpdate = () => {
  const names = [f1, f2].filter((e) => e)
  useAppStore.setState({ selected_file_list: names })
}
```

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck:web`
Expected: PASS (or only pre-existing Chord/Network issues)

- [ ] **Step 3: Commit**

```bash
git add src/renderer/src/components/Upload.tsx
git commit -m "refactor(upload): delegate chord fetch to Chord pane effect"
```

---

### Task 4: Reactive fetch + filter chips in `Chord.tsx`

**Files:**
- Modify: `src/renderer/src/components/Chord.tsx`
- Modify: `src/renderer/src/App.css`

- [ ] **Step 1: Add imports and `FilterChips` component**

Add imports:

```typescript
import { useCallback } from 'react'
import { request } from '../api'
import {
  isFilterActive,
  toApiFilter,
  type ChordFilterValue
} from '../chordFilters'
```

Remove FontAwesome imports (`faArrowRotateLeft`, `FontAwesomeIcon`) — reset buttons removed.

Add `FilterChips` below `RankSelector`:

```typescript
const FilterChips = (): React.JSX.Element | null => {
  const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
  const selected_taxon = useAppStore((state) => state.selected_taxon)
  const ann_active = isFilterActive(selected_ann_cat)
  const tax_active = isFilterActive(selected_taxon)

  if (!ann_active && !tax_active) return null

  return (
    <div id="chord-filter-chips">
      {ann_active && (
        <span className="chord-filter-chip">
          Pathway: {selected_ann_cat.name} ({selected_ann_cat.level})
          <button
            type="button"
            aria-label="Clear pathway filter"
            onClick={() => useAppStore.setState({ selected_ann_cat: {}, selected_annotations: [] })}
          >
            ×
          </button>
        </span>
      )}
      {tax_active && (
        <span className="chord-filter-chip">
          Taxon: {selected_taxon.name} ({selected_taxon.level})
          <button
            type="button"
            aria-label="Clear taxon filter"
            onClick={() => useAppStore.setState({ selected_taxon: {} })}
          >
            ×
          </button>
        </span>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add fetch effect to `Chord` parent**

Replace the current `Chord` component body (remove `reset_taxon` / `reset_ann`):

```typescript
const Chord = (): React.JSX.Element => {
  const selected_file_list = useAppStore((state) => state.selected_file_list)
  const tax_rank = useAppStore((state) => state.tax_rank)
  const ann_rank = useAppStore((state) => state.ann_rank)
  const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
  const selected_taxon = useAppStore((state) => state.selected_taxon)

  useEffect(() => {
    if (selected_file_list.length === 0) return
    request('chord', {
      names: selected_file_list,
      tax_level: tax_rank,
      ann_level: ann_rank,
      selected_ann_cat: toApiFilter(selected_ann_cat),
      selected_taxon: toApiFilter(selected_taxon)
    })
  }, [selected_file_list, tax_rank, ann_rank, selected_ann_cat, selected_taxon])

  return (
    <div id="chord-container">
      <RankSelector />
      <FilterChips />
      <div id="chord-inner-container">
        <ChordSVG />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Add CSS for filter chips**

In `App.css`, after `#chord-top-bar` rules, add:

```css
    #chord-filter-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        justify-content: center;
        margin: 6px 0;
    }
    .chord-filter-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 2px 8px;
        border: 1px solid #666;
        border-radius: 4px;
        font-size: 12px;
    }
    .chord-filter-chip button {
        border: 0;
        background: inherit;
        cursor: pointer;
        font-size: 14px;
        line-height: 1;
        padding: 0 2px;
    }
```

Update `#chord-inner-container` — remove flex row alignment for side buttons (optional cleanup; can leave as-is).

- [ ] **Step 4: Commit fetch + chips (ChordSVG refactor follows in Task 5)**

```bash
git add src/renderer/src/components/Chord.tsx src/renderer/src/App.css
git commit -m "feat(chord): reactive API fetch and filter chips in top bar"
```

---

### Task 5: Refactor `ChordSVG` — `useCallback` + `getState()`

**Files:**
- Modify: `src/renderer/src/components/Chord.tsx` (`ChordSVG` only)

- [ ] **Step 1: Remove render-scoped filter subscriptions from `ChordSVG`**

Delete these lines from `ChordSVG`:

```typescript
const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
const selected_taxon = useAppStore((state) => state.selected_taxon)
const tax_rank = useAppStore((state) => state.tax_rank)
```

Keep only:

```typescript
const chord_data = useAppStore((state) => state.chord_data)
```

Rename `parsed_data` → `chord_data` throughout `ChordSVG`.

- [ ] **Step 2: Wrap `draw_chord` in `useCallback` with `getState()`**

Replace the plain `draw_chord` function and effect with:

```typescript
const draw_chord = useCallback(() => {
  const { count_matrix, index, colors } = chord_data

  if (!Array.isArray(index) || !Array.isArray(count_matrix)) {
    console.error('[Chord] expected chord_data { count_matrix, index, colors }', chord_data)
    return
  }

  const { selected_ann_cat, selected_taxon, tax_rank, ann_rank } = useAppStore.getState()
  const ann_name = isFilterActive(selected_ann_cat) ? selected_ann_cat.name : ''
  const tax_name = isFilterActive(selected_taxon) ? selected_taxon.name : ''

  const gaps = ['gap_1', 'gap_2', 'gap_3']
  const outer_gap_idc = gaps.map((e) => index.indexOf(e))

  const handle_arc_click = (_event, d) => {
    const selected_name = String(index[d.index] ?? '')
    if (selected_name.substring(0, 3) === 'gap') return

    const state = useAppStore.getState()

    if (
      d.index > outer_gap_idc[0] &&
      d.index < outer_gap_idc[1] &&
      selected_name !== (isFilterActive(state.selected_ann_cat) ? state.selected_ann_cat.name : '')
    ) {
      useAppStore.setState({
        selected_ann_cat: { level: state.ann_rank, name: selected_name },
        selected_annotations: []
      })
    } else if (
      d.index > outer_gap_idc[1] &&
      d.index < outer_gap_idc[2] &&
      selected_name !== (isFilterActive(state.selected_taxon) ? state.selected_taxon.name : '')
    ) {
      const next_rank =
        state.tax_rank === t_ranks[t_ranks.length - 1]
          ? state.tax_rank
          : (t_ranks[t_ranks.indexOf(state.tax_rank) + 1] as typeof state.tax_rank)
      useAppStore.setState({
        selected_taxon: { level: state.tax_rank, name: selected_name },
        tax_rank: next_rank
      })
    }
  }

  // ... rest of d3 draw unchanged, except stroke line becomes:
  // .attr('stroke', (d) => (index[d.index] === ann_name ? 'blue' : 'black'))
}, [chord_data])

useEffect(() => {
  if (chord_data !== null && !_.isEmpty(chord_data)) {
    draw_chord()
  }
}, [chord_data, draw_chord])
```

Remove `console.log(parsed_data)` from the effect.

- [ ] **Step 3: Run typecheck**

Run: `npm run typecheck:web`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/components/Chord.tsx
git commit -m "refactor(chord): draw via useCallback + getState on chord_data only"
```

---

### Task 6: Update `Network.tsx` filter read

**Files:**
- Modify: `src/renderer/src/components/Network.tsx`

- [ ] **Step 1: Replace string-branch normalization**

Add import:

```typescript
import { filterName } from '../chordFilters'
```

Replace lines 337–347:

```typescript
const selected_ann_cat = useAppStore((state) => state.selected_ann_cat)
```

And:

```typescript
const superpathway_name = filterName(selected_ann_cat)
```

Remove the `as string | { level?: string; name?: string }` cast and the comment about two shapes.

- [ ] **Step 2: Run typecheck + tests**

Run: `npm run typecheck:web && npm test`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/renderer/src/components/Network.tsx
git commit -m "refactor(network): read ann filter via filterName helper"
```

---

### Task 7: Manual verification

**Files:** none

- [ ] **Step 1: Start dev stack**

Ensure FastAPI chord sidecar and Express are running (see spec §8 in `2026-06-22-chord-dbt-api-design.md`):

```bash
# Terminal 1
cd analytics && uv run uvicorn api.main:app --port 8001 --reload

# Terminal 2 (worktree root)
npm run dev
```

- [ ] **Step 2: Run manual test checklist**

From spec §8.1:

1. Load test files → Chord tab → chart loads without Upload "Update"
2. Change tax rank → spinner → chart labels re-aggregate
3. Toggle pathway / superpathway → chart re-aggregates
4. Click ann arc → chip appears → chart narrows
5. Click tax arc → chip appears + rank drills → chart narrows
6. Change rank with active filter → chip preserved → chart refetches filtered
7. Clear chip → chart widens
8. Network tab reads superpathway from normalized ann filter after chord arc click

- [ ] **Step 3: Final commit if spec tweak needed**

Only if manual testing surfaced doc updates; otherwise skip.

---

## Spec Coverage Checklist

| Spec section | Task |
|---|---|
| §3 State normalization | Task 1, 2, 5 (arc click writes `{ level, name }`) |
| §4 Reactive fetch | Task 3, 4 |
| §5 `useCallback` + `getState()` | Task 5 |
| §6 Filter UI (Chord tab) | Task 4 |
| §7 File changes | All tasks |
| §8 Manual tests | Task 7 |
| §9 Success criteria | Task 7 |

## Out of Scope (per spec §10)

- Cross-tab filter visibility bar
- Krona sharing `selected_taxon`
- Backend normaliser removal
- Automated frontend component tests
