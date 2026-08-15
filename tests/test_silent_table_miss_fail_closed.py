"""A table lookup that misses must not be allowed to continue in silence.

This is the single most expensive bug class in this emitter's history. Every
instance has the same shape and the same symptom: some table is consulted for a
configuration cell, the key is absent, the code carries on, and the resulting
image is *structurally valid*. The FCB accepts it (0x000f0002), bitgen reports
nothing wrong at any verbosity, and the design simply does not work -- a pin
stays static, a register never advances, a memory reads the canvas.

Prior instances, all of them shipped: two transposed BBMUXE_PAIR codewords; the
z-set-keyed pad ENABLE table emitting nothing on a missing key; bram_emit
dropping a field whose cell was absent; six supplemental ``ctx.addPip`` loops
that ignored EDGE_BLACKLIST entirely; and the zero-padded-name string compare,
four separate times.

Two rules follow, and this file pins both:

1. A codeword is committed WHOLE or not at all. A routed mux hop is programmed
   by a complete codeword -- for the RMUX/IMUX mesh a (lo, hi) pair. Emitting
   the half that resolved is not a degraded version of the right answer, it is
   a well-formed selection of a DIFFERENT mux input.
2. A miss on a REQUIRED field raises, naming the table and the missing key.
   Silence is only acceptable where the configuration is genuinely optional.
"""

import ast
import csv
import inspect
from pathlib import Path

import pytest

from agamemnon.engine import bram_emit, io_emit, mesh_template
from agamemnon.engine.features import (
    bram as bram_feature,
    carry as carry_feature,
    core_logic as core_logic_feature,
    mcu_ahb as mcu_ahb_feature,
    physical_io as physical_io_feature,
    route_through as route_through_feature,
    routing as routing_feature,
)


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


# --------------------------------------------------------------------------
# routing.py -- the general mesh selector resolver
# --------------------------------------------------------------------------

def test_a_partial_mesh_selector_codeword_is_refused():
    """Half a (lo, hi) pair selects a different mux input, so refuse it."""
    lookup = {(14, 8, "CFG_RMUX0", 3): (100, 1)}
    complete = routing_feature.resolve_selector_cells(
        lookup, [(14, 8, "CFG_RMUX0", 3)], "pips_full.csv", "a complete codeword"
    )
    assert complete == [(100, 1)]

    with pytest.raises(SystemExit) as excinfo:
        routing_feature.resolve_selector_cells(
            lookup,
            [(14, 8, "CFG_RMUX0", 3), (14, 8, "CFG_RMUX0", 9)],
            "pips_full.csv",
            "RMUX0 <- RMUX3 @(14,8)",
        )
    message = str(excinfo.value)
    # The diagnostic has to name the table and the exact missing key, or the
    # next person gets "it does not work" with nothing to go on.
    assert "pips_full.csv" in message
    assert "RMUX0 <- RMUX3 @(14,8)" in message
    assert "CFG_RMUX0" in message and "9" in message


def test_a_codeword_with_no_cells_at_all_is_refused_too():
    """``if found:`` counted this as neither mapped nor unmapped."""
    with pytest.raises(SystemExit):
        routing_feature.resolve_selector_cells(
            {}, [(0, 0, "CFG_RMUX0", 0)], "pips_full.csv", "an absent codeword"
        )


def test_a_wire_name_keyed_edge_can_be_matched_against_the_ban():
    """The reason 26 MCU/BRAM loaders never consulted the blacklist.

    Their tables carry whole wire names while the ban is keyed by resource and
    tile, and there was no shared translation -- so a cut ban naming
    ``RMUX21@14,8->RMUX93@14,4`` (a row of bram_x9_haddr_paths.csv) had no
    effect at all, while sibling edges of the identical (14,8)->(14,4) shape
    that arrive through the part-keyed RRG loader DID respond to the same ban.
    """
    assert routing_feature.wire_endpoint("X14Y8_RMUX21") == ("RMUX21", "14", "8")
    assert routing_feature.wire_endpoint("X14Y4_RMUX93") == ("RMUX93", "14", "4")
    # Zero padding and multi-underscore resources both have to survive it, and
    # negative tile coordinates appear in the pseudo-sink rows.
    assert routing_feature.wire_endpoint("X0Y5_SinkMUXPseudo143")[0] \
        == "SinkMUXPseudo143"
    assert routing_feature.wire_endpoint("X13Y12_BBMUXW00")[0] == "BBMUXW00"
    assert routing_feature.wire_endpoint("X-1Y-1_RMUX00") == ("RMUX00", "-1", "-1")
    # A name the ban syntax cannot spell either.
    assert routing_feature.wire_endpoint("GCLK0") is None
    assert routing_feature.wire_endpoint("") is None
    assert routing_feature.wire_endpoint(None) is None


