# Krona API via dbt Intermediates — Design Spec

> **Status:** Draft (2026-06-30; revised — upsert tree builder, PIVOT SQL, `name` via names lookup, unified path segments)  
> **Goal:** Reimplement `POST /api/viz/krona` to derive the Krona sunburst taxonomy tree from precomputed dbt intermediate tables (`int_rpkm_by_ec_tax` + `bridge_tax_rollup` + `names`) in `runs/{sample_id}/sample.duckdb`, preserving the existing JSON contract. Express keeps legacy handlers when `?backend=duckdb` is absent; the renderer defaults migrated channels to the FastAPI sidecar.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, `int_rpkm_by_ec_tax`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — sidecar proxy pattern, envelope, sample lookup
- `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` — shared `fake_rpkm` fixture and YAML golden pattern
- `docs/superpowers/specs/2026-06-29-overview-dbt-api-design.md` — migration wiring, renderer toggle, golden-test pattern

## 1. Context

Metapro Viz renders a zoomable Krona sunburst of taxonomy (`Krona.tsx`, `d3.partition`). Today the Express handler `parse_krona` (`src/server/data_functions.ts`) loads wide TSV data in memory, sums RPKM **per tax column** across all ECs, and builds a nested tree via `get_parents_multilevel` → `parse_tax_tree` (`src/server/parse.ts`).

**Legacy column rename (critical):** On upload, `add_data` renames tax_id column headers to scientific names via `get_name_from_id` (`src/server/db_functions.ts`). All downstream tree logic — including leaf `id` and `U_{id}` labels — uses these **names**, not raw NCBI tax_ids. Unknown headers (e.g. `999999999` in `fake_rpkm.tsv`) keep the raw id string as fallback.

Tree depth is driven by `levels = dedupe([tax_rank, 'genus', 'species'])` — e.g. `phylum` → genus → species (3 ranks under root). Internal nodes use resolved taxon names at each rank; leaves use the renamed column **name** as `id`.

Unlike chord/overview, Krona is **taxonomy-only** — no pathway dimension. The correct value grain is per `(ec_normalized, source_tax_id)` summed to one total per column, which is exactly what `int_rpkm_by_ec_tax` materialises before the pathway join.

**Assumption (in scope):** `int_rpkm_by_ec_tax` is already materialised in `runs/{sample_id}/sample.duckdb` before the krona endpoint is invoked (same pipeline run as other intermediates).

**Out of scope (this spec):**

