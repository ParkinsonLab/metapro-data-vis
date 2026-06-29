# Chord Golden Integration Tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared `fake_rpkm` fixture with YAML-backed golden tests for the dbt pipeline (`rollup_grid`, 21 rows) and chord DuckDB service (14 unfiltered + filter + edge cases), reusable by future viz endpoints.

**Architecture:** One tab-separated `fake_rpkm.tsv` runs through `run_pipeline.py` once per pytest session. Shared helpers in `analytics/testing/fake_rpkm_fixture.py` and `analytics/conftest.py`. Transform tests assert exact rows in `int_tax_rollup_resolved`; API tests assert chord pairs extracted from `build_chord_from_duckdb()`. A one-time dump script generates YAML goldens from the built DuckDB; engineer reviews values before commit.

**Tech Stack:** Python 3.14, DuckDB, dbt-duckdb, pytest, PyYAML

**Worktree:** `.worktrees/chord-dbt-api/` on branch `feature/chord-dbt-api`

**Spec:** `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md`

**Run tests from:** `analytics/` only (`cd analytics && uv run pytest …`)

---

## Reference Material

Read before implementing:

- `docs/superpowers/specs/2026-06-22-chord-golden-tests-design.md` — file layout, YAML schema, skip behaviour
- `analytics/transform/scripts/stg_rpkm_long.py` — TSV columns, EC normalization
- `analytics/api/chord_service.py` — runtime SQL, filter wiring
- `analytics/api/chord_matrix.py` — index layout (`gap_1`, ann cats, `gap_2`, tax cats, `gap_3`)
- `analytics/transform/tests/python/test_build_reference.py` — bridge semantics (reference tests use 9606; **fake_rpkm uses bacterial tax_ids only**)

**Prerequisite (local):** Reference Parquet built once:

```bash
cd analytics
uv run python transform/scripts/build_reference.py
```

Expected: `transform/reference/parquet/bridge_ec_pathway.parquet` and `bridge_tax_rollup.parquet` exist.

---

## File Map

```
analytics/
├── pyproject.toml                                          # MODIFY: add pyyaml to dev deps
├── conftest.py                                             # CREATE: shared fake_rpkm_db fixture
├── testing/
│   ├── __init__.py                                         # CREATE
│   ├── fake_rpkm_fixture.py                                # CREATE: paths, YAML, pipeline, pairs helper
│   └── dump_fake_rpkm_expectations.py                      # CREATE: one-time golden YAML generator
├── transform/tests/
│   ├── fixtures/
│   │   ├── fake_rpkm.tsv                                   # CREATE
│   │   └── fake_rpkm_pipeline_expectations.yaml            # CREATE (populated via dump script)
│   └── python/
│       └── test_fake_rpkm_pipeline.py                      # CREATE
└── api/tests/
    ├── fixtures/
    │   └── chord_expectations.yaml                         # CREATE (populated via dump script)
    └── test_chord_service.py                               # MODIFY: merge pair tests, use fake_rpkm
```

---

### Task 1: PyYAML dev dependency and testing package

**Files:**
- Modify: `analytics/pyproject.toml`
- Create: `analytics/testing/__init__.py`

- [ ] **Step 1: Add PyYAML to dev dependency group**

In `analytics/pyproject.toml`, under `[dependency-groups] dev`:

```toml
dev = [
    "pytest>=8.0",
    "numpy>=2.5.0",
    "pandas>=3.0.3",
    "pyyaml>=6.0",
]
```

- [ ] **Step 2: Sync**

```bash
cd analytics && uv sync
```

Expected: resolves without error.

- [ ] **Step 3: Create empty testing package**

```python
# analytics/testing/__init__.py
"""Shared pytest helpers for fake_rpkm integration fixtures."""
```

- [ ] **Step 4: Commit**

```bash
git add analytics/pyproject.toml analytics/uv.lock analytics/testing/__init__.py
git commit -m "chore(analytics): add pyyaml dev dep and testing package"
```

