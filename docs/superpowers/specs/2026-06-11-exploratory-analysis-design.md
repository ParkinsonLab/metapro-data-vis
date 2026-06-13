# Exploratory Data Analysis — Design Spec

> **Status:** Approved (2026-06-11)  
> **Goal:** Validate assumptions about MetaPro RPKM sample data and the taxonomy/pathway reference database through reproducible, SQL-first exploratory analysis; document findings and data semantics to support future `analytics/transform/` work (dbt + DuckDB, out of scope here).

## 1. Context

Metapro Viz ingests RPKM TSV output from [MetaPro](https://github.com/ParkinsonLab/MetaPro) and joins it to `resources/db/taxonomy.db` for visualizations. The reference DB is built via ad-hoc Jupyter notebooks under `resources/scripts/`; there is no reproducible Python environment or scripted data-quality pipeline.

**Datasets in scope:**

| Asset | Location | Role |
|---|---|---|
| Sample RPKM 1 | `resources/example_data/test_rpkm_1.tsv` (~51 MB, ~426K rows) | Metagenomic sample; EC + tax_id columns |
| Sample RPKM 2 | `resources/example_data/test_rpkm_2.tsv` (~71 MB, ~461K rows) | Second sample for overlap/diff profiling |
| Reference DB | `resources/db/taxonomy.db` (~793 MB) | NCBI taxonomy + KEGG pathway reference |

**Reference DB tables (7):**

| Table | ~Rows | Purpose |
|---|---|---|
| `nodes` | 2.8M | Tax_id registry |
| `names` | 2.8M | Scientific name per tax_id (builder filters NCBI to `scientific name` only; 1:1 with `nodes` in practice) |
| `parents` | 2.8M | Denormalized rank columns per tax_id |
| `pathway_nodes` | 24K | KEGG map nodes (EC numbers as `name`) |
| `pathway_edges` | 47K | Pathway graph edges |
| `pathway_superpathways` | 193 | Pathway → superpathway membership |
| `superpathways` | 13 | Superpathway names |

**RPKM TSV shape:** Fixed columns `GeneID, Length, Reads, EC#, RPKM, Unclassified` plus integer tax_id column headers holding per-taxon values. EC normalization at parse time: `EC:1.1.1.1` → `1.1.1.1`; `None`/empty → `0.0.0.0` (per `SPEC.md`).

## 2. Requirements (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Analysis style | **SQL-first via DuckDB + JupySQL** | Declarative over imperative; `%%sql` cells for syntax highlighting |
| Analysis code location | **Jupyter notebook** | Colocation and interactivity; code lives in cells |
| Dev testing | **CLI snippets** (`uv run python -c "..."`) before integrating into notebook | Validate logic in isolation |
| Validation | **Full notebook execute** at end; iterate on code cells only | Reproducible outputs |
| Result immutability | **Never hand-edit notebook `outputs` or fabricate stats** | Outputs regenerated only by execution |
| Dump production | **Outside notebook** (`export_parquet.py`) | Same dump files → same notebook output |
| Parquet versioning | **Git LFS** for all 7 table Parquet files | Version-control reference data content |
| RPKM versioning | **Git LFS** for `test_rpkm_1.tsv` and `test_rpkm_2.tsv` | Reproducible inputs |
| Repo layout | `analytics/exploration/` (now) vs `analytics/transform/` (future) | Clear lifecycle separation |
| Python env | `uv` + `analytics/pyproject.toml` + `analytics/uv.lock` | Lockfile scoped to analytics, not Node app |
| Python version | **3.14** | DuckDB has production `cp314` wheels; dbt deferred to transform phase |
| JSON sidecars | **Deferred** | Notebook outputs are canonical; add `output/` when transform needs machine-readable artifacts |
| Work isolation | **Git worktree** `.worktrees/exploration-eda/` on branch `exploration/eda` | Isolated from main development |
| Scope | **Core + RPKM profiling + reference integrity + cross-domain joins** | Full assumption validation (option C) |

## 3. Repository Layout

```
analytics/
├── pyproject.toml              # uv project, Python 3.14
├── uv.lock
└── exploration/
    ├── scripts/
    │   └── export_parquet.py   # prerequisite: SQLite → Parquet
    ├── notebooks/
    │   └── exploratory_analysis.ipynb
    ├── docs/
    │   └── data-model.md       # data dictionary + semantics (updated from notebook findings)
    └── README.md               # two-step workflow, immutability rules

resources/
├── db/
│   └── parquet/                # Git LFS — one file per table
│       ├── names.parquet
│       ├── nodes.parquet
│       ├── parents.parquet
│       ├── pathway_nodes.parquet
│       ├── pathway_edges.parquet
│       ├── pathway_superpathways.parquet
│       └── superpathways.parquet
└── example_data/
    ├── test_rpkm_1.tsv         # Git LFS
    └── test_rpkm_2.tsv         # Git LFS
```

`.gitattributes` tracks `*.parquet` and `resources/example_data/test_rpkm_*.tsv` via LFS. `.gitignore` is updated to allow these paths through the existing `resources/*` blanket ignore.

## 4. Two-Step Workflow

Analysis depends on pre-produced dump files. The notebook never writes Parquet.

```bash
# Step 1 — produce dumps (run when taxonomy.db changes)
cd analytics
uv run python exploration/scripts/export_parquet.py

# Step 2 — run analysis (reads dumps + RPKM TSVs only)
uv run jupyter execute exploration/notebooks/exploratory_analysis.ipynb
```

**Reproducibility contract:** Given identical `resources/db/parquet/*.parquet` and `resources/example_data/test_rpkm_*.tsv`, notebook execution produces equivalent results.

## 5. Infrastructure Script: `export_parquet.py`

DuckDB attaches SQLite and exports each table:

```sql
ATTACH 'resources/db/taxonomy.db' AS db (TYPE SQLITE);
COPY db.names TO 'resources/db/parquet/names.parquet' (FORMAT PARQUET);
-- repeat for all 7 tables
```

**Behavior:**
- Idempotent — overwrites existing Parquet files
- Prints row count and file size per table
- Exits non-zero if `taxonomy.db` is missing
- Runnable standalone; not invoked from notebook export logic (notebook only verifies outputs exist)

## 6. Python Environment

**Dependencies (exploration only):**
- `duckdb` — SQL engine, Parquet/TSV I/O, SQLite attach
- `jupysql` — `%%sql` cells with SQL syntax highlighting (native DuckDB connection)
- `jupyter`, `ipykernel` — notebook execution

**Not included:** `pandas`, `pyarrow`, `duckdb-engine`, `dbt-core`, `dbt-duckdb`

**Setup:**
```bash
cd analytics && uv sync
```

`.python-version` at repo root (3.14) remains the team-wide Python pin.

## 7. Notebook Structure

Single notebook: `analytics/exploration/notebooks/exploratory_analysis.ipynb`

| Section | Content |
|---|---|
| **1. Setup** | Python cell: `duckdb.connect()`, `%load_ext sql`, `%sql conn`; path constants; shared SQL snippets (e.g. `ec_normalize` as `CASE`) |
| **2. Verify inputs** | Assert Parquet + RPKM files exist; print row counts and file sizes; fail fast with pointer to `export_parquet.py` |
| **3. Data dictionary** | Schema, row counts, PK/FK relationships per table; entity-relationship narrative |
| **4. Cardinality & degrees** | min/max/median stats: names per tax_id, pathway in/out-degree, edges per pathway, etc. |
| **5. RPKM profiling** | Per-file row counts, null/sentinel rates, EC distribution, tax column sparsity, overlap/diff between files |
| **6. Reference integrity** | Orphan FKs, duplicate/ambiguous keys, rank hierarchy consistency, pathway graph connectivity |
| **7. Cross-domain joins** | RPKM tax columns → `names`; EC → `pathway_nodes` → superpathway chain; match rates + unmapped ID lists |
| **8. Findings summary** | Markdown cells summarizing validated assumptions, violations, and gotchas for future analytics |

**Display:** Analysis sections use `%%sql` cells (JupySQL). Setup and dynamic path logic stay in Python cells. CLI snippet testing during development uses `conn.sql("...")` before promoting SQL into `%%sql` cells.

### 7.1 Reference Integrity Checks

| Check | SQL approach | Output |
|---|---|---|
| Orphan FKs | `LEFT JOIN` child → parent `WHERE parent.id IS NULL` | Count + % per FK + sample IDs |
| Duplicate keys | `GROUP BY` key `HAVING COUNT(*) > 1` | Keys with unexpected multiplicity |
| Names per tax_id | `GROUP BY tax_id` cardinality stats | min/max/median (synonyms expected) |
| EC name uniqueness | `GROUP BY name` on `pathway_nodes` | Duplicates affecting `get_superpathway_info()` |
| Rank completeness | `CASE` ladder: if `t_genus` set, expect upstream ranks set | % incomplete rows |
| Rank transitive consistency | Self-join `parents` on rank columns | Mismatched denormalized snapshots |
| Pathway dangling nodes | Nodes with zero edges in pathway | Count per pathway |
| Pathway degree distribution | `GROUP BY` source/target on edges | min/max/median in/out-degree |
| Disconnected components | Per-pathway subgraph analysis | Component count (noting limitations in pure SQL) |

### 7.2 Cross-Domain Join Checks

| Check | SQL approach |
|---|---|
| RPKM tax columns → `names` | `UNPIVOT` tax columns; join to `names` on tax_id |
| RPKM EC → `pathway_nodes` | Normalize EC via `CASE`; join on `pathway_nodes.name` |
| EC → superpathway chain | Join through `pathway_superpathways` → `superpathways` |
| File overlap | Compare distinct tax_ids and ECs across both RPKM files |

## 8. Development Workflow & Immutability

**During development (agent or human):**
1. Write and test SQL/logic via `uv run python -c "..."` or throwaway temp files (not committed)
2. Integrate validated code into notebook cells
3. Execute full notebook
4. Review outputs; iterate on **code cells only**
5. Commit notebook with fresh outputs

**Rules:**
- Never hand-edit `outputs` blocks in `.ipynb` JSON
- Never fabricate statistics in markdown cells
- Parquet files change only via `export_parquet.py`
- `docs/data-model.md` factual claims must match notebook results

## 9. Git LFS Configuration

**`.gitattributes`:**
```
*.parquet filter=lfs diff=lfs merge=lfs -text
resources/example_data/test_rpkm_*.tsv filter=lfs diff=lfs merge=lfs -text
```

**`.gitignore` updates:** Negation rules to allow `resources/db/parquet/`, `test_rpkm_*.tsv`, and `analytics/` through existing `resources/*` ignore patterns.

## 10. Worktree Setup

All exploration work happens on branch `exploration/eda` in worktree `.worktrees/exploration-eda/`.

- `.worktrees/` added to `.gitignore` (project-local worktrees directory)
- First commit on this branch: this design spec (+ `.gitignore` update)
- Implementation commits follow on same branch

## 11. Documentation Deliverables

| Artifact | Purpose |
|---|---|
| `exploratory_analysis.ipynb` (executed) | Canonical analysis report with stored outputs |
| `docs/data-model.md` | Data dictionary plus **observed-grounded logical ER diagram** (how relationships should hold, cited to notebook evidence); gaps and contradictions flagged for review |
| `exploration/README.md` | How to set up env, run dumps, execute notebook, dev workflow rules |

## 12. Out of Scope

- dbt models or `analytics/transform/` pipeline
- Statistical modeling or visualization app changes
- Rebuilding `taxonomy.db` from source notebooks
- JSON sidecar output files
- Biological correctness validation (taxonomic accuracy)
- CI integration (may be added later)

## 13. Future Considerations

- **`analytics/transform/`:** Add dbt + dbt-duckdb when dbt-core 1.12 stable supports Python 3.14 and dbt-duckdb follows
- **JSON sidecars:** Add `analytics/exploration/output/` when transform pipeline needs programmatic artifacts
- **uv workspace:** Promote to root workspace if multiple Python packages emerge under `analytics/`

## 14. Entity Relationships (Logical Model)

This section states **how reference tables and RPKM sample files should relate** — grounded in schema DDL, DB build scripts (`write_to_tax_db.ipynb`), and app join logic (`SPEC.md`, `db_functions.ts`). Cardinalities here are the **intended logical constraints** for analytics and data-quality review.

**Pre-EDA diagram (superseded):** The first draft used overly permissive cardinalities (e.g. many `names` per `tax_id` for synonyms). The DB builder loads **scientific names only** and `get_name_from_id` reads `names.tax_id`; EDA confirmed exactly one `names` row per `tax_id` in the current dump. The authoritative observed-grounded diagram lives in `analytics/exploration/docs/data-model.md` (Task 14).

**Discrepancy handling:** When observed data violates an intended edge, EDA documents the gap. Whether a violation is a **problem** is decided case-by-case — e.g. unknown tax_id headers may be acceptable at parse time (app leaves raw id), but duplicate `names` per `tax_id` would break header rename logic.

### 14.1 Taxonomy + RPKM (intended cardinalities)

Join keys are on **`tax_id`**, not `names.id` (`names.id` is a UUID surrogate PK from the build script).

`rpkm_sample` stands for both `test_rpkm_1.tsv` and `test_rpkm_2.tsv`. **Per tax_id column header** (not per row, not once per file): each header is one integer tax_id in the wide TSV.

| Edge | Join key | Intended cardinality | Reverse (per sample file) |
|---|---|---|---|
| `nodes` ↔ `names` | `names.tax_id = nodes.id` | **1:1** — each node has exactly one name row; each name row belongs to exactly one node | — |
| `nodes` ↔ `parents` | `parents.tax_id = nodes.id` | **1:0..1** — each node has at most one parents row; each parents row belongs to exactly one node | — |
| RPKM header → `nodes` | header integer = `nodes.id` | **1:1** — each tax_id header resolves to exactly one node | **0..1** — a given `nodes.id` may appear as 0 or 1 column header in a given sample file (see below) |
| RPKM header → `names` | header integer = `names.tax_id` | **1:1** — each tax_id header resolves to exactly one name row | **0..1** — a given `names.tax_id` may appear as 0 or 1 column header in a given sample file |
| RPKM header → `parents` | header integer = `parents.tax_id` | **1:0..1** — each tax_id header resolves to 0 or 1 parents row | **0..1** — a given `parents.tax_id` may appear as 0 or 1 column header in a given sample file |

**Reference tax_id → sample column header (per file):** RPKM files are wide: each tax_id is a **column name**, not a cell value. If column headers are unique within a file (as they should be), then each reference `tax_id` appears **at most once** as a header in that file — 0 if absent, 1 if present. That **is** the reverse direction; no separate DB check is required beyond asserting header uniqueness if the format is ever in doubt. EDA measured overlap between samples (6 shared headers) but did not add an explicit duplicate-header SQL check.

**RPKM header → reference when unmapped:** If a header tax_id is absent from reference tables, cardinality is 0 on the reference side; the app logs a warning and keeps the raw id (`SPEC.md`). Sample files in scope matched 100% (8/8 and 12/12).

**Nodes without `parents` rows (acceptable in current dump):** Of 2,840,139 nodes, 5 have no `parents` row. All are top-level or meta taxa from NCBI — likely intentional gaps in `tax_parents.csv`, not orphan bugs:

| `tax_id` | Scientific name | Notes |
|---:|---|---|
| 1 | root | Tree root |
| 10239 | Viruses | Top-level domain |
| 131567 | cellular organisms | Meta-node above domain |
| 2787823 | unclassified entries | NCBI placeholder |
| 2787854 | other entries | NCBI placeholder |

Sample RPKM headers (8 + 12) all have `parents` rows; none of these five tax_ids appear as column headers in the test fixtures.

**Rank columns:** `parents.t_kingdom` … `parents.t_species` are denormalized rank tax_ids; each references `nodes.id` when non-null. EDA samples these as logical FKs (not all rank columns exhaustively checked).

### 14.2 Pathway + RPKM (intended cardinalities)

Row-level (not header-level) for EC joins. Pathway internal edges remain as in the original model — several are **not** strict 1:1 (e.g. `pathway_nodes.name` is not unique).

| Edge | Join key | Intended cardinality | Notes |
|---|---|---|---|
| RPKM row → `pathway_nodes` | normalized `EC#` = `pathway_nodes.name` | **0..many** pathway nodes per EC value | Fan-out observed; not a taxonomy-style 1:1 |
| `pathway_nodes` → `pathway_edges` | `source` / `target` | **0..many** edges per node | Dangling nodes observed |
| `pathway_nodes` → `pathway_superpathways` | `pathway_nodes.pathway = pathway_superpathways.id` | **logical only** (app SQL, not SQLite FK) | EDA missing-link sample returned 0 rows |
| `pathway_superpathways` → `superpathways` | `superpathway = superpathways.id` | **many:1** | Declared FK in build |

**Normalization (RPKM → `pathway_nodes` only):** `EC:x.y.z` → `x.y.z`; `None`/empty → `0.0.0.0` (per `SPEC.md`).

**Not modeled as FK edges:** `GeneID`, `Length`, `Reads`, `RPKM`, `Unclassified` are row-level attributes with no reference table in scope.

### 14.3 Observed-grounded ER diagram (deliverable)

`analytics/exploration/docs/data-model.md` must include a Mermaid ER diagram using **relationship-only syntax** (no entity attribute blocks). Each edge is annotated in prose/table with:

- Intended cardinality (from §14.1–14.2)
- Notebook evidence (section + metric) or **“not measured — review”**
- Flag if observation contradicts intent or if schema does not enforce the constraint

### 14.4 Regression validation targets (invariants without source guarantee)

Some relationships **hold in the current dump** but are **not fully guaranteed** by SQLite DDL, upstream NCBI files, or the ad-hoc build notebooks. Document these explicitly in `data-model.md` as **regression validation targets**: invariants to re-run when reference data, RPKM samples, or build scripts change.

| Invariant | Holds today | Guaranteed by | Re-validate when |
|---|---|---|---|
| Exactly one `names` row per `tax_id` | Yes (min=max=1) | ETL filter (`scientific name` only), not `UNIQUE` on `names.tax_id` | `write_to_tax_db.ipynb` or NCBI names source changes |
| `names.tax_id` → `nodes.id` orphan-free | Yes (0 orphans) | SQLite FK on `names.tax_id` | After DB rebuild |
| At most one `parents` row per `tax_id` | Yes (0 duplicates) | `UNIQUE` on `parents.tax_id` in DDL | After DB rebuild |
| Non-meta nodes have a `parents` row | Mostly (5 meta/root exceptions) | `tax_parents.csv` coverage only | `tax_parents.csv` or parents ETL changes |
| RPKM tax_id header → 1:1 `nodes`/`names` | Yes in test fixtures (100%) | MetaPro output + reference completeness | New RPKM samples or taxonomy refresh |
| Reference `tax_id` → ≤1 column header per sample file | Yes (unique headers) | Wide TSV format: column names unique per file | New RPKM layout or format change |

**Naming:** **Regression validation target** = the invariant to protect on data refresh. **Enforcement** = what (if anything) makes it hold today. **Re-validate when** = trigger for re-running the notebook check. Passing today does not mean enforced forever — it means “watch this on the next refresh.”

## 15. Success Criteria

- [ ] `uv sync` installs exploration dependencies reproducibly
- [ ] `export_parquet.py` produces 7 Parquet files matching SQLite row counts
- [ ] Parquet and RPKM files tracked via Git LFS
- [ ] Notebook executes end-to-end reading only dump files + RPKM TSVs
- [ ] All section C analyses produce stored outputs
- [ ] `docs/data-model.md` documents schemas, observed-grounded logical ER diagram, evidence per edge, and gaps for review
- [ ] No hand-edited notebook outputs in committed artifacts
