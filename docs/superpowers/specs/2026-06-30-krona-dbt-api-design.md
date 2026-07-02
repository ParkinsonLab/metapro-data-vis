# Krona API via dbt Intermediates — Design Spec

> **Status:** Draft (2026-06-30; revised — upsert tree builder, PIVOT SQL, `name` via names lookup, lineage segments)  
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
| Tree builder | **Single-pass upsert** — one SQL row → lineage segments → upsert | Simpler than porting recursive `parse_tax_tree`; shared internals emerge when siblings share a prefix |
| Path model | **`lineage_segments()`** returns an ordered rank path; **last segment is always the leaf** | Internal and leaf nodes share one segment type; leaf flagged with `is_leaf=True` |
| Tree levels | `dedupe([tax_rank, 'genus', 'species'])` | Matches legacy `parse_krona` |
| Ancestry exactness | SQL returns rank label **only when `resolved_tax_rank = requested_rank`**; else `NULL` | Preserves legacy early-leaf depth; avoids bridge `'Unclassified'` in grouping |
| Column `name` | SQL row field **`name`** = `COALESCE(names.name, CAST(source_tax_id AS VARCHAR))` | Matches legacy `get_name_from_id`; not a new term — same as `names.name` / renamed column header |
| Leaf `id` | `name` | Matches legacy column key after `add_data` rename |
| Early-leaf `label` | `U_{name}` | Matches legacy (`U_` prefixes leaf's own `id`, not parent label) |
| Species-leaf `label` | same as `id` (= `name`) | Matches legacy |
| Early-leaf grouping | If `taxon[rank]` resolved, append **internal at current rank** before `U_{name}` leaf — even at first rank | Early stop joins existing phylum bucket (e.g. `Bacillota` internal shared with taxa that have genus); only skip internal when `taxon[rank]` is NULL |
| Sibling ordering | SQL `ORDER BY` → upsert append order = **sunburst arc order** (`hierarchy.sort(null)`) | Rank columns ASC; leaf tie-break `COALESCE(w.species, d.name)` |
| Sunburst layout | Clockwise in **`children` array order** (D3 `hierarchy.sort(null)`) | Insertion order is display order; not re-sorted by value |
| Percentages | **`upsert_segment`** accumulates `subtotal` on internals; sets leaf `percentage` from `value` | Correct after all rows; no finalize pass |
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

**Deferred:** Generic `Envelope[T]` on `wrap_handler` (typed `value` per endpoint, OpenAPI `response_model`) is out of scope for this PR — same untyped envelope as chord/overview. Track as a follow-up shared analytics-API refactor.

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
  → lineage_segments() + upsert per taxon
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
    COALESCE(w.species, d.name)
```

**`ORDER BY` = sunburst arc order:** upsert appends children in SQL row order; `Krona.tsx` uses `hierarchy.sort(null)`, so **`ORDER BY` is the pie layout contract**. Python builds this clause dynamically from `krona_levels(tax_rank)` (same as `{rank_in}`):

1. **Each rank column ASC** (`w.phylum`, `w.genus`, …) — internal siblings alphabetical at that level. First rank uses `'Unclassified ' || d.name` fallback; deeper ranks use `''`.
2. **Final key `COALESCE(w.species, d.name) ASC`** — leaf sibling order within the deepest resolved rank. Use **`w.species`** when exact-rank gating resolves species (the label the tree places at species depth). Fall back to **`d.name`** when `w.species IS NULL` (early `U_{name}` leaves and columns whose `names.name` is not a species string — genus-level tax_id, unknown header, etc.).

Do **not** sort leaves by `d.name` alone — `d.name` is the column display name from `names` lookup and may be any rank, not necessarily species.

**Exact-rank gating:** bridge `'Unclassified'` and coarser fallbacks become `NULL` in pivot columns → Python treats as missing next rank (early leaf).

### 5.4 Python tree builder — single-pass upsert

No recursive port of `parse_tax_tree`. Each SQL row (already ordered) becomes a lineage of segments via `lineage_segments()`; the **last segment is always the leaf**.

#### 5.4.1 Segment type

```python
@dataclass
class Segment:
    id: str
    label: str
    is_leaf: bool = False
```

Internal segment: `is_leaf=False` (default). Leaf segment: `is_leaf=True`. Wedge amounts come from `taxon_value` in `upsert_segment`, not from `Segment`.

#### 5.4.2 `lineage_segments(taxon, levels)`

Build the ordered rank-by-rank lineage for one SQL result record (one `source_tax_id`) — internals at resolved ranks, leaf last.

```python
def lineage_segments(taxon, levels: tuple[str, ...]) -> list[Segment]:
    segments: list[Segment] = []
    for i, rank in enumerate(levels):
        is_last = i == len(levels) - 1
        if is_last:
            return segments + [Segment(taxon.name, taxon.name, is_leaf=True)]

        rank_label = taxon[rank] if taxon[rank] else f"Unclassified {taxon.name}"
        if taxon[levels[i + 1]] is None:
            # Next rank unavailable — path ends with early leaf (label U_{name}).
            if taxon[rank]:
                # Current rank resolved exactly (exact-rank gating): add internal so
                # early leaves share the bucket with taxa that continue deeper
                # (e.g. Bacillota internal, then U_{name}; not Bacillota and U_{name} both at root).
                segments.append(Segment(rank_label, rank_label))
            # taxon[rank] NULL: leaf attaches at current depth only (e.g. 999999999 under root).
            return segments + [Segment(taxon.name, f"U_{taxon.name}", is_leaf=True)]

        segments.append(Segment(rank_label, rank_label))

    raise RuntimeError("unreachable")
```

**Early-leaf branch:** when the next rank is `NULL`, append internal at **current** rank if `taxon[rank]` is set (exact-rank match from SQL), then return the `U_{name}` leaf as the final segment. **`if taxon[rank]:` only** — no `i > 0` guard: exact-rank gating prevents kingdom/domain fallback (e.g. Bacteria) from populating `taxon[phylum]`, while true phylum matches (e.g. Bacillota with null genus) must create `Internal(Bacillota)` so upsert merges with sibling taxa that have genera beneath the same phylum.

| `taxon[phylum]` | `taxon[genus]` | Path segments |
|---|---|---|
| null | (any) | `[Leaf U_{name}]` under root |
| Bacillota | null | `[Internal(Bacillota), Leaf U_{name}]` |
| Bacillota | Staphylococcus (species null) | `[Internal(Bacillota), Internal(Staphylococcus), Leaf U_{name}]` |

**Shared internals across rows:** upsert merges paths — e.g. `Bacillota` internal created by one taxon is reused when another stops early under the same phylum.

#### 5.4.3 `upsert_segment` and main loop

`Segment.is_leaf` distinguishes leaf from internal segments. All wedge amounts come from **`taxon_value`** — the SQL `total` for one `source_tax_id` (summed RPKM across ECs for that tax column). Accumulation is **inside** `upsert_segment` (no separate helper).

**What the query guarantees (and does not):**

| Invariant | Guaranteed? | Why |
|---|---|---|
| One SQL row per `source_tax_id` | Yes | `totals` CTE `GROUP BY source_tax_id` |
| One SQL row per leaf `name` | **No** | `name` comes from `names` lookup; different `tax_id`s can share the same string (e.g. `"Cavernicola"` → 3 tax_ids in `names.parquet`) |
| Unique leaf `id` among siblings | **No** | two columns with the same display `name` can land under the same parent |

**No internal/leaf `id` collision among siblings:** when an early leaf fires and `taxon[rank]` is set, `lineage_segments` appends an internal at that rank and places the `U_{name}` leaf **one level below** it (e.g. `[Internal(Bacillota), Leaf U_{name}]`, not both at the same depth). A genus-named column whose bridge resolves `taxon[genus]` stops at genus, producing `[Internal(Bacillota), Internal(Staphylococcus), Leaf U_{Staphylococcus}]` — the leaf is a child of `Internal(Staphylococcus)`, not its sibling. Rank-label internals and `U_{name}` leaves therefore never compete for the same slot in `parent.children`.

The naive `c.id == seg.id` lookup still fails for **duplicate leaf `id`:** a second row with the same `name` under the same parent hits an existing leaf and returns without merging `taxon_value` → data loss.

**Matching rule:** `id`-only lookup (sibling kind is unambiguous). Duplicate leaves merge `value`; duplicate internals merge `subtotal`.

```python
def upsert_segment(
    parent: KronaNode, seg: Segment, taxon_value: float, grand_total: float
) -> KronaNode:
    existing = next((c for c in parent.children if c.id == seg.id), None)

    if seg.is_leaf:
        if existing is not None:
            existing.value += taxon_value
            existing.percentage = existing.value / grand_total
            return existing
        child = KronaNode(
            id=seg.id,
            label=seg.label,
            value=taxon_value,
            percentage=taxon_value / grand_total,
        )
    else:
        if existing is not None:
            existing.subtotal += taxon_value
            existing.percentage = existing.subtotal / grand_total
            return existing
        child = KronaNode(
            id=seg.id,
            label=seg.label,
            children=[],
            subtotal=taxon_value,
            percentage=taxon_value / grand_total,
        )

    parent.children.append(child)
    return child


taxa = ...  # ordered SQL query result — one record per source_tax_id
grand_total = sum(t.total for t in taxa)
root = KronaNode(
    id="root",
    label="root",
    children=[],
    subtotal=grand_total,
    percentage=1.0,
)

for taxon in taxa:
    segments = lineage_segments(taxon, levels)
    node = root
    for seg in segments:
        node = upsert_segment(node, seg, taxon.total, grand_total)
```

- **Root** is initialized with `subtotal=grand_total` and `percentage=1.0` — never updated in the loop.
- **Internals:** `subtotal` / `percentage` updated on every row that walks through (new or existing node); each row contributes its full `taxon_value` at every internal on the path.
- **Leaves:** `value = taxon_value` at creation; duplicate leaf `id` under the same parent merges `taxon_value` (covers same `name` from different `source_tax_id`s).
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
| Sibling order | First-encounter column order, then D3 re-sorted by value | SQL `ORDER BY` → insertion order = sunburst arcs; leaves by `COALESCE(w.species, d.name)` |
| Unknown-header tax_ids | Raw id as `name`; `U_{name}` when early leaf | Same via names fallback |
| Early leaf under resolved rank | Legacy `no_children` may return leaf direct to root even when rank label exists (SQLite backfill) | **`if taxon[rank]:`** adds internal at current rank before `U_{name}` leaf — groups under phylum/genus bucket |
| Kingdom/domain columns (e.g. tax_id `2`) | SQLite backfill may self-match `"Bacteria"` at phylum rank → legacy `U_Bacteria` direct under root | Exact-rank gating leaves `taxon[phylum]` NULL → `[Leaf U_Bacteria]` under root (same shape, different reason) |

### 6.1 `'Unclassified'` grouping

When a rank label is `NULL` after gating, internal grouping uses `Unclassified {name}` (matches legacy `group_tax_tree_at_level`). Bridge `'Unclassified'` labels are never copied into pivot columns.

### 6.2 Watch: early `U_{name}` vs full depth (verify during implementation)

Legacy may emit `U_{name}` when the **next** rank is missing in SQLite ancestry (e.g. a species-named column grouped under the wrong genus internal with `U_Mammaliicoccus sciuri`). Bridge + exact-rank gating may resolve phylum → genus → species for the same tax_id when `resolved_tax_rank = 'species'` matches.

**Expectation to validate:** if all three rank columns are non-null for a taxon, `lineage_segments` should produce `[phylum internal, genus internal, species leaf with label = name]` — not an early `U_{name}` leaf.

**During golden test setup:** compare legacy vs analytics API trees for columns where bridge resolves full species ancestry. Document any intentional divergence in `krona_expectations.yaml` comments. Do not blindly match legacy `U_` placement if bridge data supports a deeper correct path.

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
