import os

import pytest

from agamemnon.engine.features import shared_control_graph as shared_control


class RecordingCtx:
    """Minimal stand-in for the arch recording context."""

    def __init__(self):
        self.pips = []
        self.bels = []
        self.belpins = []

    def addPip(self, name, type, srcWire, dstWire, delay, loc):
        self.pips.append((name, type, srcWire, dstWire, loc))

    def addBel(self, name, type, loc, gb=False, hidden=False):
        self.bels.append((name, type, loc.x, loc.y, loc.z))

    def addBelInput(self, bel, name, wire):
        self.belpins.append((bel, name, wire))

    def getDelayFromNS(self, ns):
        return ns


class Loc:
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = x, y, z


class Context:
    def __init__(self, wires):
        self.ctx = RecordingCtx()
        self.loc = Loc
        self.shared = {"wires": wires}


def _all_wires():
    wires = set()
    for row in shared_control.load_control_edges():
        wires.add("X%sY%s_%s" % (row["src_x"], row["src_y"], row["src_res"]))
        wires.add("X%sY%s_%s" % (row["dst_x"], row["dst_y"], row["dst_res"]))
    return wires


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv(shared_control.SHARED_CONTROL_GRAPH_OPTION, raising=False)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv(shared_control.SHARED_CONTROL_GRAPH_OPTION, "1")


def test_adds_nothing_when_the_flag_is_unset(flag_off):
    """Default builds must see an identical graph, or the byte gate moves."""
    context = Context(_all_wires())
    assert shared_control.SHARED_CONTROL_GRAPH_FEATURE.add_architecture(context) == 0
    assert context.ctx.pips == []


def test_adds_every_edge_when_enabled_and_all_wires_exist(flag_on):
    context = Context(_all_wires())
    added = shared_control.SHARED_CONTROL_GRAPH_FEATURE.add_architecture(context)

    assert added == len(shared_control.load_control_edges())
    assert len(context.ctx.pips) == added
    assert context.shared["shared_control_pips"] == added


def test_an_edge_naming_an_absent_wire_is_skipped_not_invented(flag_on):
    rows = shared_control.load_control_edges()
    keep = "X%sY%s_%s" % (rows[0]["src_x"], rows[0]["src_y"], rows[0]["src_res"])
    context = Context(_all_wires() - {keep})
    added = shared_control.SHARED_CONTROL_GRAPH_FEATURE.add_architecture(context)

    assert added < len(rows)
    assert all(keep not in (p[2], p[3]) for p in context.ctx.pips)


def test_every_pip_terminates_on_a_control_line(flag_on):
    context = Context(_all_wires())
    shared_control.SHARED_CONTROL_GRAPH_FEATURE.add_architecture(context)

    for _name, _type, _src, dst, _loc in context.ctx.pips:
        resource = dst.split("_", 1)[1]
        assert resource.startswith(("CtrlMUX",) + shared_control.CONTROL_SINKS), dst


def test_no_pip_leaves_a_control_line(flag_on):
    """The tile control line is a sink; nothing routes out of it."""
    context = Context(_all_wires())
    shared_control.SHARED_CONTROL_GRAPH_FEATURE.add_architecture(context)

    for _name, _type, src, _dst, _loc in context.ctx.pips:
        resource = src.split("_", 1)[1]
        assert not resource.startswith(shared_control.CONTROL_SINKS), src


def test_pips_are_located_at_their_destination_tile(flag_on):
    context = Context(_all_wires())
    shared_control.SHARED_CONTROL_GRAPH_FEATURE.add_architecture(context)

    for name, _type, _src, dst, loc in context.ctx.pips:
        assert dst.startswith("X%dY%d_" % (loc.x, loc.y)), name


def test_every_edge_row_carries_a_real_codeword():
    """No row may fall back to an empty cfg, which is what group_only meant."""
    for row in shared_control.load_control_edges():
        assert row["cfg"], row
        assert row["cfg"].startswith("CFG_"), row
        assert row["tier"] == "observed", row


