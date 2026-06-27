# Chord Golden Integration Tests — Design Spec

> **Status:** Approved (2026-06-22; §4 revised for dense-matrix fixture + focal-pair goldens)  
> **Goal:** Add hand-verified integration tests for the DuckDB chord path, backed by a reusable fake RPKM fixture and shared pipeline expectations for transform semantics (rollup fallback, Unclassified, unmapped EC) that future viz endpoints can reuse.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, `int_tax_rollup_resolved`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — chord API runtime SQL and matrix assembly

**Work isolation:** Branch `feature/chord-dbt-api` in worktree `.worktrees/chord-dbt-api/`.

## 1. Context

The chord DuckDB backend (`analytics/api/chord_service.py`) has unit tests for matrix assembly and filter normalisation, plus a minimal integration test that only checks response shape when `runs/test_rpkm_1/sample.duckdb` exists. There are no correctness tests for runtime SQL, tax/pathway filters, or documented rollup semantics.

This spec adds a **small hand-designed fake TSV**, a **single pipeline run**, and **YAML expectations** with parametrized pytest. Tests are tiered: shared pipeline preconditions first, then chord API pair assertions in the existing `test_chord_service.py` module.

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Reference data | Real `bridge_ec_pathway` / `bridge_tax_rollup` Parquet | Stable; matches production semantics |
| Fixture TSV | One shared `fake_rpkm.tsv` for transform + all endpoints | Same edge cases apply to overview, network, etc. |
| Taxonomy in fixture | Bacterial `tax_id`s only; focal **`1280`** (*S. aureus*) | Metagenomics domain; safe if app restricts to bacteria later |
| Sample id | `fake_rpkm` | `strip_extension(names[0])` → `runs/fake_rpkm/sample.duckdb` |
| Pipeline expectations | `fake_rpkm_pipeline_expectations.yaml` | Shared transform goldens; not chord-specific |
| Rollup grid | 21 rows for focal `(ec, source_tax_id)` with **exact** labels and value | Verifies dbt pipeline before endpoint tests; see §5.1 for value semantics |
| Chord expectations | `chord_expectations.yaml` | 14 unfiltered (focal pair primary) + filter + edge cases |
| Fixture numerics | Unit **1** per non-zero tax cell | Hand-computed focal-pair staircase; see §4.3 |
| Chord tests | Merged into `test_chord_service.py` | One module for `build_chord_from_duckdb` integration |
| Golden storage | External YAML, not inline Python tuples | Readable, diffable, parametrized via `case_id` |
| Mart / legacy parity | Out of scope | Mart may be retired; no Node parity harness |
| Missing bridges | `pytest.skip` entire modules using fake fixture | Local dev convenience; CI hardening deferred |
| CI pipeline for bridges | Out of scope | Repo CI needs broader rework |

## 3. File Layout

```
analytics/
├── conftest.py                                    # shared: bridge guard + fake_rpkm session DuckDB
├── testing/
│   └── fake_rpkm_fixture.py                       # paths, YAML load, run_pipeline helper
├── transform/tests/
│   ├── fixtures/
│   │   ├── fake_rpkm.tsv                          # SHARED synthetic input (tab-separated)
│   │   └── fake_rpkm_pipeline_expectations.yaml   # SHARED transform goldens
│   └── python/
│       └── test_fake_rpkm_pipeline.py             # pipeline / rollup_grid tests
└── api/tests/
    ├── fixtures/
    │   └── chord_expectations.yaml                # chord-only goldens
    └── test_chord_service.py                      # smoke + chord pair tests (merged)
```

**Runtime artifact (gitignored):**

```
transform/runs/fake_rpkm/sample.duckdb
```

### Ownership split