---

### Task 2: Shared fixture module (`fake_rpkm_fixture.py`)

**Files:**
- Create: `analytics/testing/fake_rpkm_fixture.py`

- [ ] **Step 1: Create fixture module**

```python
# analytics/testing/fake_rpkm_fixture.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

ANALYTICS_DIR = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ANALYTICS_DIR / "transform"
FIXTURES_DIR = TRANSFORM_DIR / "tests/fixtures"
REFERENCE_PARQUET_DIR = TRANSFORM_DIR / "reference/parquet"

SAMPLE_ID = "fake_rpkm"
TSV_PATH = FIXTURES_DIR / "fake_rpkm.tsv"
DB_PATH = TRANSFORM_DIR / f"runs/{SAMPLE_ID}/sample.duckdb"
PIPELINE_YAML = FIXTURES_DIR / "fake_rpkm_pipeline_expectations.yaml"
CHORD_YAML = ANALYTICS_DIR / "api/tests/fixtures/chord_expectations.yaml"

REQUIRED_BRIDGES = (
    REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet",
    REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet",
)
RANKS = ("kingdom", "phylum", "class", "order", "family", "genus", "species")
ANN_LEVELS = ("superpathway", "pathway")


def bridges_available() -> bool:
    return all(p.exists() for p in REQUIRED_BRIDGES)


def skip_reason() -> str:
    missing = [p.name for p in REQUIRED_BRIDGES if not p.exists()]
    return f"Reference parquet not built ({', '.join(missing)}); run build_reference.py"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_pipeline_expectations() -> dict[str, Any]:
    return load_yaml(PIPELINE_YAML)


def load_chord_expectations() -> dict[str, Any]:
    return load_yaml(CHORD_YAML)


def ensure_pipeline_built() -> Path:
    if not bridges_available():
        raise RuntimeError(skip_reason())
    if DB_PATH.exists():
        return DB_PATH
    if not TSV_PATH.exists():
        raise FileNotFoundError(f"Missing fixture TSV: {TSV_PATH}")
    cmd = [
        "uv",
        "run",
        "python",
        "transform/scripts/run_pipeline.py",
        "--sample-id",
        SAMPLE_ID,
        "--rpkm-path",
        str(TSV_PATH.resolve()),
        "--tax-rank",
        "phylum",
        "--pathway-level",
        "superpathway",
    ]
    result = subprocess.run(
        cmd,
        cwd=ANALYTICS_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"run_pipeline.py failed (exit {result.returncode}):\n{result.stderr}"
        )
    if not DB_PATH.exists():
        raise RuntimeError(f"Pipeline succeeded but DB missing: {DB_PATH}")
    return DB_PATH


def extract_chord_pairs(chord_result: dict) -> list[tuple[str, str, float]]:
    """Return sorted (pathway_label, resolved_tax_label, value) from matrix output."""
    index = chord_result["index"]
    matrix = chord_result["count_matrix"]
    gap2 = index.index("gap_2")
    ann_labels = index[1:gap2]
    tax_labels = index[gap2 + 1 : -1]
    pairs: list[tuple[str, str, float]] = []
    for ann in ann_labels:
        i = index.index(ann)
        for tax in tax_labels:
            j = index.index(tax)
            val = matrix[i][j]
            if val > 0:
                pairs.append((ann, tax, float(val)))
    return sorted(pairs)


def assert_pairs_close(
    actual: list[tuple[str, str, float]],
    expected: list[list],
) -> None:
    import pytest

    exp_tuples = [(str(a), str(b), float(v)) for a, b, v in expected]
    assert len(actual) == len(exp_tuples), f"pair count: {actual!r} vs {exp_tuples!r}"
    for got, want in zip(actual, exp_tuples):
        assert got[0] == want[0]
        assert got[1] == want[1]
        assert got[2] == pytest.approx(want[2])
```

