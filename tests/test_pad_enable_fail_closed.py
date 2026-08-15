"""The ring-pad CFG_IOMUX enable pattern must be exact, or refused.

`io_emit.ENABLE` is a hand-written table of six characterized pad-slot sets. It
used to be consulted with `.get(active, {})`, so an uncharacterized slot set
emitted the source-select and no enable bits: a clean build, nothing unmapped,
and a dead pin.

There is no safe fallback to substitute, because the pattern is proven exact in
both directions on silicon:

* omitting bits leaves the pad static -- io_emit's own comment records that
  dropping bank1/block2 and bank2/block0 from the z0 set does exactly that;
* adding bits leaves the pad static too -- on 2026-08-15 the working PIN_18
  image was patched up to a uniform all-blocks pattern (six extra enable bits),
  still config-accepted with FCB 0x000f0002, and went from 460 kHz on Pico GP8
  to zero edges.

So the only correct behaviour on a miss is to fail closed.
"""

import pytest

from agamemnon.engine import io_emit


def test_the_characterized_slot_sets_are_pinned():
    assert {frozenset(entry) for entry in io_emit.ENABLE} == {
        frozenset({0}), frozenset({1, 2}), frozenset({1, 2, 3}),
        frozenset({0, 1, 2, 3}), frozenset({2, 3}), frozenset({0, 3}),
    }


def test_the_silicon_proven_z0_pattern_is_reproduced_exactly():
    """PIN_18 z0 fed by RMUX28: the pattern decoded from the toggling image."""
    sels = io_emit.emit_sels([(0, 28)])
    assert sels["CFG_IOMUX0"] == {3, 5, 13, 20, 27, 41}
    for bank in (1, 2, 3):
        assert sels["CFG_IOMUX%d" % bank] == {6, 13, 20, 27, 34, 41}

    # 6 and 34 in bank 0 are exactly the bits whose addition killed the pad.
    assert 6 not in sels["CFG_IOMUX0"] and 34 not in sels["CFG_IOMUX0"]


def test_an_uncharacterized_slot_set_fails_closed():
    with pytest.raises(SystemExit) as raised:
        io_emit.emit_sels([(0, 28), (1, 8)])
    message = str(raised.value)
    assert "no harvested CFG_IOMUX enable pattern" in message
    assert "STATIC" in message


def test_driving_no_pad_emits_nothing_rather_than_failing():
    assert io_emit.emit_sels([]) == {}