| Asset | Owner | Purpose |
|---|---|---|
| `fake_rpkm.tsv` | Shared | One synthetic RPKM for all DuckDB viz endpoints |
| `fake_rpkm_pipeline_expectations.yaml` | Shared | `fixture` metadata, `rollup_grid` (21 rows), future pipeline sections |
| `test_fake_rpkm_pipeline.py` | Shared | Asserts `int_tax_rollup_resolved` — transform precondition |
| `chord_expectations.yaml` | Chord | `chord_unfiltered`, `chord_filtered`, `edge_cases` |
| `test_chord_service.py` | Chord | Smoke + parametrized pair tests via `build_chord_from_duckdb()` |

Future endpoints add `overview_expectations.yaml`, `test_overview_service.py`, etc., reusing the same TSV and session fixture.

## 4. Fixture Design (TSV + chord aggregation)

**File:** `analytics/transform/tests/fixtures/fake_rpkm.tsv`

The fixture is a **wide dense matrix**: tax_id **columns** (phylogenetic axis) × gene **rows** with EC assignments (pathway axis). Hand-pick IDs from real reference Parquet at implementation time. The v1 committed TSV used **different ECs** for focal vs cousin tax columns and does **not** satisfy §4.4 (regold required).

**Taxonomy policy:** Use **bacterial `tax_id`s only** in fixture columns (metagenomics domain). Default focal: **`1280`** (*Staphylococcus aureus*). Cousin, fallback, and filter taxa must resolve under kingdom `Bacteria` in `bridge_tax_rollup`. Do not use human or other eukaryote tax_ids (e.g. 9606).

### 4.1 Tax columns (phylogenetic axis)

| Column role | Purpose |
|---|---|
| **`T_focal` (`1280`)** | Focal species; baseline for rollup_grid and chord focal pair |
| **~6 cousin columns** | Bacterial tax_ids at different phylogenetic depths; each chosen so it **merges into focal’s `resolved_tax_id` bucket at exactly one coarser rank** when carrying `EC_focal` mass |
| **`T_fallback`** | Exact at rank R in reference; coarser fallback when `requested_rank` is finer |
| **`T_unknown` (`999999999`)** | Column header **absent from `bridge_tax_rollup`**; see §12 |

Pick cousins so the focal pair **increases by 1 at every rank step** from species → kingdom (see §4.3). At genus, focal may still be alone unless a same-genus cousin is added deliberately.

### 4.2 EC rows (pathway axis)

Each gene row carries one EC (or empty for unmapped) and **one non-zero tax column** (keeps row mass unambiguous).

| Row role | EC relationship to focal | Purpose |
|---|---|---|
| **Focal** | `EC_focal` — maps to **exactly one** `pathway_id` and **one** `superpathway_id` in bridge | Tier 1 rollup_grid; chord focal pair |
| **Cousin × N** | **Same `EC_focal`** | Rank-merge summation in chord |
| **`EC_alt`** | Different **pathway**, **same superpathway** as `EC_focal` | Separate pair at `ann_level=pathway`; merges with focal at `ann_level=superpathway` |
| **`EC_diff_sp`** | **Neither** same pathway nor same-superpathway alt — i.e. **different superpathway** | Ann-filter golden (dropped when filtering to focal’s superpathway) |
| **`EC_fb`** | Any mapped EC on `T_fallback` | Fallback taxon edge case |
| **Unknown column row** | Any mapped EC on `T_unknown` | Mass in `int` only (§12) |
| **Unmapped** | Empty/`None` `EC#` → `0.0.0.0` | `'Unmapped EC'` chord pair |

**Bridge note (`data-model.md`):** each `pathway_superpathways` row maps to exactly one superpathway; each `pathway_nodes` row maps to exactly one pathway group. An EC **can** fan out to multiple pathway nodes (and, empirically, multiple pathways under one superpathway). **`EC_focal` must be validated** at implementation time as single-pathway / single-superpathway so the focal pair is unambiguous at both `ann_level`s. Use **`EC_alt`** and **`EC_diff_sp`** as separate gene rows — do not rely on multi-pathway fan-out of `EC_focal`.

The fixture must still include ≥2 superpathways and ≥2 pathways (across **different EC rows**, not via `EC_focal` fan-out).

### 4.3 Numeric policy

