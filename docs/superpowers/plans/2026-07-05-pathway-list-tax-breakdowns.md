# Pathway List Tax Breakdowns — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend DuckDB `pathway-list` to return `{ pathways, breakdowns }` with graph-lineage tax ordering, update legacy to `{ pathways }`, and wire the renderer to use embedded breakdowns with counts fallback.

**Architecture:** Extract graph-lineage tax ordering into `tax_lineage_order.py` (shared by `graph_service` and `pathway_list_service`). Pathway-list runs two SQL aggregations on existing `filtered_rollup_rows`, orders tax categories via bridge-tax pivot, and returns batched per-pathway `OverviewVector`s. Renderer normalises the response into `pathway_list` + `pathway_tax_breakdowns`; `PathwayPreview` skips per-card counts when props are present.

**Tech Stack:** Python 3.14, FastAPI, DuckDB, pytest, Pydantic; Node 22, Express 5, vitest, React, Zustand

**Branch:** `feature/pathway-list-tax-breakdowns` (worktree: `.worktrees/feature/pathway-list-tax-breakdowns`)

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-07-05-pathway-list-tax-breakdowns-design.md` — approved design
- `analytics/api/pathway_list_service.py` — current pathway-list query
- `analytics/api/graph_service.py` — `_materialize_tax_metadata`, `_lineage_order_by_sql`
- `analytics/api/graph_matrix.py` — `_dedupe_preserve_order`
- `analytics/api/rollup_query.py` — `build_filtered_rollup_rows`
- `src/renderer/src/components/Network.tsx` — `PathwayPreview` counts fetch
- `docs/superpowers/plans/2026-07-01-pathway-list-dbt-api.md` — prior pathway-list plan (patterns)

**Prerequisites:**

```bash
cd analytics
uv run python transform/scripts/build_reference.py
uv run python transform/scripts/run_pipeline.py \
  --sample-id fake_rpkm \
  --rpkm-path transform/tests/fixtures/fake_rpkm.tsv \
  --tax-rank phylum \
  --pathway-level superpathway
```

---

## File Map

```
analytics/api/
├── tax_lineage_order.py               # CREATE: shared graph-lineage tax ordering
├── graph_service.py                   # MODIFY: delegate tax metadata to tax_lineage_order
├── pathway_list_service.py            # MODIFY: return PathwayListResponse + breakdowns
├── schemas.py                         # MODIFY: PathwayListResponse
├── main.py                            # unchanged envelope; service returns dict
└── tests/
    ├── test_tax_lineage_order.py      # CREATE
    ├── test_pathway_list_service.py   # MODIFY: wrapper + breakdown assertions
    ├── test_main.py                   # MODIFY: dict shape not list
    └── fixtures/
        └── pathway_list_expectations.yaml  # MODIFY: expected.pathways + expected.breakdowns

src/server/
└── data_functions.ts                  # MODIFY: parse_pathway_list → { pathways }

src/renderer/src/
├── pathwayListResponse.ts             # CREATE: normalizePathwayListResponse
├── store/AppStore.ts                  # MODIFY: pathway_tax_breakdowns
├── App.tsx                            # MODIFY: channel handler
└── components/Network.tsx             # MODIFY: pass tax_counts prop

src/tests/
├── pathwayListResponse.test.ts        # CREATE
└── data_functions.test.ts             # MODIFY: { pathways } expectations
```

---

### Task 1: `PathwayListResponse` schema

**Files:**
- Modify: `analytics/api/schemas.py`

- [ ] **Step 1: Add model after `PathwayListRequest`**

```python
class PathwayListResponse(BaseModel):
    pathways: list[str]
    breakdowns: dict[str, OverviewVector] = Field(default_factory=dict)