- [ ] **Step 2: Smoke import**

```bash
cd analytics && uv run python -c "from testing.fake_rpkm_fixture import SAMPLE_ID; print(SAMPLE_ID)"
```

Expected: `fake_rpkm`

- [ ] **Step 3: Commit**

```bash
git add analytics/testing/fake_rpkm_fixture.py
git commit -m "feat(testing): add shared fake_rpkm fixture helpers"
```

---

### Task 3: Shared pytest conftest

**Files:**
- Create: `analytics/conftest.py`

- [ ] **Step 1: Create conftest with session fixture**

```python
# analytics/conftest.py
from __future__ import annotations

import pytest

from testing import fake_rpkm_fixture as fixture


@pytest.fixture(scope="session")
def fake_rpkm_db() -> str:
    if not fixture.bridges_available():
        pytest.skip(fixture.skip_reason())
    path = fixture.ensure_pipeline_built()
    return str(path)
```

- [ ] **Step 2: Verify collection still works**

```bash
cd analytics && uv run pytest --collect-only -q api/tests/test_filters.py
```

Expected: collects without import errors.

- [ ] **Step 3: Commit**

```bash
git add analytics/conftest.py
git commit -m "feat(testing): add session fake_rpkm_db pytest fixture"
```

---

### Task 4: Build `fake_rpkm.tsv` from real bridge IDs

**Files:**
- Create: `analytics/transform/tests/fixtures/fake_rpkm.tsv`

Use DuckDB to pick concrete IDs before writing the TSV. **Use bacterial tax_ids only** (metagenomics domain; keeps the fixture valid if the app later restricts to bacterial taxonomy). Default focal: **`1280`** (*Staphylococcus aureus*).

Run from `analytics/`:

```bash
cd analytics
uv run python - <<'PY'
import duckdb
from pathlib import Path

ref = Path("transform/reference/parquet")
tax = ref / "bridge_tax_rollup.parquet"
ec = ref / "bridge_ec_pathway.parquet"
FOCAL = 1280
conn = duckdb.connect()
conn.execute(f"CREATE TABLE tax AS SELECT * FROM read_parquet('{tax}')")
conn.execute(f"CREATE TABLE ec AS SELECT * FROM read_parquet('{ec}')")

# Bacterial tax_ids: resolved kingdom label = 'Bacteria'
conn.execute("""
    CREATE TEMP TABLE bacteria AS
    SELECT DISTINCT source_tax_id
    FROM tax
    WHERE requested_rank = 'kingdom' AND resolved_tax_label = 'Bacteria'
""")

# Focal: S. aureus resolves at species
focal = conn.execute("""
    SELECT source_tax_id, resolved_tax_rank, resolved_tax_label
    FROM tax
    WHERE source_tax_id = ? AND requested_rank = 'species'
""", [FOCAL]).fetchone()
print("focal_tax_id:", focal)

# ECs mapping to KEGG pathways (metabolic genes; typical for bacteria)
ecs = conn.execute("""
    SELECT ec_normalized,
           MIN(superpathway_name) AS sp,
           MIN(pathway_name) AS pw
    FROM ec
    GROUP BY ec_normalized
    HAVING COUNT(DISTINCT superpathway_name) >= 1
    ORDER BY COUNT(DISTINCT superpathway_id) DESC, ec_normalized
    LIMIT 5
""").fetchall()
print("ec candidates:", ecs[:3])

# Same phylum as focal, different genus — bacterial sibling
sibs = conn.execute("""
    SELECT focal.source_tax_id AS focal_id,
           ga.resolved_tax_label AS focal_genus,
           sib.source_tax_id AS sibling_id,
           gs.resolved_tax_label AS sibling_genus,
           ph.resolved_tax_label AS phylum
    FROM tax focal
    JOIN tax ph ON ph.source_tax_id = focal.source_tax_id AND ph.requested_rank = 'phylum'
    JOIN tax ga ON ga.source_tax_id = focal.source_tax_id AND ga.requested_rank = 'genus'
    JOIN tax sib ON sib.source_tax_id != focal.source_tax_id
    JOIN tax ps ON ps.source_tax_id = sib.source_tax_id
               AND ps.requested_rank = 'phylum'
               AND ps.resolved_tax_id = ph.resolved_tax_id
    JOIN tax gs ON gs.source_tax_id = sib.source_tax_id AND gs.requested_rank = 'genus'
    JOIN bacteria bf ON bf.source_tax_id = focal.source_tax_id
    JOIN bacteria bs ON bs.source_tax_id = sib.source_tax_id
    WHERE focal.source_tax_id = ?
      AND ga.resolved_tax_id != gs.resolved_tax_id
    LIMIT 5
""", [FOCAL]).fetchall()
print("sibling candidates:", sibs)

# Fallback: bacterial taxon where species request resolves coarser than species
fallback = conn.execute("""
    SELECT t.source_tax_id, t.resolved_tax_rank, t.resolved_tax_label
    FROM tax t
    JOIN bacteria b ON b.source_tax_id = t.source_tax_id
    WHERE t.requested_rank = 'species'
      AND t.resolved_tax_rank IS NOT NULL
      AND t.resolved_tax_rank != 'species'
    LIMIT 5
""").fetchall()
print("fallback candidates:", fallback)
PY
```