Use **1** for every non-zero tax-column cell. Mental math:

- **Focal pair** at a given `tax_level` = count of `(EC_focal, tax column)` cells whose tax_ids resolve to the **same** `(pathway_key, resolved_tax_id)` as focal at that rank.
- Each cousin column contributes **+1** when it first merges into that bucket (typically one new cousin per rank step).
- **Tier 1** focal cell value is **constant 1.0** across all 21 rollup_grid rows (labels vary; value does not).
- Other roles (`EC_alt`, `EC_diff_sp`, fallback, unmapped) also use **1** in their cell; they appear in **secondary** golden pairs only where filters or edge cases need them.

Example focal-pair staircase (illustrative — exact ranks depend on chosen cousins):

| `tax_level` | Focal pair value |
|---|---|
| species | 1 |
| genus | 1 (or 2 if same-genus cousin) |
| family | 2 |
| order | 3 |
| class | 4 |
| phylum | 5 |
| kingdom | 6 |

### 4.4 Chord aggregation (`GROUP BY pathway_key, resolved_tax_id`)

Chord SQL (and mart-equivalent aggregation) sums `value` into buckets keyed by **`pathway_key` + `resolved_tax_id`**:

```sql
GROUP BY t.pathway_key, t.resolved_tax_id,
         COALESCE(t.pathway_label, 'Unmapped EC'),
         t.resolved_tax_label
```

Changing **`tax_level`** only affects **`resolved_tax_id`** (rollup target). Changing **`ann_level`** filters **`pathway_level`** and therefore which **`pathway_key`** grain is used. **Summation happens only when two or more `int` rows share the same `(pathway_key, resolved_tax_id)` after filters.**

| Scenario | Required TSV shape | Expected chord behavior |
|---|---|---|
| **Rank merge (cousins)** | Focal row: `EC_focal` × `T_focal` = 1; cousin rows: **`EC_focal` × `T_cousin` = 1** each | Focal pair **increases by 1** at each rank where another cousin merges |
| **Alt pathway** | Gene row with **`EC_alt`** (same superpathway as `EC_focal`) | Two pathway pairs at `ann_level=pathway`; one superpathway pair at `ann_level=superpathway` |
| **Ann filter** | Gene row with **`EC_diff_sp`** (different superpathway) | Unfiltered total > ann-filtered total; filter on focal superpathway drops `EC_diff_sp` mass |
| **Taxon filter** | Cousin shares `EC_focal` but **different genus** than focal | Genus filter on focal genus yields focal pair **1**, not merged total |
| **Fallback** | `T_fallback` with `EC_fb` | Species request shows coarser `resolved_tax_label`; bucket value unchanged |
| **Unmapped EC** | Empty `EC#` | `'Unmapped EC'` pair |
| **Unknown header** | `999999999` column | Mass excluded from chord today (§12) |

**Anti-pattern (v1 TSV):** focal `EC_focal` on `T_focal` and cousin row with **`EC ≠ EC_focal`**. Different ECs → different `pathway_key`s → **no rank summation**; pair values stay constant across all 14 unfiltered cases (labels only).

Example corrected TSV sketch:

```tsv
GeneID	…	1280	<cousin1>	…	620891	999999999
g_focal      …	EC_focal   1  0  …  0  0
g_cousin1    …	EC_focal   0  1  …  0  0
g_alt        …	EC_alt     1  0  …  0  0
g_diff_sp    …	EC_diff_sp 1  0  …  0  0
g_fallback   …	EC_fb      0  0  …  1  0
g_unknown    …	EC_focal   0  0  …  0  1
g_unmapped   …	(empty)    1  0  …  0  0
```

(`EC_focal`, `EC_alt`, `EC_diff_sp`, `EC_fb` = concrete bridge EC strings chosen at implementation time.)

**Regold checklist:**

