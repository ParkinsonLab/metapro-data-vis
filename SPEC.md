# Metapro Viz — Functional Spec

> Living document. Reflects the state of the codebase as of the last edit; update when behavior changes.

## 1. Purpose

Metapro Viz is a web application that ingests RPKM (Reads Per Kilobase Million) output from [MetaPro](https://github.com/ParkinsonLab/MetaPro) — a metatranscriptomics pipeline — and renders five interactive visualizations of the relationship between **taxonomy** and **enzymatic / pathway annotation**: Overview, Krona (sunburst), Chord, Network, and Graph (3D scatter).

Two RPKM files can be loaded simultaneously; when both are selected, all visualizations switch to **delta mode** (`df_1 − df_2`) so users can compare two samples/conditions head-to-head.

## 2. Architecture

Browser + Express server app built with Vite (frontend) and Node (backend):

| Layer | Path | Responsibility |
|---|---|---|
| Server (Node/Express) | `src/server/` | TSV parsing, in-memory data store, SQLite-backed taxonomy/pathway lookups, all heavy aggregation; serves REST API and static frontend in production |
| Renderer (React 19) | `src/renderer/src/` | Zustand store, navigation, d3/Plotly visualizations |

**Data flow:** Renderer calls `request(channel, params)` from `src/renderer/src/api.ts`, which sets `isLoading: true` and issues an HTTP request to the matching `/api/*` endpoint → Express handler runs synchronously inside a `try/catch` envelope (`wrapHandler` in `src/server/envelope.ts`) → server responds with `{ ok: true, value } | { ok: false, error }` JSON → renderer handler in `App.tsx` clears `isLoading`, surfaces `last_error` on `ok: false`, or routes `value` to the per-channel handler that writes into Zustand → component reads from store and (re)draws.

In development, Vite dev server on `:5173` proxies `/api` requests to the Express server on `:3001`. In production, a single Express process on `:8080` serves both the built SPA (`dist/`) and API routes.

Every endpoint goes through this envelope; a thrown handler returns `{ ok: false, error }` rather than leaving the renderer hanging on `isLoading: true` forever.

## 3. Data Model

### 3.1 Input file (per RPKM TSV)

Tab-separated. Header columns split into two groups:

- **Key columns** (constants in `src/server/utils.ts`): `EC#, GeneID, Length, Reads, RPKM, Unclassified` — pass through untouched in shape.
- **Taxonomy columns**: every other header is an integer NCBI tax_id; the column is **renamed at parse time** to its taxonomy name via `db_functions.get_name_from_id(id)`. Unknown ids are left as the raw id and a `${id} not found in name db` warning is logged.

Per-cell normalization (`add_data_field_cast`):
- `EC#` column: `EC:1.1.1.1` → `1.1.1.1`; `''` / `None` (any case) → `0.0.0.0`.
- `GeneID` column: passed through verbatim.
- All other columns: coerced to `number | null`. Sentinels `''` / `NaN` / `NA` / `null` / `none` → `null`.

### 3.2 SQLite database (`resources/db/taxonomy.db`)

Built ahead of time via the notebooks under `resources/scripts/` (per `README.md`). Tables touched by the app:

| Table | Purpose |
|---|---|
| `names(id, tax_id, name)` | Tax_id ↔ name lookup |
| `parents(tax_id, t_realm, t_kingdom, t_phylum, t_class, t_order, t_family, t_genus, ...)` | Per-rank parent tax_id for any tax_id |
| `pathway_nodes(id, name, x, y, type, pathway)` | KEGG pathway map nodes |
| `pathway_edges(source, target, pathway)` | KEGG pathway map edges |
| `pathway_superpathways(id, name, superpathway)` | Pathway → superpathway membership |
| `superpathways(id, name)` | Superpathway names |

`db_functions.check_db()` opens the DB at `resources/db/taxonomy.db` (relative to CWD); failure returns `false`, which `initialize()` surfaces as status code `3`.

### 3.3 In-memory state (server)

Stored as module-level `let` bindings in `src/server/data_functions.ts`:

- `data: Record<filename, ParsedRow[]>` — populated by `add_data` / `add_test_data`.
- `ec: PathwayRow[]` — populated once at handshake from `get_superpathway_info()`. Each row is `{ ec, pathway_id, pathway, superpathway }`.

A `__test__` namespace is exported for tests to inject and reset this state. Replacing these globals with a `createDataContext()` factory is queued for PR 6.

## 4. HTTP API (browser ↔ server)

All routes are registered in `src/server/index.ts`. Every JSON response is wrapped in an envelope:

```ts
type ApiEnvelope<T> = { ok: true; value: T } | { ok: false; error: string }
```

The `Channel` union in `src/renderer/src/api.ts` maps logical channel names to HTTP endpoints via `endpointFor(...)`; both `request(...)` and the response handlers in `App.tsx` are typed against it, so adding a channel without updating both sides is a compile error.

| Channel | HTTP | Handler | Params | Returns (`value`) |
|---|---|---|---|---|
| `handshake` | `GET /api/health` | `initialize()` | — | `0` ok / `3` DB missing |
| `load` | `POST /api/data` | `add_data` | multipart: `{ name, file }` | the loaded `name` |
| `load_test` | `POST /api/data/test` | `add_test_data` | — | `string[]` of fixture fnames (dev only) |
| `overview` | `POST /api/viz/overview` | `parse_overview` | `{ names }` | `{ counts_data, ann_data }` |
| `counts` | `POST /api/viz/counts` | `parse_counts` | `{ names, tax_rank, selected_taxon, selected_ann_cat }` | count vector keyed on tax_rank |
| `krona` | `POST /api/viz/krona` | `parse_krona` | `{ names, tax_rank, selected_taxon }` | hierarchical taxonomy tree |
| `chord` | `POST /api/viz/chord` | `parse_ec_chord` | `{ names, tax_level, ann_level, selected_ann_cat, selected_taxon }` | `{ count_matrix, index, colors, tax_map, ann_map }` |
| `network` | `POST /api/viz/network` | `parse_network` | `{ names, tax_level, selected_taxon, pathway_name, width, height }` | `{ nodes, edges, colors }` — `pathway_name` is the readable name; `parse_network` resolves it to a pathway id internally |
| `pathway_list` | `POST /api/viz/pathway-list` | `parse_pathway_list` | `{ superpathway }` | `string[]` of pathway names within the superpathway |

`request(channel, params, { silent? })` is the only call site renderers should use. The `silent: true` option suppresses the `isLoading: true` flip and is reserved for the startup `handshake` ping.

## 5. Core Pipeline (`data_functions.ts`)

The data layer is a small functional pipeline; every visualization handler composes the same primitives:

```
names_to_data(names)   →  raw rows (or delta if 2 names)
        │
        ├─→ subset_data(rows, selected_taxon)             # drops tax cols whose parent ≠ name
        │       └─→ subset_data_by_ann(rows, selected_ann_cat)   # drops rows whose EC# ∉ filtered ec
        │               └─→ agg_by_ec / make_count_vector / make_ann_vector / parse_tax_tree
        │
        ├─→ get_tax_map(rows, level)   # tax_col → ancestor at level, via SQLite
        └─→ get_ec_map(filter, level)  # ec → [pathway/superpathway], via filtered ec state
```

**Delta mode** (`get_delta(df_1, df_2)`): aggregates each input by `EC#` (sum), outer-joins on `EC#`, subtracts numeric columns column-wise (treating missing columns/rows as `0`). Implemented with `danfojs-node`. Result keeps `EC#` rows present in either input.

**Output of `parse_ec_chord` (and `parse.ts:parse_ec_data`):** a square count matrix indexed by a single concatenated array `[gap_1, ...annotations, gap_2, ...taxa, gap_3]`. Self-cells of gap nodes hold padding values so `d3.chord` renders correctly.

**`parse_network`** (rewritten in PR 5) computes its tax-distribution pies directly: it filters the loaded rows by the selected taxon and pathway, runs `agg_by_ec` once, then folds tax columns into the active `tax_level` ancestors. It no longer goes through `parse_ec_chord` (the previous indirection at `ann_level: 'ec'` produced an `ec → ec` `ann_map` and a row filter that never matched, so every node came back with empty pie data). The static graph layout still comes from `db_functions.get_pathway_info(pathway_name)`, which now resolves the readable name to a pathway id via a parameterized lookup.

## 6. Renderer

### 6.1 Zustand store (`src/renderer/src/store/AppStore.ts`)

Single global store. Keys:

- `mainState`: `'upload' | 'overview' | 'krona' | 'chord' | 'network' | 'graph'` — drives top-level routing.
- `file_list: string[]`, `selected_file_list: string[]` — uploaded fnames and the active 1- or 2-file selection.
- `tax_rank: 'kingdom' | 'phylum' | 'class' | 'order' | 'family' | 'genus'`, `ann_rank: 'pathway' | 'superpathway'` — drilldown levels.
- `selected_taxon: { level, name }`, `selected_ann_cat: { level, name } | string`, `selected_pathway: string`, `selected_annotations: string[]` — interaction-driven filters that round-trip to main.
- One slot per visualization: `overview_data`, `krona_data`, `chord_data`, `network_data`, `network_preview_data`.
- `pathway_list: string[]` — pathway names within the active superpathway (populated by the `pathway_list` channel; consumed by `Network.tsx`).
- `isLoading: boolean`.
- `db_ready: boolean | null` — `null` until the handshake completes, then `true` (DB opened) or `false` (DB unreachable).
- `last_error: string | null` — most recent API error surfaced through the envelope; rendered by `<ErrorBanner />` in `App.tsx` until the user dismisses it.

### 6.2 Routing in `App.tsx`

A NavBar swaps `mainState`. On mount, the renderer calls `request('handshake', undefined, { silent: true })` and registers permanent channel handlers via `registerChannelHandler` (one per `Channel`) that:

1. Always clear `isLoading`.
2. Reject malformed envelopes into `last_error`.
3. On `ok: false`, set `last_error` to `${channel}: ${error}`.
4. On `ok: true`, route `value` to the per-channel handler in `channel_handlers` (typed `Record<Channel, ...>`, so a typo on either side is a compile error).

The handshake handler additionally writes `db_ready` and surfaces a "Taxonomy database is unreachable" message via `last_error` if `initialize()` returned a non-zero status.

**Currently mounted in `App.tsx`:** `Upload`, `Overview`, `Krona`, `Chord`, `Network`. `Graph` is the only remaining unmounted pane (still reads `state.parsed_data`, slated for a future PR).

### 6.3 Visualizations

| Component | Library | Status | Behavior |
|---|---|---|---|
| **Upload** | plain inputs | mounted | File picker + label input → `request('load', ...)`; "Load Test Files" → `request('load_test')`; pair-select dropdowns → `request('chord', ...)`. All three sites go through the typed `request(...)` helper |
| **Overview** | `d3-pie` | mounted | Two pies (`counts` and `ann`) over phylum / superpathway; auto-fetches `request('overview', { names })` on mount and on `selected_file_list` change. `get_color` is inlined locally so the renderer never reaches into `src/server/utils.ts` |
| **Krona** | `d3-hierarchy/partition` | mounted | Zoomable sunburst of the taxonomy tree from `parse_krona`. Auto-fetches on mount and on `tax_rank` / `selected_file_list` change. Colors are computed client-side from a `d3.hierarchy` walk over the response, using the same HSL ramp as the rest of the app |
| **Chord** | `d3-chord` | mounted | Inner ring = ribbons of taxon↔annotation; outer ring = labeled annotations + taxa around `gap_1/gap_2/gap_3`. Click an annotation arc → set `selected_ann_cat` (the active superpathway, which the Network pane picks up); click a taxon arc → set `selected_taxon` and drill `tax_rank` one level deeper |
| **Network** | `d3` (custom) | mounted | Two views switched on `selected_pathway`. **PathwayList**: clickable grid of pathway names within the active `selected_ann_cat` superpathway, populated via `request('pathway_list', { superpathway })`. **PathwayDetail**: full d3 graph for the selected pathway, fed entirely by `network_data: { nodes, edges, colors }` from `parse_network`; supports zoom + pan and a Back button that clears `selected_pathway` and `network_data` |
| **Graph** | `react-plotly.js` | unmounted | 3D `scatter3d` of `selected_annotations × taxonomy × RPKM` with translucent per-tax-category background surfaces. Still reads `state.parsed_data.*`; not yet migrated to a dedicated store key |

## 7. Test Surface

Configured in `vitest.config.ts` (`include: src/tests/**`). 54 tests total, ~45 s wall.

- **`src/tests/data_functions.test.ts`** — 42 tests: pure helpers with synthetic inputs; integration suite with real SQLite + real `test_rpkm_1.tsv` / `test_rpkm_2.tsv` (~886k rows total) loaded once in `beforeAll`. Covers every public export in the module's call tree, including end-to-end exercises of `parse_ec_chord`, `parse_overview`, `parse_pathway_list`, and `parse_network` (both the happy path and the "filter strips every taxonomy column" edge case that was found and fixed in PR 5).
- **`src/tests/db_functions.test.ts`** — 11 tests: `node:sqlite` mocked via `vi.mock`; verifies query-result-shape transformation for `get_parents_at_level`, `get_parents_multilevel`, `get_pathway_info` (now name-based), `get_pathways_in_superpathway`, and `get_superpathway_info`.
- **`src/tests/api.test.ts`** — 1 test: real-fixture smoke test of `parse_ec_chord` (60 s timeout because the call takes ~20 s on full data).

## 8. Build & Run

```bash
npm install          # Node 22, see .nvmrc
npm run dev          # API :3001 + Vite :5173 (concurrently)
npm test             # vitest run
npm run build        # typecheck + Vite build + tsc server
npm start            # production server on :8080 (serves dist + API)
```

**Docker:**

```bash
docker build -t metapro-viz .
docker run -p 8080:8080 metapro-viz
# Open http://localhost:8080
```

**Apple Silicon:** enable Rosetta emulation in Docker Desktop (Settings → General → *Use Rosetta for x86_64/amd64 emulation on Apple Silicon*; requires Virtualization framework). Then build/run with `--platform linux/amd64` — see `README.md`.

The DB is **not** shipped with the source: per README, releases fetch it; otherwise it is built locally from the notebooks under `resources/scripts/`. The Docker image copies `resources/db/taxonomy.db` at build time.

The module-level debug harness in `src/server/data_functions.ts` (which calls `initialize()` + `add_test_data()` + `parse_ec_chord(...)`) is gated behind `RUN_HARNESS=1`. To execute it manually:

```bash
RUN_HARNESS=1 npx tsx src/server/data_functions.ts
```

## 9. Known Issues

These are surfaced for completeness; none are part of the current functional contract. Items resolved in PRs 1–5 (dead `place_nodes.ts` / `tmp.ts` / `debug.ts`, the broken `parse_data` / `get_krona_data` import in `Upload.tsx`, the `request-node-info` IPC mismatch, `parsed_data` references in Overview/Krona/Network, the `dummy_data` placeholder in `parse_overview`, the silent-failure IPC pathways) have been removed from this list.

| Where | Issue |
|---|---|
| `src/server/data_functions.ts` (`get_fname`) | `substring(-4)` is a no-op; `.tsv` is **not** stripped from registered fnames. Currently masked because every call site passes the suffixed name; will need a real fix when downstream code starts assuming "base name" |
| `src/renderer/src/components/Graph.tsx` | Still reads `state.parsed_data.*` which does not exist on the current store; component remains unmounted in `App.tsx` and is the last visualization not yet migrated |
| `src/renderer/src/components/Chord.tsx` | A handful of pre-existing TS errors (`selected_ann_cat` typed as `object` but written as a string by the click handler; `tax_rank` literal narrowing; unused `event` parameter). Functional today, but these will block strict-mode typecheck when M6 lands |
| `src/server/db_functions.ts` (`get_parents_at_level`) | The `t_${rank}` column name is interpolated into SQL. Currently safe (`rank` only ever flows in from a typed renderer literal), but the input boundary makes it worth allowlisting before any user-controlled value can reach this code path |
| `src/server/data_functions.ts` (`add_data`) | `data = { ...data, [name]: parsed }` is O(n²) in the number of loaded files; trivial to switch to direct mutation |
| `src/server/data_functions.ts` (`add_data` headers) | Header rename does N separate `SELECT name FROM names WHERE tax_id = ?` queries (one per taxonomy column). Batchable into one `WHERE tax_id IN (...)` lookup |
| `src/server/data_functions.ts` (bottom) | Module-level test harness still gated behind `RUN_HARNESS=1`. To be removed entirely when the data-context factory (PR 6) lands |
| `src/server/index.ts` | All `parse_*` calls run on the Node event loop. A wide TSV upload or a fresh `parse_ec_chord` blocks the server for 10–30 s; user-perceived hangs are worked around today by the `isLoading` spinner only |

### 9.1 Architectural items queued for PR 6

These are intentionally deferred because they touch every API site at once:

- **Module-level mutable state** (`let data`, `let ec`, `let db`) → `createDataContext()` factory closing over private state; `__test__` namespace can then go away entirely.
- **Stringly-typed channels** → an `ApiContract` mapping each channel name to its `{ request, response }` pair, with `request<C>(...)` and route handlers typed against it.
- **Synchronous handlers** → long-running `parse_*` calls could be offloaded to worker threads or a job queue so uploads and chord renders do not block the HTTP server.