- [ ] **Step 1: Run ID discovery script**

Pick from output:

| Role | Selection rule |
|---|---|
| `focal_tax_id` | **`1280`** (*Staphylococcus aureus*) — verify species-level resolution in bridge |
| `sibling_tax_id` | Bacterial tax_id from sibling query sharing phylum with 1280, different genus (e.g. another *Firmicutes* genus) |
| `fallback_tax_id` | Bacterial tax_id from fallback query (species request → coarser rank) |
| `unknown_tax_id` | `999999999` (not in bridge) |
| `ec_focal` | EC mapping to a known superpathway (e.g. first row from ec candidates) |
| `ec_sibling` | EC mapping to a **different** superpathway than `ec_focal` |
| `ec_fallback` | Any mapped EC for fallback taxon row (can reuse `ec_sibling`) |

**Do not use** eukaryote / human tax_ids (e.g. 9606) in fixture columns.

- [ ] **Step 2: Write TSV**

Create `analytics/transform/tests/fixtures/fake_rpkm.tsv` (tab-separated). Template — replace EC strings and tax_id columns with discovered values:

```tsv
GeneID	Length	Reads	EC#	RPKM	Unclassified	1280	<SIBLING_TAX_ID>	<FALLBACK_TAX_ID>	999999999
g_focal	100	10	<EC_FOCAL>	10	0	10	0	0	0
g_sib	100	10	<EC_SIBLING>	20	0	0	20	0	0
g_fallback	100	10	<EC_FALLBACK>	30	0	0	0	30	0
g_unknown	100	10	<EC_FOCAL>	40	0	0	0	0	40
g_unmapped	100	10		50	0	0	0	0	0
```

Rules:

- Row `g_focal`: value 10 at focal tax only — drives `rollup_grid` focal pair.
- Row `g_sib`: value 20 at sibling tax — same phylum, different genus; changes rollup sums at coarser ranks.
- Row `g_fallback`: value 30 at fallback tax — tests coarser resolution at species request.
- Row `g_unknown`: value 40 at unknown tax_id — `'Unclassified'` label.
- Row `g_unmapped`: empty `EC#` → `0.0.0.0` → `'Unmapped EC'`.

- [ ] **Step 3: Verify TSV parses**