- Upload endpoint that ingests RPKM and triggers `dbt build --select stg_rpkm_long+`
- Comparison mode (`names.length > 1`) on the analytics API path
- Taxon filter (`selected_taxon`) on the analytics API path
- Retiring the legacy Node implementation
- Shared TypeScript response types in the renderer (optional follow-up)

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| API contract | Unchanged request body + `{ ok, value }` envelope | No breaking frontend changes |
| FastAPI route | **`POST /api/viz/krona`** — identical path, method, envelope, HTTP 200 as Express | Drop-in replacement when Express is retired |
| Default backend | Legacy Node `parse_krona` | Safe rollout |
| Opt-in backend | `POST /api/viz/krona?backend=duckdb` (Express) or direct on FastAPI `:8001` | Explicit testing switch; mirrors chord/overview |
| Sidecar env var | **`ANALYTICS_API_URL`** (default `http://localhost:8001`) | One FastAPI process serves all viz routes |
| Migration proxy | Shared `src/server/fastapi_sidecar_proxy.ts` | Temporary Express→FastAPI bridge during viz migration |
| Data source | `int_rpkm_by_ec_tax` + `bridge_tax_rollup` + `names` Parquet | Column totals + ancestry + name lookup |
| Tree builder | **Single-pass upsert** — one SQL row → path segments → upsert | Simpler than porting recursive `parse_tax_tree`; shared internals emerge when siblings share a prefix |
| Path model | **`segments_for_row()`** returns an ordered path; **last segment is always the leaf** | Internal and leaf nodes use the same segment type; leaf carries `value` |
| Tree levels | `dedupe([tax_rank, 'genus', 'species'])` | Matches legacy `parse_krona` |
| Ancestry exactness | SQL returns rank label **only when `resolved_tax_rank = requested_rank`**; else `NULL` | Preserves legacy early-leaf depth; avoids bridge `'Unclassified'` in grouping |
| Column `name` | SQL row field **`name`** = `COALESCE(names.name, CAST(source_tax_id AS VARCHAR))` | Matches legacy `get_name_from_id`; not a new term — same as `names.name` / renamed column header |
| Leaf `id` | `name` | Matches legacy column key after `add_data` rename |
| Early-leaf `label` | `U_{name}` | Matches legacy (`U_` prefixes leaf's own `id`, not parent label) |
| Species-leaf `label` | same as `id` (= `name`) | Matches legacy |
| Early-leaf at first rank | Path is a **single leaf segment** (no internal prefix) | Matches legacy `no_children` at first level (e.g. `999999999`, `U_Bacteria` under root) |
| Sibling ordering | SQL `ORDER BY` on rank labels; upsert appends in encounter order | No Python re-sort; order visible on sunburst |
| Sunburst layout | Clockwise in **`children` array order** (D3 `hierarchy.sort(null)`) | Backend ordering is visible; not re-sorted by value |
| Percentages | **`add_mass(node, value, grand_total)`** on each node in the path: `subtotal += value`; `percentage = subtotal / grand_total` | Correct after all rows; no finalize pass |
| Comparison mode | Error when `names.length > 1` | Deferred follow-up (same as chord/overview v1) |
| Taxon filter | Error when non-empty `{ level, name }` passed | Krona UI sends `{}` today; fail loudly rather than silently ignore |
| Error wording | Feature gaps say **"analytics API"**, not "duckdb backend" | Avoid implying DuckDB limitation |
| Verification | Golden tests: `krona_expectations.yaml` + parametrized pytest on `fake_rpkm` | Mirrors overview/chord golden pattern; expect scientific names |
| Response typing | Pydantic `KronaNode` model in Python | Documents contract; used in service return type and tests |
| Renderer backend toggle | Add `'krona'` to `MIGRATED_CHANNELS` in `vizBackend.ts` | Sidecar default for krona |

## 3. Architecture

```
┌─────────────┐     POST /api/viz/krona          ┌──────────────┐
│   React     │ ───────────────────────────────► │   Express    │
│  (unchanged)│     (no query param = legacy)    │   :3001      │
└─────────────┘                                  └──────┬───────┘
                                                        │
                       ?backend=duckdb                  │
                       ────────────────────────────────►│ proxy ──────┐
                                                        │  (same path) │
                                                        ▼             ▼
                                               legacy in-process   ┌──────────────────────────┐
                                                                   │   FastAPI  :8001         │
                                                                   │   POST /api/viz/krona    │
                                                                   └──────────────┬───────────┘
                                                                                  │
                                                                                  ▼
                                                                       runs/{sample_id}/sample.duckdb
                                                                       int_rpkm_by_ec_tax
                                                                       + bridge_tax_rollup (Parquet)
                                                                       + names (Parquet)
```

| Component | Location | Role |
|---|---|---|
| Migration proxy | `src/server/fastapi_sidecar_proxy.ts` | `createSidecarProxyHandler({ legacyHandler, apiPath, label: 'krona' })` |
| Express routes | `src/server/index.ts` | Move krona from `vizRoutes` → `sidecarRoutes` |
| FastAPI route | `analytics/api/main.py` | `POST /api/viz/krona` |
| Service | `analytics/api/krona_service.py` | DuckDB PIVOT query + upsert tree builder |
| Schemas | `analytics/api/schemas.py` | `KronaRequest`, `KronaNode` |
| Filters helper | `analytics/api/filters.py` | Add `krona_levels(tax_rank)` |
| Renderer toggle | `src/renderer/src/vizBackend.ts` | Add `'krona'` to `MIGRATED_CHANNELS` |
| Renderer layout | `src/renderer/src/components/Krona.tsx` | Replace `hierarchy.sort((a,b) => b.value - a.value)` with `hierarchy.sort(null)` |

**Route parity (required):** FastAPI exposes `POST /api/viz/krona` (not a shortened internal path) so future cutover is a host/port change only.

### 3.1 Express sidecar proxy behaviour

When `?backend=duckdb` is present:

1. Forward method, path (`/api/viz/krona`), query string, and JSON body unchanged to FastAPI.
2. Return FastAPI's JSON envelope to the client unchanged.
3. On connection failure, return `{ ok: false, error: "krona analytics API unavailable: ..." }` with HTTP 200.

### 3.2 Renderer backend toggle

Add `'krona'` to `MIGRATED_CHANNELS` in `vizBackend.ts` (alongside `'chord'`, `'overview'`). No other renderer changes beyond `Krona.tsx` sort fix (§4.2).

## 4. Request / Response Contract

### 4.1 Request (unchanged JSON body)

```json
{ "names": ["fake_rpkm.tsv"], "tax_rank": "phylum", "selected_taxon": {} }
```

| Field | Analytics API semantics |
|---|---|
| `names` | Single sample only; `sample_id = strip_extension(names[0])` → `runs/{sample_id}/sample.duckdb` |
| `names.length > 1` | `{ ok: false, error: "comparison mode not supported on analytics API" }` |
| `names` empty | `{ ok: false, error: "names must contain at least one sample" }` |
| `tax_rank` | One of 7 ranks; validated via `validate_tax_level()` |
| `selected_taxon` | If `{ level, name }` both non-empty → `{ ok: false, error: "taxon filter not supported on analytics API" }`. Empty `{}` OK |

### 4.2 Response `value` (unchanged nested tree)

**Reference (legacy, `fake_rpkm`, `tax_rank = phylum`):** leaves use scientific names; early leaves use `U_{name}`; unknown column `999999999` stays numeric.

```json
{
  "id": "root",
  "label": "root",
  "children": [
    { "id": "999999999", "label": "U_999999999", "value": 1, "percentage": 0.077 },
    {
      "id": "Bacillota", "label": "Bacillota",
      "children": [
        {
          "id": "Staphylococcus", "label": "Staphylococcus",
          "children": [
            { "id": "Staphylococcus aureus", "label": "Staphylococcus aureus", "value": 5, "percentage": 0.385 },
            { "id": "Staphylococcus epidermidis", "label": "Staphylococcus epidermidis", "value": 1, "percentage": 0.077 }
          ],
          "percentage": 0.462
        },
        { "id": "Mammaliicoccus sciuri", "label": "U_Mammaliicoccus sciuri", "value": 1, "percentage": 0.077 }
      ],
      "percentage": 0.769
    },
    { "id": "Bacteria", "label": "U_Bacteria", "value": 1, "percentage": 0.077 }
  ],
  "percentage": 1.0
}
```

Root node: `{ id: "root", label: "root", children, percentage: 1.0 }`.

Internal nodes: `{ id, label, children, percentage }` — `id` = `label` = group name.

Leaf nodes: `{ id, label, value, percentage }` — no `children`.

| Leaf case | `id` | `label` |
|---|---|---|
| Species level reached (last rank in `levels`) | `name` | same as `id` |
| Early leaf (next rank is `NULL`) | `name` | `U_{name}` |

**Sunburst layout:** Arc order follows `children` array order at each level. `Krona.tsx` must use `d3.hierarchy(data).sum(...).sort(null)` so the partition layout respects backend sibling order (mirrors overview's `pie.sort(null)`).

### 4.3 Pydantic models

```python
class KronaNode(BaseModel):
    id: str
    label: str
    percentage: float
    value: float | None = None
    children: list["KronaNode"] | None = None

class KronaRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_rank: str
    selected_taxon: Any = Field(default_factory=dict)
```

FastAPI endpoint does not set `response_model` on the route (envelope wraps value), but `build_krona_from_duckdb()` returns a `KronaNode` root and tests validate against it.

### 4.4 Errors (analytics API path)

| Condition | HTTP | `{ ok: false, error }` |
|---|---|---|
| `names` empty | 200 | `"names must contain at least one sample"` |
| `names.length > 1` | 200 | `"comparison mode not supported on analytics API"` |
| Non-empty `selected_taxon` | 200 | `"taxon filter not supported on analytics API"` |
| Invalid `tax_rank` | 200 | `"invalid tax_rank: {value}"` |
| DuckDB file missing | 200 | `"sample not found: {sample_id}"` |
| `int_rpkm_by_ec_tax` missing | 200 | `"int_rpkm_by_ec_tax not materialized for sample: {sample_id}"` |
| Bridge / names Parquet missing | 200 | `"reference parquet missing: ..."` |
| FastAPI unreachable (Express proxy) | 200 | `"krona analytics API unavailable: ..."` |

## 5. Data Flow

### 5.1 Pipeline

```
int_rpkm_by_ec_tax
  → SUM(value) GROUP BY source_tax_id
  → JOIN names → name
  → JOIN bridge_tax_rollup (PIVOT, exact-rank-gated labels)
  → ORDER BY rank labels (insertion order)
  → segments_for_row() + upsert per row
  → KronaNode root
```

### 5.2 Levels helper

```python
def krona_levels(tax_rank: str) -> tuple[str, ...]:
    """dedupe preserving order: [tax_rank, genus, species]."""
    seen: set[str] = set()
    out: list[str] = []
    for r in (tax_rank, "genus", "species"):
        if r not in seen:
            seen.add(r)
            out.append(r)
    return tuple(out)
```

Examples: `phylum` → `('phylum', 'genus', 'species')`; `genus` → `('genus', 'species')`; `species` → `('species',)`.

### 5.3 SQL — single query (PIVOT + name + ORDER BY)

Python builds dynamic rank lists from `krona_levels(tax_rank)` via `_sql_in_list()` (same helper as chord). Both the bridge `WHERE requested_rank IN (...)` and the `PIVOT ... FOR requested_rank IN (...)` clauses use the same list.

```sql
WITH totals AS (
    SELECT source_tax_id, SUM(value) AS total
    FROM int_rpkm_by_ec_tax
    GROUP BY source_tax_id
    HAVING SUM(value) > 0
),
named AS (
    SELECT
        t.source_tax_id,
        t.total,
        COALESCE(n.name, CAST(t.source_tax_id AS VARCHAR)) AS name
    FROM totals t
    LEFT JOIN read_parquet('<resources/db/parquet/names.parquet>') n
           ON t.source_tax_id = n.tax_id
),
bridge_gated AS (
    SELECT
        source_tax_id,
        requested_rank,
        CASE
            WHEN resolved_tax_rank = requested_rank
            THEN resolved_tax_label
        END AS label
    FROM read_parquet('<bridge_tax_rollup>')
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
    d.name,
    d.total,
    w.*
FROM named d
LEFT JOIN bridge_wide w USING (source_tax_id)
ORDER BY
    COALESCE(w.phylum, 'Unclassified ' || d.name),
    COALESCE(w.genus, ''),
    d.name
```

**Dynamic ranks:** `{rank_in}` is injected for both filter and pivot (e.g. `'phylum', 'genus', 'species'`). When `tax_rank = 'genus'`, pivot columns are only `genus` and `species`; `ORDER BY` uses only those rank columns + `name`.

**Exact-rank gating:** bridge `'Unclassified'` and coarser fallbacks become `NULL` in pivot columns → Python treats as missing next rank (early leaf).

### 5.4 Python tree builder — single-pass upsert

No recursive port of `parse_tax_tree`. Each SQL row (already ordered) becomes an ordered path of segments; the **last segment is always the leaf**.

#### 5.4.1 Segment type

```python
@dataclass
class Segment:
    id: str
    label: str
    value: float | None = None  # set on leaf (last segment) only
```

Internal segment: `value is None`. Leaf segment: `value = row.total`.

#### 5.4.2 `segments_for_row(row, levels)`

```python
def segments_for_row(row, levels: tuple[str, ...]) -> list[Segment]:
    segments: list[Segment] = []
    for i, rank in enumerate(levels):
        is_last = i == len(levels) - 1
        if is_last:
            return segments + [Segment(row.name, row.name, row.total)]

        rank_label = row[rank] if row[rank] else f"Unclassified {row.name}"
        if row[levels[i + 1]] is None:
            # early leaf — last segment of path
            if segments and row[rank]:
                # deeper stop: upsert current rank internal (e.g. Mammaliicoccus under Staphylococcus)
                segments.append(Segment(rank_label, rank_label))
            # first-rank stop: no internal prefix (e.g. 999999999, U_Bacteria under root)
            return segments + [Segment(row.name, f"U_{row.name}", row.total)]

        segments.append(Segment(rank_label, rank_label))

    raise RuntimeError("unreachable")
```

**Shared internals across rows:** a later row may upsert into an internal node created by an earlier row (e.g. `Staphylococcus` internal exists before `U_Mammaliicoccus sciuri` is inserted beneath it).

#### 5.4.3 `add_mass` and upsert loop

```python
def add_mass(node: KronaNode, value: float, grand_total: float) -> None:
    node.subtotal += value
    node.percentage = node.subtotal / grand_total


grand_total = sum(row.total for row in rows)
root = KronaNode(id="root", label="root", children=[], subtotal=0.0, percentage=0.0)

for row in rows:
    path = segments_for_row(row, levels)
    node = root
    add_mass(root, row.total, grand_total)
    for seg in path[:-1]:
        node = upsert_child(node, seg)
        add_mass(node, row.total, grand_total)
    leaf = path[-1]
    upsert_leaf(node, leaf)  # id, label, value; percentage = value / grand_total

root.percentage = 1.0
```

- `upsert_child`: find existing child by `id`, else append (preserves SQL encounter order).
- `upsert_leaf`: append leaf under current node (one leaf per `name`); set `percentage = value / grand_total`.
- **`add_mass` applies to root and internal nodes only.** Leaf `percentage` is set directly from `value`.
- Internal **`percentage` may be partial mid-insert**; correct after all rows. No finalize pass.

### 5.5 Sample lookup

`sample_id = sample_id_from_names(body.names)` — reuses `api/filters.py` helper (strip `.tsv` extension).

## 6. Documented Deviations from Legacy

| Area | Legacy (Node) | Analytics API path |
|---|---|---|
| Tax lookup | SQLite `get_parents_at_level` — exact rank via `parents.t_{rank}` | `bridge_tax_rollup` with **exact-rank gating** in SQL |
| Display names | `add_data` → `get_name_from_id` on upload | `COALESCE(names.name, source_tax_id)` in SQL |
| Comparison mode | `get_delta` for two files | Not supported (v1) |
| Taxon filter | `subset_data` column filter | Error if non-empty filter passed |
| Sibling order | First-encounter column order, then D3 re-sorted by value | SQL `ORDER BY` rank labels; D3 preserves order (`hierarchy.sort(null)`) |
| Unknown-header tax_ids | Raw id as `name`; `U_{name}` when early leaf | Same via names fallback |

### 6.1 `'Unclassified'` grouping

When a rank label is `NULL` after gating, internal grouping uses `Unclassified {name}` (matches legacy `group_tax_tree_at_level`). Bridge `'Unclassified'` labels are never copied into pivot columns.

## 7. Repository Layout (additions)

```
analytics/
├── api/
│   ├── main.py                     # add POST /api/viz/krona
│   ├── krona_service.py            # build_krona_from_duckdb(), upsert tree builder
│   ├── filters.py                  # add krona_levels()
│   ├── schemas.py                  # add KronaRequest, KronaNode
│   └── tests/
│       ├── fixtures/
│       │   └── krona_expectations.yaml
│       └── test_krona_service.py
└── testing/
    └── dump_fake_rpkm_expectations.py   # extend to dump krona goldens

src/server/
└── index.ts                        # move krona to sidecarRoutes

src/renderer/src/
├── vizBackend.ts                   # add 'krona' to MIGRATED_CHANNELS
└── components/Krona.tsx            # hierarchy.sort(null)
```

## 8. Testing

### 8.1 Golden tests

Reuse shared `fake_rpkm` fixture (`analytics/conftest.py`, `testing/fake_rpkm_fixture.py`):

| Asset | Purpose |
|---|---|
| `krona_expectations.yaml` | Expected tree(s) for `fake_rpkm` at 2–3 `tax_rank` values (e.g. `phylum`, `genus`); leaf `id`s are **scientific names** |
| `test_krona_service.py` | Parametrized pytest via `build_krona_from_duckdb()` |
| `dump_fake_rpkm_expectations.py` | Regenerate YAML after fixture or tree-logic changes |

Tests skip when bridges/sample.duckdb/names Parquet unavailable (same guard as chord/overview).

Tree comparison: deep equality on nested `{ id, label, value?, children?, percentage }` structure; float tolerance on `value` / `percentage`.

Golden source of truth: legacy `POST /api/viz/krona` on loaded `fake_rpkm.tsv` (captures name-based leaf ids).

### 8.2 Express sidecar proxy tests

Extend `fastapi_sidecar_proxy.test.ts`:

- Default (no query param) → legacy handler
- `?backend=duckdb` → fetch to `ANALYTICS_API_URL` + route path
- Fetch failure → error envelope with `"krona analytics API unavailable"` prefix

### 8.3 Node integration test

Existing `API /api/viz/krona` test in `src/tests/server.test.ts` (if present) continues to exercise legacy path (no query param).

## 9. Development Workflow

### 9.1 Prerequisites

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id fake_rpkm \
  --rpkm-path transform/tests/fixtures/fake_rpkm.tsv \
  --tax-rank phylum \
  --pathway-level superpathway
```

### 9.2 Running locally

```bash
# Terminal 1 — FastAPI sidecar
cd analytics && uv run uvicorn api.main:app --port 8001

# Terminal 2 — Express + Vite
npm run dev

# Browser console — opt out to legacy Node (migrated channels: chord, overview, krona)
localStorage.setItem('vizBackend', 'legacy')

# Via Express proxy — curl equivalent
curl -X POST 'http://localhost:3001/api/viz/krona?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{"names": ["fake_rpkm.tsv"], "tax_rank": "phylum", "selected_taxon": {}}'
```

## 10. Implementation Checklist

- [ ] `analytics/api/filters.py` — `krona_levels(tax_rank)`
- [ ] `analytics/api/krona_service.py` — `build_krona_from_duckdb()`, PIVOT query, upsert tree builder
- [ ] `analytics/api/schemas.py` — `KronaRequest`, `KronaNode`
- [ ] `analytics/api/main.py` — `POST /api/viz/krona`
- [ ] `krona_expectations.yaml` + `test_krona_service.py` (scientific-name leaf ids)
- [ ] `src/server/index.ts` — krona sidecar route
- [ ] `src/renderer/src/vizBackend.ts` — add `'krona'` to `MIGRATED_CHANNELS`
- [ ] `src/renderer/src/components/Krona.tsx` — `hierarchy.sort(null)`
- [ ] Proxy unit tests (krona label)
- [ ] Extend `dump_fake_rpkm_expectations.py`
