"""Desk check: the constructive placer validates inter-tile bound arcs with the wire-level rule.

isBelLocationValid rejects a slot whose output wire cannot reach a bound consumer in
another tile ("local output topology cannot conduct net ... from X18Y12_SLICE4.Q to
X20Y12_SLICE14.I[0]", bram_fifo_kat 2026-09-19, 40/40 attempts).  CONDPLACE used to
check only same-tile pairs when binding a slot, so it produced placements the
validity check then refused.  It now tries a slot that also satisfies the capped
downhill-reach rule for every bound inter-tile producer/consumer first, and falls
back to the historical same-tile check only when no such slot exists.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def test_condplace_checks_inter_tile_arcs_before_binding_a_slot():
    source = UARCH.read_text(encoding="utf-8")
    start = source.index("static void pack_condplace(")
    body = source[start:start + 120000]
    reach = body.index("auto output_reach_ok = [&](WireId source, WireId target) -> bool {")
    assert "if (seen.size() > 4096) {" in body[reach:reach + 1600]
    assert "output_broad.insert(source.index);" in body[reach:reach + 1600]
    arcs = body.index("auto preserves_bound_local_arcs = [&](CellInfo *ci, BelId candidate, int tile, bool inter_tile)")
    assert "} else if (inter_tile && !output_reach_ok(src, dst)) {" in body[arcs:arcs + 3200]
    binding = body.index("for (int attempt = 0; attempt < 2 && b == BelId(); attempt++)")
    assert "preserves_bound_local_arcs(ci, try_b, t, attempt == 0)" in body[binding:binding + 2400]
    assert reach < arcs < binding
