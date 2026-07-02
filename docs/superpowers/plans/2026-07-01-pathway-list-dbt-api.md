# Pathway List API via dbt Intermediates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI `POST /api/viz/pathway-list` returning sample-filtered pathway names (alphabetical) from `int_tax_rollup_resolved` with chord filter parity, shared `rollup_query` extraction, Express sidecar proxy, renderer toggle, and golden tests on `fake_rpkm`.

**Architecture:** Extract `build_filtered_rollup_rows()` from `chord_service.py` into `rollup_query.py` (temp table `filtered_rollup_rows`). Pathway-list queries distinct pathway labels at `pathway_level = 'pathway'` with `ORDER BY display_label ASC`. Request is chord-aligned (`names`, `tax_level`, `selected_ann_cat`, `selected_taxon`); server pins `ann_level = 'pathway'`. Express defaults to legacy; renderer appends `?backend=duckdb` for migrated channels.

**Tech Stack:** Python 3.14, FastAPI, DuckDB, pytest, Pydantic; Node 22, Express 5, vitest, React

**Branch:** `feature/pathway-list-dbt-api`

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-07-01-pathway-list-dbt-api-design.md` — approved design
- `analytics/api/chord_service.py` — source for rollup extraction (`chord_prefix_rows` → `filtered_rollup_rows`)
- `analytics/api/filters.py` — `normalise_ann_filter`, `normalise_taxon_filter`, `sample_id_from_names`
- `analytics/api/envelope.py` — `wrap_handler`
- `analytics/api/tests/test_overview_service.py` — golden test pattern
- `src/server/index.ts` — sidecar route registration
- `src/server/fastapi_sidecar_proxy.ts` — shared proxy
- `src/renderer/src/vizBackend.ts` — `MIGRATED_CHANNELS`
- `src/renderer/src/components/Chord.tsx` — request shape to mirror in Network

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
├── rollup_query.py                    # CREATE: shared filter SQL + build_filtered_rollup_rows
├── chord_service.py                   # MODIFY: import rollup_query; rename temp table refs
├── pathway_list_service.py            # CREATE: build_pathway_list_from_duckdb
├── schemas.py                         # MODIFY: PathwayListRequest
├── main.py                            # MODIFY: POST /api/viz/pathway-list
└── tests/
    ├── fixtures/
    │   └── pathway_list_expectations.yaml   # CREATE (via dump or hand-authored)
    ├── test_rollup_query.py           # CREATE: chord still works after extraction
    ├── test_pathway_list_service.py  # CREATE: integration + golden + chord set cross-check
    └── test_main.py                   # MODIFY: pathway-list endpoint smoke

analytics/testing/
├── fake_rpkm_fixture.py               # MODIFY: PATHWAY_LIST_YAML + loader
└── dump_fake_rpkm_expectations.py     # MODIFY: dump pathway-list goldens (optional)

src/server/
├── data_functions.ts                  # MODIFY: selected_ann_cat name fallback
└── index.ts                           # MODIFY: pathway-list → sidecarRoutes

src/renderer/src/
├── vizBackend.ts                      # MODIFY: add 'pathway_list'
├── api.ts                             # MODIFY: sidecarQuery('pathway_list')
└── components/Network.tsx             # MODIFY: chord-aligned request + deps

src/tests/
├── data_functions.test.ts             # MODIFY: selected_ann_cat legacy fallback test
└── fastapi_sidecar_proxy.test.ts      # MODIFY: pathway_list label case
```

---

### Task 1: `PathwayListRequest` schema

**Files:**
- Modify: `analytics/api/schemas.py`

- [ ] **Step 1: Add model**

```python
class PathwayListRequest(BaseModel):
    names: list[str] = Field(default_factory=list)
    tax_level: str
    selected_ann_cat: Any = Field(default_factory=dict)
    selected_taxon: Any = Field(default_factory=dict)
```

- [ ] **Step 2: Commit**

```bash
git add analytics/api/schemas.py
git commit -m "feat(analytics): add PathwayListRequest schema"
```

---

### Task 2: Extract `rollup_query.py`

**Files:**
- Create: `analytics/api/rollup_query.py`
- Modify: `analytics/api/chord_service.py`
- Create: `analytics/api/tests/test_rollup_query.py`

- [ ] **Step 1: Write failing test — chord matrix unchanged after extraction**

```python
import pytest
from api.chord_service import build_chord_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_chord_matrix_unchanged_after_rollup_extraction(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
        names=[f"{SAMPLE_ID}.tsv"],
    )
    assert len(out["index"]) > 0
    assert len(out["count_matrix"]) == len(out["index"])
```

