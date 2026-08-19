# Exploratory Data Analysis

SQL-first validation of MetaPro RPKM sample data against taxonomy/pathway reference tables.

## Prerequisites

- Python 3.14 (see repo-root `.python-version`)
- [uv](https://docs.astral.sh/uv/)
- [Git LFS](https://git-lfs.com/)
- `resources/db/taxonomy.db` (local, gitignored — needed only to refresh Parquet dumps; see root [Refreshing reference data](../../README.md#refreshing-reference-data))

## Setup

Prerequisites include Git LFS — see the root [Prerequisites](../../README.md#prerequisites) for install, clone, and pull commands.

```bash
cd analytics
uv sync --all-groups   # includes dev: pytest, Jupyter, jupysql
```

## Two-step workflow

### Step 1 — Produce dumps (when `taxonomy.db` changes)

```bash
cd analytics
uv run python exploration/scripts/export_parquet.py
```

### Step 2 — Run analysis

```bash
cd analytics
uv run jupyter execute exploration/notebooks/exploratory_analysis.ipynb
```

## Development rules

1. Test SQL via CLI before adding to notebook: `uv run python -c "import duckdb; ..."`
2. Integrate validated SQL into `%%sql` cells
3. Execute full notebook to refresh outputs
4. **Never hand-edit notebook output cells**
5. Parquet changes only via `export_parquet.py`

## Layout

- `scripts/export_parquet.py` — infrastructure (SQLite → Parquet)
- `notebooks/exploratory_analysis.ipynb` — all analysis code + results
- `docs/data-model.md` — data dictionary, logical ER diagram, and regression validation targets
