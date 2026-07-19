"""Invalid RPKM TSV fixtures for pipeline failure integration tests."""
from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "transform" / "tests" / "fixtures"

# Zero-byte file: ingest model fails (no expected columns). Listed as dev fixture `bad_rpkm_empty`.
BAD_RPKM_EMPTY = FIXTURES_DIR / "bad_rpkm_empty.tsv"

# Future candidates: header-only, wrong column names, all-invalid tax cells, etc.