```

- [ ] **Step 2: Verify import path**

```bash
cd analytics && uv run python -c "from api.schemas import PathwayListResponse; print(PathwayListResponse(pathways=['a']))"
```

Expected: no import error

- [ ] **Step 3: Commit**

```bash
git add analytics/api/schemas.py
git commit -m "feat(analytics): add PathwayListResponse schema"
```

---

### Task 2: `tax_lineage_order.py` (shared graph-lineage ordering)

**Files:**
- Create: `analytics/api/tax_lineage_order.py`
- Create: `analytics/api/tests/test_tax_lineage_order.py`

- [ ] **Step 1: Write failing test**

```python
from __future__ import annotations

import duckdb
import pytest

from api.tax_lineage_order import dedupe_preserve_order, tax_cat_order_from_metadata_rows


def test_dedupe_preserve_order():
    assert dedupe_preserve_order(["B", "A", "B", "C", "A"]) == ["B", "A", "C"]


def test_tax_cat_order_from_metadata_rows():
    rows = [
        {"display_name": "tax-2", "tax_map_value": "Firmicutes"},
        {"display_name": "tax-1", "tax_map_value": "Actinomycetota"},
        {"display_name": "tax-3", "tax_map_value": "Firmicutes"},
    ]
    assert tax_cat_order_from_metadata_rows(rows) == ["Firmicutes", "Actinomycetota"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd analytics && uv run pytest api/tests/test_tax_lineage_order.py -v
```

Expected: FAIL — module not found

- [ ] **Step 3: Implement minimal module**

```python
from __future__ import annotations

from pathlib import Path

import duckdb

from api.filters import TAX_RANK_ORDER, validate_tax_level

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"
BRIDGE_TAX_PATH = REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet"
REPO_ROOT = ANALYTICS_DIR.parent
NAMES_PATH = REPO_ROOT / "resources/db/parquet/names.parquet"


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def lineage_order_by_sql() -> str:
    parts = list(TAX_RANK_ORDER) + ["display_name"]
    return ", ".join(f'"{rank}"' if rank == "order" else rank for rank in parts)


def dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def tax_cat_order_from_metadata_rows(rows: list[dict]) -> list[str]:
    return dedupe_preserve_order(
        [row["tax_map_value"] for row in rows if row.get("tax_map_value")]
    )


def materialize_tax_metadata_from_ids(
    conn: duckdb.DuckDBPyConnection,
    *,
    tax_level: str,
    ids_table: str,
    output_table: str = "tax_lineage_metadata",
) -> None:
    validate_tax_level(tax_level)
    if not BRIDGE_TAX_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {BRIDGE_TAX_PATH}")
    if not NAMES_PATH.exists():
        raise FileNotFoundError(f"reference parquet missing: {NAMES_PATH}")

    rank_in = _sql_in_list(TAX_RANK_ORDER)
    lineage_cols = ", ".join(f"COALESCE(w.{rank}, '') AS {rank}" for rank in TAX_RANK_ORDER)
    order_by = lineage_order_by_sql()
    bridge = BRIDGE_TAX_PATH.as_posix()
    names = NAMES_PATH.as_posix()
    conn.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {output_table} AS
        WITH ids AS (
            SELECT DISTINCT source_tax_id FROM {ids_table}
        ),
        bridge_gated AS (
            SELECT source_tax_id, requested_rank, resolved_tax_label AS label
            FROM read_parquet('{bridge}')
            WHERE requested_rank IN ({rank_in})
        ),
        bridge_wide AS (
            SELECT *
            FROM (
                SELECT source_tax_id, requested_rank, label
                FROM bridge_gated
            )
            PIVOT (MAX(label) FOR requested_rank IN ({rank_in}))
        )
        SELECT
            d.source_tax_id,
            {lineage_cols},
            COALESCE(n.name, CAST(d.source_tax_id AS VARCHAR)) AS display_name,
            COALESCE(
                NULLIF(w.{tax_level}, ''),
                COALESCE(n.name, CAST(d.source_tax_id AS VARCHAR))
            ) AS tax_map_value
        FROM ids d
        LEFT JOIN bridge_wide w USING (source_tax_id)
        LEFT JOIN read_parquet('{names}') n ON d.source_tax_id = n.tax_id
        ORDER BY {order_by}
        """
    )


def read_tax_metadata_rows(
    conn: duckdb.DuckDBPyConnection,
    *,
    table: str = "tax_lineage_metadata",
) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT display_name, COALESCE(tax_map_value, '')
        FROM {table}
        """
    ).fetchall()
    return [
        {"display_name": name, "tax_map_value": tax_map_value}
        for name, tax_map_value in rows
    ]


