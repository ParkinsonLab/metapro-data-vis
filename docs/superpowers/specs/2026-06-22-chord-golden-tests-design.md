# Chord Golden Integration Tests — Design Spec

> **Status:** Approved (2026-06-22, revised naming)  
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
| Chord expectations | `chord_expectations.yaml` | 14 unfiltered + filter + edge cases |
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

## 4. Fixture TSV Design

**File:** `analytics/transform/tests/fixtures/fake_rpkm.tsv`

Hand-pick IDs from real reference Parquet at implementation time. Use round numeric values (10, 20, 30, …) for hand-computed expectations.

**Taxonomy policy:** Use **bacterial `tax_id`s only** in fixture columns (metagenomics domain). Default focal: **`1280`** (*Staphylococcus aureus*). Sibling and fallback taxa must also resolve under kingdom `Bacteria` in `bridge_tax_rollup`. Do not use human or other eukaryote tax_ids (e.g. 9606).

EC choices must map to ≥2 superpathways and ≥2 pathways under one superpathway (real bridge rows). See **§13** for chord `GROUP BY` / summation rules — the v1 committed TSV used **different ECs** for focal vs sibling and does **not** yet satisfy §13 (regold required).

### 4.1 Row roles (summary)

| Row role | Purpose |
|---|---|
| **Focal** `(EC₁, T_focal)` | `rollup_grid` (21 rows) and chord parametric cases |
| **Tax sibling** `T_sib` | Same phylum, different genus; **same `EC₁` as focal** on a second gene row (see §13) |
| **Second pathway** `EC₂` | Different superpathway (for ann filter); optional second tax column |
| **Fallback taxon** `T_fallback` | Exact at rank R, coarser fallback when `requested_rank` is finer |
| **Unknown header** `T_unknown` | Column header `tax_id` **absent from `bridge_tax_rollup`** (e.g. `999999999`); see §12 |
| **Unmapped EC** | Empty/`None` `EC#` → `0.0.0.0` |

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

**Value semantics (int vs chord):** At this tier the query filters to a **single** `(focal_ec, focal_tax_id)` pair. Each row is that cell’s raw mass at a different `(requested_rank, pathway_level)` — so **`value` is the same** across all 21 rows (e.g. 10.0 from the focal TSV cell). What **varies** is `pathway_label` and `resolved_tax_label` (pathway level and rank resolution). Sibling tax columns affect **chord** goldens after mart-equivalent `GROUP BY`, not the focal row’s `value` in `int_tax_rollup_resolved`.

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

**Unfiltered (14 cases):** Parametrize `tax_level ∈ VALID_TAX_RANKS`, `ann_level ∈ {superpathway, pathway}`. Assert golden pairs `(pathway_label, resolved_tax_label, value)`. **Pair values must differ across `tax_level`** where coarser ranks merge sibling mass into the same `(pathway_key, resolved_tax_id)` bucket (§13). **`ann_level`** changes labels/`pathway_key` grain; totals may differ when pathway vs superpathway splits or merges rows differently.

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
    value: 30.0
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
      - ["Metabolism", "Bacteria", 30.0]

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
- Full-matrix golden comparison (only golden pairs, not gap fillers / colors / full index)
- `pathway_node` as chord `ann_level` (not in API)
- Separate `test_chord_golden.py` module
- **Synthesizing 7 `requested_rank` rows for unknown header tax_ids** in `int_tax_rollup_resolved` (deferred — see §12)

## 10. Success Criteria

