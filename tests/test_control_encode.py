import pytest

from agamemnon.engine import control_encode as ce


def A(x, y, family, line, source):
    return ce.ControlAssignment(x, y, family, line, source)


def test_bit_base_stays_in_bits_so_odd_x_is_not_misaligned():
    """The x stride is 36 bits; dividing by 8 first breaks every odd-x tile."""
    even = ce.tile_bit_base(14, 8)
    odd = ce.tile_bit_base(15, 8)

    assert even - odd == 36            # not a whole number of bytes
    assert odd % 8 != even % 8         # so the two land on different bit phases


def test_odd_and_even_x_tiles_both_produce_a_live_bit():
    for x in (14, 15, 16):
        byte, mask = A(x, 8, "clock_enable", 1, "ctrl_a").bit()
        assert byte > 0
        assert mask in (1, 2, 4, 8, 16, 32, 64, 128)


def test_family_and_line_select_the_documented_row():
    # clock_enable line 1 -> W32, sync line 1 -> W33: one row apart = 116 bytes.
    ck = A(14, 8, "clock_enable", 1, "ctrl_a").bit()
    sy = A(14, 8, "sync", 1, "ctrl_a").bit()
    assert sy[0] - ck[0] == 116

    # clock_enable line 0 -> W35, three rows past W32.
    lo = A(14, 8, "clock_enable", 0, "ctrl_a").bit()
    assert lo[0] - ck[0] == 3 * 116


def test_source_positions_are_adjacent_descending_bits():
    a = A(14, 8, "clock_enable", 1, "ctrl_a").bit()      # B33
    b = A(14, 8, "clock_enable", 1, "ctrl_b").bit()      # B32
    c = A(14, 8, "clock_enable", 1, "constant").bit()    # B31

    def index(pair):
        byte, mask = pair
        return byte * 8 + (8 - mask.bit_length())

    # index subtracts (B - 31), so B33 is lowest and B31 highest.
    assert index(b) == index(a) + 1
    assert index(c) == index(b) + 1


def test_ctrl_index_matches_the_routing_graph_numbering():
    assert A(1, 1, "sync", 1, "ctrl_a").ctrl_index == 0
    assert A(1, 1, "sync", 1, "ctrl_b").ctrl_index == 1
    assert A(1, 1, "sync", 0, "ctrl_a").ctrl_index == 2
    assert A(1, 1, "sync", 0, "ctrl_b").ctrl_index == 3
    assert A(1, 1, "sync", 0, "constant").ctrl_index is None   # no route


def test_constant_tie_is_reported_as_weaker_evidence():
    assert ce.source_confidence("ctrl_a") == "exact"
    assert ce.source_confidence("ctrl_b") == "exact"
    assert ce.source_confidence("constant") == "correlated"


def test_encode_returns_one_bit_per_assignment():
    edits = ce.encode([A(14, 8, "clock_enable", 1, "ctrl_a"),
                       A(14, 8, "clock_enable", 0, "ctrl_b")])
    assert len(edits) == 2


def test_assigning_the_same_line_twice_is_refused():
    with pytest.raises(ce.ControlEncodeError, match="assigned twice"):
        ce.encode([A(14, 8, "sync", 1, "ctrl_a"),
                   A(14, 8, "sync", 1, "ctrl_b")])


def test_the_line_budget_is_structural_and_a_third_line_cannot_be_named():
    """No separate budget check is needed: only lines 0 and 1 exist."""
    for family, rows in ce.FAMILY_ROWS.items():
        assert len(rows) == ce.LINES_PER_FAMILY, family
        assert set(rows) == {0, 1}, family

    with pytest.raises(ce.ControlEncodeError, match="has no line"):
        ce.ControlAssignment(14, 8, "sync", 2, "ctrl_a").bit()


def test_two_families_on_one_tile_are_independent():
    edits = ce.encode([A(14, 8, "clock_enable", 1, "ctrl_a"),
                       A(14, 8, "clock_enable", 0, "ctrl_b"),
                       A(14, 8, "sync", 1, "ctrl_a"),
                       A(14, 8, "sync", 0, "constant")])
    assert len(edits) == 4


