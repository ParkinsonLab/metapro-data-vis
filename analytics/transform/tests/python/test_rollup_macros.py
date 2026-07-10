"""Tests for resolve_tax_label, resolve_tax_id, canonical_pathway_label, aggregate_pathway_tax macros."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

TRANSFORM_DIR = Path(__file__).resolve().parents[2]
ANALYTICS_DIR = TRANSFORM_DIR.parent
MACRO_DIR = TRANSFORM_DIR / "macros"
RANKS = ("kingdom", "phylum", "class", "order", "family", "genus", "species")


@pytest.fixture(scope="session")
def macro_dbt_project(tmp_path_factory):
    """Minimal dbt project with macros only (avoids legacy source deps)."""
    root = tmp_path_factory.mktemp("macro_dbt")
    macros_dst = root / "macros"
    models_dst = root / "models"
    macros_dst.mkdir()
    models_dst.mkdir()
    for path in MACRO_DIR.glob("*.sql"):
        shutil.copy(path, macros_dst / path.name)
    (root / "dbt_project.yml").write_text(
        "\n".join(
            [
                "name: macro_probe",
                "version: '1.0.0'",
                "config-version: 2",
                "profile: macro_probe",
                'macro-paths: ["macros"]',
                'model-paths: ["models"]',
            ]
        )
    )
    (root / "profiles.yml").write_text(
        "\n".join(
            [
                "macro_probe:",
                "  target: dev",
                "  outputs:",
                "    dev:",
                "      type: duckdb",
                "      path: ':memory:'",
            ]
        )
    )
    return root


@pytest.fixture
def conn():
    return duckdb.connect()


@pytest.fixture
def compile_macro(macro_dbt_project):
    """Compile a dbt/Jinja SQL fragment via dbt compile."""

    probe_model = macro_dbt_project / "models" / "_macro_probe.sql"
    compiled_probe = (
        macro_dbt_project
        / "target"
        / "compiled"
        / "macro_probe"
        / "models"
        / "_macro_probe.sql"
    )

    def _compile(sql_body: str) -> str:
        probe_model.write_text(sql_body)
        subprocess.run(
            [
                "uv",
                "run",
                "dbt",
                "compile",
                "--project-dir",
                str(macro_dbt_project),
                "--profiles-dir",
                str(macro_dbt_project),
                "--select",
                "_macro_probe",
            ],
            cwd=ANALYTICS_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        return compiled_probe.read_text()

    yield _compile
    if probe_model.exists():
        probe_model.unlink()


def _select_expr(compile_macro, expr: str) -> str:
    compiled = compile_macro(f"SELECT {expr} AS result")
    match = re.search(r"SELECT\s+(.*)\s+AS result", compiled, re.DOTALL | re.IGNORECASE)
    assert match, f"could not parse compiled SQL:\n{compiled}"
    return match.group(1).strip()



def test_resolve_tax_label_species_falls_back_to_genus(conn, compile_macro):
    expr = "{{ resolve_tax_label('species') }}"
    sql_expr = _select_expr(compile_macro, expr)
    row = conn.execute(
        f"""
        SELECT {sql_expr} AS lbl
        FROM (SELECT
            CAST(NULL AS VARCHAR) AS species_label,
            'GenusName' AS genus_label,
            CAST(NULL AS VARCHAR) AS family_label,
            CAST(NULL AS VARCHAR) AS order_label,
            CAST(NULL AS VARCHAR) AS class_label,
            CAST(NULL AS VARCHAR) AS phylum_label,
            CAST(NULL AS VARCHAR) AS kingdom_label
        )
        """
    ).fetchone()
    assert row[0] == "GenusName"


@pytest.mark.parametrize("tax_level", RANKS)
def test_resolve_tax_label_exact_match(conn, compile_macro, tax_level):
    labels = {f"{r}_label": f"lbl_{r}" for r in RANKS}
    cols = ", ".join(f"'{v}' AS {k}" for k, v in labels.items())
    expr = f"{{{{ resolve_tax_label('{tax_level}') }}}}"
    sql_expr = _select_expr(compile_macro, expr)
    result = conn.execute(f"SELECT {sql_expr} AS lbl FROM (SELECT {cols})").fetchone()[0]
    assert result == f"lbl_{tax_level}"


@pytest.mark.parametrize("tax_level", RANKS)
def test_resolve_tax_label_unclassified_when_all_null(conn, compile_macro, tax_level):
    cols = ", ".join(f"CAST(NULL AS VARCHAR) AS {r}_label" for r in RANKS)
    expr = f"{{{{ resolve_tax_label('{tax_level}') }}}}"
    sql_expr = _select_expr(compile_macro, expr)
    result = conn.execute(f"SELECT {sql_expr} AS lbl FROM (SELECT {cols})").fetchone()[0]
    assert result == "Unclassified"


def test_resolve_tax_id_species_falls_back_to_genus(conn, compile_macro):
    expr = "{{ resolve_tax_id('species') }}"
    sql_expr = _select_expr(compile_macro, expr)
    row = conn.execute(
        f"""
        SELECT {sql_expr} AS tax_id
        FROM (SELECT
            CAST(NULL AS BIGINT) AS species_id,
            42 AS genus_id,
            CAST(NULL AS BIGINT) AS family_id,
            CAST(NULL AS BIGINT) AS order_id,
            CAST(NULL AS BIGINT) AS class_id,
            CAST(NULL AS BIGINT) AS phylum_id,
            CAST(NULL AS BIGINT) AS kingdom_id
        )
        """
    ).fetchone()
    assert row[0] == 42


def test_canonical_pathway_label_node_is_ec(conn, compile_macro):
    expr = (
        "{{ canonical_pathway_label('pathway_node', 'ec_normalized', "
        "'pathway_id', 'pathway_name', 'superpathway_name') }}"
    )
    sql_expr = _select_expr(compile_macro, expr)
    row = conn.execute(
        f"""
        SELECT {sql_expr} AS lbl
        FROM (SELECT
            '1.1.1.1' AS ec_normalized,
            1 AS pathway_id,
            'Pathway A' AS pathway_name,
            'Super A' AS superpathway_name
        )
        """
    ).fetchone()
    assert row[0] == "1.1.1.1"


def test_canonical_pathway_label_unmapped_zero_ec(conn, compile_macro):
    expr = (
        "{{ canonical_pathway_label('pathway', 'ec_normalized', "
        "'pathway_id', 'pathway_name', 'superpathway_name') }}"
    )
    sql_expr = _select_expr(compile_macro, expr)
    row = conn.execute(
        f"""
        SELECT {sql_expr} AS lbl
        FROM (SELECT
            '0.0.0.0' AS ec_normalized,
            1 AS pathway_id,
            'Pathway A' AS pathway_name,
            'Super A' AS superpathway_name
        )
        """
    ).fetchone()
    assert row[0] == "Unmapped EC"


def test_canonical_pathway_label_unmapped_null_pathway_id(conn, compile_macro):
    expr = (
        "{{ canonical_pathway_label('pathway', 'ec_normalized', "
        "'pathway_id', 'pathway_name', 'superpathway_name') }}"
    )
    sql_expr = _select_expr(compile_macro, expr)
    row = conn.execute(
        f"""
        SELECT {sql_expr} AS lbl
        FROM (SELECT
            '1.1.1.1' AS ec_normalized,
            CAST(NULL AS INTEGER) AS pathway_id,
            CAST(NULL AS VARCHAR) AS pathway_name,
            CAST(NULL AS VARCHAR) AS superpathway_name
        )
        """
    ).fetchone()
    assert row[0] == "Unmapped EC"


def test_canonical_pathway_label_superpathway(conn, compile_macro):
    expr = (
        "{{ canonical_pathway_label('superpathway', 'ec_normalized', "
        "'pathway_id', 'pathway_name', 'superpathway_name') }}"
    )
    sql_expr = _select_expr(compile_macro, expr)
    row = conn.execute(
        f"""
        SELECT {sql_expr} AS lbl
        FROM (SELECT
            '1.1.1.1' AS ec_normalized,
            1 AS pathway_id,
            'Pathway A' AS pathway_name,
            'Super A' AS superpathway_name
        )
        """
    ).fetchone()
    assert row[0] == "Super A"


def test_canonical_pathway_label_pathway(conn, compile_macro):
    expr = (
        "{{ canonical_pathway_label('pathway', 'ec_normalized', "
        "'pathway_id', 'pathway_name', 'superpathway_name') }}"
    )
    sql_expr = _select_expr(compile_macro, expr)
    row = conn.execute(
        f"""
        SELECT {sql_expr} AS lbl
        FROM (SELECT
            '1.1.1.1' AS ec_normalized,
            1 AS pathway_id,
            'Pathway A' AS pathway_name,
            'Super A' AS superpathway_name
        )
        """
    ).fetchone()
    assert row[0] == "Pathway A"


def test_aggregate_pathway_tax_groups_and_sums(conn, compile_macro):
    null_id_cols = ", ".join(
        f"CAST(NULL AS BIGINT) AS {r}_id" for r in RANKS if r != "kingdom"
    )
    null_label_cols = ", ".join(
        f"CAST(NULL AS VARCHAR) AS {r}_label" for r in RANKS if r != "kingdom"
    )
    compiled = compile_macro(
        f"""
        WITH src AS (
            SELECT
                's1' AS sample_id,
                ec_normalized,
                pathway_id,
                pathway_name,
                superpathway_name,
                value,
                kingdom_id,
                kingdom_label,
                {null_id_cols},
                {null_label_cols}
            FROM (VALUES
                ('1.1.1.1', 1, 'Path A', 'Super A', 10.0, 100, 'K'),
                ('2.2.2.2', 1, 'Path A', 'Super A', 5.0, 100, 'K')
            ) AS v(ec_normalized, pathway_id, pathway_name, superpathway_name, value, kingdom_id, kingdom_label)
        )
        {{{{ aggregate_pathway_tax('src', 'kingdom', 'pathway') }}}}
        """
    )
    df = conn.execute(compiled).df()
    assert len(df) == 1
    assert df.iloc[0]["sample_id"] == "s1"
    assert df.iloc[0]["pathway_label"] == "Path A"
    assert df.iloc[0]["resolved_tax_label"] == "K"
    assert float(df.iloc[0]["value"]) == 15.0