- [ ] **Step 2: Run — expect FAIL** (module not found or import error)

```bash
cd analytics && uv run pytest api/tests/test_rollup_query.py -v
```

- [ ] **Step 3: Create `rollup_query.py`**

Move from `chord_service.py` into `rollup_query.py`:

- `PATHWAY_LABEL_SQL`
- `_sql_in_list`
- `_ann_predicate`
- `BRIDGE_EC_PATH`, `REFERENCE_PARQUET_DIR` paths as needed
- `build_filtered_rollup_rows(conn, *, tax_level, ann_level, ann_filter, taxon_filter) -> None`

`build_filtered_rollup_rows` creates temp table **`filtered_rollup_rows`** (same columns as today's `chord_prefix_rows`).

- [ ] **Step 4: Refactor `chord_service.py`**

- Import `build_filtered_rollup_rows`, `PATHWAY_LABEL_SQL` from `api.rollup_query`
- Replace inline `CREATE TEMP TABLE chord_prefix_rows` with `build_filtered_rollup_rows(...)`
- Update `_fetch_tax_order` and `_fetch_ann_order` SQL to read from `filtered_rollup_rows` instead of `chord_prefix_rows`
- Keep `_fetch_tax_order`, `_fetch_ann_order`, `build_chord_from_duckdb` in `chord_service.py`

- [ ] **Step 5: Run test — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_rollup_query.py -v
```

Also run existing chord tests:

```bash
cd analytics && uv run pytest api/tests/test_main.py -v -k chord
```

- [ ] **Step 6: Commit**

```bash
git add analytics/api/rollup_query.py analytics/api/chord_service.py analytics/api/tests/test_rollup_query.py
git commit -m "refactor(analytics): extract rollup_query shared filter builder"
```

---

### Task 3: `pathway_list_service.py`

**Files:**
- Create: `analytics/api/pathway_list_service.py`
- Create: `analytics/api/tests/test_pathway_list_service.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from api.chord_service import build_chord_from_duckdb
from api.pathway_list_service import build_pathway_list_from_duckdb
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason

SUPERPATHWAY = "Carbohydrate metabolism"  # verify against fake_rpkm chord output; adjust if needed


def test_pathway_list_rejects_empty_names():
    with pytest.raises(ValueError, match="at least one sample"):
        build_pathway_list_from_duckdb(
            names=[],
            tax_level="phylum",
            selected_ann_cat={"level": "superpathway", "name": SUPERPATHWAY},
            selected_taxon={},
        )


def test_pathway_list_rejects_inactive_ann_cat():
    with pytest.raises(ValueError, match="selected_ann_cat is required"):
        build_pathway_list_from_duckdb(
            names=[f"{SAMPLE_ID}.tsv"],
            tax_level="phylum",
            selected_ann_cat={},
            selected_taxon={},
        )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_pathway_list_alphabetical_and_matches_chord_set(fake_rpkm_db):
    ann_filter = {"level": "superpathway", "name": SUPERPATHWAY}
    names = [f"{SAMPLE_ID}.tsv"]
    tax_level = "phylum"
    selected_taxon = {}

    pathways = build_pathway_list_from_duckdb(
        names=names,
        tax_level=tax_level,
        selected_ann_cat=ann_filter,
        selected_taxon=selected_taxon,
    )
    assert pathways == sorted(pathways)
    assert len(pathways) > 0

    chord = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level=tax_level,
        ann_level="pathway",
        ann_filter=ann_filter,
        taxon_filter=None,
        names=names,
    )
    # ann-axis labels between gap markers — extract pathway labels from index
    gaps = {"gap_1", "gap_2", "gap_3"}
    chord_pathways = {lbl for lbl in chord["index"] if lbl not in gaps}
    assert set(pathways) == chord_pathways
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_pathway_list_service.py -v
```

- [ ] **Step 3: Implement `build_pathway_list_from_duckdb`**

```python
def build_pathway_list_from_duckdb(
    *,
    names: list[str],
    tax_level: str,
    selected_ann_cat,
    selected_taxon,
) -> list[str]:
    if len(names) == 0:
        raise ValueError("names must contain at least one sample")
    if len(names) > 1:
        raise ValueError("comparison mode not supported on analytics API")

    validate_tax_level(tax_level)
    ann_filter = normalise_ann_filter(selected_ann_cat, "pathway")
    if ann_filter is None:
        raise ValueError("selected_ann_cat is required")
    taxon_filter = normalise_taxon_filter(selected_taxon)

    sample_id = sample_id_from_names(names)
    # open sample.duckdb, verify int_tax_rollup_resolved exists
    # attach bridge_ec if present
    # build_filtered_rollup_rows(..., ann_level="pathway", ann_filter=ann_filter, ...)
    # run pathway-list SQL with PATHWAY_LABEL_SQL, ORDER BY display_label ASC
    # return list[str]
