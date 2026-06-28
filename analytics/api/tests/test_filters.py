from api.filters import (
    ann_levels_up_to,
    normalise_ann_filter,
    normalise_taxon_filter,
    ranks_up_to,
    sample_id_from_names,
)


def test_ranks_up_to_kingdom():
    assert ranks_up_to("kingdom") == ("kingdom",)


def test_ranks_up_to_class():
    assert ranks_up_to("class") == (
        "kingdom",
        "phylum",
        "class",
    )


def test_ranks_up_to_species():
    assert ranks_up_to("species") == (
        "kingdom",
        "phylum",
        "class",
        "order",
        "family",
        "genus",
        "species",
    )


def test_ann_levels_up_to_superpathway():
    assert ann_levels_up_to("superpathway") == ("superpathway",)


def test_ann_levels_up_to_pathway():
    assert ann_levels_up_to("pathway") == ("superpathway", "pathway")


def test_ann_levels_up_to_pathway_node():
    assert ann_levels_up_to("pathway_node") == (
        "superpathway",
        "pathway",
        "pathway_node",
    )


def test_sample_id_strips_tsv():
    assert sample_id_from_names(["test_rpkm_1.tsv"]) == "test_rpkm_1"


def test_ann_filter_empty():
    assert normalise_ann_filter({}, "superpathway") is None
    assert normalise_ann_filter("", "superpathway") is None


def test_ann_filter_string_superpathway():
    f = normalise_ann_filter("Carbohydrate Metabolism", "superpathway")
    assert f == {"level": "superpathway", "name": "Carbohydrate Metabolism"}


def test_ann_filter_string_at_pathway_level():
    f = normalise_ann_filter("Carbohydrate Metabolism", "pathway")
    assert f == {"level": "superpathway", "name": "Carbohydrate Metabolism"}


def test_taxon_filter_empty():
    assert normalise_taxon_filter({}) is None
    assert normalise_taxon_filter({"level": "", "name": ""}) is None


def test_taxon_filter_set():
    f = normalise_taxon_filter({"level": "phylum", "name": "Bacillota"})
    assert f == {"level": "phylum", "name": "Bacillota"}