def test_codewords_name_only_the_decoded_families():
    families = {row["cfg"].split("[")[0] for row in shared_control.load_control_edges()}
    assert families <= {"CFG_CTRLMUX", "CFG_TILECLKENMUX", "CFG_TILESYNCMUX"}


def test_ctrlmux_sources_are_two_hot_and_line_selectors_are_one_hot():
    for row in shared_control.load_control_edges():
        cfg = row["cfg"]
        sels = cfg.split("[")[1].rstrip("]").split(",") if "[" in cfg else []
        if cfg.startswith("CFG_CTRLMUX"):
            assert len(sels) == 2, cfg
        else:
            assert len(sels) == 1, cfg


def test_descriptor_records_bounded_qualification_and_owns_no_chipdb_file():
    descriptor = shared_control.SHARED_CONTROL_GRAPH_FEATURE.descriptor
    assert descriptor.maturity == "release"
    assert descriptor.evidence_tier == "individually_qualified"
    assert descriptor.chipdb_files == ()
    assert descriptor.options == (shared_control.SHARED_CONTROL_GRAPH_OPTION,
                                  shared_control.ASYNC_CLEAR_GRAPH_OPTION)


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

import csv
from pathlib import Path

CHIPDB = Path(__file__).resolve().parent.parent / "agamemnon" / "chipdb"


