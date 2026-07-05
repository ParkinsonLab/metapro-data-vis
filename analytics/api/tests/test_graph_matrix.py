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


def test_outer_matrix_index_has_gap_structure_and_ann_tax_categories():
    triples = [("1.1.1.1", "TaxA", 10.0), ("2.2.2.2", "TaxB", 5.0)]
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "SpA", "pathway_name": "Pw1",
         "ann_category": "SpA"},
        {"ec_normalized": "2.2.2.2", "superpathway_name": "SpB", "pathway_name": "Pw2",
         "ann_category": "SpB"},
    ]
    tax_rows = [
        {"display_name": "TaxA", "tax_map_value": "PhA",
         "kingdom": "K", "phylum": "PhA", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
        {"display_name": "TaxB", "tax_map_value": "PhB",
         "kingdom": "K", "phylum": "PhB", "class": "", "order": "",
         "family": "", "genus": "", "species": ""},
    ]
    out = build_graph_matrix(
        triples=triples,
        ec_rows=ec_rows,
        tax_rows=tax_rows,
        ann_level="superpathway",
        tax_level="phylum",
    )
    outer = out["outer_matrix_index"]
    assert outer[0] == "gap_1"
    assert outer[-1] == "gap_3"
    gap2 = outer.index("gap_2")
    assert gap2 > 0 and gap2 < len(outer) - 1
    ann_cats = outer[1:gap2]
    tax_cats = outer[gap2 + 1 : -1]
    assert "SpA" in ann_cats
    assert "SpB" in ann_cats
    assert "PhA" in tax_cats
    assert "PhB" in tax_cats


def test_ecs_ordered_by_pathway_tuple_when_shared_ann_category():
    triples = [("1.1.1.1", "TaxA", 10.0), ("2.2.2.2", "TaxA", 5.0)]
    # ec_rows pre-ordered as returned by graph_service metadata query
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "Sp", "pathway_name": "PwA",
         "ann_category": "Sp"},
        {"ec_normalized": "2.2.2.2", "superpathway_name": "Sp", "pathway_name": "PwB",
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
    assert idx.index("1.1.1.1") < idx.index("2.2.2.2")


def test_tax_level_affects_outer_tax_category_ordering():
    triples = [("1.1.1.1", "TaxA", 10.0), ("1.1.1.1", "TaxB", 5.0)]
    ec_rows = [
        {"ec_normalized": "1.1.1.1", "superpathway_name": "Sp", "pathway_name": "Pw",
         "ann_category": "Sp"},
    ]
    tax_rows_phylum = [
        {"display_name": "TaxB", "tax_map_value": "PhylumA",
         "kingdom": "Archaea", "phylum": "PhylumA", "class": "ClsA", "order": "",
         "family": "", "genus": "", "species": ""},
        {"display_name": "TaxA", "tax_map_value": "PhylumZ",
         "kingdom": "Bacteria", "phylum": "PhylumZ", "class": "ClsZ", "order": "",
         "family": "", "genus": "", "species": ""},
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
        {"display_name": "TaxB", "tax_map_value": "ClsA",
         "kingdom": "Archaea", "phylum": "PhylumA", "class": "ClsA", "order": "",
         "family": "", "genus": "", "species": ""},
        {"display_name": "TaxA", "tax_map_value": "ClsZ",
         "kingdom": "Bacteria", "phylum": "PhylumZ", "class": "ClsZ", "order": "",
         "family": "", "genus": "", "species": ""},
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