```bash
cd analytics && uv run python - <<'PY'
from pathlib import Path
import duckdb
from analytics.transform.scripts.stg_rpkm_long import _transform

p = Path("transform/tests/fixtures/fake_rpkm.tsv").resolve()
conn = duckdb.connect()
rel = _transform(conn, str(p), "fake_rpkm")
df = rel.df()
print(df)
assert len(df) >= 5
assert (df["source_tax_id"] == 999999999).any()
assert (df["ec_normalized"] == "0.0.0.0").any()
PY
```

Expected: long rows for each non-zero cell; includes unmapped EC and unknown tax_id.

- [ ] **Step 4: Commit**

```bash
git add analytics/transform/tests/fixtures/fake_rpkm.tsv
git commit -m "test: add hand-designed fake_rpkm.tsv fixture"
```

---

### Task 5: Golden YAML dump script and populated expectations

**Files:**
- Create: `analytics/testing/dump_fake_rpkm_expectations.py`
- Create: `analytics/transform/tests/fixtures/fake_rpkm_pipeline_expectations.yaml`
- Create: `analytics/api/tests/fixtures/chord_expectations.yaml`

- [ ] **Step 1: Create dump script**

```python
# analytics/testing/dump_fake_rpkm_expectations.py
"""Generate golden YAML from built fake_rpkm DuckDB. Run once after TSV is final."""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import yaml

from api.chord_service import build_chord_from_duckdb
from api.filters import normalise_ann_filter, normalise_taxon_filter
from testing.fake_rpkm_fixture import (
    ANN_LEVELS,
    CHORD_YAML,
    PIPELINE_YAML,
    RANKS,
    SAMPLE_ID,
    ensure_pipeline_built,
    extract_chord_pairs,
    load_pipeline_expectations,
)


def dump_rollup_grid(conn, focal_ec: str, focal_tax_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT requested_rank, pathway_level, pathway_label,
               resolved_tax_label, value
        FROM int_tax_rollup_resolved
        WHERE ec_normalized = ? AND source_tax_id = ?
        ORDER BY requested_rank, pathway_level
        """,
        [focal_ec, focal_tax_id],
    ).fetchall()
    if len(rows) != 21:
        raise RuntimeError(f"expected 21 rollup rows, got {len(rows)}")
    return [
        {
            "requested_rank": r[0],
            "pathway_level": r[1],
            "pathway_label": r[2] or "Unmapped EC",
            "resolved_tax_label": r[3],
            "value": float(r[4]),
        }
        for r in rows
    ]


def dump_chord_case(tax_level: str, ann_level: str, **filters) -> dict:
    ann = normalise_ann_filter(filters.get("selected_ann_cat"), ann_level)
    tax = normalise_taxon_filter(filters.get("selected_taxon"))
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level=tax_level,
        ann_level=ann_level,
        ann_filter=ann,
        taxon_filter=tax,
    )
    pairs = extract_chord_pairs(out)
    case = {
        "case_id": filters.get("case_id", f"{tax_level}_{ann_level}"),
        "tax_level": tax_level,
        "ann_level": ann_level,
        "pairs": [[a, t, v] for a, t, v in pairs],
    }
    for key in ("selected_ann_cat", "selected_taxon"):
        if key in filters:
            case[key] = filters[key]
    return case


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--focal-ec", required=True)
    parser.add_argument("--focal-tax-id", type=int, required=True)
    parser.add_argument("--fallback-tax-id", type=int, required=True)
    parser.add_argument("--sibling-genus-name", required=True)
    parser.add_argument("--ann-superpathway-name", required=True)
    args = parser.parse_args()

    db = ensure_pipeline_built()
    conn = duckdb.connect(str(db), read_only=True)

    pipeline_doc = {
        "fixture": {
            "sample_id": SAMPLE_ID,
            "tsv": "fake_rpkm.tsv",
            "focal_ec": args.focal_ec,
            "focal_tax_id": args.focal_tax_id,
            "roles": {
                "fallback_tax_id": args.fallback_tax_id,
                "unknown_tax_id": 999999999,
            },
        },
        "rollup_grid": dump_rollup_grid(conn, args.focal_ec, args.focal_tax_id),
    }
    conn.close()

    unfiltered = [
        dump_chord_case(rank, ann, case_id=f"{rank}_{ann}")
        for rank in RANKS
        for ann in ANN_LEVELS
    ]

    filtered = [
        dump_chord_case(
            "phylum",
            "superpathway",
            case_id="taxon_filter_sibling_genus",
            selected_taxon={"level": "genus", "name": args.sibling_genus_name},
        ),
        dump_chord_case(
            "phylum",
            "superpathway",
            case_id="ann_filter_superpathway",
            selected_ann_cat=args.ann_superpathway_name,
        ),
    ]

    edge_cases = [
        dump_chord_case("phylum", "superpathway", case_id="unmapped_ec_snapshot"),
        dump_chord_case("phylum", "superpathway", case_id="unclassified_tax_snapshot"),
        dump_chord_case("species", "superpathway", case_id="fallback_species_request"),
    ]

    chord_doc = {
        "sample_id": SAMPLE_ID,
        "chord_unfiltered": unfiltered,
        "chord_filtered": filtered,
        "edge_cases": edge_cases,
    }

    PIPELINE_YAML.write_text(yaml.safe_dump(pipeline_doc, sort_keys=False), encoding="utf-8")
    CHORD_YAML.parent.mkdir(parents=True, exist_ok=True)
    CHORD_YAML.write_text(yaml.safe_dump(chord_doc, sort_keys=False), encoding="utf-8")
    print(f"Wrote {PIPELINE_YAML}")
    print(f"Wrote {CHORD_YAML}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run pipeline + dump**

After Task 4 TSV is committed, with bridges present:

```bash
cd analytics
uv run python transform/scripts/run_pipeline.py \
  --sample-id fake_rpkm \
  --rpkm-path transform/tests/fixtures/fake_rpkm.tsv \
  --tax-rank phylum \
  --pathway-level superpathway
