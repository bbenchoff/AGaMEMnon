import os

import pytest

from agamemnon.engine.features import shared_control_graph as shared_control


class RecordingCtx:
    """Minimal stand-in for the arch recording context."""

    def __init__(self):
        self.pips = []

    def addPip(self, name, type, srcWire, dstWire, delay, loc):
        self.pips.append((name, type, srcWire, dstWire, loc))

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


def test_descriptor_is_experimental_and_owns_no_chipdb_file():
    descriptor = shared_control.SHARED_CONTROL_GRAPH_FEATURE.descriptor
    assert descriptor.maturity == "experimental"
    assert descriptor.evidence_tier == "differentially_validated"
    assert descriptor.chipdb_files == ()
    assert descriptor.options == (shared_control.SHARED_CONTROL_GRAPH_OPTION,)


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


def test_only_slices_taking_line_one_get_a_selector_bit():
    """Clear means line 0, which the cleared baseline already gives."""
    from agamemnon.engine import control_encode

    on = shared_control.FEATURE.prepare([], {}, slice_lines={(14, 8, 3): 1})
    off = shared_control.FEATURE.prepare([], {}, slice_lines={(14, 8, 3): 0})

    assert on.sets == [control_encode.slice_line_bit(14, 8, 3, "clock_enable")]
    assert off.sets == []


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
