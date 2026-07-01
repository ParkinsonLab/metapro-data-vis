# Krona API via dbt Intermediates — Design Spec

> **Status:** Draft (2026-06-30)  
> **Goal:** Reimplement `POST /api/viz/krona` to derive the Krona sunburst taxonomy tree from precomputed dbt intermediate tables (`int_rpkm_by_ec_tax` + `bridge_tax_rollup`) in `runs/{sample_id}/sample.duckdb`, preserving the existing JSON contract. Express keeps legacy handlers when `?backend=duckdb` is absent; the renderer defaults migrated channels to the FastAPI sidecar.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, `int_rpkm_by_ec_tax`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — sidecar proxy pattern, envelope, sample lookup
- `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` — shared `fake_rpkm` fixture and YAML golden pattern
- `docs/superpowers/specs/2026-06-29-overview-dbt-api-design.md` — migration wiring, renderer toggle, golden-test pattern

## 1. Context

Metapro Viz renders a zoomable Krona sunburst of taxonomy (`Krona.tsx`, `d3.partition`). Today the Express handler `parse_krona` (`src/server/data_functions.ts`) loads wide TSV data in memory, sums RPKM **per tax column** (`source_tax_id`) across all ECs, and builds a nested tree via `get_parents_multilevel` → `parse_tax_tree` (`src/server/parse.ts`).

Tree depth is driven by `levels = dedupe([tax_rank, 'genus', 'species'])` — e.g. `phylum` → genus → species (3 levels under root). Leaves are always raw column ids (`source_tax_id` strings); internal nodes use resolved taxon names.

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
| Data source | `int_rpkm_by_ec_tax` for column totals; `bridge_tax_rollup` for multilevel ancestry | Krona sums per column, not pathway×taxonomy pairs; avoids rollup fan-out dedup |
| Tree levels | `dedupe([tax_rank, 'genus', 'species'])` | Matches legacy `parse_krona` |
| Ancestry exactness | SQL returns label **only when `resolved_tax_rank` matches requested rank**; else `NULL` | Preserves legacy early-leaf depth; avoids `'Unclassified'` bridge label in tree grouping |
| Leaf identity | `id` = `source_tax_id` string; `label` = `id` at species level, `U_{id}` on early leaf | Matches `parse_tax_tree_recursive` |
| Sibling ordering | Alphabetical by `label` ASC at each internal level | Predictable, testable; visible on sunburst |
| Sunburst layout | Clockwise in **`children` array order** (D3 `hierarchy.sort(null)`) | Backend ordering is visible; not re-sorted by value |
| Comparison mode | Error when `names.length > 1` | Deferred follow-up (same as chord/overview v1) |
| Taxon filter | Error when non-empty `{ level, name }` passed | Krona UI sends `{}` today; fail loudly rather than silently ignore |
| Error wording | Feature gaps say **"analytics API"**, not "duckdb backend" | Avoid implying DuckDB limitation |
| Verification | Golden tests: `krona_expectations.yaml` + parametrized pytest on `fake_rpkm` | Mirrors overview/chord golden pattern |
| Response typing | Pydantic `KronaNode` / `KronaResponse` models in Python | Documents contract; used in service return type and tests |
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
```

| Component | Location | Role |
|---|---|---|
| Migration proxy | `src/server/fastapi_sidecar_proxy.ts` | `createSidecarProxyHandler({ legacyHandler, apiPath, label: 'krona' })` |
| Express routes | `src/server/index.ts` | Move krona from `vizRoutes` → `sidecarRoutes` |
| FastAPI route | `analytics/api/main.py` | `POST /api/viz/krona` |
| Service | `analytics/api/krona_service.py` | DuckDB query + tree assembly |
| Schemas | `analytics/api/schemas.py` | `KronaRequest`, `KronaNode`, `KronaResponse` |
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

Root node:

```json
{
  "id": "root",
  "label": "root",
  "children": [ ... ],
  "percentage": 1.0
}
```

Internal nodes: `{ id, label, children, percentage }` — `id` = `label` = group name.

Leaf nodes: `{ id, label, value, percentage }` — no `children`.

| Leaf case | `id` | `label` |
|---|---|---|
| Species level reached (`levels` exhausted) | `source_tax_id` | same as `id` |
| Early leaf (`no_children`) | `source_tax_id` | `U_{source_tax_id}` |

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
| Bridge Parquet missing | 200 | `"bridge parquet missing: ..."` |
| FastAPI unreachable (Express proxy) | 200 | `"krona analytics API unavailable: ..."` |

## 5. Data Flow

### 5.1 Pipeline

```
int_rpkm_by_ec_tax
  → SUM(value) GROUP BY source_tax_id          # one total per TSV column
  → JOIN bridge_tax_rollup at krona_levels     # one row per column, nullable labels per rank
  → build_krona_tree() in Python               # port of parse_tax_tree_recursive
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

### 5.3 SQL — column totals + multilevel ancestry (single query)

**Open during implementation:** whether to use per-rank `CASE`/`MAX` columns or DuckDB `PIVOT` for fully dynamic rank columns. Both are acceptable; pick based on readability and test coverage. The contract is the **output shape**, not the SQL style.

**Required semantics:** for each rank `L` in `krona_levels(tax_rank)`, the query returns a nullable label column that is **non-null only when `resolved_tax_rank = L`** at the bridge row for `requested_rank = L`. Coarser fallbacks and `'Unclassified'` bridge labels must **not** appear in the label column — they become `NULL`, and Python applies the same rules as legacy (`no_children`, `Unclassified {id}` grouping).

Illustrative SQL (CASE style; ranks injected via `_sql_in_list(levels)`):

