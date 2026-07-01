from types import SimpleNamespace

from api.krona_service import KronaNode, Segment, lineage_segments, upsert_segment


def _taxon(**kwargs):
    return SimpleNamespace(**kwargs)


def test_lineage_species_leaf_at_last_rank():
    taxon = _taxon(
        name="Staphylococcus aureus",
        phylum="Bacillota",
        genus="Staphylococcus",
        species="Staphylococcus aureus",
    )
    segs = lineage_segments(taxon, ("phylum", "genus", "species"))
    assert [s.id for s in segs] == [
        "Bacillota",
        "Staphylococcus",
        "Staphylococcus aureus",
    ]
    assert segs[-1].is_leaf is True
    assert segs[-1].label == "Staphylococcus aureus"


def test_lineage_early_leaf_under_phylum():
    taxon = _taxon(
        name="Lactobacillus sp. 100-5",
        phylum="Bacillota",
        genus=None,
        species=None,
    )
    segs = lineage_segments(taxon, ("phylum", "genus", "species"))
    assert len(segs) == 2
    assert segs[0].id == "Bacillota" and segs[0].is_leaf is False
    assert segs[1].id == "Lactobacillus sp. 100-5"
    assert segs[1].label == "U_Lactobacillus sp. 100-5"
    assert segs[1].is_leaf is True


def test_lineage_orphan_under_root():
    taxon = _taxon(name="999999999", phylum=None, genus=None, species=None)
    segs = lineage_segments(taxon, ("phylum", "genus", "species"))
    assert len(segs) == 1
    assert segs[0].label == "U_999999999"


def test_upsert_creates_internal_then_leaf():
    root = KronaNode(id="root", label="root", children=[], subtotal=0.0, percentage=1.0)
    grand = 10.0
    n1 = upsert_segment(root, Segment("Bacillota", "Bacillota"), 5.0, grand)
    assert n1.id == "Bacillota"
    n2 = upsert_segment(
        n1, Segment("S. aureus", "S. aureus", is_leaf=True), 5.0, grand
    )
    assert n2.value == 5.0
    assert root.children[0].id == "Bacillota"
    assert root.children[0].children[0].value == 5.0


def test_upsert_merges_duplicate_leaf_ids():
    root = KronaNode(id="root", label="root", children=[], subtotal=0.0, percentage=1.0)
    leaf = Segment("dup", "dup", is_leaf=True)
    upsert_segment(root, leaf, 3.0, 10.0)
    upsert_segment(root, leaf, 2.0, 10.0)
    node = root.children[0]
    assert node.value == 5.0
    assert node.percentage == 0.5