def test_unknown_family_line_or_source_is_refused():
    for bad in (A(1, 1, "nope", 1, "ctrl_a"),
                A(1, 1, "sync", 7, "ctrl_a"),
                A(1, 1, "sync", 1, "nope")):
        with pytest.raises(ce.ControlEncodeError):
            bad.bit()


def test_apply_then_decode_round_trips():
    raw = bytearray(120000)
    assignments = [A(14, 8, "clock_enable", 1, "ctrl_b"),
                   A(15, 8, "sync", 0, "ctrl_a"),
                   A(16, 9, "sync", 1, "constant")]
    assert ce.apply(raw, assignments) == 3

    assert ce.decode_tile(raw, 14, 8, "clock_enable") == {1: "ctrl_b"}
    assert ce.decode_tile(raw, 15, 8, "sync") == {0: "ctrl_a"}
    assert ce.decode_tile(raw, 16, 9, "sync") == {1: "constant"}


def test_decode_of_an_untouched_image_is_empty():
    assert ce.decode_tile(bytearray(120000), 14, 8, "clock_enable") == {}


def test_decode_reports_an_ambiguous_line_rather_than_guessing():
    raw = bytearray(120000)
    ce.apply(raw, [A(14, 8, "sync", 1, "ctrl_a")])
    byte, mask = A(14, 8, "sync", 1, "constant").bit()
    raw[byte] |= mask                                  # both positions set

    assert ce.decode_tile(raw, 14, 8, "sync") == {1: ("constant", "ctrl_a")}


def test_apply_refuses_to_run_past_the_image():
    with pytest.raises(ce.ControlEncodeError, match="past the image"):
        ce.apply(bytearray(16), [A(14, 8, "clock_enable", 1, "ctrl_a")])


def test_source_table_is_tile_invariant_and_two_hot():
    table = ce._source_table()

    assert len(table) == 96                       # 24 sources x 4 instances
    assert {inst for inst, _ in table} == {0, 1, 2, 3}
    for (inst, _src), (lo, hi) in table.items():
        window = range(inst * ce.SELS_PER_INSTANCE, (inst + 1) * ce.SELS_PER_INSTANCE)
        assert lo in window and hi in window
        assert lo != hi                           # two-hot, not one


def test_every_instance_offers_the_same_offset_pairs():
    table = ce._source_table()
    offsets = {}
    for (inst, src), (lo, hi) in table.items():
        offsets.setdefault(inst, set()).add((lo - inst * 12, hi - inst * 12))
    assert len({frozenset(v) for v in offsets.values()}) == 1
    assert len(next(iter(offsets.values()))) == 24


def test_a_known_source_resolves_to_its_recorded_pair():
    lo, hi = ce.ctrlmux_source_sels(0, "OMUX01")
    assert (lo, hi) == (0, 8)


def test_an_unrecorded_source_is_refused_rather_than_invented():
    with pytest.raises(ce.ControlEncodeError, match="no recorded CtrlMUX"):
        ce.ctrlmux_source_sels(0, "RMUX999")


def test_control_route_bits_covers_both_halves_of_the_path():
    lo, hi = ce.ctrlmux_source_sels(0, "OMUX01")
    pips = {(14, 8, "CFG_CTRLMUX", lo): (5000, 1),
            (14, 8, "CFG_CTRLMUX", hi): (5001, 2)}
    bits = ce.control_route_bits(14, 8, "clock_enable", 1, "OMUX01", pips)

    assert (5000, 1) in bits and (5001, 2) in bits          # CtrlMUX selection
    assert ce.ControlAssignment(14, 8, "clock_enable", 1, "ctrl_a").bit() in bits
    assert len(bits) == 3


def test_control_route_bits_refuses_a_source_that_reaches_neither_instance():
    with pytest.raises(ce.ControlEncodeError, match="reaches neither"):
        ce.control_route_bits(14, 8, "sync", 1, "RMUX999", {})


def test_control_route_bits_refuses_a_tile_missing_the_pip_entry():
    with pytest.raises(ce.ControlEncodeError, match="no CFG_CTRLMUX bit"):
        ce.control_route_bits(14, 8, "clock_enable", 1, "OMUX01", {})