```sql
WITH totals AS (
    SELECT CAST(source_tax_id AS VARCHAR) AS source_tax_id,
           SUM(value) AS total
    FROM int_rpkm_by_ec_tax
    GROUP BY source_tax_id
    HAVING SUM(value) > 0
),
bridge AS (
    SELECT source_tax_id,
           requested_rank,
           resolved_tax_rank,
           resolved_tax_label
    FROM read_parquet('<bridge_tax_rollup>')
    WHERE requested_rank IN ({rank_in})   -- dynamic: krona_levels(tax_rank)
),
ancestry AS (
    SELECT source_tax_id,
           -- repeat per rank L in levels:
           MAX(CASE
               WHEN requested_rank = 'genus'
                AND resolved_tax_rank = 'genus'
               THEN resolved_tax_label
           END) AS genus
           -- , MAX(CASE WHEN requested_rank = 'phylum' AND resolved_tax_rank = 'phylum'
           --       THEN resolved_tax_label END) AS phylum
           -- , ...
    FROM bridge
    GROUP BY source_tax_id
)
SELECT t.source_tax_id, t.total, a.*
FROM totals t
LEFT JOIN ancestry a USING (source_tax_id)
```

Dynamic rank list: built in Python via existing `_sql_in_list()` (same helper as chord). Dynamic label columns: generated in Python from `krona_levels(tax_rank)` for either CASE or PIVOT approach.

### 5.4 Python tree builder

Port `parse_tax_tree` / `parse_tax_tree_recursive` / `group_tax_tree_at_level` from `src/server/parse.ts`:

**Input per column row:** `{ id: source_tax_id, total, <rank>: label | null for each rank in levels }`

**Grouping key at level L:** `row[L] if row[L] else f"Unclassified {row.id}"` (matches legacy `group_tax_tree_at_level`).

**Early leaf (`no_children`):** `len(subset) == 1 and not subset[0][levels[1]]` → leaf with `label = f"U_{id}"`.

**Species leaf:** `len(levels) == 0` → leaf with `label = id`.

**Sibling order:** sort `children` alphabetically by `label` ASC before returning each internal node.

**Root assembly:**

```python
def build_krona_tree(rows, levels: tuple[str, ...]) -> KronaNode:
    totals = {r.id: r.total for r in rows}
    grand_total = sum(totals.values())
    children = _build_level(rows, levels, grand_total)
    return KronaNode(id="root", label="root", children=children, percentage=1.0)
```

### 5.5 Sample lookup

`sample_id = sample_id_from_names(body.names)` — reuses `api/filters.py` helper (strip `.tsv` extension).

## 6. Documented Deviations from Legacy

| Area | Legacy (Node) | Analytics API path |
|---|---|---|
| Tax lookup | SQLite `get_parents_at_level` — exact rank via `parents.t_{rank}` | `bridge_tax_rollup` with **exact-rank gating** in SQL (`resolved_tax_rank = requested_rank`) |
| Comparison mode | `get_delta` for two files | Not supported (v1) |
| Taxon filter | `subset_data` column filter | Error if non-empty filter passed |
| Sibling order | First-encounter TSV column order, then D3 re-sorted by value | Alphabetical by sibling label; D3 preserves API order (`hierarchy.sort(null)`) |
| Unknown-header tax_ids | Included as columns; null ancestry → `Unclassified {id}` | Included in `int_rpkm_by_ec_tax`; null gated label → same grouping |

### 6.1 `'Unclassified'` label semantics

Bridge `'Unclassified'` (`resolved_tax_id IS NULL`) is **never surfaced** as an internal node label because SQL gates on `resolved_tax_rank = requested_rank` and `'Unclassified'` rows have `resolved_tax_rank IS NULL`. Columns with no exact match at a level get `NULL` → Python groups as `Unclassified {source_tax_id}`, matching legacy behavior for missing ancestry.

## 7. Repository Layout (additions)

```
analytics/
├── api/
│   ├── main.py                     # add POST /api/viz/krona
│   ├── krona_service.py            # build_krona_from_duckdb(), build_krona_tree()
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
| `krona_expectations.yaml` | Expected tree(s) for `fake_rpkm` at 2–3 `tax_rank` values (e.g. `phylum`, `genus`) |
| `test_krona_service.py` | Parametrized pytest via `build_krona_from_duckdb()` |
| `dump_fake_rpkm_expectations.py` | Regenerate YAML after fixture or tree-logic changes |

Tests skip when bridges/sample.duckdb unavailable (same guard as chord/overview).

Tree comparison: deep equality on nested `{ id, label, value?, children?, percentage }` structure; float tolerance on `value` / `percentage`.

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
- [ ] `analytics/api/krona_service.py` — `build_krona_from_duckdb()`, `build_krona_tree()`
- [ ] `analytics/api/schemas.py` — `KronaRequest`, `KronaNode`
- [ ] `analytics/api/main.py` — `POST /api/viz/krona`
- [ ] `krona_expectations.yaml` + `test_krona_service.py`
- [ ] `src/server/index.ts` — krona sidecar route
- [ ] `src/renderer/src/vizBackend.ts` — add `'krona'` to `MIGRATED_CHANNELS`
- [ ] `src/renderer/src/components/Krona.tsx` — `hierarchy.sort(null)`
- [ ] Proxy unit tests (krona label)
- [ ] Extend `dump_fake_rpkm_expectations.py`

## 11. Open Questions (resolve during implementation)

| Question | Options | Notes |
|---|---|---|
| Dynamic rank columns in SQL | Per-rank `CASE`/`MAX` generated in Python vs DuckDB `PIVOT` | Output contract identical either way; pick based on clarity and test ergonomics |
| Golden YAML tree depth | Full nested tree vs normalised flat node list | Full tree preferred for readability; flat list fallback if YAML gets unwieldy |