1. Re-run pipeline + `dump_fake_rpkm_expectations.py`
2. Verify **focal pair values increase** across `tax_level` for each `ann_level` (not just label changes)
3. Verify taxon and ann filter cases drop mass vs matching unfiltered case
4. Tier 1 `rollup_grid`: still 21 rows for focal `(EC_focal, T_focal)`; constant value **1.0**

### 4.5 Golden pair strategy

Goldens stay **sorted pair lists**, not full matrices. The wide TSV is dense; expectations are sparse.

| Tier | Primary assertion | Secondary pairs |
|---|---|---|
| **14 unfiltered** | **Focal pair** `(pathway_label, resolved_tax_label, value)` per `(tax_level, ann_level)` — staircase per §4.3 | Optional split cousin pair at fine ranks (genus/species) |
| **Filtered** | Focal pair or total **lower** than unfiltered | — |
| **Edge cases** | Fuller lists where behavior is the point (unmapped, fallback, unknown absent from chord) | — |

Do not golden every cousin × EC combination.

## 5. Tiered Test Architecture

```
fake_rpkm.tsv
        │
        ▼  run_pipeline.py (session fixture in analytics/conftest.py)
runs/fake_rpkm/sample.duckdb
        │
        ├── Tier 1: pipeline / rollup_grid (transform)
        │     test_fake_rpkm_pipeline.py
        │     21 rows × exact (pathway_label, resolved_tax_label, value)
        │
        └── Tier 2: chord pairs (api)
              test_chord_service.py
              14 unfiltered + filters + edge cases
```

### 5.1 Tier 1 — Pipeline rollup grid (shared, not chord-specific)

**Purpose:** Confirm `int_tax_rollup_resolved` materialized focal rows correctly across all rank × pathway_level combinations. Failure here invalidates endpoint goldens but does **not** test any HTTP/service layer.

**Query:** Filter `int_tax_rollup_resolved` where `ec_normalized = focal_ec` and `source_tax_id = focal_tax_id`.

**Assert:**

- Exactly **21 rows** (7 `requested_rank` × 3 `pathway_level`)
- Each row matches YAML: `requested_rank`, `pathway_level`, `pathway_label`, `resolved_tax_label`, `value` (all exact)

**Value semantics (int vs chord):** At this tier the query filters to a **single** `(focal_ec, focal_tax_id)` pair. Each row is that cell’s raw mass at a different `(requested_rank, pathway_level)` — so **`value` is the same** across all 21 rows (**1.0** from the focal TSV cell). What **varies** is `pathway_label` and `resolved_tax_label`. Cousin tax columns affect **chord** goldens after mart-equivalent `GROUP BY`, not the focal row’s `value` in `int_tax_rollup_resolved`.

**Location:** `analytics/transform/tests/python/test_fake_rpkm_pipeline.py`

**Test name:** `test_rollup_grid_row[...]` (parametrized over 21 YAML rows)

### 5.2 Tier 2 — Chord pair tests (merged into existing module)

**Purpose:** Verify `chord_service.py` runtime SQL + `build_chord_matrix()`.

**Location:** `analytics/api/tests/test_chord_service.py` (no separate golden file)

**Structure within module:**

```python
# Always runs — no DB
def test_build_chord_rejects_comparison(): ...

# fake_rpkm fixture — parametrized from chord_expectations.yaml
@pytest.mark.parametrize("case", ..., ids=lambda c: c["case_id"])
def test_chord_pairs(case, fake_rpkm_db): ...

# Optional smoke on fake_rpkm (replaces test_rpkm_1 skip pattern for this module)
def test_build_chord_from_duckdb_shape(fake_rpkm_db): ...
```

**Unfiltered (14 cases):** Parametrize `tax_level ∈ VALID_TAX_RANKS`, `ann_level ∈ {superpathway, pathway}`. Assert golden pairs `(pathway_label, resolved_tax_label, value)` — **primarily the focal pair** (§4.5). Focal pair **values must increase** across `tax_level` as cousins merge (§4.4). **`ann_level`** changes labels/`pathway_key` grain; pathway vs superpathway may split or merge `EC_alt` relative to `EC_focal`.

