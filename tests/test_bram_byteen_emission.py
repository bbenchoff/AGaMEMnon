"""Native per-byte write-enable (ByteEnA) emission: the board-proven CFG_KMUX gnd tie.

Per-byte write masking on the AGRV2K BRAM is a CFG_KMUX *local-gnd tie* (position 8 of each
nine-selector KMUX lane), not a routed net. Board-proven at X13Y4 (2026-09-15): ByteEnA[0] -> sel 17
(low byte), ByteEnA[1] -> sel 26 (high byte); the open-flow A/B image_w2ei vs image_w2ei_be0 flipped
obs 0xE4->0xFF (low byte held at INIT), and a natively-emitted A/B (w356 vs w356_be10, differing by
exactly config byte 65990 + CRC) reproduces the identical bit. Intent is carried from qin_pack
(synth-visible ByteEnA='0') via the AGM_BYTEEN_A_MASK cell parameter, because the constant is
net-ified by bitgen. Opt-in (AGAMEMNON_BRAM_BYTEEN) so default builds stay byte-identical.

These tests pin the emitter table against the device DB (no drift), the fail-closed behaviour on an
unmodeled tile, and the packer stamp -- all without a board or a build.
"""
import csv
import json
import os

from agamemnon.engine import bram_emit
from agamemnon.engine import qin_pack


def _chipdb_kmux_sel(x, y, sel):
    path = os.path.join(os.path.dirname(os.path.dirname(bram_emit.__file__)),
                        "chipdb", "bram_cell.csv")
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            if (row["mux"] == "CFG_KMUX" and int(row["x"]) == x
                    and int(row["y"]) == y and int(row["sel"]) == sel):
                return (int(row["byte"]), int(row["mask"]))
    return None


def test_x13y4_byteen_cells_match_the_board_proven_bits():
    # These exact cells were board-proven to mask the byte (sel17=low, sel26=high).
    assert bram_emit.byteen_gnd_ties(13, 4, True, False) == {(65990, 2)}
    assert bram_emit.byteen_gnd_ties(13, 4, False, True) == {(66454, 2)}
    assert bram_emit.byteen_gnd_ties(13, 4, True, True) == {(65990, 2), (66454, 2)}
    # An enabled byte needs no selector (vcc is the canvas default) -> additive/empty.
    assert bram_emit.byteen_gnd_ties(13, 4, False, False) == set()


def test_byteen_table_does_not_drift_from_the_device_db():
    # The emitter loads sel17/sel26 from bram_cell.csv; assert every modeled site's
    # cells equal the device DB rows so a chipdb edit can never silently diverge.
    for (x, y), lanes in bram_emit.BYTEEN_GND_TIE.items():
        assert lanes[0] == _chipdb_kmux_sel(x, y, 17), (x, y, "low")
        assert lanes[1] == _chipdb_kmux_sel(x, y, 26), (x, y, "high")
    # All four BramTILEs are decoded; only X13Y4 is silicon-qualified.
    assert set(bram_emit.BYTEEN_GND_TIE) == {(13, 1), (13, 2), (13, 3), (13, 4)}
    assert bram_emit.BYTEEN_BOARD_PROVEN_TILES == frozenset({(13, 4)})


def test_unmodeled_tile_fails_closed():
    # A tile with no decoded ByteEn tie must raise, never silently write both bytes.
    try:
        bram_emit.byteen_gnd_ties(0, 0, True, False)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for an unmodeled BRAM tile")


def _bram_design(byteen_a):
    return {"modules": {"top": {"cells": {
        "mem": {"type": "ALTA_BRAM9K",
                "connections": {"ByteEnA": list(byteen_a)},
                "parameters": {}}}}}}


def _stamp(tmp_path, byteen_a, enabled):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(_bram_design(byteen_a)))
    prev = os.environ.get("AGAMEMNON_BRAM_BYTEEN")
    if enabled:
        os.environ["AGAMEMNON_BRAM_BYTEEN"] = "1"
    elif "AGAMEMNON_BRAM_BYTEEN" in os.environ:
        del os.environ["AGAMEMNON_BRAM_BYTEEN"]
    try:
        qin_pack.stamp_byteen_mask(str(p))
    finally:
        if prev is None:
            os.environ.pop("AGAMEMNON_BRAM_BYTEEN", None)
        else:
            os.environ["AGAMEMNON_BRAM_BYTEEN"] = prev
    return json.loads(p.read_text())["modules"]["top"]["cells"]["mem"]["parameters"]


def test_qin_pack_stamps_the_masked_lane_only_when_enabled(tmp_path):
    # ByteEnA = [bit0, bit1]; '0' == gnd == that byte masked.
    assert _stamp(tmp_path, ["0", "1"], True).get("AGM_BYTEEN_A_MASK") == "LOW"
    assert _stamp(tmp_path, ["1", "0"], True).get("AGM_BYTEEN_A_MASK") == "HIGH"
    assert _stamp(tmp_path, ["0", "0"], True).get("AGM_BYTEEN_A_MASK") == "BOTH"
    # Both enabled -> no stamp (nothing to mask).
    assert "AGM_BYTEEN_A_MASK" not in _stamp(tmp_path, ["1", "1"], True)
    # A routed/dynamic lane (int net bit) is not a constant gnd -> no stamp.
    assert "AGM_BYTEEN_A_MASK" not in _stamp(tmp_path, [7, "1"], True)


def test_qin_pack_stamp_is_gated_off_by_default(tmp_path):
    # Default builds (no opt-in) carry no new parameter -> byte-identical bitstreams.
    assert "AGM_BYTEEN_A_MASK" not in _stamp(tmp_path, ["0", "1"], False)