def test_the_reported_repro_edge_now_matches_its_ban_after_translation():
    """Close the loop on the concrete hop the ban used to miss entirely.

    ``bram_x9_haddr_paths.csv`` row
    ``4,AddressA,5,2,X14Y8_RMUX21,X14Y4_RMUX93,vendor-l48-x9-silicon-control``
    was added to the graph unconditionally, so banning
    ``RMUX21@14,8->RMUX93@14,4`` did nothing and a conduction-cut top-up loop
    never converged.
    """
    import re as _re

    row_present = any(
        (row["src_wire"], row["dst_wire"]) == ("X14Y8_RMUX21", "X14Y4_RMUX93")
        for row in csv.DictReader((CHIPDB / "bram_x9_haddr_paths.csv").open())
    )
    assert row_present, "the repro row moved; re-point this test at a live one"

    def norm_res(res):
        match = _re.fullmatch(r"([A-Za-z]+)0*(\d+)", str(res))
        return "%s%d" % (match.group(1), int(match.group(2))) if match else str(res)

    def norm_edge(sr, sx, sy, dr, dx, dy):
        return (norm_res(sr), str(int(sx)), str(int(sy)),
                norm_res(dr), str(int(dx)), str(int(dy)))

    # The ban syntax, parsed exactly as routing.py's _dead_edge_re does.
    ban = _re.fullmatch(
        r"(\w+)@(-?\d+),(-?\d+)\s*->\s*(\w+)@(-?\d+),(-?\d+)",
        "RMUX21@14,8->RMUX93@14,4",
    )
    source = routing_feature.wire_endpoint("X14Y8_RMUX21")
    destination = routing_feature.wire_endpoint("X14Y4_RMUX93")
    assert norm_edge(source[0], source[1], source[2],
                     destination[0], destination[1], destination[2]) \
        == norm_edge(*ban.groups())


