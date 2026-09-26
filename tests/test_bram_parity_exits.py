"""The BRAM DataOut parity lanes have admitted, byte-exact, board-witnessed exits at X13Y4.

DataOutA[8] and DataOutA[17] leave the BRAM tile on X13Y4_BufMUX32 and BufMUX33 (Port B:
BufMUX34/35).  Until 2026-09-25 no graph admitted a single pip out of those four wires: the
tile model listed a few exits, but bitgen requires a byte-exact bram_pip_cfg.csv row for a
BufMUX -> RMUX hop and none existed, and the witnessed-feeder rule kept even the encodable
ones out of the ring-witnessed terminals.  Every full 18-lane read therefore failed packing
with "BRAM output DataOutA[17] reaches slice input pins in only 0 tile(s)" -- an open-flow
gap, because af.exe routed those very hops in direct-instantiated BRAM mode images that
PASSED their self-checking oracles on the board (tools/rando_corpus/results/parity_20260925
in the workbench).  chipdb/bram_vendor_recovered_exits.csv records those first hops with the
2-hot selector pair read from each passing image; the ten X13Y4 rows carry topology in
bram9k_edges.csv and their codeword bytes in bram_pip_cfg.csv.
"""
import csv
from pathlib import Path

from agamemnon.engine.features import bram as bram_feature

ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
ROUTING = ROOT / "agamemnon" / "engine" / "features" / "routing.py"
PARITY_WIRES = {"BufMUX32", "BufMUX33", "BufMUX34", "BufMUX35"}
PORT_B_WIRES = {"BufMUX%02d" % n for n in range(16, 32)}   # DataOutB lanes 0..7 and 9..16
RECOVERED_WIRES = PARITY_WIRES | PORT_B_WIRES
NPI = {"RMUX": 6}
BS = {"RMUX": 10}


def _rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _recovered():
    rows = _rows("bram_vendor_recovered_exits.csv")
    assert rows, "the evidence table must not be empty"
    for row in rows:
        assert row["src_res"] in RECOVERED_WIRES, row
        assert row["dst_res"].startswith("RMUX"), row
        assert (row["src_x"], row["dst_x"]) == ("13", "13"), row
        assert row["src_y"] == row["dst_y"], row
        assert row["source"] == "vendor_passing_image", row
        assert int(row["passing_images"]) >= 1, row
        lo, hi = int(row["sel_lo"]), int(row["sel_hi"])
        assert 0 <= lo < hi < 60, row
    return rows


def test_every_parity_lane_has_an_admitted_exit_at_x13y4():
    at_y4 = {(r["src_res"], r["dst_res"]) for r in _recovered() if r["dst_y"] == "4"}
    assert {src for src, _ in at_y4} == RECOVERED_WIRES
    # every Port-B lane: the dual-port 18/18 read failed packing on DataOutB[10] after the
    # parity lanes alone were admitted (bmd_sdp18_18_c00, 2026-09-25 00:15)
    assert all("BufMUX%02d" % n in {src for src, _ in at_y4} for n in range(16, 32))
    # the vendor's most-used exits, in four and two passing images respectively
    assert ("BufMUX32", "RMUX01") in at_y4
    assert ("BufMUX33", "RMUX31") in at_y4