def tax_cat_order_for_ids_table(
    conn: duckdb.DuckDBPyConnection,
    *,
    tax_level: str,
    ids_table: str,
) -> list[str]:
    materialize_tax_metadata_from_ids(
        conn, tax_level=tax_level, ids_table=ids_table
    )
    return tax_cat_order_from_metadata_rows(read_tax_metadata_rows(conn))
```

- [ ] **Step 4: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_tax_lineage_order.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analytics/api/tax_lineage_order.py analytics/api/tests/test_tax_lineage_order.py
git commit -m "feat(analytics): add shared tax lineage ordering helper"
```

---

### Task 3: Refactor `graph_service` to use `tax_lineage_order`

**Files:**
- Modify: `analytics/api/graph_service.py`
- Modify: `analytics/api/graph_matrix.py`

- [ ] **Step 1: Run graph tests (baseline)**

```bash
cd analytics && uv run pytest api/tests/test_graph_service.py -v
```

Expected: PASS (record baseline)

- [ ] **Step 2: Replace `_lineage_order_by_sql` and `_materialize_tax_metadata` in graph_service**

Import from `tax_lineage_order`:

```python
from api.tax_lineage_order import (
    materialize_tax_metadata_from_ids,
    read_tax_metadata_rows,
)
```

In `build_graph_from_duckdb`, after `_materialize_filtered_triples`:

```python
materialize_tax_metadata_from_ids(
    conn,
    tax_level=tax_level,
    ids_table="filtered_triples",
    output_table="graph_tax_metadata",
)
tax_rows = read_tax_metadata_rows(conn, table="graph_tax_metadata")
```

Remove the old `_materialize_tax_metadata`, `_read_tax_metadata`, and `_lineage_order_by_sql` definitions from `graph_service.py`.

- [ ] **Step 3: Update `graph_matrix.py` to import dedupe from tax_lineage_order**

```python
from api.tax_lineage_order import dedupe_preserve_order
```

Remove local `_dedupe_preserve_order`; use `dedupe_preserve_order` in `build_graph_matrix`.

- [ ] **Step 4: Run graph tests**

```bash
cd analytics && uv run pytest api/tests/test_graph_service.py api/tests/test_main.py -v -k graph
```

Expected: PASS (no behaviour change)

- [ ] **Step 5: Commit**

```bash
git add analytics/api/graph_service.py analytics/api/graph_matrix.py
git commit -m "refactor(analytics): share tax lineage ordering with graph service"
```

---

### Task 4: Pathway-list service — wrapper + breakdowns

**Files:**
- Modify: `analytics/api/pathway_list_service.py`
- Modify: `analytics/api/tests/test_pathway_list_service.py`

- [ ] **Step 1: Update failing tests for new return type**

Change imports and assertions. Example for `test_pathway_list_alphabetical_and_matches_chord_set`:

```python
from api.schemas import PathwayListResponse

# ...
out = build_pathway_list_from_duckdb(...)
assert isinstance(out, PathwayListResponse)
pathways = out.pathways
assert pathways == sorted(pathways)
assert set(pathways) == chord_pathways
assert out.breakdowns  # non-empty for fake_rpkm
for name in pathways:
    assert name in out.breakdowns
    vec = out.breakdowns[name]
    assert len(vec.index) == len(vec.counts)
    assert sum(vec.counts) > 0
```

Add lineage-order assertion (compare against global `tax_cat_order`):

