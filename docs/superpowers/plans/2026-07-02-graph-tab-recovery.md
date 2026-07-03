# Graph Tab Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the Graph tab 3D scatter plot via Express `POST /api/viz/graph` and reactive renderer fetch.

**Architecture:** Port upstream `parse_data_callback` to server `parse_graph_data` (inner EC × taxon matrix); chord-aligned `parse_graph` orchestration; mount `Graph.tsx` with `graph_data` store key.

**Tech Stack:** Express (`parse.ts`, `data_functions.ts`), React + Plotly (`Graph.tsx`), Vitest

**Spec:** `docs/superpowers/specs/2026-07-02-graph-tab-recovery-design.md`

**Worktree:** `/Users/sibyl/study/metapro-data-vis/.worktrees/feature/graph-tab-recovery`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/server/utils.ts` | Modify | Export `get_sub_color` |
| `src/server/parse.ts` | Modify | `sort_by_category`, `make_inner_count_matrix`, `parse_graph_data` |
| `src/tests/parse.test.ts` | Create | Unit tests (ported from upstream) |
| `src/server/data_functions.ts` | Modify | `parse_graph` handler |
| `src/server/index.ts` | Modify | Register `/api/viz/graph` |
| `src/tests/data_functions.test.ts` | Modify | `parse_graph` integration tests |
| `src/renderer/src/api.ts` | Modify | `graph` channel |
| `src/renderer/src/store/AppStore.ts` | Modify | `graph_data` |
| `src/renderer/src/App.tsx` | Modify | Mount Graph, handler |
| `src/renderer/src/components/Graph.tsx` | Modify | `graph_data`, fetch, empty state |

---

### Task 1: `parse_graph_data` helpers + unit tests

**Files:**
- Modify: `src/server/utils.ts`
- Modify: `src/server/parse.ts`
- Create: `src/tests/parse.test.ts`

- [ ] **Step 1: Export `get_sub_color` in `utils.ts`**

Uncomment and export:

```typescript
const get_sub_color = (c: string, e: string) => c.replace(` ${base_lum})`, ` ${map_lum(e)})`)

export { map_lum, get_color, get_sub_color, sum, mean, key_cols, reduce_to_dict, empty_filter }
```

- [ ] **Step 2: Create failing `src/tests/parse.test.ts`**

```typescript
import { describe, it, expect } from 'vitest'
import {
  sort_by_category,
  make_inner_count_matrix,
  parse_graph_data
} from '../server/parse'

describe('sort_by_category', () => {
  it('sorts by category index first', () => {
    const getCatIdx = (x: string) => (x === 'a' ? 0 : x === 'b' ? 1 : 2)
    expect(sort_by_category('a', 'c', getCatIdx)).toBe(-1)
    expect(sort_by_category('c', 'a', getCatIdx)).toBe(1)
    expect(sort_by_category('b', 'a', getCatIdx)).toBe(1)
  })

  it('sorts alphabetically when same category', () => {
    const getCatIdx = () => 0
    expect(sort_by_category('apple', 'banana', getCatIdx)).toBe(-1)
    expect(sort_by_category('banana', 'apple', getCatIdx)).toBe(1)
    expect(sort_by_category('same', 'same', getCatIdx)).toBe(0)
  })
})

describe('make_inner_count_matrix', () => {
  it('builds symmetric count matrix using EC# directly', () => {
    const data = [
      { 'EC#': '1.1.1.1', GeneID: 'g1', Length: 100, Reads: 10, RPKM: 1, Species_A: 5, Species_B: 0 },
      { 'EC#': '2.2.2.2', GeneID: 'g2', Length: 200, Reads: 20, RPKM: 2, Species_A: 0, Species_B: 3 }
    ]
    const index = ['gap_1', '1.1.1.1', '2.2.2.2', 'gap_2', 'Species_A', 'Species_B', 'gap_3']
    const matrix = make_inner_count_matrix(data, index)
    const ec1 = index.indexOf('1.1.1.1')
    const ec2 = index.indexOf('2.2.2.2')
    const spA = index.indexOf('Species_A')
    const spB = index.indexOf('Species_B')
    expect(matrix[ec1][spA]).toBe(5)
    expect(matrix[spA][ec1]).toBe(5)
    expect(matrix[ec2][spB]).toBe(3)
    expect(matrix[spB][ec2]).toBe(3)
  })
})

