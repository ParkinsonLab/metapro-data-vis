# Chord Golden Integration Tests — Design Spec

> **Status:** Approved (2026-06-22)  
> **Goal:** Add hand-verified golden integration tests for the DuckDB chord path, with a reusable fake RPKM fixture that covers shared transform semantics (rollup fallback, Unclassified, unmapped EC) for this and future viz endpoints.

**Parent specs:**

- `docs/superpowers/specs/2026-06-15-rpkm-transform-design.md` — pipeline, bridges, `int_tax_rollup_resolved`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` — chord API runtime SQL and matrix assembly

**Work isolation:** Branch `feature/chord-dbt-api` in worktree `.worktrees/chord-dbt-api/`.

## 1. Context

The chord DuckDB backend (`analytics/api/chord_service.py`) has unit tests for matrix assembly and filter normalisation, plus a minimal integration test that only checks response shape when `runs/test_rpkm_1/sample.duckdb` exists. There are no golden correctness tests for runtime SQL, tax/pathway filters, or documented rollup semantics.

This spec adds a **small hand-designed fake TSV**, a **single pipeline run**, and **YAML golden expectations** with parametrized pytest. Tests are tiered: transform preconditions first, then chord API goldens.

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Reference data | Real `bridge_ec_pathway` / `bridge_tax_rollup` Parquet | Stable; matches production semantics |
| Fixture TSV | One shared fake file for transform + multiple endpoints | Same edge cases apply to overview, network, etc. |
| TSV naming | `fake_rpkm_chord_golden.tsv` | Clearly synthetic; not confused with `resources/example_data/` |
| Sample id | `fake_rpkm_chord_golden` | `strip_extension(names[0])` → `runs/fake_rpkm_chord_golden/sample.duckdb` |
| Int precondition | 21 rows for anchor `(ec, source_tax_id)` with **exact** golden values | Verifies dbt pipeline before chord tests |
| Chord goldens | 14 unfiltered cases (7 ranks × 2 `ann_level`s) + filter + edge cases | API contract; `pathway_node` not exposed to chord |
| Golden storage | External YAML, not inline Python tuples | Readable, diffable, parametrized via `case_id` |
| Mart / legacy parity | Out of scope | Mart may be retired; no Node parity harness |
| Missing bridges | `pytest.skip` entire golden module | Local dev convenience; CI hardening deferred |
| CI pipeline for bridges | Out of scope | Repo CI needs broader rework |

## 3. Shared Fake Fixture (Cross-Endpoint)

The fake TSV is **transform-level**, not chord-specific. Future DuckDB endpoints (overview, pathway list, network) filter and aggregate the same `int_tax_rollup_resolved` rows and need the same semantic coverage:

| Scenario | Why shared |
|---|---|
| Tax siblings (same phylum, different genus) | Rank drilldown and rollup aggregation |
| Rollup fallback | Coarser resolution at finer requested ranks |
| Unclassified (`tax_id` absent from bridge) | NULL `resolved_tax_id`, label `'Unclassified'` |
| Unmapped EC (`0.0.0.0`) | `pathway_key IS NULL` → `'Unmapped EC'` |
| Multiple superpathways / pathways | Pathway and ann filters |

**Layout:**

```
analytics/transform/tests/fixtures/
├── fake_rpkm_chord_golden.tsv              # shared input (rename later if generic: fake_rpkm_viz_golden.tsv)
├── fake_rpkm_chord_golden_expectations.yaml # chord-specific goldens (this spec)
└── (future) fake_rpkm_overview_expectations.yaml
```

**Shared test infrastructure (future-friendly):**

| Component | Location | Role |
|---|---|---|
| TSV | `transform/tests/fixtures/fake_rpkm_chord_golden.tsv` | Committed synthetic input |
| Pipeline session fixture | `transform/tests/conftest.py` (or `tests/python/conftest.py`) | Run `run_pipeline.py` once → `runs/fake_rpkm_chord_golden/sample.duckdb` |
| Bridge guard | Same conftest | Skip module if `reference/parquet/bridge_*.parquet` missing |
| Expectations | Per-endpoint YAML beside fixture | Each endpoint owns its golden pairs; same `sample_id` |

Chord tests import the shared DuckDB fixture; overview/network tests add their own YAML later without duplicating the TSV or pipeline run.

**Naming note:** File is named `fake_rpkm_chord_golden` for v1 because chord drives the first consumer. When a second endpoint adds goldens, consider renaming to `fake_rpkm_viz_golden` in a follow-up (TSV + sample_id + YAML paths) — not required for v1.

## 4. Fixture TSV Design

**File:** `analytics/transform/tests/fixtures/fake_rpkm_chord_golden.tsv`

Hand-pick IDs from real reference Parquet at implementation time. Use round numeric values (10, 20, 30, …) for hand-computed goldens.

| Row role | Purpose |
|---|---|
| **Anchor** `(EC₁, T_anchor)` | Parametric int (21) and chord (14) cases |
| **Tax siblings** `T_sib1`, `T_sib2` | Same phylum, different genus; different ECs so rank rollup changes summed values |
| **Fallback taxon** `T_fallback` | Exact at rank R, coarser fallback when `requested_rank` is finer |
| **Unclassified** `T_unknown` | Column header tax_id not in `bridge_tax_rollup` (e.g. `999999999`) |
| **Unmapped EC** | Empty/`None` `EC#` → `0.0.0.0` |

EC choices must map to ≥2 superpathways and ≥2 pathways under one superpathway (real bridge rows).

## 5. Tiered Test Architecture

