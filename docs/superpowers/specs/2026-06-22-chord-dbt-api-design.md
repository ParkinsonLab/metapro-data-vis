# Chord API via dbt Intermediates — Design Spec

> **Status:** Draft (2026-06-22)  
> **Goal:** Reimplement `POST /api/viz/chord` to derive the chord diagram from precomputed dbt intermediate tables (`int_tax_rollup_resolved`) in `runs/{sample_id}/sample.duckdb`, preserving the existing JSON contract so no frontend changes are required. Legacy Node implementation remains the default; opt-in via query param.

**Parent pipeline:** `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` (branch `feature/rpkm-transform`).

**Work isolation:** Branch `feature/chord-dbt-api` in worktree `.worktrees/chord-dbt-api/`, forked from `feature/rpkm-transform`.

## 1. Context

Metapro Viz renders a chord diagram from `{ count_matrix, index, colors, tax_map, ann_map }`. Today the Express handler `parse_ec_chord` (`src/server/data_functions.ts`) loads wide TSV data in memory, applies tax/pathway filters, and builds a symmetric matrix via `parse_ec_data` (`src/server/parse.ts`).

The rpkm-transform pipeline (`analytics/transform/`) materialises `int_tax_rollup_resolved` with all 7 taxonomy ranks and 3 pathway levels pre-joined. The mart model `mart_pathway_taxonomy_long` applies the same aggregation the chord needs — filter `int_tax_rollup_resolved` by `(requested_rank, pathway_level)`, then `GROUP BY (pathway_key, resolved_tax_id)` and `SUM(value)`.

**Key insight:** Every chord request parameter is a **pre-aggregation filter** on `int_tax_rollup_resolved`. The mart is the aggregation *shape*, not necessarily a table read on every request. At query time the FastAPI service applies all request filters, runs the mart-equivalent GROUP BY, and passes the result to `build_chord_matrix()`.

**Assumption (in scope):** `int_tax_rollup_resolved` is already materialised in `runs/{sample_id}/sample.duckdb` before the chord endpoint is invoked.

**Out of scope (this spec):**

- Upload endpoint that ingests RPKM and triggers `dbt build --select stg_rpkm_long+`
- Comparison mode (`names.length > 1`) on the DuckDB backend
- Retiring the legacy Node implementation
- Reading or updating `run_context.json` (skipped for simplicity)

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| API contract | Unchanged request body + `{ ok, value }` envelope | No frontend changes |
| Default backend | Legacy Node `parse_ec_chord` | Safe rollout |
| Opt-in backend | `POST /api/viz/chord?backend=duckdb` | Explicit testing switch; no env var |
| Integration | Express sidecar proxy → FastAPI on separate port | dbt ecosystem lives in Python; Express keeps single URL |
| Data source | Query `int_tax_rollup_resolved` at request time | All ranks/levels precomputed; no mart rebuild or `run_context.json` |
| Aggregation | Mart-equivalent GROUP BY after runtime filters | Shared logic with `mart_pathway_taxonomy_long` via dbt macro |
| Sample lookup (v1 interim) | `sample_id = strip_extension(names[0])` → `runs/{sample_id}/sample.duckdb` | Matches `run_pipeline.py --sample-id test_rpkm_1`; upload integration defines final filename mapping later |
| Comparison mode | Error on duckdb path when `names.length > 1` | Deferred follow-up |
| Matrix assembly | Python `build_chord_matrix()` (not dbt) | Symmetric matrix, gap fillers, HSL colors — UI-specific logic |

## 3. Architecture

```
┌─────────────┐     POST /api/viz/chord          ┌──────────────┐
│   React     │ ─────────────────────────────► │   Express    │
│  (unchanged)│     (no query param = legacy)   │   :3001      │
└─────────────┘                                 └──────┬───────┘
                                                       │
                         ?backend=duckdb               │
                         ─────────────────────────────►│ proxy ──────┐
                                                       │             │
                                                       ▼             ▼
                                              legacy in-process   ┌──────────────┐
                                                                  │   FastAPI    │
                                                                  │   :8001      │
                                                                  └──────┬───────┘
                                                                         │
                                                                         ▼
                                                              runs/{sample_id}/sample.duckdb
                                                              int_tax_rollup_resolved
                                                              (+ bridge_ec_pathway for ann filter)
```

