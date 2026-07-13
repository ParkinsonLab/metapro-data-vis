from __future__ import annotations

import pytest

from api.query_enriched import (
    ann_filter_where_sql,
    ann_order_by_sql,
    ann_order_distinct_cols_sql,
    canonical_pathway_label_sql,
    lineage_order_by_sql,
    resolve_tax_id_sql,
    resolve_tax_label_sql,
    taxon_filter_where_sql,
)


def test_resolve_tax_label_sql_phylum():
    sql = resolve_tax_label_sql("phylum")
    assert "phylum_label" in sql
    assert "kingdom_label" in sql
    assert "class_label" not in sql


def test_resolve_tax_label_sql_species_includes_full_chain():
    sql = resolve_tax_label_sql("species")
    for rank in ("species", "genus", "family", "order", "class", "phylum", "kingdom"):
        assert f"{rank}_label" in sql
    assert "'Unclassified'" in sql


def test_resolve_tax_label_sql_with_prefix():
    sql = resolve_tax_label_sql("genus", prefix="m")
    assert "m.genus_label" in sql
    assert "m.kingdom_label" in sql
    assert "m.species_label" not in sql


def test_resolve_tax_label_sql_invalid_rank():
    with pytest.raises(ValueError, match="invalid tax_level"):
        resolve_tax_label_sql("domain")


def test_resolve_tax_id_sql_kingdom_no_coalesce():
    assert resolve_tax_id_sql("kingdom") == "kingdom_id"


def test_resolve_tax_id_sql_phylum():
    sql = resolve_tax_id_sql("phylum")
    assert "phylum_id" in sql
    assert "kingdom_id" in sql
    assert "COALESCE" in sql


def test_resolve_tax_id_sql_with_prefix():
    sql = resolve_tax_id_sql("order", prefix="t")
    assert "t.order_id" in sql
    assert "t.kingdom_id" in sql


def test_canonical_pathway_label_sql_node():
    sql = canonical_pathway_label_sql("pathway_node")
    assert "ec_normalized" in sql
    assert "'pathway_node'" in sql


def test_canonical_pathway_label_sql_superpathway():
    sql = canonical_pathway_label_sql("superpathway")
    assert "superpathway_name" in sql
    assert "WHEN 'superpathway' = 'superpathway' THEN superpathway_name" in sql


def test_canonical_pathway_label_sql_with_prefix():
    sql = canonical_pathway_label_sql("pathway", prefix="m")
    assert "m.ec_normalized" in sql
    assert "m.pathway_name" in sql


def test_lineage_order_by_sql_quotes_order_rank():
    sql = lineage_order_by_sql()
    assert sql == 'kingdom, phylum, class, "order", family, genus, species, display_name'


def test_ann_order_by_sql_superpathway():
    assert ann_order_by_sql("superpathway") == "superpathway_name ASC"


def test_ann_order_by_sql_pathway():
    assert ann_order_by_sql("pathway") == "superpathway_name ASC, pathway_name ASC"


def test_ann_order_by_sql_rejects_pathway_node():
    with pytest.raises(ValueError, match="unsupported ann_level"):
        ann_order_by_sql("pathway_node")


def test_ann_order_distinct_cols_sql_superpathway():
    sql = ann_order_distinct_cols_sql("superpathway")
    assert "AS display_label" in sql
    assert sql.endswith("superpathway_name")
    assert ", pathway_name" not in sql


def test_ann_order_distinct_cols_sql_pathway():
    sql = ann_order_distinct_cols_sql("pathway")
    assert "AS display_label" in sql
    assert "superpathway_name" in sql
    assert "pathway_name" in sql


def test_ann_filter_where_sql_none():
    sql, params = ann_filter_where_sql(None, "superpathway")
    assert sql == "TRUE"
    assert params == []


def test_ann_filter_where_sql_superpathway_level():
    sql, params = ann_filter_where_sql(
        {"level": "superpathway", "name": "Carbohydrate Metabolism"},
        "superpathway",
    )
    assert "superpathway_name" in sql
    assert params == ["Carbohydrate Metabolism"]


def test_ann_filter_where_sql_pathway_node_pathway_filter():
    sql, params = ann_filter_where_sql(
        {"level": "pathway", "name": "Glycolysis"},
        "pathway_node",
    )
    assert sql == "pathway_name = ?"
    assert params == ["Glycolysis"]


def test_ann_filter_where_sql_pathway_node_superpathway_filter():
    sql, params = ann_filter_where_sql(
        {"level": "superpathway", "name": "Carbohydrate Metabolism"},
        "pathway_node",
    )
    assert sql == "superpathway_name = ?"
    assert params == ["Carbohydrate Metabolism"]


def test_ann_filter_where_sql_pathway_level_pathway_filter():
    sql, params = ann_filter_where_sql(
        {"level": "pathway", "name": "Glycolysis"},
        "pathway",
    )
    assert sql == "pathway_name = ?"
    assert params == ["Glycolysis"]


def test_taxon_filter_where_sql_none():
    sql, params = taxon_filter_where_sql(None)
    assert sql == "TRUE"
    assert params == []


def test_taxon_filter_where_sql_phylum():
    sql, params = taxon_filter_where_sql({"level": "phylum", "name": "Bacillota"})
    assert "phylum_label" in sql
    assert "kingdom_label" in sql
    assert "class_label" not in sql
    assert params == ["Bacillota"]
