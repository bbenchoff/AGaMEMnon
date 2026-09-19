"""Desk check: a BRAM output lane with narrow egress gets a bound identity bridge.

DataOutA[12] (X13Y4_BufMUX11) reaches 29 slice input pins in the admitted
graph, all in X14Y4, while every other lane reaches ~8,400 pins fabric-wide.
The tile-level constructive placer put bram_rom_kat's data[3] consumers on
X14Y6 and every attempt died with "cannot conduct fixed input net 'data[3]'"
followed by "compaction requires a legal initial placement" (2026-09-19).  The
uarch now re-drives such a lane through one identity LUT bound at a reachable
pin, right after the pin packer seats the address/data drivers and before the
single-user output bridges look for exact chains.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def test_bram_output_reach_bridge_pass_is_present_and_ordered():
    source = UARCH.read_text(encoding="utf-8")
    definition = source.index("void pack_bram_output_reach_bridges()")
    assert "constexpr size_t narrow_tiles = 2;" in source[definition:definition + 4000]
    assert 'ctx->bindBel(bridge.site, raw, STRENGTH_LOCKED);' in source[definition:definition + 8000]
    assert 'AGRV2K_NO_BRAM_OUTPUT_REACH_BRIDGE' in source[definition:definition + 1500]
    pin_drivers = source.index("pack_bram_pin_drivers(ctx); // slot-exact dynamic BRAM ingress")
    reach_bridge = source.index("pack_bram_output_reach_bridges(); // narrow-egress output lanes")
    output_bridges = source.index("pack_bram_output_bridges(); // derive output identities")
    assert pin_drivers < reach_bridge < output_bridges


def test_bram_output_reach_bridge_names_are_json_safe():
    source = UARCH.read_text(encoding="utf-8")
    definition = source.index("void pack_bram_output_reach_bridges()")
    body = source[definition:definition + 8000]
    # the lane name DataOutA[12] becomes DataOutA_12_ in the cell name
    assert "if (ch == '[' || ch == ']') ch = '_';" in body
    assert '"OUTBRIDGE"' in body
