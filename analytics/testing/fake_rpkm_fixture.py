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
REPO_ROOT = ANALYTICS_DIR.parent

SAMPLE_ID = "fake_rpkm"
TSV_PATH = FIXTURES_DIR / "fake_rpkm.tsv"
DB_PATH = TRANSFORM_DIR / f"runs/{SAMPLE_ID}/sample.duckdb"
PIPELINE_YAML = FIXTURES_DIR / "fake_rpkm_pipeline_expectations.yaml"
CHORD_YAML = ANALYTICS_DIR / "api/tests/fixtures/chord_expectations.yaml"
OVERVIEW_YAML = ANALYTICS_DIR / "api/tests/fixtures/overview_expectations.yaml"
KRONA_YAML = ANALYTICS_DIR / "api/tests/fixtures/krona_expectations.yaml"
PATHWAY_LIST_YAML = ANALYTICS_DIR / "api/tests/fixtures/pathway_list_expectations.yaml"
GRAPH_YAML = ANALYTICS_DIR / "api/tests/fixtures/graph_expectations.yaml"
NETWORK_YAML = ANALYTICS_DIR / "api/tests/fixtures/network_expectations.yaml"
NAMES_PATH = REPO_ROOT / "resources/db/parquet/names.parquet"

REQUIRED_BRIDGES = (
    REFERENCE_PARQUET_DIR / "bridge_ec_pathway.parquet",
    REFERENCE_PARQUET_DIR / "bridge_tax_rollup.parquet",
)
RANKS = ("species", "genus", "family", "order", "class", "phylum", "kingdom")
# Finest → coarsest annotation grain (matches tax RANKS ordering intent).
ANN_LEVELS = ("pathway_node", "pathway", "superpathway")


def bridges_available() -> bool:
    return all(p.exists() for p in REQUIRED_BRIDGES)


def skip_reason() -> str:
    missing = [p.name for p in REQUIRED_BRIDGES if not p.exists()]
    return f"Reference parquet not built ({', '.join(missing)}); run build_reference.py"


def krona_fixtures_available() -> bool:
    return bridges_available() and NAMES_PATH.exists()


def krona_skip_reason() -> str:
    if not bridges_available():
        return skip_reason()
    if not NAMES_PATH.exists():
        return f"names parquet missing ({NAMES_PATH.name}); build resources/db/parquet"
    return ""


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_pipeline_expectations() -> dict[str, Any]:
    return load_yaml(PIPELINE_YAML)


def load_chord_expectations() -> dict[str, Any]:
    return load_yaml(CHORD_YAML)


def load_overview_expectations() -> dict[str, Any]:
    return load_yaml(OVERVIEW_YAML)


def load_krona_expectations() -> dict[str, Any]:
    return load_yaml(KRONA_YAML)


def load_pathway_list_expectations() -> dict[str, Any]:
    return load_yaml(PATHWAY_LIST_YAML)


def load_graph_expectations() -> dict[str, Any]:
    return load_yaml(GRAPH_YAML)


def load_network_expectations() -> dict[str, Any]:
    return load_yaml(NETWORK_YAML)


def ensure_pipeline_built() -> Path:
    if not bridges_available():
        raise RuntimeError(skip_reason())
    if DB_PATH.exists() and TSV_PATH.exists():
        if TSV_PATH.stat().st_mtime > DB_PATH.stat().st_mtime:
            DB_PATH.unlink()
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


def extract_chord_index(chord_result: dict) -> list[str]:
    return list(chord_result["index"])


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


def extract_graph_inner_index(graph_result: dict) -> list[str]:
    return list(graph_result["inner_matrix_index"])


def extract_graph_outer_index(graph_result: dict) -> list[str]:
    return list(graph_result["outer_matrix_index"])


def extract_graph_pairs(graph_result: dict) -> list[tuple[str, str, float]]:
    """Return sorted (ec_normalized, display_name, value) from inner matrix output."""
    index = graph_result["inner_matrix_index"]
    matrix = graph_result["inner_count_matrix"]
    gap2 = index.index("gap_2")
    ec_labels = index[1:gap2]
    tax_labels = index[gap2 + 1 : -1]
    pairs: list[tuple[str, str, float]] = []
    for ec in ec_labels:
        i = index.index(ec)
        for tax in tax_labels:
            j = index.index(tax)
            val = matrix[i][j]
            if val > 0:
                pairs.append((ec, tax, float(val)))
    return sorted(pairs)


def extract_graph_tax_map(graph_result: dict) -> dict[str, str]:
    return dict(graph_result["tax_map"])


def extract_network_ec_values(out: dict, ec: str) -> list[list]:
    node = next(n for n in out["nodes"] if n["label"] == ec and n["values"])
    return [[v["id"], v["value"]] for v in node["values"] if v["value"] > 0]


def extract_network_colors(out: dict) -> dict[str, str]:
    return out["colors"]


def assert_pairs_close(
    actual: list,
    expected: list[list],
) -> None:
    import pytest

    if not expected:
        assert actual == []
        return
    if len(expected[0]) == 2:
        exp_tuples = [(str(a), float(b)) for a, b in expected]
        act_tuples = [(str(a), float(b)) for a, b in actual]
        assert len(act_tuples) == len(exp_tuples), (
            f"pair count: {act_tuples!r} vs {exp_tuples!r}"
        )
        for got, want in zip(act_tuples, exp_tuples):
            assert got[0] == want[0]
            assert got[1] == pytest.approx(want[1])
        return

    exp_tuples = [(str(a), str(b), float(v)) for a, b, v in expected]
    assert len(actual) == len(exp_tuples), f"pair count: {actual!r} vs {exp_tuples!r}"
    for got, want in zip(actual, exp_tuples):
        assert got[0] == want[0]
        assert got[1] == want[1]
        assert got[2] == pytest.approx(want[2])