**Filtered:** taxon filter + ann filter cases must assert **lower totals** or **fewer pairs** than the matching unfiltered case ( proves filters and `GROUP BY` interact).

**Edge cases:** unmapped EC, unknown header tax_id (mass in `int` only — see §12), fallback taxon.

**Pair extraction:** Helper converts `build_chord_matrix()` output to sorted `(pathway_label, resolved_tax_label, value)` list from `index` + `count_matrix` (annotation × taxon submatrix only; not gap fillers).

## 6. Expectations YAML

### 6.1 Shared — `fake_rpkm_pipeline_expectations.yaml`

```yaml
fixture:
  sample_id: fake_rpkm
  tsv: fake_rpkm.tsv
  focal_ec: "..."          # set at implementation from real bridge
  focal_tax_id: 1280          # Staphylococcus aureus (bacterial focal)
  roles:
    fallback_tax_id: ...
    unknown_tax_id: 999999999

rollup_grid:               # 21 rows — labels vary; value constant for focal cell
  - requested_rank: kingdom
    pathway_level: superpathway
    pathway_label: "..."
    resolved_tax_label: "..."
    value: 1.0
  # ... 20 more
```

### 6.2 Chord — `chord_expectations.yaml`

```yaml
sample_id: fake_rpkm        # references shared fixture

chord_unfiltered:
  - case_id: kingdom_superpathway
    tax_level: kingdom
    ann_level: superpathway
    pairs:
      - ["Energy metabolism", "Bacteria", 6.0]   # focal pair — primary assertion
      # optional secondary pairs at fine ranks or for EC_alt / unmapped

chord_filtered:
  - case_id: taxon_filter_genus_a
    tax_level: phylum
    ann_level: superpathway
    selected_taxon: { level: genus, name: "..." }
    pairs: [...]

edge_cases:
  - case_id: unmapped_ec
    tax_level: phylum
    ann_level: superpathway
    pairs: [...]
```

Float comparison via `pytest.approx`. Pair lists compared as sorted tuples.

## 7. Shared Test Infrastructure

**`analytics/conftest.py`:**

- Skip modules using fake fixture if `reference/parquet/bridge_*.parquet` missing → **SKIPPED** with message to run `build_reference.py`
- Session fixture `fake_rpkm_db`: run `run_pipeline.py` once if DuckDB absent; propagate failures as **FAILED**

**`analytics/testing/fake_rpkm_fixture.py`:**

- Constants: `SAMPLE_ID`, TSV path, DB path, YAML paths
- `load_yaml()`, `ensure_pipeline_built()`, bridge-exists check

Example import:

```python
from testing.fake_rpkm_fixture import SAMPLE_ID, ensure_built, load_pipeline_expectations
```

Both `test_fake_rpkm_pipeline.py` and `test_chord_service.py` import the same session fixture.

## 8. Preconditions and Skip Behaviour

| Precondition | Behaviour |
|---|---|
| Bridge Parquet missing | `pytest.skip` on fake-fixture modules → **SKIPPED** (not failed) |
| Bridges present | Session fixture runs pipeline; failure → **FAILED** |
| Wrong expected value | **FAILED** |

No CI changes in v1. `test_main.py` may keep its existing `test_rpkm_1` skip pattern for HTTP integration until migrated separately.

## 9. Out of Scope

- Mart parity or legacy Node parity scripts
- CI job that builds reference Parquet automatically
- Full-matrix golden comparison (only focal pair + sparse secondary pairs; not gap fillers / colors / full index)
- `pathway_node` as chord `ann_level` (not in API)
- Separate `test_chord_golden.py` module
- **Synthesizing 7 `requested_rank` rows for unknown header tax_ids** in `int_tax_rollup_resolved` (deferred — see §12)

## 10. Success Criteria

