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
