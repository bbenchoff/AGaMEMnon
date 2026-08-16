"""The ring-pad CFG_IOMUX config is a park/unpark rule, not a lookup table.

`io_emit.ENABLE` held six of the fifteen possible pad-slot sets and the other
nine could not be driven at all. Fifteen af.exe oracles, one per non-empty
subset of {0,1,2,3} on IOTILE (19,13), plus a no-pad control from the same flow,
show the bits are not a per-set pattern to memorise:

    every IOMUX index parks at 7 * block + 6;
    driving index i unparks it and writes its two source-select bits;
    a pad slot z occupies TWO indices, z and z + 4;
    index i lives at bank, block = divmod(i, 6).

That last clause is why the old flat `7 * z + ...` form was wrong for z >= 6 on
the wider left-edge tiles: it ran off the end of bank 0.

chipdb/pad_iomux_slotset_L48.csv carries the fifteen measured deltas, and these
tests require the rule to reproduce every one exactly. Silicon closes the model
in both directions on the known-good PIN_18 image -- re-parking a driven block
kills the pad, unparking an unused one is harmless -- so a partial match is not
good enough here.
"""

import csv
from pathlib import Path

import pytest

from agamemnon.engine import default_frame, io_emit


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "agamemnon" / "chipdb" / "pad_iomux_slotset_L48.csv"


def rows():
    return list(csv.DictReader(CORPUS.open(newline="")))


def parse(field):
    return {tuple(int(part) for part in item.split("."))
            for item in field.split(";") if item}


def test_the_corpus_covers_every_non_empty_slot_set():
    observed = {tuple(int(z) for z in row["active_z"].split("|")) for row in rows()}
    expected = set()
    for mask in range(1, 16):
        expected.add(tuple(z for z in range(4) if mask >> z & 1))
    assert observed == expected
    assert len(rows()) == 15


def test_every_measured_set_has_both_iomux_indices_of_each_slot():
    for row in rows():
        slots = [int(z) for z in row["active_z"].split("|")]
        indices = sorted(int(i) for i in row["iomux_indices"].split("|"))
        assert indices == sorted({i for z in slots for i in (z, z + 4)})


@pytest.mark.parametrize("row", rows(), ids=lambda row: "z" + row["active_z"].replace("|", ""))
def test_the_rule_reproduces_the_vendor_measurement_exactly(row):
    feeders = {}
    for item in row["feeders"].split("|"):
        index, rmux = item.split(":")
        feeders[int(index)] = int(rmux)

    # index_config is the measured form: af.exe drives BOTH indices of a slot
    # and gives each its own feeder. slot_config is the open flow's narrower
    # form and is checked separately against the PIN_18 silicon case.
    sets, clears = io_emit.index_config(feeders)

    assert sets == parse(row["set_bits"])
    assert clears == parse(row["clear_bits"])


def test_the_rule_reproduces_the_silicon_proven_pin18_slot_zero_case():
    """PIN_18 is z0 fed by RMUX28; its two park clears are what silicon needs."""
    sets, clears = io_emit.slot_config([(0, 28)])
    assert sets == {(0, 3), (0, 5)}
    assert clears == {(0, 0), (0, 1), (0, 2), (0, 4), (0, 6), (0, 34)}

    # Those clears are precisely the bits whose RE-setting took the pad from
    # 460,856 Hz to zero edges, and the legacy ENABLE entry for {0} is the same
    # statement written as an absolute pattern: park everything except blocks
    # 0 and 4 of bank 0.
    legacy = io_emit.ENABLE[frozenset({0})]
    parked = {(bank, 7 * block + 6)
              for bank, blocks in legacy.items() for block in blocks}
    everything = {(bank, 7 * block + 6) for bank in range(4) for block in range(6)}
    park_clears = {pair for pair in clears if pair[1] % 7 == 6}
    assert everything - parked == park_clears


@pytest.mark.parametrize("z,rmux,stale,selected", [
    (1, 8, {8, 12}, {9, 11}),
    (2, 4, {17, 19}, {15, 18}),
    (3, 0, set(), {21, 25}),
])
def test_active_data_block_replaces_stale_selector_state(z, rmux, stale, selected):
    """The exceptional (19,13) base must end with one low and one high sel."""
    raw = bytearray(default_frame.build())
    before = set()
    for sel, (byte, mask) in io_emit.CELLS[(19, 13, "CFG_IOMUX0")].items():
        if raw[byte] & mask:
            before.add(sel)
    assert before.intersection(set(range(7 * z, 7 * z + 6))) == stale

    sets, clears = io_emit.slot_config_bits(19, 13, [(z, rmux)])
    for byte, mask in clears:
        raw[byte] &= (~mask) & 0xFF
    for byte, mask in sets:
        raw[byte] |= mask

    after = set()
    for sel, (byte, mask) in io_emit.CELLS[(19, 13, "CFG_IOMUX0")].items():
        if raw[byte] & mask:
            after.add(sel)
    assert after.intersection(set(range(7 * z, 7 * z + 6))) == selected
    assert 7 * z + 6 not in after


def test_an_index_past_the_first_bank_lands_in_the_right_bank():
    """The old flat form put index 6+ off the end of bank 0; divmod fixes it."""
    sets, clears = io_emit.slot_config([(3, 8)])
    assert (1, 7 * 1 + 6) in clears          # index 7 -> bank 1, block 1
    assert (0, 7 * 3 + 6) in clears          # index 3 -> bank 0, block 3
    assert all(bank == 0 for bank, _sel in sets)
