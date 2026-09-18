"""Slice inputs fed only by same-tile OMUX wires (2026-09-17).

In the tiered (plain ``build --uarch``) admission graph a handful of slice input pins have admitted
feeders, but every one of them is an OMUX wire of the same tile: no net driven from outside the
tile can ever reach the pin. The placement legality floor (``AGRV2K_MIN_INPUT_INDEG``) counts
feeders without regard to family, so an ordinary LUT with an externally driven net could be parked
on such a pin and lose its arc in routing (acc_probe: ``X20Y10_IMUX56``). The uarch now refuses
those pins for free (non-cluster) cells; dedicated-carry cluster members keep the count rule because
their ``I[0]`` carries the slice's own Q feedback, which those OMUX feeders exist for.

These tests pin the data fact (the pins are few, all ``I[0]``, and include the two X20 corridor
sites) and the presence of the rule in the shipped uarch source and its overlay copy.
"""
import csv
import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k"
SOURCE = UARCH / "agrv2k.cc"
OVERLAY = ROOT / "third_party" / "nextpnr" / "generic" / "viaduct" / "agrv2k" / "agrv2k.cc"


def _family(wire):
    fam = wire.split("_", 1)[1] if "_" in wire else wire
    return fam.rstrip("0123456789")


def _omux_only_slice_inputs(devdb):
    feeders = {}
    with open(devdb / "dev_pips.csv", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            feeders.setdefault(row["dst"], set()).add(_family(row["src"]))
    pins = []
    with open(devdb / "dev_belpins.csv", newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) < 3 or "_SLICE" not in row[0] or not row[1].startswith("I["):
                continue
            fams = feeders.get(row[2], set())
            if fams and fams <= {"OMUX"}:
                pins.append((row[0], row[1], row[2]))
    return pins


@pytest.mark.skipif(not (UARCH / "devdb_tiered_pcf" / "dev_pips.csv").exists(),
                    reason="tiered devdb cache not emitted in this checkout")
def test_tiered_graph_has_only_a_few_omux_only_slice_inputs_all_on_i0():
    pins = _omux_only_slice_inputs(UARCH / "devdb_tiered_pcf")
    assert pins, "the trap this rule guards against should still be present in the data"
    assert len(pins) <= 16, pins
    assert {pin for _, pin, _ in pins} == {"I[0]"}, pins
    wires = {wire for _, _, wire in pins}
    assert {"X20Y10_IMUX56", "X20Y11_IMUX56"} <= wires, wires


def test_uarch_refuses_omux_only_inputs_for_free_cells():
    text = SOURCE.read_text(encoding="utf-8")
    assert "g_wire_external_feed" in text
    assert 'wire_family_of(c.at(2)) != "OMUX"' in text
    assert "has only same-tile OMUX feeders" in text
    # the rule must not touch cluster members (dedicated carry keeps own-Q feedback on I[0])
    assert "cell->cluster == ClusterId() && target != WireId()" in text
    if OVERLAY.exists():
        assert OVERLAY.read_text(encoding="utf-8") == text