```

Then dump (fill CLI args from Task 4 discovery output):

```bash
cd analytics
uv run python -m testing.dump_fake_rpkm_expectations \
  --focal-ec "<EC_FOCAL>" \
  --focal-tax-id 1280 \
  --fallback-tax-id <FALLBACK_TAX_ID> \
  --sibling-genus-name "<SIBLING_GENUS_NAME>" \
  --ann-superpathway-name "<SUPERPATHWAY_FOR_EC_FOCAL>"
```

Expected: writes both YAML files; `rollup_grid` has 21 entries; `chord_unfiltered` has 14 entries.

- [ ] **Step 3: Manual review**

Open both YAML files and confirm:

- Focal `rollup_grid` **values are constant** (raw focal cell mass, e.g. 10.0); **labels** vary across rank × pathway_level. Sibling rollup effects appear in **chord** pair goldens after GROUP BY, not in int focal row values.
- `edge_cases` include `'Unmapped EC'` and `'Unclassified'` pairs where expected.
- `fallback_species_request` shows coarser label than species for fallback taxon mass.
- No zero-value pairs listed.

- [ ] **Step 4: Commit**

```bash
git add analytics/testing/dump_fake_rpkm_expectations.py \
  analytics/transform/tests/fixtures/fake_rpkm_pipeline_expectations.yaml \
  analytics/api/tests/fixtures/chord_expectations.yaml
git commit -m "test: add fake_rpkm golden expectations YAML"
```

---

### Task 6: Pipeline rollup grid tests

**Files:**
- Create: `analytics/transform/tests/python/test_fake_rpkm_pipeline.py`

- [ ] **Step 1: Write pipeline test module**

```python
# analytics/transform/tests/python/test_fake_rpkm_pipeline.py
from __future__ import annotations

import duckdb
import pytest

from testing.fake_rpkm_fixture import (
    bridges_available,
    load_pipeline_expectations,
    skip_reason,
)

pytestmark = pytest.mark.skipif(not bridges_available(), reason=skip_reason())

