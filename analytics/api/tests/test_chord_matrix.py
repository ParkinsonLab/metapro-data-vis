from api.chord_matrix import build_chord_matrix


def test_build_chord_matrix_structure():
    pairs = [("PathA", "TaxA", 10.0), ("PathB", "TaxB", 5.0)]
    out = build_chord_matrix(pairs)
    assert out["index"][0] == "gap_1"
    assert out["index"][-1] == "gap_3"
    assert "gap_2" in out["index"]
    n = len(out["index"])
    assert len(out["count_matrix"]) == n
    assert all(len(row) == n for row in out["count_matrix"])


def test_build_chord_matrix_symmetric():
    pairs = [("PathA", "TaxA", 10.0)]
    out = build_chord_matrix(pairs)
    idx = out["index"]
    i_ann = idx.index("PathA")
    i_tax = idx.index("TaxA")
    assert out["count_matrix"][i_ann][i_tax] == 10.0
    assert out["count_matrix"][i_tax][i_ann] == 10.0


def test_build_chord_matrix_gap_fillers():
    pairs = [("PathA", "TaxA", 8.0)]
    out = build_chord_matrix(pairs)
    idx = out["index"]
    i_ann = idx.index("PathA")
    i_tax = idx.index("TaxA")
    # Gap fillers use pair mass before padding (matches parse.ts add_filler_value)
    flat_sum = out["count_matrix"][i_ann][i_tax] + out["count_matrix"][i_tax][i_ann]
    assert out["count_matrix"][idx.index("gap_1")][idx.index("gap_1")] == flat_sum / 4
    assert out["count_matrix"][idx.index("gap_2")][idx.index("gap_2")] == flat_sum / 2


def test_apply_order_uses_explicit_tax_order():
    pairs = [("A", "tax_b", 1.0), ("A", "tax_a", 1.0)]
    out = build_chord_matrix(pairs, tax_order=["tax_b", "tax_a"])
    tax_section = out["index"][out["index"].index("gap_2") + 1 : -1]
    assert tax_section == ["tax_b", "tax_a"]


def test_apply_order_uses_explicit_ann_order():
    pairs = [("ann_b", "T", 1.0), ("ann_a", "T", 1.0)]
    out = build_chord_matrix(pairs, ann_order=["ann_b", "ann_a"])
    ann_section = out["index"][1 : out["index"].index("gap_2")]
    assert ann_section == ["ann_b", "ann_a"]


def test_apply_order_none_falls_back_to_sorted():
    pairs = [("B", "z", 1.0), ("A", "a", 1.0)]
    out = build_chord_matrix(pairs)
    assert out["index"][1:-1:1]  # smoke — gaps present
    ann_section = out["index"][1 : out["index"].index("gap_2")]
    tax_section = out["index"][out["index"].index("gap_2") + 1 : -1]
    assert ann_section == ["A", "B"]
    assert tax_section == ["a", "z"]


def test_apply_order_appends_extra_labels_not_in_list():
    pairs = [("A", "tax_a", 1.0), ("B", "tax_a", 1.0)]
    out = build_chord_matrix(pairs, ann_order=["A"])
    ann_section = out["index"][1 : out["index"].index("gap_2")]
    assert ann_section == ["A", "B"]