```

Label SQL: import `PATHWAY_LABEL_SQL` from `rollup_query`; use `.replace("t.", "cf.")` in FROM clause.

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_pathway_list_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/pathway_list_service.py analytics/api/tests/test_pathway_list_service.py
git commit -m "feat(analytics): add pathway list service from filtered rollup rows"
```

---

### Task 4: FastAPI route

**Files:**
- Modify: `analytics/api/main.py`
- Modify: `analytics/api/tests/test_main.py`

- [ ] **Step 1: Write failing smoke test**

```python
def test_pathway_list_endpoint_ok(client, fake_rpkm_db):
    if not bridges_available():
        pytest.skip(skip_reason())
    res = client.post(
        "/api/viz/pathway-list",
        json={
            "names": ["fake_rpkm.tsv"],
            "tax_level": "phylum",
            "selected_ann_cat": {"level": "superpathway", "name": "Carbohydrate metabolism"},
            "selected_taxon": {},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert isinstance(body["value"], list)
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd analytics && uv run pytest api/tests/test_main.py -v -k pathway_list
```

- [ ] **Step 3: Add endpoint**

```python
from api.pathway_list_service import build_pathway_list_from_duckdb
from api.schemas import PathwayListRequest

@app.post("/api/viz/pathway-list")
def pathway_list_endpoint(body: PathwayListRequest):
    def _handle():
        return build_pathway_list_from_duckdb(
            names=body.names,
            tax_level=body.tax_level,
            selected_ann_cat=body.selected_ann_cat,
            selected_taxon=body.selected_taxon,
        )
    return wrap_handler(_handle)
```

- [ ] **Step 4: Run — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_main.py -v -k pathway_list
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/main.py analytics/api/tests/test_main.py
git commit -m "feat(analytics): add POST /api/viz/pathway-list endpoint"
```

---

### Task 5: Golden YAML fixture

**Files:**
- Create: `analytics/api/tests/fixtures/pathway_list_expectations.yaml`
- Modify: `analytics/testing/fake_rpkm_fixture.py`
- Modify: `analytics/api/tests/test_pathway_list_service.py`

- [ ] **Step 1: Add loader to `fake_rpkm_fixture.py`**

```python
PATHWAY_LIST_YAML = ANALYTICS_DIR / "api/tests/fixtures/pathway_list_expectations.yaml"

def load_pathway_list_expectations() -> dict[str, Any]:
    return load_yaml(PATHWAY_LIST_YAML)
```

- [ ] **Step 2: Generate YAML** (run service once, capture output for 1–2 cases)

```bash
cd analytics && uv run python -c "
from api.pathway_list_service import build_pathway_list_from_duckdb
import yaml
cases = [{
  'tax_level': 'phylum',
  'selected_ann_cat': {'level': 'superpathway', 'name': 'Carbohydrate metabolism'},
  'selected_taxon': {},
}]
out = {}
for i, c in enumerate(cases):
    out[f'case_{i}'] = {
        **c,
        'names': ['fake_rpkm.tsv'],
        'expected': build_pathway_list_from_duckdb(names=['fake_rpkm.tsv'], **c),
    }
print(yaml.dump({'pathway_list': out}, sort_keys=False))
"
```

Write output to `pathway_list_expectations.yaml`.

- [ ] **Step 3: Add parametrized golden test**

```python
@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case_key", ["case_0"])  # extend as YAML grows
def test_pathway_list_matches_golden(fake_rpkm_db, case_key):
    cases = load_pathway_list_expectations()["pathway_list"]
    case = cases[case_key]
    out = build_pathway_list_from_duckdb(
        names=case["names"],
        tax_level=case["tax_level"],
        selected_ann_cat=case["selected_ann_cat"],
        selected_taxon=case["selected_taxon"],
    )
    assert out == case["expected"]
    assert out == sorted(out)
