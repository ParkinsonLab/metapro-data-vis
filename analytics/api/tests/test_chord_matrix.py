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