```
fake_rpkm_chord_golden.tsv
        │
        ▼  run_pipeline.py (session fixture)
runs/fake_rpkm_chord_golden/sample.duckdb
        │
        ├── Tier 1: int anchor precondition (transform tests)
        │     21 rows × exact (pathway_label, resolved_tax_label, value)
        │
        └── Tier 2: chord API goldens (api tests)
              14 unfiltered + filters + edge cases
              assert golden pairs via build_chord_from_duckdb()
```

### 5.1 Tier 1 — Int anchor precondition (dbt, not chord)

**Purpose:** Confirm `int_tax_rollup_resolved` materialized anchor rows correctly. Failure here invalidates chord goldens but does **not** test the chord endpoint.

**Query:** Filter `int_tax_rollup_resolved` where `ec_normalized = EC₁` and `source_tax_id = T_anchor`.

**Assert:**

- Exactly **21 rows** (7 `requested_rank` × 3 `pathway_level`)
- Each row matches YAML golden: `requested_rank`, `pathway_level`, `pathway_label`, `resolved_tax_label`, `value` (all exact; values **are not constant** across rows because siblings and pathway level affect labels and rollup sums)

**Location:** `analytics/transform/tests/python/test_chord_golden_int.py`

### 5.2 Tier 2 — Chord API goldens

**Purpose:** Verify `chord_service.py` runtime SQL + `build_chord_matrix()`.

**Unfiltered (14 cases):** Parametrize `tax_level ∈ VALID_TAX_RANKS`, `ann_level ∈ {superpathway, pathway}`. For each case, assert one or more golden pairs `(pathway_label, resolved_tax_label, value)` — the cells receiving anchor-related mass after GROUP BY. Values differ across cases due to sibling rollup.

**Filtered:**

| `case_id` | Params |
|---|---|
| `taxon_filter_*` | `selected_taxon` matching one sibling |
| `ann_filter_*` | `selected_ann_cat` restricting to one superpathway |

**Edge cases:**

| `case_id` | Assert |
|---|---|
| `unmapped_ec` | `'Unmapped EC'` pair with expected sum |
| `unclassified_tax` | `'Unclassified'` pair for unknown tax_id mass |
| `fallback_*` | Finer `tax_level` resolves to coarser label for `T_fallback` |

**Location:** `analytics/api/tests/test_chord_golden.py`

**Pair extraction:** Helper converts `build_chord_matrix()` output to sorted `(pathway_label, resolved_tax_label, value)` list from `index` + `count_matrix` (annotation × taxon submatrix only; not gap fillers).

## 6. Expectations YAML

**File:** `analytics/transform/tests/fixtures/fake_rpkm_chord_golden_expectations.yaml`

```yaml
fixture:
  sample_id: fake_rpkm_chord_golden
  tsv_name: fake_rpkm_chord_golden.tsv
  anchor_ec: "..."       # set at implementation from real bridge
  anchor_tax_id: ...     # e.g. 9606

int_anchor:
  - requested_rank: kingdom
    pathway_level: superpathway
    pathway_label: "..."
    resolved_tax_label: "..."
    value: 30.0
  # ... 20 more rows

chord_unfiltered:
  - case_id: kingdom_superpathway
    tax_level: kingdom
    ann_level: superpathway
    pairs:
      - ["Metabolism", "Bacteria", 30.0]
  # ... 13 more cases

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

**Wiring:**

```python
@pytest.mark.parametrize("case", cases, ids=lambda c: c["case_id"])
def test_chord_unfiltered(case, golden_db):
    ...
```

Float comparison via `pytest.approx`. Pair lists compared as sorted tuples.

## 7. Preconditions and Skip Behaviour

| Precondition | Behaviour |
|---|---|
| `reference/parquet/bridge_ec_pathway.parquet` or `bridge_tax_rollup.parquet` missing | `pytest.skip` on golden modules: *"Reference parquet not built; run build_reference.py"* → **SKIPPED** (not failed) |
| Bridges present | Session fixture runs `run_pipeline.py`; failure → **FAILED** |
| Wrong golden value | **FAILED** |

No CI changes in v1. Developers run `build_reference.py` and pytest locally. Existing shape-only tests (`test_chord_service.py`) keep their current skip-if-`test_rpkm_1` pattern unchanged.

## 8. Out of Scope

- Mart parity or legacy Node parity scripts
- CI job that builds reference Parquet automatically
- Renaming fixture to generic `fake_rpkm_viz_golden` (optional follow-up when second endpoint lands)
- Full-matrix golden comparison (only golden pairs, not gap fillers / colors / full index)
- `pathway_node` as chord `ann_level` (not in API)

## 9. Success Criteria

- [ ] `fake_rpkm_chord_golden.tsv` committed with documented row roles in YAML header comment or spec
- [ ] Tier 1: 21 int anchor rows assert exact values
- [ ] Tier 2: 14 unfiltered chord cases + taxon filter + ann filter + 3 edge cases
- [ ] Golden module skips cleanly when bridge Parquet missing
- [ ] Shared session fixture reusable from future endpoint test modules
- [ ] Existing unit tests and Node tests unaffected

## 10. References

- `analytics/api/chord_service.py` — runtime SQL
- `analytics/transform/models/intermediate/int_tax_rollup_resolved.sql`
- `analytics/transform/scripts/run_pipeline.py`
- `analytics/transform/scripts/build_reference.py`
- `docs/superpowers/specs/2026-06-22-chord-dbt-api-design.md` §6 — documented deviations (fallback, Unclassified, unmapped)