```

- [ ] **Step 4: Run — expect PASS**

```bash
cd analytics && uv run pytest api/tests/test_pathway_list_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add analytics/api/tests/fixtures/pathway_list_expectations.yaml analytics/testing/fake_rpkm_fixture.py analytics/api/tests/test_pathway_list_service.py
git commit -m "test(analytics): add pathway list golden expectations"
```

---

### Task 6: Legacy `parse_pathway_list` fallback

**Files:**
- Modify: `src/server/data_functions.ts`
- Modify: `src/tests/data_functions.test.ts`

- [ ] **Step 1: Write failing test**

```typescript
it('resolves superpathway from selected_ann_cat when superpathway omitted', () => {
  const ec = __test__.getEc() as Array<Record<string, unknown>>
  const sp_value = ec.find((r) => r.superpathway != null)?.superpathway as string
  const via_field = parse_pathway_list({ superpathway: sp_value })
  const via_ann = parse_pathway_list({
    selected_ann_cat: { level: 'superpathway', name: sp_value },
  })
  expect(via_ann).toEqual(via_field)
})
```

- [ ] **Step 2: Run — expect FAIL**

```bash
npm test -- src/tests/data_functions.test.ts -t "selected_ann_cat"
```

- [ ] **Step 3: Update handler** (per spec §4.3)

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/server/data_functions.ts src/tests/data_functions.test.ts
git commit -m "fix(server): resolve pathway list superpathway from selected_ann_cat"
```

---

### Task 7: Express sidecar route

**Files:**
- Modify: `src/server/index.ts`
- Modify: `src/tests/fastapi_sidecar_proxy.test.ts`

- [ ] **Step 1: Add proxy test for `pathway_list` label**

Copy chord test pattern; use `label: 'pathway_list'`, `apiPath: '/api/viz/pathway-list'`, expect error prefix `'pathway_list duckdb backend unavailable'`.

- [ ] **Step 2: Run — expect FAIL** (if route not moved yet, skip)

- [ ] **Step 3: Move route in `index.ts`**

Remove from `vizRoutes`; add to `sidecarRoutes`:

```typescript
{
  path: '/api/viz/pathway-list',
  label: 'pathway_list',
  legacyHandler: parse_pathway_list,
},
```

- [ ] **Step 4: Run proxy tests — expect PASS**

```bash
npm test -- src/tests/fastapi_sidecar_proxy.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add src/server/index.ts src/tests/fastapi_sidecar_proxy.test.ts
git commit -m "feat(server): pathway-list sidecar proxy route"
```

---

### Task 8: Renderer wiring

**Files:**
- Modify: `src/renderer/src/vizBackend.ts`
- Modify: `src/renderer/src/api.ts`
- Modify: `src/renderer/src/components/Network.tsx`

- [ ] **Step 1: Add `'pathway_list'` to `MIGRATED_CHANNELS`**

- [ ] **Step 2: Update `api.ts`**

```typescript
pathway_list: { method: 'POST', url: `/api/viz/pathway-list${sidecarQuery('pathway_list')}` },
```

- [ ] **Step 3: Update `Network.tsx`**

Import `toApiFilter` from `chordFilters`. Add store selectors for `selected_file_list`, `tax_rank`, `selected_taxon`. Replace `useEffect` deps and request body per spec §4.3.

- [ ] **Step 4: Manual smoke** (optional)

```bash
npm run dev
# select superpathway in Chord → Network grid loads
```

- [ ] **Step 5: Commit**

```bash
git add src/renderer/src/vizBackend.ts src/renderer/src/api.ts src/renderer/src/components/Network.tsx
git commit -m "feat(renderer): wire pathway-list to sidecar with chord-aligned payload"
```

---

### Task 9: Full verification

- [ ] **Step 1: Python suite**

```bash
cd analytics && uv run pytest api/tests/ -v
```

- [ ] **Step 2: Node suite**

```bash
npm test
```

- [ ] **Step 3: Final commit if any fixups**

```bash
git status
```

---

## Plan Self-Review (spec coverage)

| Spec requirement | Task |
|---|---|
| `rollup_query.py` / `filtered_rollup_rows` | Task 2 |
| `pathway_list_service.py` alphabetical SQL | Task 3 |
| `PathwayListRequest` with `selected_ann_cat` | Task 1, 4 |
| Chord filter parity | Task 3 (`normalise_ann_filter`, `ann_level='pathway'`) |
| Legacy `selected_ann_cat` fallback | Task 6 |
| Express sidecar proxy | Task 7 |
| Renderer `MIGRATED_CHANNELS` + Network payload | Task 8 |
| Golden tests + chord set cross-check | Task 3, 5 |
| Error: `selected_ann_cat is required` | Task 3 |
| Comparison mode error | Task 3 |
