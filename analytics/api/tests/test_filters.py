from api.filters import ann_levels_up_to, ranks_up_to


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