describe('parse_graph_data', () => {
  it('returns inner/outer index, colors, and tax_map (no ann_map)', () => {
    const data = [
      { 'EC#': '1.1.1.1', GeneID: 'g1', Length: 100, Reads: 10, RPKM: 1, A: 1, B: 2 },
      { 'EC#': '2.2.2.2', GeneID: 'g2', Length: 200, Reads: 20, RPKM: 2, A: 0, B: 1 }
    ]
    const ec_map: Record<string, string[]> = {
      '1.1.1.1': ['P1'],
      '2.2.2.2': ['P2']
    }
    const tax_map: Record<string, string> = { A: 'T1', B: 'T1' }
    const result = parse_graph_data({ data, ec_map, tax_map })
    expect(result).toHaveProperty('inner_count_matrix')
    expect(result).toHaveProperty('inner_matrix_index')
    expect(result).toHaveProperty('outer_matrix_index')
    expect(result).not.toHaveProperty('outer_count_matrix')
    expect(result).not.toHaveProperty('ann_map')
    expect(result.tax_map).toEqual(tax_map)
    expect(result.outer_matrix_index).toContain('gap_1')
    expect(result.outer_matrix_index).toContain('gap_2')
    expect(result.outer_matrix_index).toContain('gap_3')
    expect(result.colors['P1']).toBeDefined()
    expect(result.colors['T1']).toBeDefined()
    expect(result.colors['1.1.1.1']).toBeDefined()
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm test -- --run src/tests/parse.test.ts`

Expected: FAIL — exports not found

- [ ] **Step 4: Implement helpers in `parse.ts`**

Add imports: `import { get_color, get_sub_color, key_cols, sum } from './utils'`

Add before `parse_ec_data`:

```typescript
const sort_by_category = (
  a: string,
  b: string,
  get_cat_idx: (name: string) => number
): number => {
  const m_a = get_cat_idx(a)
  const m_b = get_cat_idx(b)
  const v_a = m_a === m_b ? a : m_a
  const v_b = m_a === m_b ? b : m_b
  if (v_a < v_b) return -1
  if (v_a > v_b) return 1
  return 0
}

const make_inner_count_matrix = (
  data: Array<object>,
  matrix_index: string[]
): number[][] => {
  const add_to_count_map = (
    acc: number[][],
    species: string,
    annotation: string,
    value: number
  ): void => {
    const species_index = matrix_index.indexOf(species)
    const annotation_index = matrix_index.indexOf(annotation)
    if (species_index >= 0 && annotation_index >= 0) {
      acc[species_index][annotation_index] += Number(value)
      acc[annotation_index][species_index] += Number(value)
    }
  }

  const rows = data as Array<Record<string, string | number>>
  const val_cols = Object.keys(rows[0]).filter((e) => !key_cols.includes(e))
  return rows.reduce(
    (acc: number[][], row) => {
      const ec_key = String(row['EC#'])
      for (const key of val_cols) {
        const val = Number(row[key])
        if (val > 0) add_to_count_map(acc, key, ec_key, val)
      }
      return acc
    },
    Array.from({ length: matrix_index.length }, () =>
      Array(matrix_index.length).fill(0)
    )
  )
}

const primary_ann_cat = (ec_map: Record<string, string[]>, ec: string): string =>
  ec_map[ec]?.[0] ?? ''

const parse_graph_data = ({
  data,
  ec_map,
  tax_map
}: {
  data: Array<object>
  ec_map: Record<string, string[]>
  tax_map: Record<string, string>
}) => {
  const tax_cats = _.uniq(_.sortBy(Object.values(tax_map)))
  const all_taxa = _.uniq(Object.keys(tax_map)).sort((a, b) =>
    sort_by_category(a, b, (name) => tax_cats.indexOf(tax_map[name]))
  )

  const annotation_cats = _.sortBy(
    _.uniq(Object.values(ec_map).reduce((acc, vals) => [...acc, ...vals], [] as string[]))
  )
  const all_annotations = _.uniq(Object.keys(ec_map)).sort((a, b) =>
    sort_by_category(a, b, (name) => annotation_cats.indexOf(primary_ann_cat(ec_map, name)))
  )

  const outer_matrix_index = ['gap_1', ...annotation_cats, 'gap_2', ...tax_cats, 'gap_3']

  const inner_matrix_index = ['gap_1', ...all_annotations, 'gap_2', ...all_taxa, 'gap_3']
  const inner_count_matrix = make_inner_count_matrix(data, inner_matrix_index)

  const idx_to_keep = inner_count_matrix.reduce((acc: number[], row, i) => {
    if (sum(row) > 0) acc.push(i)
    return acc
  }, [])
  const trimmed_inner_count_matrix = idx_to_keep.map((i) =>
    idx_to_keep.map((j) => inner_count_matrix[i][j])
  )
  const trimmed_inner_matrix_idx = idx_to_keep.map((i) => inner_matrix_index[i])

  const cat_colors = Object.fromEntries([
    ...annotation_cats.map((e, i, arr) => [e, get_color(i, arr.length)]),
    ...tax_cats.map((e, i, arr) => [e, get_color(i, arr.length)])
  ])
  const sub_colors = Object.fromEntries([
    ...all_annotations.map((e) => [
      e,
      get_sub_color(cat_colors[primary_ann_cat(ec_map, e)], e)
    ]),
    ...all_taxa.map((e) => [e, get_sub_color(cat_colors[tax_map[e]], e)])
  ])
  const colors = { ...sub_colors, ...cat_colors }

  return {
    inner_count_matrix: trimmed_inner_count_matrix,
    inner_matrix_index: trimmed_inner_matrix_idx,
    outer_matrix_index,
    colors,
    tax_map
  }
}
```

Update export line:

```typescript
export {
  parse_ec_data,
  parse_graph_data,
  make_inner_count_matrix,
  sort_by_category,
  make_count_vector,
  make_ann_vector,
  parse_tax_tree
}
```

- [ ] **Step 5: Run tests**

Run: `npm test -- --run src/tests/parse.test.ts`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/server/utils.ts src/server/parse.ts src/tests/parse.test.ts
git commit -m "feat(server): add parse_graph_data matrix builders"
```

---

### Task 2: `parse_graph` handler + route + integration tests

**Files:**
- Modify: `src/server/data_functions.ts`
- Modify: `src/server/index.ts`
- Modify: `src/tests/data_functions.test.ts`

- [ ] **Step 1: Add failing integration test**

In `data_functions.test.ts`, add import `parse_graph` and after `parse_ec_chord` describe block:

```typescript
  describe('parse_graph (end-to-end)', () => {
    it('returns graph_data shape with non-empty inner matrix on fixtures', () => {
      const out = parse_graph({
        names: [loaded_names[0]],
        tax_level: 'phylum',
        ann_level: 'superpathway',
        selected_ann_cat: empty_filter,
        selected_taxon: empty_filter
      })
      expect(out.inner_matrix_index[0]).toBe('gap_1')
      expect(out.inner_matrix_index).toContain('gap_2')
      expect(out.inner_matrix_index[out.inner_matrix_index.length - 1]).toBe('gap_3')
      expect(out.outer_matrix_index).toContain('gap_2')
      const gap1 = out.inner_matrix_index.indexOf('gap_1')
      const gap2 = out.inner_matrix_index.indexOf('gap_2')
      const ec_labels = out.inner_matrix_index.slice(gap1 + 1, gap2)
      expect(ec_labels.length).toBeGreaterThan(0)
      const flat = out.inner_count_matrix.flat()
      expect(flat.some((v) => v > 0)).toBe(true)
      expect(Object.keys(out.colors).length).toBeGreaterThan(0)
      expect(out).not.toHaveProperty('ann_map')
    }, 180_000)

    it('narrows matrix when selected_ann_cat filter is active', () => {
      const ec = __test__.getEc() as Array<Record<string, unknown>>
      const sp = ec.find((r) => r.superpathway != null)?.superpathway as string
      expect(sp).toBeTruthy()
      const unfiltered = parse_graph({
        names: [loaded_names[0]],
        tax_level: 'phylum',
        ann_level: 'superpathway',
        selected_ann_cat: empty_filter,
        selected_taxon: empty_filter
      })
      const filtered = parse_graph({
        names: [loaded_names[0]],
        tax_level: 'phylum',
        ann_level: 'superpathway',
        selected_ann_cat: { level: 'superpathway', name: sp },
        selected_taxon: empty_filter
      })
      expect(filtered.inner_matrix_index.length).toBeLessThanOrEqual(
        unfiltered.inner_matrix_index.length
      )
    }, 180_000)
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run src/tests/data_functions.test.ts -t "parse_graph"`

Expected: FAIL — `parse_graph` not exported

- [ ] **Step 3: Implement `parse_graph` in `data_functions.ts`**

Add import: `import { parse_ec_data, parse_graph_data, ... } from './parse'`

After `parse_ec_chord`:

```typescript
const parse_graph = ({
  names,
  tax_level,
  ann_level,
  selected_ann_cat,
  selected_taxon
}: {
  names: string[]
  tax_level: string
  ann_level: string
  selected_ann_cat: { level: string; name: string }
  selected_taxon: { level: string; name: string }
}) => {
  const raw_data = names_to_data(names)
  const filtered = subset_data_by_ann(
    subset_data(raw_data, selected_taxon),
    selected_ann_cat
  )
  const agg_data = agg_by_ec(filtered)
  const ec_map = get_ec_map(selected_ann_cat, ann_level)
  const tax_map = get_tax_map(agg_data, tax_level)
  return parse_graph_data({ data: agg_data, ec_map, tax_map })
}
```

Add `parse_graph` to module exports at bottom.

- [ ] **Step 4: Register route in `index.ts`**

Import `parse_graph` from `./data_functions`.

Add to `vizRoutes`:

```typescript
{ path: '/api/viz/graph', handler: parse_graph },
```

- [ ] **Step 5: Run tests**

Run: `npm test -- --run src/tests/data_functions.test.ts -t "parse_graph"`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/server/data_functions.ts src/server/index.ts src/tests/data_functions.test.ts
git commit -m "feat(server): add parse_graph endpoint for Graph tab data"
```

---

### Task 3: Renderer — graph channel + mount Graph tab

**Files:**
- Modify: `src/renderer/src/api.ts`
- Modify: `src/renderer/src/store/AppStore.ts`
- Modify: `src/renderer/src/App.tsx`
- Modify: `src/renderer/src/components/Graph.tsx`

- [ ] **Step 1: Add `graph` channel in `api.ts`**

Add to `Channel` type: `| 'graph'`

Add to `endpointFor` map:

```typescript
graph: { method: 'POST', url: '/api/viz/graph' },
```

- [ ] **Step 2: Add `graph_data` to `AppStore.ts`**

In interface:

```typescript
graph_data: any
```

In initial state:

```typescript
graph_data: {},
```

Remove `parsed_data` optional field and its deprecation comment if still present.

- [ ] **Step 3: Wire `App.tsx`**

Import Graph. Add handler:

```typescript
graph: (value) => {
  useAppStore.setState({ graph_data: value })
},
```

Uncomment mount:

```typescript
{mainState === 'graph' && <Graph />}
```

- [ ] **Step 4: Update `Graph.tsx`**

- Import `request` from `../api` and `toApiFilter` from `../chordFilters`
- Replace `parsed_data` with `graph_data` from store
- Add store selectors: `selected_file_list`, `tax_rank`, `ann_rank`, `selected_ann_cat`, `selected_taxon`
- Add reactive fetch `useEffect` (mirror Chord deps) calling `request('graph', { ... })`
- Update plot `useEffect` deps to `[graph_data, selected_annotations]`
- Guard plot effect: return early if `!graph_data || _.isEmpty(graph_data)`
- Remove unused destructuring of `outer_count_matrix` and `ann_map`
- Empty state when `selected_annotations.length === 0`:

```tsx
if (selected_annotations.length === 0) {
  return (
    <div id="graph-container">
      <p>Select ECs in the Network view to plot RPKM.</p>
    </div>
  )
}
```

- [ ] **Step 5: Typecheck**

Run: `npm run typecheck:web`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/renderer/src/api.ts src/renderer/src/store/AppStore.ts src/renderer/src/App.tsx src/renderer/src/components/Graph.tsx
git commit -m "feat(graph): restore Graph tab with reactive graph_data fetch"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full test suite**

Run: `npm test`

Expected: all PASS

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck`

Expected: PASS

- [ ] **Step 3: Manual smoke test**

1. `npm run dev`
2. Load test files
3. Chord → optional superpathway filter
4. Network → pathway → click EC nodes
5. Graph tab → 3D plot visible; empty state before EC selection