```python
@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_pathway_breakdown_tax_index_respects_lineage_order(fake_rpkm_db):
    import duckdb
    from api.rollup_query import build_filtered_rollup_rows
    from api.tax_lineage_order import tax_cat_order_for_ids_table
    from testing.fake_rpkm_fixture import DB_PATH, SAMPLE_ID

    ann_filter = {"level": "superpathway", "name": SUPERPATHWAY}
    tax_level = "phylum"
    out = build_pathway_list_from_duckdb(
        names=[f"{SAMPLE_ID}.tsv"],
        tax_level=tax_level,
        selected_ann_cat=ann_filter,
        selected_taxon={},
    )
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        build_filtered_rollup_rows(
            conn,
            tax_level=tax_level,
            ann_level="pathway",
            ann_filter=ann_filter,
            taxon_filter=None,
        )
        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE pathway_tax_ids AS
            SELECT DISTINCT source_tax_id
            FROM filtered_rollup_rows
            WHERE requested_rank = ?
              AND pathway_level = 'pathway'
            """,
            [tax_level],
        )
        tax_cat_order = tax_cat_order_for_ids_table(
            conn, tax_level=tax_level, ids_table="pathway_tax_ids"
        )
    finally:
        conn.close()

    pos = {cat: i for i, cat in enumerate(tax_cat_order)}
    for pathway, vec in out.breakdowns.items():
        for i in range(len(vec.index) - 1):
            assert pos[vec.index[i]] < pos[vec.index[i + 1]]
```

Add count-totals check (values match independent sums):

```python
def _sum_breakdown(vec) -> float:
    return float(sum(vec.counts))

# in golden test: assert _sum_breakdown(out.breakdowns[p]) > 0 for each pathway
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd analytics && uv run pytest api/tests/test_pathway_list_service.py -v
```

Expected: FAIL — return type still `list[str]`

- [ ] **Step 3: Implement `build_pathway_list_from_duckdb`**

```python
from api.schemas import OverviewVector, PathwayListResponse
from api.tax_lineage_order import tax_cat_order_for_ids_table


def build_pathway_list_from_duckdb(...) -> PathwayListResponse:
    # ... existing setup through build_filtered_rollup_rows ...

    pathway_rows = conn.execute(
        """
        SELECT cf.pathway_label AS display_label
        FROM filtered_rollup_rows cf
        WHERE cf.requested_rank = ?
          AND cf.pathway_level = 'pathway'
        GROUP BY cf.pathway_key, cf.pathway_label
        ORDER BY display_label ASC
        """,
        [tax_level],
    ).fetchall()
    pathway_names = [r[0] for r in pathway_rows]

    conn.execute(
        """
        CREATE OR REPLACE TEMP TABLE pathway_tax_ids AS
        SELECT DISTINCT cf.source_tax_id
        FROM filtered_rollup_rows cf
        WHERE cf.requested_rank = ?
          AND cf.pathway_level = 'pathway'
        """,
        [tax_level],
    )
    tax_cat_order = tax_cat_order_for_ids_table(
        conn, tax_level=tax_level, ids_table="pathway_tax_ids"
    )

    breakdown_rows = conn.execute(
        """
        SELECT
          cf.pathway_label AS display_label,
          cf.resolved_tax_label,
          SUM(cf.value) AS value
        FROM filtered_rollup_rows cf
        WHERE cf.requested_rank = ?
          AND cf.pathway_level = 'pathway'
        GROUP BY cf.pathway_key, cf.pathway_label, cf.resolved_tax_label
        ORDER BY display_label ASC
        """,
        [tax_level],
    ).fetchall()

    by_pathway: dict[str, dict[str, float]] = {}
    for label, tax_label, value in breakdown_rows:
        by_pathway.setdefault(label, {})
        by_pathway[label][tax_label] = by_pathway[label].get(tax_label, 0.0) + float(value)

    breakdowns: dict[str, OverviewVector] = {}
    for pathway in pathway_names:
        totals = by_pathway.get(pathway, {})
        index = [cat for cat in tax_cat_order if totals.get(cat, 0) > 0]
        counts = [totals[cat] for cat in index]
        breakdowns[pathway] = OverviewVector(index=index, counts=counts)

    return PathwayListResponse(pathways=pathway_names, breakdowns=breakdowns)
```

