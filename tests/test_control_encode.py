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


# ---------------------------------------------------------------------------
# The whole-array pin.
#
# Every test above uses x=14, 15 or 16, and every harvested control arc in the
# retained route corpus lands on a tile with x >= 13. So nothing here, and
# nothing in the 1,758-observation corpus validation, ever exercised a tile left
# of the BRAM column -- which is exactly where tile_bit_base was wrong by 18
# bytes. slice_cfg.csv is independent of both: a different derivation, and all
# 132 LogicTiles.
# ---------------------------------------------------------------------------

import csv
from pathlib import Path

CHIPDB = Path(__file__).resolve().parent.parent / "agamemnon" / "chipdb"


def _template_positions():
    """``CFG_NAME<i>`` -> ``(W row, B column)`` from the decoded tile template."""
    positions = {}
    with (CHIPDB / "logictile_config_template.csv").open(
            newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        columns = [c for c in next(reader) if c.startswith("B")]
        for row in reader:
            if not row or not row[0].startswith("W"):
                continue
            w = int(row[0][1:])
            for index, column in enumerate(columns):
                name = row[1 + index]
                if name and name != "XXXX":
                    positions[name] = (w, int(column[1:]))
    return positions


def _exact_slice_bits():
    with (CHIPDB / "slice_cfg.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            yield (int(row["x"]), int(row["y"]), row["feature"],
                   int(row["byte"]), int(row["mask"]))


def test_bit_position_reproduces_every_exact_per_slice_bit_that_ships():
    positions = _template_positions()
    checked = 0
    for x, y, feature, byte, mask in _exact_slice_bits():
        w, b = positions[feature.replace("[", "<").replace("]", ">")]
        assert ce.bit_position(x, y, w, b) == (byte, mask), (
            "X%dY%d %s" % (x, y, feature))
        checked += 1
    assert checked == 8448


def test_tiles_left_of_the_bram_column_are_shifted_eighteen_bytes():
    """The correction physmap.py has carried for LUT init, applied here too."""
    positions = _template_positions()
    w, b = positions["CFG_LUTCMUX<1>"]

    left = [(x, y, byte, mask) for x, y, feature, byte, mask
            in _exact_slice_bits()
            if feature == "CFG_LUTCMUX[1]" and x < ce.BRAM_COLUMN_X]
    assert left, "no x<13 tile in slice_cfg.csv"

    for x, y, byte, mask in left:
        assert ce.bit_position(x, y, w, b) == (byte, mask)
        # And the uncorrected formula would have missed, by exactly 18 bytes.
        naive = 779736 - y * 63104 - x * 36 + w * 928 - (b - 31)
        assert byte - naive // 8 == 18


def test_slice_line_selector_matches_the_template_for_every_slice_and_tile():
    """CFG_CLKMUX<z> / CFG_ASYNCMUX<z>, all 132 tiles x 16 slices x 2 families."""
    positions = _template_positions()
    checked = 0
    for family, prefix in (("clock_enable", "CFG_CLKMUX"),
                           ("sync", "CFG_ASYNCMUX")):
        for z in range(16):
            w, b = positions["%s<%d>" % (prefix, z)]
            assert b == ce.SLICE_SELECTOR_COLUMN
            assert w == 4 * ce.zblock(z) + ce.SLICE_SELECTOR_ROW_OFFSET[family]
            for x, y in _logic_tiles():
                assert ce.slice_line_bit(x, y, z, family) == \
                    ce.bit_position(x, y, w, b)
                checked += 1
    assert checked == 132 * 16 * 2


def test_slice_line_bit_refuses_a_slice_outside_the_tile():
    for z in (-1, 16, 99):
        with pytest.raises(ce.ControlEncodeError, match="outside 0..15"):
            ce.slice_line_bit(14, 8, z, "clock_enable")


def test_sync_line_selection_is_flagged_undetermined():
    """It maps by row pairing only; 424 of 424 observations use line 0."""
    assert ce.slice_line_confidence("clock_enable") == "exact"
    assert ce.slice_line_confidence("sync") == "undetermined"


def _logic_tiles():
    with (CHIPDB / "slice_cfg.csv").open(newline="", encoding="utf-8") as stream:
        return sorted({(int(r["x"]), int(r["y"])) for r in csv.DictReader(stream)})
