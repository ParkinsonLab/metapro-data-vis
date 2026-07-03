# Network Pie Chart Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore tax-distribution pie charts in the Network list grid and detail graph using Express handlers only.

**Architecture:** Fix `parse_network` to iterate `agg_by_ec` row output so node pies populate; replace `PathwayCard` with `PathwayPreview` that fetches `POST /api/viz/counts` per pathway into local state and renders d3 mini pies.

**Tech Stack:** Express (`data_functions.ts`), React + d3 (`Network.tsx`), Vitest (`data_functions.test.ts`)

**Spec:** `docs/superpowers/specs/2026-07-02-network-pie-recovery-design.md`

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/tests/data_functions.test.ts` | Modify | Add failing assertion for non-empty node pies |
| `src/server/data_functions.ts` | Modify | Fix `parse_network` agg row iteration |
| `src/renderer/src/components/Network.tsx` | Modify | `PathwayCard` → `PathwayPreview` with counts fetch + d3 pie |

---

### Task 1: Fix `parse_network` node pies (server)

**Files:**
- Modify: `src/server/data_functions.ts:306-330`
- Test: `src/tests/data_functions.test.ts:378-400`

- [ ] **Step 1: Add failing test assertion**

In `describe('parse_network (end-to-end, real DB+TSV)')` → first test (`returns nodes, edges, and colors…`), after the existing shape checks, add:

```typescript
const with_pie = out.nodes.filter((n) =>
  Array.isArray(n.values) && n.values.some((v) => v.value > 0)
)
expect(with_pie.length).toBeGreaterThan(0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- --run src/tests/data_functions.test.ts -t "returns nodes, edges, and colors"`

Expected: FAIL — `with_pie.length` is `0`

- [ ] **Step 3: Fix `parse_network` aggregation loop**

Replace the `if (has_value_cols) { … }` block body (lines ~306–330) with:

```typescript
  if (has_value_cols) {
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
  }
```

Delete the outdated comment about column-format `toJSON` output.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- --run src/tests/data_functions.test.ts -t "parse_network"`

Expected: PASS (both tests in the describe block)

- [ ] **Step 5: Smoke-test via curl**

With dev API running and test data loaded:

```bash
curl -s -X POST http://localhost:3001/api/data/test -H 'Content-Type: application/json' -d '{}'
curl -s -X POST http://localhost:3001/api/viz/network \
  -H 'Content-Type: application/json' \
  -d '{"names":["test_rpkm_1.tsv"],"tax_level":"phylum","selected_taxon":{},"pathway_name":"Glycolysis / Gluconeogenesis","width":900,"height":550}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); nodes=d['value']['nodes']; print('pies', sum(1 for n in nodes if any(v['value']>0 for v in n.get('values',[]))))"
```

Expected: `pies` > 0

- [ ] **Step 6: Commit**

```bash
git add src/server/data_functions.ts src/tests/data_functions.test.ts
git commit -m "fix(server): restore per-EC tax pies in parse_network"
```

---

### Task 2: Restore list-view preview pies (renderer)

**Files:**
- Modify: `src/renderer/src/components/Network.tsx:239-330`

- [ ] **Step 1: Add `get_color` helper and counts types at top of file**

After the `NetworkData` interface block, add:

```typescript
const get_color = (i: number, n: number): string =>
  `hsl(${Math.trunc((360 / (n + 1)) * i)} 75 50)`

interface CountsData {
  index: string[]
  counts: number[]
}
```

- [ ] **Step 2: Replace `PathwayCard` with `PathwayPreview`**

Remove `PathwayCard`. Add:

```typescript
const PathwayPreview = ({
  pathway,
  width,
  height
}: {
  pathway: string
  width: number
  height: number
}): React.JSX.Element => {
  const ref = useRef<SVGSVGElement>(null)
  const selected_file_list = useAppStore((state) => state.selected_file_list)
  const selected_taxon = useAppStore((state) => state.selected_taxon)
  const tax_rank = useAppStore((state) => state.tax_rank)

  const [counts_data, set_counts_data] = useState<CountsData | null>(null)

  const base_radius = Math.min(height, width) * 0.3
  const rad_step = Math.ceil(base_radius * 0.2)
  const text_height = 25

  useEffect(() => {
    if (selected_file_list.length === 0) return
    let cancelled = false
    ;(async () => {
      const res = await fetch('/api/viz/counts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          names: selected_file_list,
          tax_rank,
          selected_taxon: toApiFilter(selected_taxon),
          selected_ann_cat: { level: 'pathway', name: pathway }
        })
      })
      const envelope = (await res.json()) as { ok: boolean; value?: CountsData }
      if (!cancelled && envelope.ok && envelope.value) {
        set_counts_data(envelope.value)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [pathway, selected_file_list, tax_rank, selected_taxon])

  useEffect(() => {
    if (!counts_data || !ref.current) return
    const { index, counts } = counts_data
    const pie_data = index.map((id, i) => ({ id, value: counts[i] ?? 0 }))
    const colors = Object.fromEntries(index.map((id, i) => [id, get_color(i, index.length)]))

    const arc = d3.arc<d3.PieArcDatum<{ id: string; value: number }>>()
      .innerRadius(base_radius)
      .outerRadius(base_radius + rad_step)

    const svg = d3.select(ref.current)
    svg.selectAll('*').remove()
    svg
      .attr('width', width)
      .attr('height', height - text_height)
      .attr('viewBox', [-width / 2, -height / 2, width, height])

    const pie = d3.pie<{ id: string; value: number }>().value((d) => d.value)
    svg
      .append('g')
      .selectAll('path')
      .data(pie(pie_data))
      .join('path')
      .attr('fill', (d) => colors[d.data.id] ?? 'lightgray')
      .attr('d', arc)
      .attr('stroke', 'white')
      .append('title')
      .text((d) => d.data.id)
  }, [counts_data, width, height, base_radius, rad_step])

  const handle_click = (): void => {
    useAppStore.setState({ selected_pathway: pathway })
    request('network', {
      names: selected_file_list,
      tax_level: tax_rank,
      selected_taxon: toApiFilter(selected_taxon),
      pathway_name: pathway,
      width: 900,
      height: 550
    })
  }

  return (
    <div
      onClick={handle_click}
      className="pathway-preview-item"
      style={{ height, width, cursor: 'pointer' }}
      title={pathway}
    >
      <svg ref={ref} />
      <span className="pathway-preview-item-name">{pathway}</span>
    </div>
  )
}
```

- [ ] **Step 3: Update `PathwayList` to use `PathwayPreview`**

Change the map in `PathwayList`:

```typescript
{pathways.map((p) => (
  <PathwayPreview key={p} pathway={p} width={c_width} height={c_height} />
))}
```

- [ ] **Step 4: Run typecheck**

Run: `npm run typecheck:web`

Expected: PASS with no errors in `Network.tsx`

- [ ] **Step 5: Manual verification**

1. `npm run dev`
2. Load test files
3. Chord → click a superpathway arc
4. Network tab → each pathway card shows a colored pie + name
5. Click a pathway → detail graph shows pie wedges on enzyme nodes

- [ ] **Step 6: Commit**

```bash
git add src/renderer/src/components/Network.tsx
git commit -m "feat(network): restore pathway preview pies via counts API"
```

---

### Task 3: Final verification

- [ ] **Step 1: Run full test suite**

Run: `npm test`

Expected: all tests PASS

- [ ] **Step 2: Run typecheck**

Run: `npm run typecheck`

Expected: PASS