_expectations = load_pipeline_expectations()
_fixture = _expectations["fixture"]
_rollup_rows = _expectations["rollup_grid"]


@pytest.mark.parametrize(
    "row",
    _rollup_rows,
    ids=lambda r: f"{r['requested_rank']}-{r['pathway_level']}",
)
def test_rollup_grid_row(row, fake_rpkm_db):
    conn = duckdb.connect(fake_rpkm_db, read_only=True)
    try:
        result = conn.execute(
            """
            SELECT pathway_label, resolved_tax_label, value
            FROM int_tax_rollup_resolved
            WHERE ec_normalized = ?
              AND source_tax_id = ?
              AND requested_rank = ?
              AND pathway_level = ?
            """,
            [
                _fixture["focal_ec"],
                _fixture["focal_tax_id"],
                row["requested_rank"],
                row["pathway_level"],
            ],
        ).fetchone()
    finally:
        conn.close()

    assert result is not None, f"missing row: {row}"
    pathway_label, resolved_tax_label, value = result
    expected_label = row["pathway_label"]
    if pathway_label is None:
        pathway_label = "Unmapped EC"
    assert pathway_label == expected_label
    assert resolved_tax_label == row["resolved_tax_label"]
    assert float(value) == pytest.approx(float(row["value"]))


def test_rollup_grid_row_count(fake_rpkm_db):
    conn = duckdb.connect(fake_rpkm_db, read_only=True)
    try:
        n = conn.execute(
            """
            SELECT COUNT(*) FROM int_tax_rollup_resolved
            WHERE ec_normalized = ? AND source_tax_id = ?
            """,
            [_fixture["focal_ec"], _fixture["focal_tax_id"]],
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 21
```

Note: module loads YAML at import time; skip if bridges missing **before** YAML read would fail — order matters. Guard:

```python
if bridges_available():
    _expectations = load_pipeline_expectations()
    _fixture = _expectations["fixture"]
    _rollup_rows = _expectations["rollup_grid"]
else:
    _expectations = _fixture = None
    _rollup_rows = []
```

Use that pattern in the final file.

- [ ] **Step 2: Run pipeline tests**

```bash
cd analytics && uv run pytest transform/tests/python/test_fake_rpkm_pipeline.py -v
```

Expected: 22 passed (21 parametrized + 1 count) when bridges and YAML present; SKIPPED when bridges absent.

- [ ] **Step 3: Commit**

```bash
git add analytics/transform/tests/python/test_fake_rpkm_pipeline.py
git commit -m "test: assert fake_rpkm rollup_grid against pipeline YAML"
```

---

### Task 7: Chord pair tests in `test_chord_service.py`

**Files:**
- Modify: `analytics/api/tests/test_chord_service.py`

- [ ] **Step 1: Replace module contents**

```python
# analytics/api/tests/test_chord_service.py
from __future__ import annotations

import pytest

from api.chord_service import build_chord_from_duckdb
from api.filters import normalise_ann_filter, normalise_taxon_filter
from testing.fake_rpkm_fixture import (
    SAMPLE_ID,
    assert_pairs_close,
    bridges_available,
    extract_chord_pairs,
    load_chord_expectations,
    skip_reason,
)

if bridges_available():
    _chord = load_chord_expectations()
    _unfiltered = _chord["chord_unfiltered"]
    _filtered = _chord["chord_filtered"]
    _edge = _chord["edge_cases"]
else:
    _unfiltered = _filtered = _edge = []


def test_build_chord_rejects_comparison():
    with pytest.raises(ValueError, match="comparison mode"):
        build_chord_from_duckdb(
            sample_id=SAMPLE_ID,
            tax_level="phylum",
            ann_level="superpathway",
            ann_filter=None,
            taxon_filter=None,
            names=["a.tsv", "b.tsv"],
        )


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
def test_build_chord_from_duckdb_shape(fake_rpkm_db):
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level="phylum",
        ann_level="superpathway",
        ann_filter=None,
        taxon_filter=None,
    )
    assert "count_matrix" in out
    assert out["index"][0] == "gap_1"
    assert len(out["count_matrix"]) == len(out["index"])