Remove `PATHWAY_LABEL_SQL` import if no longer used in this file.

- [ ] **Step 4: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_pathway_list_service.py -v
```

Expected: tests fail on golden YAML until Task 5

- [ ] **Step 5: Commit service (may fail golden until next task)**

```bash
git add analytics/api/pathway_list_service.py analytics/api/tests/test_pathway_list_service.py
git commit -m "feat(analytics): return pathway-list breakdowns with lineage tax order"
```

---

### Task 5: Golden fixtures for breakdowns

**Files:**
- Modify: `analytics/api/tests/fixtures/pathway_list_expectations.yaml`
- Modify: `analytics/api/tests/test_pathway_list_service.py` (golden assertion)

- [ ] **Step 1: Dump updated expectations**

From `analytics/`:

```python
# One-off dump (run in uv python -c or short script)
import yaml
from api.pathway_list_service import build_pathway_list_from_duckdb
from testing.fake_rpkm_fixture import load_pathway_list_expectations

cases = load_pathway_list_expectations()["pathway_list"]
out = {}
for key, case in cases.items():
    resp = build_pathway_list_from_duckdb(
        names=case["names"],
        tax_level=case["tax_level"],
        selected_ann_cat=case["selected_ann_cat"],
        selected_taxon=case["selected_taxon"],
    )
    out[key] = {**case, "expected": resp.model_dump()}
print(yaml.dump({"pathway_list": out}, sort_keys=False))
```

Write output to `pathway_list_expectations.yaml`, replacing bare `expected: [...]` lists with:

```yaml
expected:
  pathways: [...]
  breakdowns:
    "Oxidative phosphorylation":
      index: [...]
      counts: [...]
```

- [ ] **Step 2: Update golden test**

```python
def test_pathway_list_matches_golden(fake_rpkm_db, case_key):
    cases = load_pathway_list_expectations()["pathway_list"]
    case = cases[case_key]
    out = build_pathway_list_from_duckdb(
        names=case["names"],
        tax_level=case["tax_level"],
        selected_ann_cat=case["selected_ann_cat"],
        selected_taxon=case["selected_taxon"],
    )
    assert out.model_dump() == case["expected"]
    assert out.pathways == sorted(out.pathways)
```

- [ ] **Step 3: Run tests**

```bash
cd analytics && uv run pytest api/tests/test_pathway_list_service.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add analytics/api/tests/fixtures/pathway_list_expectations.yaml analytics/api/tests/test_pathway_list_service.py
git commit -m "test(analytics): golden pathway-list breakdown fixtures"
```

---

### Task 6: FastAPI endpoint smoke

**Files:**
- Modify: `analytics/api/tests/test_main.py`

- [ ] **Step 1: Update `test_pathway_list_endpoint_ok`**

```python
    assert body["ok"] is True
    value = body["value"]
    assert isinstance(value, dict)
    assert "pathways" in value
    assert "breakdowns" in value
    assert isinstance(value["pathways"], list)
    assert len(value["pathways"]) > 0
    assert value["pathways"][0] in value["breakdowns"]
```

- [ ] **Step 2: Run test**

```bash
cd analytics && uv run pytest api/tests/test_main.py -v -k pathway_list
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add analytics/api/tests/test_main.py
git commit -m "test(analytics): pathway-list endpoint returns breakdown wrapper"
```

---

### Task 7: Legacy `parse_pathway_list` wrapper

**Files:**
- Modify: `src/server/data_functions.ts`
- Modify: `src/tests/data_functions.test.ts`

- [ ] **Step 1: Update tests first**

In `parse_pathway_list` describe block, change expectations:

```typescript
const out = parse_pathway_list({ superpathway: sp_value })
expect(out).toEqual({ pathways: expect.any(Array) })
expect(out.pathways.length).toBeGreaterThan(0)
for (const p of out.pathways) {
  expect(typeof p).toBe('string')
}

expect(parse_pathway_list({ superpathway: '__no_such_superpathway__' })).toEqual({
  pathways: []
})