- [ ] `fake_rpkm.tsv` committed with tax columns + EC rows documented in pipeline YAML (§4)
- [ ] Tier 1: 21 `rollup_grid` rows assert exact values in `test_fake_rpkm_pipeline.py`
- [ ] Tier 2: chord pair tests in `test_chord_service.py` (14 unfiltered + filters + 3 edge cases); **focal pair staircase** per §4.3–§4.5
- [ ] Fake-fixture modules skip cleanly when bridge Parquet missing
- [ ] Shared session fixture reusable from future endpoint test modules
- [ ] Existing unit tests (`test_chord_matrix`, `test_filters`, etc.) and Node tests unaffected

## 11. References

- `analytics/api/chord_service.py` — runtime SQL
- `analytics/transform/models/intermediate/int_tax_rollup_resolved.sql`
- `analytics/transform/scripts/run_pipeline.py`
- `analytics/transform/scripts/build_reference.py`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` §6 — documented deviations (fallback, Unclassified, unmapped)

## 12. Unknown header tax_id semantics (deferred fix)

The fake TSV includes column `999999999` to document **current pipeline behavior** for sample tax_id headers that are not in the reference taxonomy. Fixing this is **deferred**; goldens and tests assert today’s behavior, not the aspirational `'Unclassified'` rows described in `2026-06-15-rpkm-transform-design.md` §6.7 for absent tax_ids.

### Three distinct cases

| Case | In `bridge_tax_rollup`? | Rows in `int_tax_rollup_resolved` (per pathway row) | `requested_rank` | `resolved_tax_label` | Visible in mart / chord (`WHERE requested_rank = ?`) |
|---|---|---|---|---|---|
| **Known** tax_id (e.g. `1280`) | Yes — 7 ranks per tax_id | 7 × 3 pathway levels = **21** for focal `(ec, tax_id)` | Set (kingdom…species) | Resolved name at rank | Yes |
| **Bridge Unclassified** — tax_id in reference but no ancestor at requested rank | Yes — row with null `resolved_tax_id` | 7 × 3 = **21** | Set | **`'Unclassified'`** (from `build_reference.py`) | Yes |
| **Unknown header** — tax_id not in reference at all (e.g. `999999999`) | **No** | **3** only (one null-bridge row per `pathway_level`) | **`NULL`** | **`NULL`** (not `'Unclassified'`) | **No** — filtered out by rank predicate |

### Why unknown headers differ

`int_tax_rollup_resolved` LEFT JOINs `int_rpkm_pathway` to `bridge_tax_rollup` on `source_tax_id` only. Known tax_ids fan out to seven `requested_rank` rows from the bridge. Unknown tax_ids have **no bridge rows**, so the join yields **one** row with all bridge columns NULL per `int_rpkm_pathway` row — not seven synthetic ranks and not the `'Unclassified'` label (that label is produced inside `build_reference.py` only for tax_ids **present** in the reference graph).

Observed shape for `999999999` in `fake_rpkm` (example):

```
source_tax_id=999999999, value=1, pathway_level=superpathway|pathway|pathway_node
requested_rank=NULL, resolved_tax_id=NULL, resolved_tax_rank=NULL, resolved_tax_label=NULL
```

### Impact on golden tests

- **Tier 1 (`rollup_grid`):** Asserts focal **known** tax_id only (21 rows). No `rollup_grid` assertions for `999999999` in v1.
- **Tier 2 (chord):** `unclassified_tax_snapshot` golden pairs reflect phylum/superpathway aggregation **without** unknown-column mass — chord SQL cannot surface `'Unclassified'` for unknown headers until pipeline or API handling changes.
- **Fixture role:** `T_unknown` column remains in `fake_rpkm.tsv` so mass is present in `int_rpkm_pathway` and the gap is reproducible; it is **not** a test that chord shows `'Unclassified'` for unknown headers.

### Deferred follow-up (not v1)

Expand unknown header tax_ids to seven `requested_rank` rows with `'Unclassified'` semantics in `int_tax_rollup_resolved` (e.g. known/unknown UNION in dbt), then regold expectations and assert chord/mart include that mass. See implementation discussion on branch `feature/chord-dbt-api`.
