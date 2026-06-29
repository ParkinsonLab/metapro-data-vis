from api.filters import normalise_ann_filter, normalise_taxon_filter, sample_id_from_names


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