| Component | Location | Role |
|---|---|---|
| Express router switch | `src/server/chord_handler.ts` | Default → legacy; `?backend=duckdb` → HTTP proxy to FastAPI |
| FastAPI app | `analytics/api/main.py` | Chord endpoint service |
| Query + matrix | `analytics/api/chord_service.py` | Runtime SQL filters, mart aggregation, `build_chord_matrix()` |
| Shared SQL macro | `analytics/transform/macros/mart_pathway_taxonomy_agg.sql` | Mart model + API query share GROUP BY logic |
| DuckDB access | read-only attach/open `sample.duckdb` | No writes at request time |

**FastAPI port:** `8001` (configurable via `CHORD_API_PORT` env on Express proxy side only; FastAPI binds via uvicorn `--port`).

## 4. Request / Response Contract

### 4.1 Request (unchanged JSON body)

```json
{
  "names": ["test_rpkm_1.tsv"],
  "tax_level": "phylum",
  "ann_level": "superpathway",
  "selected_ann_cat": {},
  "selected_taxon": {}
}
```

| Field | Type | DuckDB semantics |
|---|---|---|
| `names` | `string[]` | Single sample only on duckdb path; `sample_id = names[0]` with `.tsv` stripped |
| `tax_level` | `string` | `requested_rank = tax_level` — display/rollup rank |
| `ann_level` | `string` | `pathway_level = ann_level` (`superpathway` \| `pathway`) |
| `selected_ann_cat` | `{}` \| `string` \| `{ level, name }` | Pathway subset filter (see §5.2) |
| `selected_taxon` | `{}` \| `{ level, name }` | Taxonomy subset filter on `source_tax_id` (see §5.3) |

### 4.2 Response (unchanged)

```json
{
  "ok": true,
  "value": {
    "count_matrix": [[0, 1, ...], ...],
    "index": ["gap_1", "...", "gap_2", "...", "gap_3"],
    "colors": { "CategoryA": "hsl(0 75 50)", ... },
    "tax_map": {},
    "ann_map": {}
  }
}
```

Frontend (`Chord.tsx`) consumes `count_matrix`, `index`, `colors` only. `tax_map` and `ann_map` are included for contract parity; may be `{}` in v1 unless an EC-grain side query is added.

### 4.3 Errors (duckdb path)

| Condition | HTTP | `{ ok: false, error }` |
|---|---|---|
| `names.length > 1` | 200 (envelope) | `"comparison mode not supported on duckdb backend"` |
| DuckDB file missing | 200 | `"sample not found: {sample_id}"` |
| `int_tax_rollup_resolved` missing | 200 | `"int_tax_rollup_resolved not materialized for sample: {sample_id}"` |
| FastAPI unreachable | 200 | `"chord duckdb backend unavailable: ..."` |
| Invalid `tax_level` / `ann_level` | 200 | `"invalid tax_level: ..."` / `"invalid ann_level: ..."` |

Express always returns HTTP 200 with envelope (matches existing pattern).

## 5. Data Flow

### 5.1 Pipeline

```
int_tax_rollup_resolved
  → runtime WHERE (tax_level, ann_level, selected_ann_cat, selected_taxon)
  → mart-equivalent GROUP BY (pathway_key, resolved_tax_id)
  → build_chord_matrix(pathway_label, resolved_tax_label, value)
  → JSON response
```

No dbt invocation at request time. No `run_context.json` read. Rank/level changes are free because all ranks and pathway levels are already in `int_tax_rollup_resolved`.

### 5.2 Annotation filter (`selected_ann_cat`)