def _run_case(case: dict) -> list[tuple[str, str, float]]:
    ann = normalise_ann_filter(case.get("selected_ann_cat"), case["ann_level"])
    tax = normalise_taxon_filter(case.get("selected_taxon"))
    out = build_chord_from_duckdb(
        sample_id=SAMPLE_ID,
        tax_level=case["tax_level"],
        ann_level=case["ann_level"],
        ann_filter=ann,
        taxon_filter=tax,
    )
    return extract_chord_pairs(out)


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _unfiltered, ids=lambda c: c["case_id"])
def test_chord_unfiltered_pairs(case, fake_rpkm_db):
    assert_pairs_close(_run_case(case), case["pairs"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _filtered, ids=lambda c: c["case_id"])
def test_chord_filtered_pairs(case, fake_rpkm_db):
    assert_pairs_close(_run_case(case), case["pairs"])


@pytest.mark.skipif(not bridges_available(), reason=skip_reason())
@pytest.mark.parametrize("case", _edge, ids=lambda c: c["case_id"])
def test_chord_edge_case_pairs(case, fake_rpkm_db):
    actual = _run_case(case)
    assert_pairs_close(actual, case["pairs"])
    if case["case_id"] == "unmapped_ec_snapshot":
        assert any(p[0] == "Unmapped EC" for p in actual)
    if case["case_id"] == "unclassified_tax_snapshot":
        assert any(p[1] == "Unclassified" for p in actual)
```

- [ ] **Step 2: Run chord service tests**

```bash
cd analytics && uv run pytest api/tests/test_chord_service.py -v
```

Expected: all tests pass when bridges present; comparison test always runs; others skip without bridges.

- [ ] **Step 3: Commit**

```bash
git add analytics/api/tests/test_chord_service.py
git commit -m "test: add fake_rpkm chord pair golden tests"
```

---

### Task 8: Full verification

- [ ] **Step 1: Run full analytics test suite**

```bash
cd analytics && uv run pytest -v
```

Expected: all previously passing tests still pass; new fake_rpkm tests pass when bridges built; fake_rpkm tests SKIPPED when bridges removed.

- [ ] **Step 2: Run Node tests (unchanged)**

```bash
npm test
```

Expected: 58 passed (or current baseline unchanged).

- [ ] **Step 3: Final commit if any fixups needed**

Only if step 1–2 required changes.

---

## Spec Coverage Checklist

| Spec requirement | Task |
|---|---|
| `fake_rpkm.tsv` shared fixture | Task 4 |
| `fake_rpkm_pipeline_expectations.yaml` with `rollup_grid` (21) | Task 5 |
| `chord_expectations.yaml` (14 + filter + edge) | Task 5 |
| `test_fake_rpkm_pipeline.py` | Task 6 |
| Merged into `test_chord_service.py` | Task 7 |
| `fake_rpkm_fixture.py` + `conftest.py` | Tasks 2–3 |
| Skip when bridges missing | Tasks 2–3, 6–7 |
| Run from `analytics/` only | All commands |
| No CI changes | — |
| Existing unit tests unaffected | Task 8 |

---

## Plan Self-Review Notes

- Dump script generates YAML from actual pipeline output; engineer **must review** YAML before commit (Task 5 Step 3) — values are oracle-quality only after review.
- `test_fake_rpkm_pipeline.py` guards YAML load when bridges absent to avoid import errors.
- `dump_fake_rpkm_expectations.py` is a dev tool, not run in CI; committed so goldens can be regenerated when TSV changes.
- Edge-case YAML snapshots capture full pair lists at phylum/superpathway (or specified rank); review ensures unmapped/unclassified pairs are present.