def test_x13y4_rows_carry_topology_and_byte_exact_codewords():
    topology = {(r["src_res"], r["dst_res"]) for r in _rows("bram9k_edges.csv")
                if (r["src_x"], r["src_y"], r["dst_x"], r["dst_y"]) == ("13", "4", "13", "4")}
    exact = {}
    for r in _rows("bram_pip_cfg.csv"):
        if (int(r["ddx"]), int(r["ddy"])) == (0, 0):
            exact.setdefault((r["dst_res"], r["src_res"]), []).append((int(r["byte"]), int(r["mask"])))
    cells = {}
    for r in _rows("bram_cell.csv"):
        if (r["x"], r["y"]) == ("13", "4"):
            cells[(r["mux"], int(r["sel"]))] = (int(r["byte"]), int(r["mask"]))
    for row in _recovered():
        if row["dst_y"] != "4":
            continue
        pair = (row["src_res"], row["dst_res"])
        assert pair in topology, "%s has no bram9k_edges.csv row" % (pair,)
        index = int(row["dst_res"][4:])
        key = ("RMUX%d" % index, "BufMUX%d" % int(row["src_res"][6:]))
        bits = exact.get(key)
        assert bits and len(bits) == 2, "%s has no byte-exact bram_pip_cfg.csv pair" % (pair,)
        # the recorded 2-hot pair lies inside the destination's own selector block and
        # names exactly the bytes bitgen will set
        config = "CFG_RMUX%d" % (index // NPI["RMUX"])
        block = (index % NPI["RMUX"]) * BS["RMUX"]
        sels = (int(row["sel_lo"]), int(row["sel_hi"]))
        assert all(block <= sel < block + BS["RMUX"] for sel in sels), (pair, sels)
        assert sorted(cells[(config, sel)] for sel in sels) == sorted(bits), (pair, sels, bits)


def test_bram_pip_cfg_rows_for_the_exits_sit_in_their_destination_block():
    exact = {}
    for r in _rows("bram_pip_cfg.csv"):
        if r["src_res"] in {"BufMUX%d" % n for n in (32, 33, 34, 35)}:
            key = (r["dst_res"], r["src_res"], int(r["ddx"]), int(r["ddy"]))
            exact.setdefault(key, []).append((int(r["byte"]), int(r["mask"])))
    assert exact
    cells = bram_feature.BramFeature._selector_cells(CHIPDB)
    assert bram_feature.BramFeature.inconsistent_exact_pips(exact, cells) == []


def test_other_sites_are_evidence_only_until_their_bytes_are_mapped():
    # bitgen applies bram_pip_cfg.csv bytes only at X13Y4, so a recovered-wire topology row at
    # another site must stay unencodable (and therefore pruned by the loader) until that site's
    # cells are mapped; the X13Y2/Y3 parity observations are recorded as evidence only.
    exact = {(r["dst_res"], r["src_res"]) for r in _rows("bram_pip_cfg.csv")
             if (int(r["ddx"]), int(r["ddy"])) == (0, 0)}
    for r in _rows("bram9k_edges.csv"):
        if r["src_res"] in PARITY_WIRES and r["src_x"] == "13" and r["src_y"] != "4":
            key = ("RMUX%d" % int(r["dst_res"][4:]), "BufMUX%d" % int(r["src_res"][6:]))
            assert key not in exact, (r, "would be routable but unencodable at X13Y%s" % r["src_y"])
    assert any(r["dst_y"] != "4" for r in _recovered())
    assert all(r["src_res"] in PARITY_WIRES for r in _recovered() if r["dst_y"] != "4")


def test_witnessed_feeder_rule_reads_the_recovered_exits():
    source = ROUTING.read_text(encoding="utf-8")
    rule = source.index("_rec = os.path.join(DATA, \"bram_vendor_recovered_exits.csv\")")
    joined = source.index("if dk in _BRAM_FINAL_DST and dk not in _bram_wl_governed:", rule)
    # joins an already-restricted terminal's whitelist; never restricts one (no _BRAM_FINAL_DST.add)
    assert "_BRAM_FINAL_DST.add" not in source[rule:joined + 400]
    conduct = source.index("CONDUCT = set()")
    assert '"bram_vendor_recovered_exits.csv"' in source[conduct:conduct + 1500]


def test_open_primitive_declares_every_experimental_field():
    """A direct instantiation that sets an experimental BRAM field must reach bitgen's gate.

    bram_emit.EXPERIMENTAL_FIELDS refuses a non-zero PACKEDMODE/DLYTIME/RSEN_DLY unless
    AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG is set; that refusal names the flag.  When the open
    ALTA_BRAM9K did not declare those parameters, yosys rejected the instantiation first
    (vendor-parity matrix 2026-09-25, bmd_packed18_c00: synthesis error), so the design never
    saw the real reason.  Declaring them admits nothing: default 0 is byte-identical.
    """
    import re
    from agamemnon.engine import bram_emit
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    start = prims.index("module ALTA_BRAM9K")
    header = prims[start:prims.index(") (", start)]
    declared = set(re.findall(r"parameter(?:\s*\[[^\]]+\])?\s+(\w+)\s*=", header))
    assert set(bram_emit.EXPERIMENTAL_FIELDS) <= declared, sorted(set(bram_emit.EXPERIMENTAL_FIELDS) - declared)


def test_every_x13y4_address_terminal_has_a_board_proven_feeder_whitelist():
    """Every AddressA/AddressB terminal at X13Y4 is governed by chipdb/bram_wl.csv.

    Until 2026-09-25 the final-hop whitelist covered ten Port-A address terminals; the low
    Port-A bits (AddressA[0], [1], [3]) and all of Port B were open to any config-accepting
    feeder. The 0278236 widening (same date) covered all 26 terminals but excluded
    X13Y4_RMUX22 -> IMUX52 (AddressB[1]) and X13Y4_RMUX17 -> IMUX11 (AddressA[1]),
    reasoning from the open x1/x2 simple-dual-port board failures (bmd_sdp1_1_c00,
    bmd_sdp2_2_c00) that those were "the known shape of a config-accepting but dead entry
    pip." That reasoning is corrected here: both hops were already silicon-ring-witnessed
    (chipdb/ring_witness_conduction.csv, source=silicon_ring) -- the campaign's own
    ring-oscillator conduction proof, independent of any one design -- and
    integration-testing serv_blinky (SERV's x2 TRUE-dual-port register file, always
    admitted per QUALIFIED_WRITE_WIDTHS, unrelated to the narrow-write feature) showed it
    fails to build on work/integrate-20260925 with exactly these two hops as its only
    placement-reachable feeders for rf_raddr[0], while it builds AND PASSES on the board
    from plain main (AG32-Docs tools/rando_corpus/results/omux_ab,
    RESULT_omuxab_on_serv_blinky_pin17.json, verdict PASS, 77/77/77 edges) using exactly
    X13Y4_RMUX17 -> IMUX11 and X13Y4_RMUX22 -> IMUX52 (confirmed from a fresh
    --write-routed main build's ROUTING attributes on 2026-09-25). The bmd_sdp1_1_c00 /
    bmd_sdp2_2_c00 board failures are therefore not evidence against these address-entry
    pips: both modes are already documented elsewhere (docs/STATUS.md,
    BOARD_PROVEN_NARROW_WRITES) as failing on a DataOut-egress lane bug, not an address-
    entry one. The whitelist lists, per terminal, the feeders af.exe routed in images that
    passed their self-checking oracle (vendor_passing_image), the feeders of passing
    default-build open images (open_passing_image), and ring/design-witnessed feeders
    (silicon, silicon_ring_20260925).
    """
    pins = {r["wire"]: (r["port"], int(r["bit"])) for r in _rows("bram9k_pinmap.csv")
            if r["port"] in ("AddressA", "AddressB")}
    assert len(pins) == 26
    allowed = {}
    for r in _rows("bram_wl.csv"):
        if (r["dst_x"], r["dst_y"]) == ("13", "4") and r["dst_res"].startswith("IMUX"):
            dst = "X13Y4_IMUX%02d" % int(r["dst_res"][4:])
            allowed.setdefault(dst, set()).add("X%sY%s_%s%02d" % (
                r["src_x"], r["src_y"], r["src_res"].rstrip("0123456789"),
                int(r["src_res"][len(r["src_res"].rstrip("0123456789")):])))
    missing = sorted(w for w in pins if w not in allowed)
    assert not missing, missing
    # 2026-09-25 (serv_blinky integration): re-admitted on ring-witness + serv_blinky board-PASS
    # evidence (see docstring); both were silicon_ring-witnessed all along.
    assert "X13Y4_RMUX22" in allowed["X13Y4_IMUX52"]
    assert "X13Y4_RMUX17" in allowed["X13Y4_IMUX11"]
    # the feeders the passing open x1 single-port image used stay admitted
    assert "X13Y4_RMUX23" in allowed["X13Y4_IMUX11"]
    assert "X13Y4_RMUX46" in allowed["X13Y4_IMUX12"]