Normalise input:

- `{}`, `""`, or missing → no filter
- `string` → treat as `{ level: ann_level, name: string }` when `ann_level === 'superpathway'`, or as superpathway name when `ann_level === 'pathway'` (matches Chord UI arc-click behaviour)
- `{ level, name }` → use as-is

| `ann_level` | Filter predicate |
|---|---|
| `superpathway` | `COALESCE(pathway_label, 'Unmapped EC') = :ann_name` |
| `pathway` | Join `bridge_ec_pathway` on `pathway_key = CAST(pathway_id AS VARCHAR)` where `superpathway_name = :ann_name` when filter is a superpathway selection; if filter level is `pathway`, match `pathway_name = :ann_name` directly |

When `ann_level = pathway` and the user selects a superpathway from the chord outer ring, the filter restricts to pathway rows whose parent superpathway matches — equivalent to legacy `subset_ec({ level: 'superpathway', name })` then filtering rows by EC membership (achieved here via pathway hierarchy in `bridge_ec_pathway`).

### 5.3 Taxonomy filter (`selected_taxon`)

When `{ level, name }` is set (both truthy):

```sql
source_tax_id IN (
  SELECT DISTINCT source_tax_id
  FROM int_tax_rollup_resolved
  WHERE requested_rank = :filter_level
    AND resolved_tax_label = :filter_name
)
```

The main query still uses `requested_rank = :tax_level` for display aggregation. This mirrors legacy `subset_data`: filter tax columns at the filter rank, aggregate at the display rank.

When unset: no taxon filter.

### 5.4 Mart-equivalent aggregation SQL

```sql
SELECT
    pathway_key,
    ANY_VALUE(COALESCE(pathway_label, 'Unmapped EC')) AS pathway_label,
    resolved_tax_id,
    ANY_VALUE(resolved_tax_label)                       AS resolved_tax_label,
    SUM(value)                                          AS value
FROM filtered_int_rows
GROUP BY pathway_key, resolved_tax_id
HAVING SUM(value) > 0
```

Refactor into dbt macro `mart_pathway_taxonomy_agg(filtered_relation)` used by:

- `mart_pathway_taxonomy_long.sql` — wraps `int_tax_rollup_resolved` with `WHERE requested_rank = var('tax_rank') AND pathway_level = var('pathway_level')` only (pipeline/tests, unfiltered case)
- FastAPI — wraps runtime-filtered subset of `int_tax_rollup_resolved`

### 5.5 Chord matrix assembly (`build_chord_matrix`)

Python port of `src/server/parse.ts` logic:

1. Collect unique sorted `pathway_label` (annotation categories) and `resolved_tax_label` (tax categories)
2. Build `index = ['gap_1'] + ann_cats + ['gap_2'] + tax_cats + ['gap_3']`
3. Accumulate symmetric `count_matrix[i][j]` and `count_matrix[j][i]` from `(pathway_label, resolved_tax_label, value)` pairs
4. Apply gap fillers: `gap_2[i][i] = flat_sum/2`, others `flat_sum/4` (matches `add_filler_value`)
5. Assign HSL colors via `get_color(i, n)` matching `src/server/utils.ts`: `` `hsl(${Math.trunc((360 / (n + 1)) * i)} 75 50)` ``

## 6. Documented Deviations from Legacy

These are expected per rpkm-transform semantics, not bugs:

| Area | Legacy (Node) | DuckDB path |
|---|---|---|
| Tax rollup | `get_parents_at_level` — exact rank only | `bridge_tax_rollup` — exact → coarser fallback → `Unclassified` |
| Unmapped ECs | `0.0.0.0` / SQLite pathway map | `pathway_key IS NULL` → label `'Unmapped EC'` |
| Comparison mode | `get_delta` for two files | Not supported (v1) |
| `ann_map` | Full EC → pathway map from SQLite | `{}` in v1 (frontend does not consume it) |
| Sample resolution | In-memory `data[filename]` | Pre-built DuckDB; v1 interim strip-extension mapping |