expect(via_ann).toEqual(via_field)

const sp_pathways = parse_pathway_list({ superpathway: sp_value })
expect(sp_pathways.pathways).toContain(pathway_name)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
npm test -- src/tests/data_functions.test.ts -t parse_pathway_list
```

Expected: FAIL

- [ ] **Step 3: Update handler**

```typescript
const parse_pathway_list = ({
  superpathway,
  selected_ann_cat,
}: {
  superpathway?: string
  selected_ann_cat?: { level?: string; name?: string }
}): { pathways: string[] } => {
  const sp =
    superpathway?.trim() ||
    (selected_ann_cat?.name?.trim() ?? '')
  if (!sp) return { pathways: [] }
  return { pathways: get_pathways_in_superpathway(sp).map((p) => p.name) }
}
```

- [ ] **Step 4: Run tests**

```bash
npm test -- src/tests/data_functions.test.ts -t parse_pathway_list
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/server/data_functions.ts src/tests/data_functions.test.ts
git commit -m "feat(server): wrap legacy pathway-list as { pathways }"
```

---

### Task 8: Renderer normaliser

**Files:**
- Create: `src/renderer/src/pathwayListResponse.ts`
- Create: `src/tests/pathwayListResponse.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
import { describe, expect, it } from 'vitest'
import { normalizePathwayListResponse } from '../renderer/src/pathwayListResponse'

describe('normalizePathwayListResponse', () => {
  it('parses wrapper with breakdowns', () => {
    const value = {
      pathways: ['A', 'B'],
      breakdowns: { A: { index: ['p1'], counts: [1] } }
    }
    expect(normalizePathwayListResponse(value)).toEqual(value)
  })

  it('parses wrapper without breakdowns', () => {
    expect(normalizePathwayListResponse({ pathways: ['A'] })).toEqual({
      pathways: ['A'],
      breakdowns: {}
    })
  })

  it('accepts bare string[]', () => {
    expect(normalizePathwayListResponse(['A', 'B'])).toEqual({
      pathways: ['A', 'B'],
      breakdowns: {}
    })
  })

  it('returns empty for invalid input', () => {
    expect(normalizePathwayListResponse(null)).toEqual({
      pathways: [],
      breakdowns: {}
    })
  })
})
```

- [ ] **Step 2: Run tests**

```bash
npm test -- src/tests/pathwayListResponse.test.ts
```

Expected: FAIL

- [ ] **Step 3: Implement**

```typescript
export interface CountsData {
  index: string[]
  counts: number[]
}

export interface PathwayListValue {
  pathways: string[]
  breakdowns: Record<string, CountsData>
}

export function normalizePathwayListResponse(value: unknown): PathwayListValue {
  if (typeof value === 'object' && value !== null && 'pathways' in value) {
    const v = value as { pathways: string[]; breakdowns?: Record<string, CountsData> }
    return { pathways: v.pathways, breakdowns: v.breakdowns ?? {} }
  }
  if (Array.isArray(value)) {
    return { pathways: value as string[], breakdowns: {} }
  }
  return { pathways: [], breakdowns: {} }
}
```

- [ ] **Step 4: Run tests**

```bash
npm test -- src/tests/pathwayListResponse.test.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/renderer/src/pathwayListResponse.ts src/tests/pathwayListResponse.test.ts
git commit -m "feat(renderer): add pathway-list response normaliser"
```

---

### Task 9: Store + channel handler

**Files:**
- Modify: `src/renderer/src/store/AppStore.ts`
- Modify: `src/renderer/src/App.tsx`

- [ ] **Step 1: Extend AppStore**

```typescript
import type { CountsData } from './pathwayListResponse'

// in AppState:
pathway_tax_breakdowns: Record<string, CountsData>

// in initial state:
pathway_tax_breakdowns: {},
```

- [ ] **Step 2: Update channel handler in App.tsx**

```typescript
import { normalizePathwayListResponse } from './pathwayListResponse'

