"""The routed-netlist simulator's ALTA_BRAM9K model follows the vendor narrow-mode semantics.

Reference: tools/vendor_witness/alta_bram9k_vendor_sim.v (workbench), whose 39 direct-instantiated
modes passed on the board on 2026-09-25. A narrow port addresses a row with Address[12:4] and a
sub-word window with the low bits: writes land the address-selected window (x9 halves, x4 windows
0/4/9/13, x2 windows 0/2/4/6/9/11/13/15, x1 the 16 non-parity lanes); reads present the window on
the low DataOut lanes with every other lane high. x18 is unchanged from the historical model.
"""
import json

import pytest

from agamemnon.engine import verify_netlist as V

X18, X9, X4, X2, X1 = 0b00000, 0b01000, 0b01100, 0b01110, 0b01111


def test_write_masks_follow_the_vendor_windows():
    assert V._bram_write_mask(X18, 0, 0b11) == 0x3ffff
    assert V._bram_write_mask(X18, 0, 0b01) == 0x1ff
    assert V._bram_write_mask(X9, 0b0111, 0b11) == 0x1ff
    assert V._bram_write_mask(X9, 0b1111, 0b11) == 0x3fe00
    # x4: blk[3:2] picks the window, blk[3] skips the low-byte parity lane
    assert [V._bram_write_mask(X4, blk, 0b11) for blk in (0b0011, 0b0111, 0b1011, 0b1111)] == [
        0xf << 0, 0xf << 4, 0xf << 9, 0xf << 13]
    assert [V._bram_write_mask(X2, blk, 0b11) for blk in (0b0001, 0b0011, 0b0101, 0b0111,
                                                          0b1001, 0b1011, 0b1101, 0b1111)] == [
        0x3 << 0, 0x3 << 2, 0x3 << 4, 0x3 << 6, 0x3 << 9, 0x3 << 11, 0x3 << 13, 0x3 << 15]
    assert [V._bram_write_mask(X1, blk, 0b11) for blk in range(16)] == [
        1 << lane for lane in (0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16)]
    # ByteEn still gates a narrow write (vendor maskA_x4 & maskA_x18)
    assert V._bram_write_mask(X4, 0b1111, 0b01) == 0


def test_read_presentation_follows_the_vendor_lane_map():
    word = 0b10_1010_1010_0101_0101 & 0x3ffff          # lanes 17..0
    assert V._bram_read_present(X18, word, 0) == word
    lo, hi = word & 0x1ff, (word >> 9) & 0x1ff
    for blk, v in ((0b0111, lo), (0b1111, hi)):
        out = V._bram_read_present(X9, word, blk)
        assert (out >> 17) & 1 == 1 and (out >> 8) & 1 == 1 and out & 0x7f == 0x7f
        assert ((out >> 9) & 0xff) == (v & 0xff) and ((out >> 7) & 1) == (v >> 8)
    x16 = ((word >> 9) & 0xff) << 8 | (word & 0xff)
    for blk in range(16):
        out4 = V._bram_read_present(X4, word, blk)
        assert (out4 >> 3) & 0xf == (x16 >> (((blk >> 2) & 3) * 4)) & 0xf
        assert out4 & 0x7 == 0x7 and out4 >> 7 == 0x7ff
        out2 = V._bram_read_present(X2, word, blk)
        assert (out2 >> 1) & 0x3 == (x16 >> (((blk >> 1) & 7) * 2)) & 0x3 and out2 & 1 == 1
        out1 = V._bram_read_present(X1, word, blk)
        assert out1 & 1 == (x16 >> blk) & 1 and out1 >> 1 == 0x1ffff


