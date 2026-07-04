from api.graph_ordering import (
    TAX_RANKS,
    compare_tuples,
    pathway_sort_key,
    lineage_sort_key,
    ann_category_depth,
    truncate_pathway_tuple,
    truncate_lineage_tuple,
)


def test_compare_tuples_lexicographic():
    assert compare_tuples(("A", "B"), ("A", "C")) < 0
    assert compare_tuples(("A",), ("B",)) < 0


def test_compare_tuples_equality():
    assert compare_tuples(("A", "B"), ("A", "B")) == 0
    assert compare_tuples(("A",), ("A",)) == 0


def test_pathway_sort_key_always_three_segments():
    row = {"superpathway_name": "SpA", "pathway_name": "Pw1", "ec_normalized": "1.1.1.1"}
    assert pathway_sort_key(row) == ("SpA", "Pw1", "1.1.1.1")


def test_pathway_sort_key_none_fields():
    row = {"superpathway_name": None, "pathway_name": None, "ec_normalized": None}
    assert pathway_sort_key(row) == ("", "", "")


def test_lineage_sort_key_missing_ranks():
    row = {"kingdom": "Bacteria", "display_name": "Unknown"}
    key = lineage_sort_key(row)
    assert key == ("Bacteria", "", "", "", "", "", "", "Unknown")


def test_ann_category_depth():
    assert ann_category_depth("superpathway") == 1
    assert ann_category_depth("pathway") == 2
    assert ann_category_depth("pathway_node") == 2


def test_truncate_pathway_tuple_depth_1():
    key = ("SpA", "Pw1", "1.1.1.1")
    assert truncate_pathway_tuple(key, 1) == ("SpA",)


def test_truncate_pathway_tuple_depth_2():
    key = ("SpA", "Pw1", "1.1.1.1")
    assert truncate_pathway_tuple(key, 2) == ("SpA", "Pw1")


def test_truncate_lineage_at_phylum():
    row = {
        "kingdom": "Bacteria",
        "phylum": "Bacillota",
        "class": "Bacilli",
        "order": "o",
        "family": "f",
        "genus": "g",
        "species": "s",
        "display_name": "Bacillus subtilis",
    }
    assert truncate_lineage_tuple(row, "phylum") == (
        "Bacteria", "Bacillota"
    )


def test_tax_ranks_reexported_from_filters():
    assert TAX_RANKS == (
        "kingdom", "phylum", "class", "order", "family", "genus", "species"
    )
