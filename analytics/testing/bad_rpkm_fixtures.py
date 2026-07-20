"""Invalid RPKM TSV fixtures for pipeline failure integration tests."""
from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "transform" / "tests" / "fixtures"

# Zero-byte file: preflight fails. Listed as dev fixture `bad_rpkm_empty`.
BAD_RPKM_EMPTY = FIXTURES_DIR / "bad_rpkm_empty.tsv"

# Valid headers/rows but all tax column values are zero → ingest yields no rows → assert_mart_nonempty fails.
BAD_RPKM_EMPTY_MART = FIXTURES_DIR / "bad_rpkm_empty_mart.tsv"