def ctrlmux_cells():
    """The shipped CFG_CTRLMUX selector bits, keyed as prepare() expects."""
    cells = {}
    with (CHIPDB / "pips_full.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if "CTRLMUX" in row["mux"]:
                cells[(int(row["x"]), int(row["y"]), row["mux"],
                       int(row["sel"]))] = (int(row["byte"]), int(row["mask"]))
    return cells


def harvested_pips():
    with shared_control.EDGE_TABLE.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            yield row, "X%sY%s_%s.X%sY%s_%s" % (
                row["src_x"], row["src_y"], row["src_res"],
                row["dst_x"], row["dst_y"], row["dst_res"])


def test_every_harvested_edge_either_resolves_or_refuses_by_name():
    """No harvested control edge may resolve to nothing in silence."""
    cells = ctrlmux_cells()
    resolved = refused_bram = 0
    for row, pip in harvested_pips():
        try:
            state = shared_control.FEATURE.prepare([pip], cells)
        except shared_control.SharedControlEmitError as error:
            assert "not a LogicTile" in str(error)
            assert row["dst_tile"] == "BramTILE"
            refused_bram += 1
            continue
        assert state.sets, pip
        resolved += 1
    assert resolved == 1068
    assert refused_bram == 6


def test_a_bram_tile_control_line_is_refused_not_guessed():
    """x=13 is not a LogicTile; the selector formula does not cover it."""
    with pytest.raises(shared_control.SharedControlEmitError,
                       match="not a LogicTile"):
        shared_control.FEATURE.prepare(
            ["X13Y2_CtrlMUX02.X13Y2_TileClkEnMUX00"], {})


def test_logic_tiles_are_the_hundred_and_thirty_two():
    tiles = shared_control.logic_tiles()
    assert len(tiles) == 132
    assert not [t for t in tiles if t[0] == 13]


def test_a_line_driven_by_the_wrong_ctrlmux_instance_is_refused():
    # CtrlMUX0 drives line 1; naming line 0 is a contradiction, not a choice.
    with pytest.raises(shared_control.SharedControlEmitError, match="drives line"):
        shared_control.FEATURE.prepare(
            ["X14Y8_CtrlMUX00.X14Y8_TileClkEnMUX00"], {})


def test_a_control_line_driven_by_something_other_than_a_ctrlmux_is_refused():
    with pytest.raises(shared_control.SharedControlEmitError, match="takes only"):
        shared_control.FEATURE.prepare(
            ["X14Y8_RMUX89.X14Y8_TileClkEnMUX01"], {})


def test_a_destination_that_is_not_a_control_resource_is_refused():
    with pytest.raises(shared_control.SharedControlEmitError,
                       match="not a control destination"):
        shared_control.FEATURE.prepare(["X14Y8_RMUX89.X14Y8_IMUX04"], {})


def test_an_unparseable_wire_is_refused():
    with pytest.raises(shared_control.SharedControlEmitError, match="unparseable"):
        shared_control.FEATURE.prepare(["GCLK0.X14Y8_TileClkEnMUX01"], {})


def test_two_sources_on_one_line_are_refused():
    with pytest.raises(shared_control.SharedControlEmitError,
                       match="driven twice"):
        shared_control.FEATURE.prepare(
            ["X14Y8_CtrlMUX02.X14Y8_TileClkEnMUX00",
             "X14Y8_CtrlMUX03.X14Y8_TileClkEnMUX00"], {})


def test_a_ctrlmux_source_with_no_selector_bit_at_that_tile_is_refused():
    with pytest.raises(shared_control.SharedControlEmitError,
                       match="no CFG_CTRLMUX bit"):
        shared_control.FEATURE.prepare(["X14Y8_OMUX01.X14Y8_CtrlMUX00"], {})


def test_only_slices_taking_line_one_get_a_LINE_selector_bit():
    """Line zero is baseline; BYPASSEN must not be asserted as an enable."""
    from agamemnon.engine import control_encode

    on = shared_control.FEATURE.prepare([], {}, slice_lines={(14, 8, 3): 1})
    off = shared_control.FEATURE.prepare([], {}, slice_lines={(14, 8, 3): 0})

    line_bit = control_encode.slice_line_bit(14, 8, 3, "clock_enable")
    assert line_bit in on.sets
    assert line_bit not in off.sets
    assert control_encode.slice_bypass_bit(14, 8, 3) in on.clears
    assert control_encode.slice_bypass_bit(14, 8, 3) in off.clears


def test_a_slice_asking_for_a_line_that_does_not_exist_is_refused():
    with pytest.raises(shared_control.SharedControlEmitError, match="asks for line"):
        shared_control.FEATURE.prepare([], {}, slice_lines={(14, 8, 3): 2})


def test_emit_writes_the_prepared_bits_and_nothing_else():
    state = shared_control.FEATURE.prepare(
        ["X14Y8_CtrlMUX02.X14Y8_TileClkEnMUX00"], {})
    (byte, mask), = state.sets

    image = bytearray(byte + 1)
    context = type("Ctx", (), {"image": image, "state": state,
                               "ownership": None})()
    assert shared_control.FEATURE.emit_bitstream(context) == 1
    assert image[byte] == mask
    assert sum(image) == mask          # exactly one bit set in the whole image


def test_emit_skips_a_bit_past_the_end_of_the_image():
    state = shared_control.FEATURE.prepare(
        ["X14Y8_CtrlMUX02.X14Y8_TileClkEnMUX00"], {})
    context = type("Ctx", (), {"image": bytearray(4), "state": state,
                               "ownership": None})()
    assert shared_control.FEATURE.emit_bitstream(context) == 0


def test_emit_with_no_prepared_state_writes_nothing():
    context = type("Ctx", (), {"image": bytearray(16), "state": None,
                               "ownership": None})()
    assert shared_control.FEATURE.emit_bitstream(context) == 0


# ---------------------------------------------------------------------------
# Sink bels
# ---------------------------------------------------------------------------

def _arch_context(wires):
    return type("Ctx", (), {"ctx": RecordingCtx(), "loc": Loc,
                            "shared": {"wires": set(wires)}})()


def _all_control_wires():
    wires = set()
    for x, y in shared_control.logic_tiles():
        for line in range(2):
            wires.add("X%dY%d_TileClkEnMUX%02d" % (x, y, line))
    return wires


def test_each_logic_tile_gets_two_clock_enable_sink_bels(monkeypatch):
    monkeypatch.setenv(shared_control.SHARED_CONTROL_GRAPH_OPTION, "1")
    context = _arch_context(_all_control_wires())
    shared_control.FEATURE.add_architecture(context)

    bels = [b for b in context.ctx.bels
            if b[1] == shared_control.TILE_CONTROL_BEL]
    assert len(bels) == 132 * 2
    assert context.shared["shared_control_bels"] == len(bels)
    assert {b[4] for b in bels} == {16, 17}          # past the sixteen slices
    assert len({b[0] for b in bels}) == len(bels)    # names are unique


def test_every_sink_bel_has_its_input_on_the_tile_line():
    context = _arch_context(_all_control_wires())
    with_flag = os.environ.get(shared_control.SHARED_CONTROL_GRAPH_OPTION)
    os.environ[shared_control.SHARED_CONTROL_GRAPH_OPTION] = "1"
    try:
        shared_control.FEATURE.add_architecture(context)
    finally:
        if with_flag is None:
            del os.environ[shared_control.SHARED_CONTROL_GRAPH_OPTION]

    pins = {bel: (pin, wire) for bel, pin, wire in context.ctx.belpins}
    assert len(pins) == 132 * 2
    for bel, (pin, wire) in pins.items():
        assert pin == "I"
        x, y, line = bel.replace("X", "").replace("_CLKEN", " ").replace("Y", " ").split()
        assert wire == "X%sY%s_TileClkEnMUX%02d" % (x, y, int(line))


def test_no_sink_bel_is_added_for_sync():
    """Its per-slice line selection is not established; a bindable sink the
    emitter would have to refuse is worse than none."""
    context = _arch_context(_all_control_wires() | {
        "X14Y8_TileSyncMUX00", "X14Y8_TileSyncMUX01"})
    with_flag = os.environ.get(shared_control.SHARED_CONTROL_GRAPH_OPTION)
    os.environ[shared_control.SHARED_CONTROL_GRAPH_OPTION] = "1"
    try:
        shared_control.FEATURE.add_architecture(context)
    finally:
        if with_flag is None:
            del os.environ[shared_control.SHARED_CONTROL_GRAPH_OPTION]

    assert not [w for _bel, _pin, w in context.ctx.belpins if "Sync" in w]


def test_a_tile_whose_line_wire_is_absent_gets_no_bel():
    context = _arch_context(_all_control_wires() - {"X14Y8_TileClkEnMUX01"})
    with_flag = os.environ.get(shared_control.SHARED_CONTROL_GRAPH_OPTION)
    os.environ[shared_control.SHARED_CONTROL_GRAPH_OPTION] = "1"
    try:
        shared_control.FEATURE.add_architecture(context)
    finally:
        if with_flag is None:
            del os.environ[shared_control.SHARED_CONTROL_GRAPH_OPTION]

    assert "X14Y8_CLKEN1" not in {b[0] for b in context.ctx.bels}
    assert "X14Y8_CLKEN0" in {b[0] for b in context.ctx.bels}


def test_the_flag_being_unset_adds_no_bel_at_all():
    context = _arch_context(_all_control_wires())
    os.environ.pop(shared_control.SHARED_CONTROL_GRAPH_OPTION, None)
    assert shared_control.FEATURE.add_architecture(context) == 0
    assert context.ctx.bels == []


def test_native_enable_clears_the_erroneous_bypass_setting():
    from agamemnon.engine import control_encode

    on = shared_control.FEATURE.prepare([], {}, slice_lines={(14, 8, 3): 0})
    assert on.sets == []
    assert on.clears == [control_encode.slice_bypass_bit(14, 8, 3)]

    line1 = shared_control.FEATURE.prepare([], {}, slice_lines={(14, 8, 3): 1})
    assert line1.sets == [control_encode.slice_line_bit(14, 8, 3, "clock_enable")]
    byte, mask = on.clears[0]
    image = bytearray([255]) * (byte + 1)
    context = type("Ctx", (), {"image": image, "state": on, "ownership": None})()
    shared_control.FEATURE.emit_bitstream(context)
    assert image[byte] == (255 & ~mask)


def test_experimental_enable_requires_separate_tiles_for_ordinary_registers():
    controller = dict(type=shared_control.TILE_CONTROL_BEL,
                      attributes=dict(NEXTPNR_BEL="X14Y8_CLKEN0", AGRV2K_CLOCK_ENABLE_NET="enable"))
    active = dict(type="GENERIC_SLICE", parameters=dict(FF_USED="1"),
                  attributes=dict(NEXTPNR_BEL="X14Y8_SLICE3", AGRV2K_CLOCK_ENABLE_NET="enable"))
    ordinary = dict(type="GENERIC_SLICE", parameters=dict(FF_USED="1"),
                    attributes=dict(NEXTPNR_BEL="X14Y8_SLICE4"))
    module = dict(cells=dict(control=controller, active=active, ordinary=ordinary))
    with pytest.raises(shared_control.SharedControlEmitError, match="mixed sequential control"):
        shared_control.FEATURE.slice_lines_from_module(module)
    ordinary["parameters"]["FF_USED"] = "0"
    assert shared_control.FEATURE.slice_lines_from_module(module) == {(14, 8, 3): 0}
    ordinary["parameters"]["FF_USED"] = "1"
    ordinary["attributes"]["NEXTPNR_BEL"] = "X14Y9_SLICE4"
    assert shared_control.FEATURE.slice_lines_from_module(module) == {(14, 8, 3): 0}


def _dual_native_module():
    """Two DFFE groups at one tile, as the guarded C++ path must emit."""
    return dict(cells=dict(
        root_a=dict(type=shared_control.TILE_CONTROL_BEL,
                    attributes=dict(NEXTPNR_BEL="X14Y8_CLKEN0",
                                    AGRV2K_CLOCK_ENABLE_NET="enable_a")),
        root_b=dict(type=shared_control.TILE_CONTROL_BEL,
                    attributes=dict(NEXTPNR_BEL="X14Y8_CLKEN1",
                                    AGRV2K_CLOCK_ENABLE_NET="enable_b")),
        a=dict(type="GENERIC_SLICE", parameters=dict(FF_USED="1"),
               attributes=dict(NEXTPNR_BEL="X14Y8_SLICE3",
                               AGRV2K_CLOCK_ENABLE_NET="enable_a")),
        b=dict(type="GENERIC_SLICE", parameters=dict(FF_USED="1"),
               attributes=dict(NEXTPNR_BEL="X14Y8_SLICE7",
                               AGRV2K_CLOCK_ENABLE_NET="enable_b")),
    ))


def test_dual_native_line_one_is_strictly_opt_in(monkeypatch):
    module = _dual_native_module()
    monkeypatch.delenv(shared_control.DUAL_NATIVE_CONTROL_OPTION, raising=False)
    with pytest.raises(shared_control.SharedControlEmitError, match="DUAL_NATIVE_CONTROL=1"):
        shared_control.FEATURE.slice_lines_from_module(module)
    monkeypatch.setenv(shared_control.DUAL_NATIVE_CONTROL_OPTION, "0")
    with pytest.raises(shared_control.SharedControlEmitError, match="DUAL_NATIVE_CONTROL=1"):
        shared_control.FEATURE.slice_lines_from_module(module)
    monkeypatch.setenv(shared_control.DUAL_NATIVE_CONTROL_OPTION, "1")
    assert shared_control.FEATURE.slice_lines_from_module(module) == {
        (14, 8, 3): 0, (14, 8, 7): 1}


@pytest.mark.parametrize("value", ["", "yes", "2", "-1"])
def test_dual_native_switch_rejects_non_boolean_values(monkeypatch, value):
    monkeypatch.setenv(shared_control.DUAL_NATIVE_CONTROL_OPTION, value)
    with pytest.raises(shared_control.SharedControlEmitError, match="must be 0 or 1"):
        shared_control.FEATURE.slice_lines_from_module(dict(cells={}))


def test_dual_native_rejects_duplicate_line_and_enable_assignments(monkeypatch):
    monkeypatch.setenv(shared_control.DUAL_NATIVE_CONTROL_OPTION, "1")
    module = _dual_native_module()
    module["cells"]["duplicate_line"] = dict(
        type=shared_control.TILE_CONTROL_BEL,
        attributes=dict(NEXTPNR_BEL="X14Y8_CLKEN1", AGRV2K_CLOCK_ENABLE_NET="other"))
    with pytest.raises(shared_control.SharedControlEmitError, match="more than one native control root"):
        shared_control.FEATURE.slice_lines_from_module(module)
    del module["cells"]["duplicate_line"]
    module["cells"]["root_b"]["attributes"]["AGRV2K_CLOCK_ENABLE_NET"] = "enable_a"
    with pytest.raises(shared_control.SharedControlEmitError, match="more than one control line"):
        shared_control.FEATURE.slice_lines_from_module(module)


def test_dual_native_keeps_ordinary_ff_isolation(monkeypatch):
    monkeypatch.setenv(shared_control.DUAL_NATIVE_CONTROL_OPTION, "1")
    module = _dual_native_module()
    module["cells"]["ordinary"] = dict(
        type="GENERIC_SLICE", parameters=dict(FF_USED="1"),
        attributes=dict(NEXTPNR_BEL="X14Y8_SLICE9"))
    with pytest.raises(shared_control.SharedControlEmitError, match="mixed sequential control"):
        shared_control.FEATURE.slice_lines_from_module(module)


def test_dual_native_emits_both_tile_lines_and_only_b_slices_select_line_one(monkeypatch):
    from agamemnon.engine import control_encode
    monkeypatch.setenv(shared_control.DUAL_NATIVE_CONTROL_OPTION, "1")
    lines = shared_control.FEATURE.slice_lines_from_module(_dual_native_module())
    state = shared_control.FEATURE.prepare([
        "X14Y8_CtrlMUX02.X14Y8_TileClkEnMUX00",
        "X14Y8_CtrlMUX00.X14Y8_TileClkEnMUX01",
    ], {}, slice_lines=lines)
    line0 = control_encode.ControlAssignment(14, 8, "clock_enable", 0, "ctrl_a").bit()
    line1 = control_encode.ControlAssignment(14, 8, "clock_enable", 1, "ctrl_a").bit()
    a_bypass = control_encode.slice_bypass_bit(14, 8, 3)
    b_bypass = control_encode.slice_bypass_bit(14, 8, 7)
    b_line = control_encode.slice_line_bit(14, 8, 7, "clock_enable")
    a_line = control_encode.slice_line_bit(14, 8, 3, "clock_enable")
    assert line0 in state.sets and line1 in state.sets
    assert b_line in state.sets and a_line not in state.sets
    assert {a_bypass, b_bypass} <= set(state.clears)


# ---------------------------------------------------------------------------
# async_clear: CtrlMUX -> TileAsyncMUX, gated on its own flag
# ---------------------------------------------------------------------------

def test_async_edge_table_is_the_one_evidenced_topology():
    rows = shared_control.load_async_control_edges()
    assert len(rows) == 132
    for row in rows:
        assert row["src_res"] == "CtrlMUX03"
        assert row["dst_res"] == "TileAsyncMUX01"
        assert row["cfg"] == "CFG_TILEASYNCMUX[1]"
        assert row["tier"] == "formula"   # NOT "observed": see ASYNC_EDGE_TABLE
    assert {(int(r["src_x"]), int(r["src_y"])) for r in rows} == \
        shared_control.logic_tiles()


def test_async_edges_are_not_added_by_the_base_flag_alone(flag_on):
    """AGRV2K_SHARED_CONTROL_GRAPH=1 alone must not pull in async pips: the
    async kill switch is a SEPARATE flag."""
    context = _arch_context(_all_wires() | {
        "X14Y8_TileAsyncMUX00", "X14Y8_TileAsyncMUX01"})
    shared_control.FEATURE.add_architecture(context)
    assert not [p for p in context.ctx.pips if "TileAsyncMUX" in p[0]]
    assert "X14Y8_ASYNCCLR1" not in {b[0] for b in context.ctx.bels}


def test_async_edges_and_sink_bel_appear_once_both_flags_are_set(monkeypatch):
    monkeypatch.setenv(shared_control.SHARED_CONTROL_GRAPH_OPTION, "1")
    monkeypatch.setenv(shared_control.ASYNC_CLEAR_GRAPH_OPTION, "1")
    wires = _all_wires() | {"X14Y8_TileAsyncMUX00", "X14Y8_TileAsyncMUX01"}
    context = _arch_context(wires)
    shared_control.FEATURE.add_architecture(context)

    async_pips = [p for p in context.ctx.pips
                  if p[2].endswith("_CtrlMUX03") and p[3].endswith("_TileAsyncMUX01")]
    assert len(async_pips) == 1
    assert async_pips[0][0] == "X14Y8_CtrlMUX03.X14Y8_TileAsyncMUX01"

    async_bels = [b for b in context.ctx.bels if b[0] == "X14Y8_ASYNCCLR1"]
    assert len(async_bels) == 1
    assert async_bels[0][1] == shared_control.TILE_CONTROL_BEL
    assert async_bels[0][4] == shared_control.ASYNC_CONTROL_Z_BASE   # z=18, past CLKEN0/1

    pins = {(bel, pin): wire for bel, pin, wire in context.ctx.belpins}
    assert pins[("X14Y8_ASYNCCLR1", "I")] == "X14Y8_TileAsyncMUX01"

    # No TileAsyncMUX00 (line 0) sink: unevidenced, so unbindable by design.
    assert "X14Y8_ASYNCCLR0" not in {b[0] for b in context.ctx.bels}


def test_async_clear_works_standalone_without_the_base_clock_enable_flag(monkeypatch):
    """The two flags are independent: a build with async-clear but NOT
    clock-enable (e.g. --no-native-clock-enable) must still get the async
    graph -- INCLUDING the shared wire->CtrlMUX input half of
    tile_control_edges.csv, not just async's own CtrlMUX->TileAsyncMUX edges.

    Regression test for two real bugs, both hit building clk_rst_high.v
    2026-09-25: (1) the base flag's early return used to swallow async's
    block whenever cli.py popped AGRV2K_SHARED_CONTROL_GRAPH for
    --no-native-clock-enable ("no BELs remaining to implement cell type
    AGRV2K_TILE_CONTROL"); (2) fixing (1) by gating the WHOLE edge table on
    the base flag then starved async_clear of the wire->CtrlMUX rows it
    shares with clock-enable/sync (811 of tile_control_edges.csv's 1,074
    rows), so no pad's reset net could reach ANY CtrlMUX at all --
    "ERROR: Failed to route arc ... net '$iopadmap$reset' ... unroutable".
    """
    monkeypatch.delenv(shared_control.SHARED_CONTROL_GRAPH_OPTION, raising=False)
    monkeypatch.setenv(shared_control.ASYNC_CLEAR_GRAPH_OPTION, "1")
    context = _arch_context(_all_wires() | {"X14Y8_TileAsyncMUX00", "X14Y8_TileAsyncMUX01"})
    added = shared_control.FEATURE.add_architecture(context)
    # The shared wire->CtrlMUX input half (811 rows) plus async's own one
    # CtrlMUX03->TileAsyncMUX01 edge this fixture's wire set admits.
    assert added == 812
    ctrlmux_pips = [p for p in context.ctx.pips if "_CtrlMUX0" in p[3]]
    assert len(ctrlmux_pips) == 811
    assert "X14Y8_ASYNCCLR1" in {b[0] for b in context.ctx.bels}
    # Clock-enable/sync's own OUTPUT half (CtrlMUX -> TileClkEnMUX/TileSyncMUX)
    # and sink bels stay absent: the base flag is genuinely off.
    assert not [b for b in context.ctx.bels if b[0].endswith("_CLKEN0") or b[0].endswith("_CLKEN1")]
    assert not [p for p in context.ctx.pips if p[3].endswith("_TileClkEnMUX00")
                or p[3].endswith("_TileClkEnMUX01")
                or "_TileSyncMUX0" in p[3]]


def test_clock_enable_works_standalone_without_the_async_clear_flag(flag_on):
    """The converse: an ordinary clock-enable-only build (async flag unset,
    the default before this feature existed) must see an identical graph to
    before -- no async pip or bel leaks in."""
    context = _arch_context(_all_wires())
    shared_control.FEATURE.add_architecture(context)
    assert not [b for b in context.ctx.bels if "ASYNCCLR" in b[0]]
    assert not [p for p in context.ctx.pips if "TileAsyncMUX" in p[0]]


def test_slice_lines_from_module_skips_async_control_cells():
    """An async-clear tile control cell needs no per-slice line resolution
    and must not be mistaken for an unnamed/misnamed clock-enable one."""
    module = {"cells": {
        "async_root": {
            "type": shared_control.TILE_CONTROL_BEL,
            "attributes": {
                "NEXTPNR_BEL": "X14Y8_ASYNCCLR1",
                "AGRV2K_SHARED_CONTROL_MODE": "ASYNC_CLEAR_POS_ZERO",
                "AGRV2K_ASYNC_CLEAR_NET": "reset",
            },
        },
    }}
    assert shared_control.FEATURE.slice_lines_from_module(module) == {}


def test_prepare_resolves_one_async_clear_edge_to_the_board_witnessed_bit():
    """RMUX65 -> CtrlMUX3 -> TileAsyncMUX01: CtrlMUX03 is the instance vendor
    evidence at X14Y10 (docs/archive/2026-09/GPT6_ASYNC_CONTROL_ROUTE_INVENTORY
    _2026-09-05.md, tools/vendor_parity/gpt6_async_independent_sources_20260906
    /RESULT.json in AG32-Docs) shows driving TileAsyncMUX01/line 1; CtrlMUX00
    (used until the 2026-09-25 board round's CONTROL_FAIL diagnosis) never
    reaches TileAsyncMUX at all. RMUX65 -> (38, 47) is the exact source/sel
    pair the corrected open flow's own router picked rebuilding clk_rst_high
    (LogicTile 16,11) the same day."""
    from agamemnon.engine import control_encode
    lo, hi = control_encode.ctrlmux_source_sels(3, "RMUX65")
    state = shared_control.FEATURE.prepare(
        ["X19Y12_RMUX65.X19Y12_CtrlMUX03", "X19Y12_CtrlMUX03.X19Y12_TileAsyncMUX01"],
        {(19, 12, "CFG_CTRLMUX3", lo): (1, 1), (19, 12, "CFG_CTRLMUX3", hi): (1, 2)},
    )
    assert state.routes == 1
    assert state.sources == 1
    expected_line_bit = control_encode.ControlAssignment(
        19, 12, "async_clear", 1, "ctrl_a").bit()
    assert expected_line_bit in state.sets
    # No per-slice bit: async-clear claims no per-slice line selector.
    assert state.slice_lines == {}


def test_prepare_refuses_an_async_edge_from_the_wrong_ctrlmux_instance():
    # CtrlMUX01 drives async line 0 (ASYNC_LINE_OF_CTRL[1] == 0); naming line 1
    # is a contradiction, exactly as the pre-existing clock_enable/sync check
    # already refuses for those families. (CtrlMUX00/02 are not valid async
    # sources at all -- they carry clock-enable/sync instead -- so this also
    # covers "wrong instance entirely" via KeyError->.get(...)==None.)
    with pytest.raises(shared_control.SharedControlEmitError, match="drives line"):
        shared_control.FEATURE.prepare(
            ["X19Y12_CtrlMUX01.X19Y12_TileAsyncMUX01"], {})


def test_async_clear_line_zero_has_no_graph_offer_even_though_the_formula_resolves():
    """No pip/bel ever names TileAsyncMUX00 (see ASYNC_EDGE_TABLE and
    _add_control_sinks's line-1-only sink), so the router can never produce
    this edge in a real build even though control_encode's formula (line 0 is
    real silicon) will compute a bit for it if asked directly -- consistent
    with how this module already treats "sync"'s per-slice line ambiguity:
    no sink offered, rather than a runtime check for a case that cannot
    arise."""
    rows = shared_control.load_async_control_edges()
    assert not [r for r in rows if r["dst_res"] == "TileAsyncMUX00"]