def test_every_wire_keyed_chipdb_row_can_be_matched_against_the_ban():
    """If a row did not parse, that hop would be silently unbannable."""
    import glob

    unparsed = []
    checked = 0
    for path in sorted(glob.glob(str(CHIPDB / "*.csv"))):
        with open(path, newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if not rows or "src_wire" not in rows[0] or "dst_wire" not in rows[0]:
            continue
        for row in rows:
            checked += 1
            for column in ("src_wire", "dst_wire"):
                if routing_feature.wire_endpoint(row[column]) is None:
                    unparsed.append((Path(path).name, row[column]))
    assert checked > 2000, "the wire-keyed table sweep went vacuous"
    assert not unparsed, unparsed[:10]


def test_the_routing_hot_paths_still_route_through_the_all_or_nothing_helper():
    """Structural, so an inlined ``if bit:`` cannot creep back in unnoticed.

    Four selector sites in ``prepare`` used to append the part of the codeword
    that resolved and only afterwards decide the edge was unmapped. They now
    resolve through one helper that commits nothing until the codeword is
    complete. Count the call sites rather than matching source text: a rename
    keeps working, a re-inlining does not.
    """
    source = Path(inspect.getsourcefile(routing_feature)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    prepare = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "prepare"
        and any(isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "resolve_selector_cells"
                for inner in ast.walk(node))
    )
    calls = [
        node for node in ast.walk(prepare)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "resolve_selector_cells"
    ]
    assert len(calls) >= 4, (
        "a selector site stopped using the all-or-nothing resolver; a partial "
        "codeword is a well-formed selection of the wrong mux input"
    )


# --------------------------------------------------------------------------
# mesh_template.py -- the decoded mesh predictor
# --------------------------------------------------------------------------

def test_cfg_bits_refuses_a_partial_pair():
    """It promises two bits; returning one silently mis-encodes the hop."""
    with pytest.raises(KeyError) as excinfo:
        # sel 900 exists nowhere, so the pair can never be completed.
        mesh_template.cfg_bits(14, 8, "RMUX", 0, 0, 900)
    assert "pips_full.csv" in str(excinfo.value)
    assert "900" in str(excinfo.value)


def test_the_fan_in_guard_cannot_be_switched_off_by_its_own_table_miss():
    """``if not ls or ...`` / ``if ls and ...`` passed on an EMPTY fan-in.

    A miss in the template fan-in did not fail closed, it disabled the check and
    returned the unvalidated codeword -- which routing.py adopts as a
    ``decoded-mesh-template-prediction`` and emits. The edge counts as mapped,
    so the unmapped gate never sees it.
    """
    # Every reachable instance is present: RMUX indices stop at 95 over 6 nodes
    # per instance and IMUX at 63 over 4, so both stop at instance 15.
    for family, highest in (("RMUX", 15), ("IMUX", 15)):
        assert mesh_template.legal_sels(family, highest)
    with pytest.raises(KeyError) as excinfo:
        mesh_template._require_legal_sels("RMUX", 99)
    assert "fan-in" in str(excinfo.value)


# --------------------------------------------------------------------------
# bram_emit.py -- the required BRAM configuration surface
# --------------------------------------------------------------------------

def test_bram_emit_refuses_a_tile_with_no_decoded_surface():
    """emit() used to return an empty set: a BRAM with no INIT and no width.

    ``owned_surface`` is empty for the same tile, so the clear phase is a no-op
    too and nothing is asymmetric enough for the ownership trace to notice. Only
    the *experimental* path was ever scoped to X13Y1..Y4.
    """
    enables = {"PORTA_CLKIN_EN": 1}
    # A real BramTILE works.
    assert bram_emit.emit(13, 4, 0b01000, 0, 0, enables)
    # The PLL tile is in the cell table but carries no BRAM field at all.
    assert (22, 5) in bram_emit.ENCODABLE_BRAM_TILES
    assert (22, 5) not in bram_emit.CONFIGURABLE_BRAM_TILES
    for tile in ((22, 5), (14, 4)):
        with pytest.raises(ValueError) as excinfo:
            bram_emit.emit(tile[0], tile[1], 0b01000, 0, 0, enables)
        assert "pips_bram_pll.csv" in str(excinfo.value)


def test_bram_emit_refuses_an_unknown_port_enable_name():
    """``"CFG_%s" % en`` turned a caller typo into a mux that is not in the table."""
    with pytest.raises(ValueError) as excinfo:
        bram_emit.emit(13, 4, 0, 0, 0, {"PORTA_WE_EN": 1})
    assert "PORTA_WE_EN" in str(excinfo.value)
    # The eight real names are accepted.
    assert bram_emit.PORT_ENABLE_NAMES == frozenset(
        "%s_%s_EN" % (port, signal)
        for port in ("PORTA", "PORTB")
        for signal in ("CLKIN", "CLKOUT", "RSTIN", "RSTOUT")
    )
    bram_emit.emit(13, 4, 0, 0, 0, {name: 1 for name in bram_emit.PORT_ENABLE_NAMES})


def test_bram_routing_selector_refuses_a_partial_bramtile_codeword():
    state = bram_feature.BramState()
    state.resolver = {
        "NPI": {"IMUX": 4}, "BS": {"IMUX": 12},
        "L0": {"IMUX|3|RMUX|9|0|0": [1, 5]}, "L1": {}, "L2": {},
    }
    # group = 3 % 4, block = 3 * 12, so the codeword is CFG_IMUX0 sels 37 and 41.
    complete = {(13, 4, "CFG_IMUX0", 37): (700, 2), (13, 4, "CFG_IMUX0", 41): (700, 4)}
    route_sets = []
    assert bram_feature.FEATURE.resolve_route(
        state, (13, 4, "RMUX", 9), (13, 4, "IMUX", 3), complete, {"IMUX": 4}, route_sets
    )
    assert sorted(route_sets) == [(700, 2), (700, 4)]

    partial = {(13, 4, "CFG_IMUX0", 37): (700, 2)}      # sel 41 deliberately absent
    with pytest.raises(SystemExit) as excinfo:
        bram_feature.FEATURE.resolve_route(
            state, (13, 4, "RMUX", 9), (13, 4, "IMUX", 3), partial,
            {"IMUX": 4}, [],
        )
    assert "CFG_IMUX0" in str(excinfo.value)
    assert "41" in str(excinfo.value)

    # A codeword with NO cells at all still reports unmapped, which the routing
    # gate refuses; that path must stay distinguishable from the partial one.
    assert bram_feature.FEATURE.resolve_route(
        state, (13, 4, "RMUX", 9), (13, 4, "IMUX", 3), {}, {"IMUX": 4}, []
    ) is False


# --------------------------------------------------------------------------
# io_emit.py -- the ring pad
# --------------------------------------------------------------------------

@pytest.mark.parametrize("emitter", ("emit_bits", "slot_config_bits"))
def test_ring_pad_emitters_refuse_a_missing_cell(emitter):
    """A subset of the pad codeword is a config-accepted image with a dead pin."""
    with pytest.raises(SystemExit) as excinfo:
        # (5, 5) is not a pad config tile, so no CFG_IOMUX cell resolves there.
        getattr(io_emit, emitter)(5, 5, [(0, 8)])
    assert "config tile" in str(excinfo.value)


# --------------------------------------------------------------------------
# core_logic.py / carry.py -- slice presentation and dedicated carry
# --------------------------------------------------------------------------

def test_a_slice_output_that_cannot_be_presented_is_refused():
    """Skipping CFG_OMUX left the register placed, clocked, routed and static."""
    with pytest.raises(SystemExit) as excinfo:
        core_logic_feature.CoreLogicFeature._require_omux({}, 3, 7, 2, 2)
    message = str(excinfo.value)
    assert "pips_full.csv" in message and "CFG_OMUX2" in message and "X3Y7" in message


def test_a_carry_slice_with_no_slice_config_cell_is_refused():
    """The missing bit is the one that selects dedicated Cin instead of pinC."""
    with pytest.raises(SystemExit) as excinfo:
        carry_feature.CarryFeature._require({}, 4, 9, 1, "CFG_LUTCMUX[3]")
    message = str(excinfo.value)
    assert "slice_cfg.csv" in message and "CFG_LUTCMUX[3]" in message


# --------------------------------------------------------------------------
# physical_io.py -- the pad-feed codeword table
# --------------------------------------------------------------------------

def _padfeed_state(chipdb_root):
    return physical_io_feature.FEATURE.prepare(
        {}, Path(chipdb_root), {}, archival_legacy=False
    )


def test_an_unharvested_padfeed_row_does_not_erase_a_harvested_codeword():
    """Plain assignment made the LAST row win, and the last row was empty.

    The padfeed key is (pad tile x, feeder RMUX, source) and deliberately omits
    ``iomux_z``, because the hop it names is the same physical edge whichever
    pad slot consumes it. So two rows share a key, and one of them is an
    unharvested placeholder retained for the routing-restriction table. When the
    placeholder won, the route still resolved through ``padfeed_exact``, emitted
    NOTHING, counted itself mapped -- bypassing the unmapped gate -- and skipped
    the general selector path that would have encoded the hop.
    """
    rows = [
        row for row in csv.DictReader((CHIPDB / "padfeed_L48_top.csv").open())
        if (row["padtile_x"], row["padfeed_rmux"], row["src_res"],
            row["src_x"], row["src_y"]) == ("19", "0", "RMUX25", "19", "12")
    ]
    # The situation this defends against must still exist in the shipped table,
    # otherwise the test proves nothing.
    assert len(rows) > 1, "the colliding padfeed rows are gone; revisit this test"
    assert any(not row["codeword_bytes"] for row in rows)
    harvested = [row for row in rows if row["codeword_bytes"]]
    assert len(harvested) == 1

    state = _padfeed_state(CHIPDB)
    key = (19, 13, 0, 19, 12, "RMUX", 25)
    expected = list(zip(
        [int(v) for v in harvested[0]["codeword_bytes"].split(",") if v],
        [int(v) for v in harvested[0]["codeword_masks"].split(",") if v],
    ))
    assert state.padfeed_exact[key] == expected


def test_a_padfeed_row_with_no_codeword_and_no_owner_is_marked_unowned():
    """The row exists, so routing.py takes the short-circuit and emits nothing.

    ``padfeed_L48_*.csv`` does double duty: every row names the vendor's feeder
    (which shapes the graph) and only some carry a harvested codeword. A row
    without one still lands in ``padfeed_exact``, and the resolver keys on the
    key being PRESENT -- so it emitted an empty codeword, counted the edge
    MAPPED (past the unmapped gate) and skipped the general selector path.

    Where the hop is owned by iomux_hop_vendor.csv or by a left-edge companion
    field that suppression is deliberate. Where it is owned by nothing, the pin
    is simply dead, and those keys must be refused rather than emitted empty.
    """
    state = _padfeed_state(CHIPDB)
    assert state.padfeed_unowned, "the unowned pad-feed detection went vacuous"

    for key in state.padfeed_unowned:
        assert not state.padfeed_exact[key]

    # An owned empty row must NOT be flagged: three shipped SERV images and
    # three more top-edge images resolve through one, and they work on silicon.
    left_pin25 = (0, 4, 30, 4, 4, "RMUX", 20)           # companion_cfg owns it
    top_pin16 = (19, 13, 24, 19, 12, "RMUX", 19)        # iomux_hop_vendor owns it
    for key in (left_pin25, top_pin16):
        assert key in state.padfeed_exact and not state.padfeed_exact[key]
        assert key not in state.padfeed_unowned

    # And a slot with neither owner must be flagged.
    assert (20, 13, 28, 20, 12, "RMUX", 69) in state.padfeed_unowned


def test_the_padfeed_key_names_a_pad_TILE_not_a_pad_COLUMN():
    """Without padtile_y the key matched ordinary mesh edges in other rows.

    ``RMUX25@(19,12) -> RMUX00`` at y=9, y=11 and y=12 are all routable edges in
    rrg_edges_full.csv, and every one of them matched the pad-feed row for
    ``RMUX00@(19,13)``. A route using one took the pad-feed short-circuit: the
    pad tile's codeword was written at the wrong tile AND the selector the hop
    actually needed was never emitted, because the short-circuit skips the
    general path. Two wrongs in one config-accepted image.
    """
    state = _padfeed_state(CHIPDB)
    # Every key carries a tile, and the tile is a real pad tile.
    assert state.padfeed_exact
    for key in state.padfeed_exact:
        pad_x, pad_y = key[0], key[1]
        assert (pad_x, pad_y) == (0, 4) or pad_y == 13, key

    # The pad-feed row and the colliding mesh edges are now distinct keys.
    pad_hop = (19, 13, 0, 19, 12, "RMUX", 25)
    assert state.padfeed_exact[pad_hop] == [(409, 64), (409, 16)]
    for colliding_y in (9, 11, 12):
        assert (19, colliding_y, 0, 19, 12, "RMUX", 25) not in state.padfeed_exact

    # And routing.py must build the key with the destination y in it.
    source = Path(inspect.getsourcefile(routing_feature)).read_text(encoding="utf-8")
    assert "padfeed_key = (dx, dy, di, sx, sy, sf, si)" in source


def test_no_pinned_artifact_resolves_through_an_unowned_padfeed_hop():
    """If one did, the refusal above would be moving a qualified emission."""
    import json
    import re as _re

    state = _padfeed_state(CHIPDB)
    wire = _re.compile(r"X(-?\d+)Y(-?\d+)_([A-Za-z]+)(\d+)")

    def parse(token):
        match = wire.fullmatch(token)
        return match and (int(match.group(1)), int(match.group(2)),
                          match.group(3), int(match.group(4)))

    manifest = json.loads(
        (ROOT / "qualification" / "pack_regression.json").read_text(encoding="utf-8")
    )
    assert manifest["artifacts"]
    for artifact in manifest["artifacts"]:
        design = json.loads((ROOT / artifact["routed"]).read_text(encoding="utf-8"))
        for module in design.get("modules", {}).values():
            for net in module.get("netnames", {}).values():
                for token in net.get("attributes", {}).get("ROUTING", "").split(";"):
                    if "." not in token or "GCLK" in token:
                        continue
                    source, destination = (parse(part) for part in token.split(".", 1))
                    if not source or not destination:
                        continue
                    sx, sy, sf, si = source
                    dx, dy, df, di = destination
                    if df != "RMUX":
                        continue
                    assert (dx, dy, di, sx, sy, sf, si) not in state.padfeed_unowned, (
                        "%s routes through a pad-feed hop with no codeword owner"
                        % artifact["routed"]
                    )


def test_conflicting_padfeed_codewords_are_refused(tmp_path):
    header = ("padtile_x,padtile_y,iomux_z,padfeed_rmux,cfg_group,src_res,"
              "src_x,src_y,dy,codeword_sels,codeword_bytes,codeword_masks\n")
    (tmp_path / "padfeed_L48_top.csv").write_text(
        header
        + '19,13,0,0,CFG_RMUX0,RMUX25,19,12,1,"0,3","409,409","64,16"\n'
        + '19,13,2,0,CFG_RMUX0,RMUX25,19,12,1,"1,4","525,525","64,32"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as excinfo:
        _padfeed_state(tmp_path)
    assert "conflicting pad-feed codewords" in str(excinfo.value)


def test_a_truncated_padfeed_codeword_is_refused(tmp_path):
    """zip() silently drops the tail when the byte and mask columns disagree."""
    header = ("padtile_x,padtile_y,iomux_z,padfeed_rmux,cfg_group,src_res,"
              "src_x,src_y,dy,codeword_sels,codeword_bytes,codeword_masks\n")
    (tmp_path / "padfeed_L48_top.csv").write_text(
        header + '19,13,0,0,CFG_RMUX0,RMUX25,19,12,1,"0,3","409,409,410","64,16"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as excinfo:
        _padfeed_state(tmp_path)
    assert "truncate" in str(excinfo.value)


def test_an_uncharacterized_left_edge_pad_feeder_is_refused():
    """The retired pad-ENABLE shape: an unlisted (slot, feeder) used to ``continue``."""
    source = Path(inspect.getsourcefile(physical_io_feature)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    prepare = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef) and node.name == "prepare")
    # The left-edge loop must raise on an unlisted selector rather than skip it.
    lookups = [
        node for node in ast.walk(prepare)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "get"
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "left_selectors"
    ]
    assert lookups, "the LEFT_IOMUX0_SEL lookup moved; re-point this test"
    guard = next(
        node for node in ast.walk(prepare)
        if isinstance(node, ast.If)
        and any(isinstance(inner, ast.Raise) for inner in node.body)
        and "left-edge pad" in ast.dump(node)
    )
    assert guard, "an unlisted left-edge feeder must fail closed, not `continue`"


# --------------------------------------------------------------------------
# route_through.py -- the characterized identity footprint
# --------------------------------------------------------------------------

FOOTPRINT_HEADER = ("x,y,z,init,source_wire,dest_wire,byte,value,write_mask,"
                    "selector_mask,sparse_policy\n")
FOOTPRINT_ROW = "1,2,3,0,X1Y2_OMUX02,X1Y2_IMUX03,%d,1,255,1,fail_closed\n"


def _footprint_file(tmp_path, *rows):
    path = tmp_path / "route_through_footprints.csv"
    path.write_text(FOOTPRINT_HEADER + "".join(rows), encoding="utf-8")
    return path


def test_the_control_footprint_loads_so_the_two_tests_below_isolate_one_column(tmp_path):
    rows = [FOOTPRINT_ROW % byte for byte in range(4)]
    assert route_through_feature.load_footprints(_footprint_file(tmp_path, *rows))


def test_a_blank_write_mask_is_refused_rather_than_becoming_a_full_byte(tmp_path):
    """255 overwrites bits other features own AND no-ops both mask validators.

    Every row is blanked, so the substituted default is uniform and none of the
    consistency checks below it can fire: without the explicit refusal this file
    loads cleanly.
    """
    rows = [FOOTPRINT_ROW.replace(",255,", ",,") % byte for byte in range(4)]
    with pytest.raises(route_through_feature.RouteThroughPolicyError) as excinfo:
        route_through_feature.load_footprints(_footprint_file(tmp_path, *rows))
    assert "write_mask" in str(excinfo.value)


def test_a_blank_sparse_policy_is_refused_rather_than_becoming_permissive(tmp_path):
    """"allow" silently disables the site's fail-closed final-edge check.

    Blank every row for the same reason: a uniform "allow" passes the
    ``len(policies) != 1`` check, which runs AFTER the default is substituted
    and therefore can never see it.
    """
    rows = [FOOTPRINT_ROW.replace(",fail_closed", ",") % byte for byte in range(4)]
    with pytest.raises(route_through_feature.RouteThroughPolicyError) as excinfo:
        route_through_feature.load_footprints(_footprint_file(tmp_path, *rows))
    assert "sparse_policy" in str(excinfo.value)


def test_the_shipped_footprint_table_still_loads(tmp_path):
    """The two columns above are populated in every shipped row."""
    path = CHIPDB / "route_through_footprints.csv"
    footprints = route_through_feature.load_footprints(path)
    assert footprints
    assert any(entry["sparse_policy"] == "fail_closed"
               for entries in footprints.values() for entry in entries)


# --------------------------------------------------------------------------
# mcu_ahb.py -- the MCU-edge bit bindings
# --------------------------------------------------------------------------

def test_every_mcu_edge_row_names_its_bit_and_resolves_to_a_real_wire():
    """Two silent drops lived here: ``or 0`` and ``if t in wireset``.

    ``int(r.get("bit") or 0)`` aliased a blank column onto GPIO bit 0, last row
    winning. The two ``in wireset`` guards dropped a binding without even
    incrementing the skip counter, and add_bels() derives the MCU bel TYPE from
    which of entry/exit survived -- so losing one half silently demotes a
    loopback ``MCU`` bel to ``MCU_DOUT``. The diagnostic prints the entry/exit
    INTERSECTION, so a half-bound bit vanishes from it entirely.
    """
    # Structural half: the loader must refuse, not skip. Both guards sit in the
    # `alta_rv` entry/exit branches of add_architecture's MCU-edge loop.
    source = Path(inspect.getsourcefile(mcu_ahb_feature)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    def bound_maps(node):
        return {
            inner.targets[0].value.id
            for inner in ast.walk(node)
            if isinstance(inner, ast.Assign)
            and isinstance(inner.targets[0], ast.Subscript)
            and isinstance(inner.targets[0].value, ast.Name)
            and inner.targets[0].value.id in ("bit_entry", "bit_exit")
        }

    # The pips_mcuedge_routing loop is the one that binds BOTH halves; the
    # haddr-lane loader binds only bit_entry and does report its skip count
    # against a stated denominator.
    loop = next(node for node in ast.walk(tree)
                if isinstance(node, (ast.For, ast.AsyncFor))
                and bound_maps(node) == {"bit_entry", "bit_exit"})
    guards = [
        node for node in ast.walk(loop)
        if isinstance(node, ast.If)
        and "wireset" in ast.dump(node.test)
        and any(isinstance(inner, ast.Raise) for inner in ast.walk(node))
    ]
    assert len(guards) >= 2, (
        "an MCU-edge entry/exit binding can be dropped without a diagnostic "
        "again; add_bels() derives the bel TYPE from which half survived"
    )

    wires = {
        "X%sY%s_%s" % (row["x"], row["y"], row["resource"])
        for row in csv.DictReader((CHIPDB / "wires.csv").open())
    }
    rows = list(csv.DictReader((CHIPDB / "pips_mcuedge_routing.csv").open()))
    assert rows
    for row in rows:
        assert (row.get("bit") or "").strip(), row
        for prefix, other in (("src", "dst"), ("dst", "src")):
            if row["%s_res" % prefix].startswith("alta_rv"):
                wire = "X%sY%s_%s" % (row["%s_x" % other], row["%s_y" % other],
                                      row["%s_res" % other])
                assert wire in wires, (
                    "MCU-edge binding %s is absent from wires.csv; dropping it "
                    "silently changes the bel type for bit %s" % (wire, row["bit"])
                )
