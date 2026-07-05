from api.graph_matrix import build_graph_matrix


def _ec_rows(*ecs: str) -> list[dict]:
    return [{"ec_normalized": ec} for ec in ecs]


def test_build_graph_matrix_shape_and_gaps():
    triples = [("1.1.1.1", "TaxA", 10.0), ("1.1.1.2", "TaxB", 5.0)]
    ec_rows = _ec_rows("1.1.1.1", "1.1.1.2")
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA"},
        {"display_name": "TaxB", "tax_map_value": "PhA"},
    ]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    assert out["inner_matrix_index"][0] == "gap_1"
    assert "gap_2" in out["inner_matrix_index"]
    assert out["inner_matrix_index"][-1] == "gap_3"
    assert len(out["inner_count_matrix"]) == len(out["inner_matrix_index"])
    assert out["tax_map"]["TaxA"] == "PhA"
    assert "1.1.1.1" in out["colors"]


def test_build_graph_matrix_symmetric():
    triples = [("1.1.1.1", "TaxA", 10.0)]
    ec_rows = _ec_rows("1.1.1.1")
    tax_rows = [{"display_name": "TaxA", "tax_map_value": "PhA"}]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    idx = out["inner_matrix_index"]
    i_ec = idx.index("1.1.1.1")
    i_tax = idx.index("TaxA")
    assert out["inner_count_matrix"][i_ec][i_tax] == 10.0
    assert out["inner_count_matrix"][i_tax][i_ec] == 10.0


def test_build_graph_matrix_gap_fillers():
    triples = [("1.1.1.1", "TaxA", 8.0)]
    ec_rows = _ec_rows("1.1.1.1")
    tax_rows = [{"display_name": "TaxA", "tax_map_value": "PhA"}]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    idx = out["inner_matrix_index"]
    i_ec = idx.index("1.1.1.1")
    i_tax = idx.index("TaxA")
    flat_sum = (
        out["inner_count_matrix"][i_ec][i_tax]
        + out["inner_count_matrix"][i_tax][i_ec]
    )
    assert out["inner_count_matrix"][idx.index("gap_1")][idx.index("gap_1")] == flat_sum / 4
    assert out["inner_count_matrix"][idx.index("gap_2")][idx.index("gap_2")] == flat_sum / 2


def test_build_graph_matrix_no_zero_row_trim():
    triples = [("1.1.1.1", "TaxA", 10.0), ("1.1.1.2", "TaxB", 0.0)]
    ec_rows = _ec_rows("1.1.1.1", "1.1.1.2")
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA"},
        {"display_name": "TaxB", "tax_map_value": "PhA"},
    ]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    assert "1.1.1.2" in out["inner_matrix_index"]
    assert "TaxB" in out["inner_matrix_index"]
    assert len(out["inner_count_matrix"]) == len(out["inner_matrix_index"])


def test_outer_matrix_index_tax_categories_only():
    triples = [("1.1.1.1", "TaxA", 10.0), ("2.2.2.2", "TaxB", 5.0)]
    ec_rows = _ec_rows("1.1.1.1", "2.2.2.2")
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA"},
        {"display_name": "TaxB", "tax_map_value": "PhB"},
    ]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    outer = out["outer_matrix_index"]
    assert outer == ["gap_1", "gap_2", "PhA", "PhB", "gap_3"]


def test_ecs_follow_ec_rows_order():
    triples = [("1.1.1.1", "TaxA", 10.0), ("2.2.2.2", "TaxA", 5.0)]
    ec_rows = _ec_rows("1.1.1.1", "2.2.2.2")
    tax_rows = [{"display_name": "TaxA", "tax_map_value": "PhA"}]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    idx = out["inner_matrix_index"]
    assert idx.index("1.1.1.1") < idx.index("2.2.2.2")


def test_ec_colors_do_not_require_ann_category():
    triples = [("1.1.1.1", "TaxA", 10.0), ("2.2.2.2", "TaxA", 5.0)]
    ec_rows = _ec_rows("1.1.1.1", "2.2.2.2")
    tax_rows = [{"display_name": "TaxA", "tax_map_value": "PhA"}]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    assert out["colors"]["1.1.1.1"] != out["colors"]["2.2.2.2"]


def test_tax_level_affects_outer_tax_category_ordering():
    triples = [("1.1.1.1", "TaxA", 10.0), ("1.1.1.1", "TaxB", 5.0)]
    ec_rows = _ec_rows("1.1.1.1")
    tax_rows_phylum = [
        {"display_name": "TaxB", "tax_map_value": "PhylumA"},
        {"display_name": "TaxA", "tax_map_value": "PhylumZ"},
    ]
    out_phylum = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows_phylum,
        ann_level="superpathway",
        tax_level="phylum",
    )
    outer_phylum = out_phylum["outer_matrix_index"]
    gap2 = outer_phylum.index("gap_2")
    phylum_cats = outer_phylum[gap2 + 1 : -1]
    assert phylum_cats.index("PhylumA") < phylum_cats.index("PhylumZ")

    tax_rows_class = [
        {"display_name": "TaxB", "tax_map_value": "ClsA"},
        {"display_name": "TaxA", "tax_map_value": "ClsZ"},
    ]
    out_class = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows_class,
        ann_level="superpathway",
        tax_level="class",
    )
    outer_class = out_class["outer_matrix_index"]
    gap2 = outer_class.index("gap_2")
    class_cats = outer_class[gap2 + 1 : -1]
    assert class_cats.index("ClsA") < class_cats.index("ClsZ")