// in channel_handlers:
pathway_list: (value) => {
  const { pathways, breakdowns } = normalizePathwayListResponse(value)
  useAppStore.setState({ pathway_list: pathways, pathway_tax_breakdowns: breakdowns })
},
```

- [ ] **Step 3: Commit**

```bash
git add src/renderer/src/store/AppStore.ts src/renderer/src/App.tsx
git commit -m "feat(renderer): store pathway tax breakdowns from pathway-list"
```

---

### Task 10: `Network.tsx` — use embedded breakdowns

**Files:**
- Modify: `src/renderer/src/components/Network.tsx`

- [ ] **Step 1: Update `PathwayPreview`**

Add prop and conditional fetch:

```typescript
import type { CountsData } from '../pathwayListResponse'

const PathwayPreview = ({
  pathway,
  width,
  height,
  tax_counts: tax_counts_prop
}: {
  pathway: string
  width: number
  height: number
  tax_counts?: CountsData
}): React.JSX.Element => {
  // ...
  const [counts_data, set_counts_data] = useState<CountsData | null>(
    tax_counts_prop ?? null
  )

  useEffect(() => {
    if (tax_counts_prop) {
      set_counts_data(tax_counts_prop)
      return
    }
    if (selected_file_list.length === 0) return
    set_counts_data(null)
    let cancelled = false
    ;(async () => {
      const res = await fetch('/api/viz/counts', { /* unchanged body */ })
      const envelope = (await res.json()) as { ok: boolean; value?: CountsData }
      if (!cancelled && envelope.ok && envelope.value) {
        set_counts_data(envelope.value)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [pathway, selected_file_list, tax_rank, selected_taxon, tax_counts_prop])
```

- [ ] **Step 2: Update `PathwayList`**

```typescript
const PathwayList = ({ height, width, superpathway, pathways }: { ... }): React.JSX.Element => {
  const pathway_tax_breakdowns = useAppStore((state) => state.pathway_tax_breakdowns)
  // ...
  {pathways.map((p) => (
    <PathwayPreview
      key={p}
      pathway={p}
      width={c_width}
      height={c_height}
      tax_counts={pathway_tax_breakdowns[p]}
    />
  ))}
```

Note: pass `tax_counts` only when key exists — use `pathway_tax_breakdowns[p]` which is `undefined` when absent (triggers fallback).

- [ ] **Step 3: Clear breakdowns on re-fetch in `Network` useEffect (optional safety)**

The channel handler overwrites on each response; no extra clear needed if pathway_list request always runs on filter change.

- [ ] **Step 4: Run full test suite**

```bash
npm test
cd analytics && uv run pytest
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/renderer/src/components/Network.tsx
git commit -m "feat(network): use pathway-list breakdowns with counts fallback"
```

---

### Task 11: Manual verification

- [ ] **Step 1: Sidecar path**

```bash
# Terminal 1: analytics API
cd analytics && uv run uvicorn api.main:app --port 8001

# Terminal 2: express + renderer
npm run dev
```

1. Load test files → Chord → select superpathway → Network tab
2. DevTools Network: one `pathway-list` request, no `/api/viz/counts` per card
3. Pies render on pathway cards

- [ ] **Step 2: Legacy path**

```javascript
localStorage.setItem('vizBackend', 'legacy')
// reload
```

1. Pies still render (via per-card counts)
2. `pathway-list` response is `{ pathways: [...] }` without breakdowns

- [ ] **Step 3: Final commit if any fixups needed**

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| DuckDB `{ pathways, breakdowns }` | Task 4, 6 |
| Graph-lineage tax ordering | Task 2, 3, 4 |
| Plain `pathway_label` not PATHWAY_LABEL_SQL | Task 4 |
| No redundant HAVING | Task 4 |
| Legacy `{ pathways }` | Task 7 |
| Renderer normaliser + store | Task 8, 9 |
| PathwayPreview prop + fallback | Task 10 |
| Golden breakdown fixtures | Task 5 |
| Count totals vs legacy (not order) | Task 5 golden dump + manual |

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-05-pathway-list-tax-breakdowns.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