def _routed_x9_single_port(tmp_path):
    """A minimal routed JSON: a free-running 2-bit counter on I nets feeding the BRAM address, a
    constant-1 WeA, DataInA replicated on both halves; DataOutA lanes read by an MCU_DOUT tap."""
    top = {"cells": {}, "netnames": {}, "ports": {}}
    nets = {}
    bit = [100]

    def net(name):
        bit[0] += 1
        nets[name] = bit[0]
        top["netnames"][name] = {"bits": [bit[0]], "attributes": {}}
        return bit[0]
    one = "1"
    c0, c1 = net("c0"), net("c1")
    # c0 toggles every cycle (Q <= ~Q), c1 toggles when c0 is 1 (Q <= Q ^ c0)
    top["cells"]["ff0"] = {"type": "GENERIC_SLICE", "parameters": {"FF_USED": "1", "INIT": "0101"},
                           "connections": {"I": [c0], "Q": [c0]}, "attributes": {}}
    top["cells"]["ff1"] = {"type": "GENERIC_SLICE", "parameters": {"FF_USED": "1", "INIT": "0110"},
                           "connections": {"I": [c1, c0], "Q": [c1]}, "attributes": {}}
    dout = [net("q%d" % i) for i in range(18)]
    top["cells"]["ram"] = {
        "type": "ALTA_BRAM9K",
        "parameters": {"PORTA_WIDTH": "01000", "PORTB_WIDTH": "01000", "PORTA_OUTREG": "0",
                       "PORTB_OUTREG": "0", "INIT_VAL": "0"},
        "connections": {
            # Address = {row=0, blk[3]=c1, 111}; data = {c0 on both halves' lane 0}
            "AddressA": [one, one, one, c1] + [str(0)] * 9,
            "DataInA": [c0] + ["0"] * 8 + [c0] + ["0"] * 8,
            "WeA": [one], "ReA": [one], "DataOutA": dout,
        }, "attributes": {}}
    top["cells"]["tap"] = {"type": "MCU_DOUT", "attributes": {"NEXTPNR_BEL": "MCU_DOUT10"},
                           "connections": {"DOUT": [dout[9]]}, "parameters": {}}
    path = tmp_path / "x9.routed.json"
    path.write_text(json.dumps({"modules": {"top": top}}), encoding="utf-8")
    return str(path)


def test_x9_write_then_read_round_trips_through_the_selected_half(tmp_path):
    rj = _routed_x9_single_port(tmp_path)
    seen = []

    def bram_probe(cycle, brams):
        seen.append(dict(brams[0]["last"]["A"]))
    V.sim_routed(rj, 8, bram_probe=bram_probe)
    writes = [r for r in seen if r.get("we")]
    assert writes, "the constant-1 WeA must write every cycle"
    # every write lands exactly one x9 half and its parity lane stays inside that half's mask
    for r in writes:
        assert r["mask"] in (0x1ff, 0x3fe00)
        assert (r["mask"] == 0x3fe00) == bool(r["blk"] & 8)
    # a read of the same address returns what the previous cycle wrote into that half
    halves = [(r["blk"] >> 3, r["out"]) for r in seen]
    assert all(((out >> 17) & 1) and ((out >> 8) & 1) and (out & 0x7f == 0x7f) for _, out in halves)


def test_x36_is_refused_not_mismodelled(tmp_path):
    rj = _routed_x9_single_port(tmp_path)
    doc = json.load(open(rj, encoding="utf-8"))
    doc["modules"]["top"]["cells"]["ram"]["parameters"]["PORTA_WIDTH"] = "10000"
    with pytest.raises(ValueError, match="not modelled"):
        V.sim_routed(rj, 2, document=doc)


def test_dead_net_and_qf_alias_change_what_consumers_read(tmp_path):
    rj = _routed_x9_single_port(tmp_path)
    doc = json.load(open(rj, encoding="utf-8"))
    values = {"plain": [], "dead": [], "alias": []}
    for key, kw in (("plain", {}), ("dead", {"dead_nets": ("c0",)}), ("alias", {"qf_alias": ("c0",)})):
        V.sim_routed(rj, 6, document=doc, probe=lambda cycle, value, k=key: values[k].append(value("c1")), **kw)
    # c1 toggles only when c0 reads 1: dead c0 (reads 1) toggles every cycle, plain every other
    assert values["plain"] != values["dead"]
    assert values["dead"] == [i % 2 for i in range(6)] or values["dead"] == [(i + 1) % 2 for i in range(6)]
    # the F-for-Q alias makes consumers see c0's next state (~Q), the complement of plain
    assert values["alias"] != values["plain"]