- [ ] `fake_rpkm.tsv` committed with row roles documented in pipeline YAML
- [ ] Tier 1: 21 `rollup_grid` rows assert exact values in `test_fake_rpkm_pipeline.py`
- [ ] Tier 2: chord pair tests in `test_chord_service.py` (14 unfiltered + filters + 3 edge cases); goldens satisfy §13 (rank-dependent summation)
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
source_tax_id=999999999, value=40, pathway_level=superpathway|pathway|pathway_node
requested_rank=NULL, resolved_tax_id=NULL, resolved_tax_rank=NULL, resolved_tax_label=NULL
```

### Impact on golden tests

- **Tier 1 (`rollup_grid`):** Asserts focal **known** tax_id only (21 rows). No `rollup_grid` assertions for `999999999` in v1.
- **Tier 2 (chord):** `unclassified_tax_snapshot` golden pairs reflect phylum/superpathway aggregation **without** unknown-column mass — chord SQL cannot surface `'Unclassified'` for unknown headers until pipeline or API handling changes.
- **Fixture role:** `T_unknown` column remains in `fake_rpkm.tsv` so mass is present in `int_rpkm_pathway` and the gap is reproducible; it is **not** a test that chord shows `'Unclassified'` for unknown headers.

### Deferred follow-up (not v1)

Expand unknown header tax_ids to seven `requested_rank` rows with `'Unclassified'` semantics in `int_tax_rollup_resolved` (e.g. known/unknown UNION in dbt), then regold expectations and assert chord/mart include that mass. See implementation discussion on branch `feature/chord-dbt-api`.

## 13. Chord aggregation: `GROUP BY (pathway_key, resolved_tax_id)`

Chord SQL (and mart-equivalent aggregation) sums `value` into buckets keyed by **`pathway_key` + `resolved_tax_id`** (labels carried via `ANY_VALUE` / `GROUP BY` display columns):

```sql
GROUP BY t.pathway_key, t.resolved_tax_id,
         COALESCE(t.pathway_label, 'Unmapped EC'),
         t.resolved_tax_label
```

Changing **`tax_level`** only affects **`resolved_tax_id`** (rollup target). Changing **`ann_level`** filters **`pathway_level`** and therefore which **`pathway_key`** grain is used. **Summation happens only when two or more `int` rows share the same `(pathway_key, resolved_tax_id)` after filters.**

### What the fixture must exercise

| Scenario | Required TSV shape | Expected chord behavior |
|---|---|---|
| **Rank merge (siblings)** | Focal row: `EC₁` × `T_focal` = 10; sibling row: **`EC₁` × `T_sib` = 20** (same EC, different tax columns) | At **phylum**: one pair `(pathway_label, phylum_label)` with **30**; at **genus**: two pairs with **10** and **20** |
| **Ann filter** | Second gene row with **`EC₂`** mapping to a **different superpathway** than `EC₁` | Unfiltered total > ann-filtered total; ann filter drops `EC₂` mass |
| **Taxon filter** | Sibling shares `EC₁` but resolves to a **different genus label** than focal | Genus taxon filter on focal genus yields **10**, not 30 |
| **Fallback** | `T_fallback` with its own EC mass | Species request shows coarser `resolved_tax_label`; value unchanged for that taxon's bucket |
| **Unmapped EC** | Empty `EC#` | `'Unmapped EC'` pair; `pathway_key IS NULL` bucket |
| **Unknown header** | `999999999` column | Mass excluded from chord today (§12) |

**Anti-pattern (v1 TSV):** focal `EC₁` on `T_focal` and sibling **`EC₂` ≠ EC₁** on `T_sib`. Different ECs → different `pathway_key`s at every `ann_level` → **no summation ever**; each pair keeps its raw cell value (10, 20, 30, 50) and **grand total stays constant (110)** across all 14 unfiltered `tax_level` / `ann_level` combos. Labels change; **values do not test rollup aggregation.**

### Example corrected TSV sketch

```tsv
GeneID	…	1280	298593	620891	999999999
g_focal	…	EC₁	10	0	0	0          # rollup_grid focal
g_sib   …	EC₁	0	20	0	0          # same EC₁ — merges at coarser ranks
g_alt_sp …	EC₂	0	0	0	0          # EC₂ on sib tax OR separate col — ann filter
g_fallback …	EC₃	0	0	30	0
g_unknown …	EC₁	0	0	0	40
g_unmapped …	(empty)	50	0	0	0
```

(`EC₁` / `EC₂` / `EC₃` = concrete bridge EC strings chosen at implementation time; `EC₂` must map to a different superpathway than `EC₁`.)

### Regold checklist

When fixing `fake_rpkm.tsv`:

1. Re-run pipeline + `dump_fake_rpkm_expectations.py`
2. Verify **at least two** unfiltered cases differ in pair **values** (not just labels) — e.g. phylum/superpathway focal+sibling pair = 30, genus/superpathway = 10
3. Verify taxon and ann filter cases drop mass vs matching unfiltered case
4. Tier 1 `rollup_grid` unchanged in structure (still 21 rows for focal `(EC₁, T_focal)`; constant value per row)