## 7. Repository Layout (additions)

```
analytics/
├── pyproject.toml              # add fastapi, uvicorn, httpx
├── api/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app, POST /chord
│   ├── chord_service.py        # filters, SQL, build_chord_matrix
│   ├── colors.py               # get_color port
│   └── schemas.py              # Pydantic request/response models
└── transform/
    └── macros/
        └── mart_pathway_taxonomy_agg.sql   # shared with mart model

src/server/
├── chord_handler.ts            # legacy vs proxy switch
└── index.ts                    # wire chord_handler for /api/viz/chord
```

## 8. Development Workflow

### 8.1 Prerequisites

1. `feature/rpkm-transform` pipeline already run for test sample:
   ```bash
   cd analytics
   uv run python transform/scripts/run_pipeline.py \
     --sample-id test_rpkm_1 \
     --rpkm-path ../resources/example_data/test_rpkm_1.tsv \
     --tax-rank phylum \
     --pathway-level superpathway
   ```
2. Produces `analytics/transform/runs/test_rpkm_1/sample.duckdb` with `int_tax_rollup_resolved`.

### 8.2 Running locally

```bash
# Terminal 1 — FastAPI sidecar
cd analytics && uv run uvicorn api.main:app --port 8001

# Terminal 2 — Express
npm run dev:server

# Manual test (duckdb backend)
curl -X POST 'http://localhost:3001/api/viz/chord?backend=duckdb' \
  -H 'Content-Type: application/json' \
  -d '{
    "names": ["test_rpkm_1.tsv"],
    "tax_level": "phylum",
    "ann_level": "superpathway",
    "selected_ann_cat": {},
    "selected_taxon": {}
  }'
```

## 9. Testing Strategy

| Layer | Scope |
|---|---|
| Python unit | `build_chord_matrix()` on synthetic pairs; gap filler math; color strings; filter normalisation |
| Python integration | Open `runs/test_rpkm_1/sample.duckdb`; assert matrix shape, index structure, non-negative values |
| Python SQL | Taxon filter + ann filter predicates return expected row counts on fixture |
| Express | Proxy forwards to FastAPI; default route still calls legacy; envelope shape preserved |
| Parity script (optional) | Compare legacy vs duckdb for same params; document expected rollup deltas |

## 10. Future Considerations

- **Upload integration:** `/api/data` triggers dbt ingest; filename → `sample_id` mapping replaces strip-extension interim
- **Comparison mode:** delta two samples via attached DuckDB files (rpkm-transform spec §12)
- **Retire legacy:** flip default once parity validated; remove `?backend=duckdb` gate
- **`ann_map` population:** EC-grain query from `int_rpkm_pathway` if needed downstream
- **Frontend re-fetch:** restore `useEffect` on rank/filter changes (currently commented out in `App.tsx`) — independent of this backend work

## 11. Success Criteria

- [ ] Worktree `feature/chord-dbt-api` branched from `feature/rpkm-transform`
- [ ] FastAPI service returns valid chord JSON from `runs/test_rpkm_1/sample.duckdb`
- [ ] Express default path unchanged (legacy); `?backend=duckdb` proxies successfully
- [ ] Runtime rank/level change works without dbt rebuild (query different `requested_rank` / `pathway_level`)
- [ ] `selected_ann_cat` and `selected_taxon` filters reduce matrix as expected
- [ ] dbt macro shared between mart model and documented API query shape
- [ ] Python tests pass; existing Node tests unaffected

## 12. References

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, mart semantics, bridge rollup
- `src/server/parse.ts`, `src/server/data_functions.ts` — legacy chord behaviour (parity reference)
- `src/renderer/src/components/Chord.tsx` — frontend consumption (`count_matrix`, `index`, `colors`)
- `analytics/transform/models/marts/mart_pathway_taxonomy_long.sql` — aggregation shape to share via macro
