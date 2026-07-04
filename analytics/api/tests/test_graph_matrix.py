from api.graph_matrix import build_graph_matrix


def test_build_graph_matrix_shape_and_gaps():
    triples = [("1.1.1.1", "TaxA", 10.0), ("1.1.1.2", "TaxB", 5.0)]
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
        {"ec_normalized": "1.1.1.2", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
    ]
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
        {"display_name": "TaxB", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
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
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
    ]
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
    ]
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
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
    ]
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
    ]
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
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
        {"ec_normalized": "1.1.1.2", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
    ]
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
        {"display_name": "TaxB", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
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
