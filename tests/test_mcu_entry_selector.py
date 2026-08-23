"""Guard the InputMUX-at-x13 -> RMUX fabric-entry fallback selector.

``_mcu_entry_pair`` is a hand-derived fallback for an MCU/InputMUX entry hop
with no exact per-edge tuple in the chipdb exit-pair tables. It was wrong
(``block + 3, block + 9``) and never board-tested: every earlier caller was
intercepted upstream by ``MCU_ENTRY``, ``clean_edge`` or ``relative_edge``, so
the formula sat dormant until a 257-row chipdb addition admitted three new
InputMUX-at-x13 -> RMUX pips with no such coverage. All three hit it for the
first time and encoded WRONG -- ``htrans1``, ``hwdata[0]``, ``hwdata[1]``, the
public16 W1C overlay's gating signals, failed 3/3 on L48 silicon.

Fixed 2026-08-21 to ``block + 2, block + 8``, which matches all three curated
``MCU_ENTRY`` ground-truth rows exactly. Two things are pinned here so this
cannot regress silently:

1. The formula agrees with ``MCU_ENTRY`` (this test derives its expectation
   from the dict itself, so it also covers any curated row added later).
2. The fallback REFUSES (fails closed) for any source x other than 13 --
   the offset is evidenced only for the InputMUX-at-x13 -> RMUX mechanism,
   not for "RMUX destination fallback" in general. A different source family
   at a similar-looking location (``X13Y9_BufMUX14 -> X14Y9_RMUX38``, resolved
   entirely separately via ``bufmux_rmux_entry_pip_cfg.csv`` /
   ``exact_mcu_pips``, never reaching this function) uses an unrelated local
   ``(0, 7)`` -- proof the offset is not a source-x-independent constant.
"""

import pytest

from agamemnon.engine.features.routing import (
    MCU_ENTRY, NPG, BS, _SILICON_QUALIFIED_UNSCOPED_ENTRY,
    _mcu_entry_pair, _resolve_mcu_inputmux_entry,
)


def test_mcu_entry_pair_matches_curated_ground_truth():
    assert len(MCU_ENTRY) == 3
    for (dx, dy, di), entries in MCU_ENTRY.items():
        cfg_names = {cfg for cfg, _ in entries}
        assert len(cfg_names) == 1, (dx, dy, di, entries)
        expected_cfg = cfg_names.pop()
        expected_selections = tuple(sorted(selection for _, selection in entries))

        cfg, selections = _mcu_entry_pair(di)

        assert cfg == expected_cfg, (dx, dy, di)
        assert tuple(sorted(selections)) == expected_selections, (dx, dy, di)


def test_mcu_entry_pair_literal_values_unchanged():
    # A second, independent pin on the literal dict content: if MCU_ENTRY
    # itself were ever edited to quietly match a wrong formula, the test
    # above would stop catching it. These are the three board-derived rows
    # from the L1 task writeup, transcribed once, here, from evidence.
    assert MCU_ENTRY == {
        (14, 10, 14): [("CFG_RMUX2", 22), ("CFG_RMUX2", 28)],
        (14, 12, 73): [("CFG_RMUX12", 12), ("CFG_RMUX12", 18)],
        (14, 12, 21): [("CFG_RMUX3", 32), ("CFG_RMUX3", 38)],
    }
    for di, expected in ((14, "CFG_RMUX2"), (73, "CFG_RMUX12"), (21, "CFG_RMUX3")):
        assert _mcu_entry_pair(di)[0] == expected
    assert _mcu_entry_pair(14)[1] == (22, 28)
    assert _mcu_entry_pair(73)[1] == (12, 18)
    assert _mcu_entry_pair(21)[1] == (32, 38)


def test_mcu_entry_pair_is_a_fixed_offset_from_the_rmux_block():
    for di in (14, 73, 21):
        block = BS["RMUX"] * (di % NPG["RMUX"])
        _cfg, (lo, hi) = _mcu_entry_pair(di)
        assert (lo - block, hi - block) == (2, 8)


# -- _resolve_mcu_inputmux_entry: the scope guard around the formula --------


def test_resolve_prefers_clean_edge_observation_over_the_formula():
    entries, source_class, predicted = _resolve_mcu_inputmux_entry(
        dx=14, dy=10, di=14, sx=13,
        clean_pair=(1, 7), relative_pair=None,
        label="RMUX14 <- InputMUX00 @(14,10)",
    )
    assert source_class == "conflict-free-physical-observation"
    assert predicted is False
    block = BS["RMUX"] * (14 % NPG["RMUX"])
    assert entries == [("CFG_RMUX2", block + 1), ("CFG_RMUX2", block + 7)]


def test_resolve_prefers_relative_edge_observation_over_the_formula():
    entries, source_class, predicted = _resolve_mcu_inputmux_entry(
        dx=14, dy=10, di=14, sx=13,
        clean_pair=None, relative_pair=(0, 6),
        label="RMUX14 <- InputMUX00 @(14,10)",
    )
    assert source_class == "unanimous-relative-observation"
    assert predicted is False
    block = BS["RMUX"] * (14 % NPG["RMUX"])
    assert entries == [("CFG_RMUX2", block + 0), ("CFG_RMUX2", block + 6)]


def test_resolve_prefers_curated_mcu_entry_over_the_formula():
    # di=14 has a curated MCU_ENTRY row; with no clean/relative evidence it
    # must come back curated, NOT via the formula, even though sx == 13 would
    # also satisfy the formula's guard.
    entries, source_class, predicted = _resolve_mcu_inputmux_entry(
        dx=14, dy=10, di=14, sx=13,
        clean_pair=None, relative_pair=None,
        label="RMUX14 <- InputMUX00 @(14,10)",
    )
    assert source_class == "mcu-entry-curated-observation"
    assert predicted is False
    assert entries == MCU_ENTRY[(14, 10, 14)]


def test_resolve_uses_only_the_pinned_silicon_qualified_interior_entry():
    assert _SILICON_QUALIFIED_UNSCOPED_ENTRY == {
        (11, 4, 93): ("CFG_RMUX15", (33, 39)),
    }
    entries, source_class, predicted = _resolve_mcu_inputmux_entry(
        dx=11, dy=4, di=93, sx=11,
        clean_pair=None, relative_pair=None,
        label="RMUX93 <- InputMUX11 @(11,4)",
    )
    assert source_class == "mcu-entry-silicon-qualified-interior"
    assert predicted is False
    assert entries == [("CFG_RMUX15", 33), ("CFG_RMUX15", 39)]


def test_resolve_falls_back_to_the_formula_only_at_sx_13():
    # di=999 has no curated row, so with no clean/relative evidence and
    # sx == 13 this must hit the (evidenced) blind formula, and it must be
    # counted `predicted`.
    entries, source_class, predicted = _resolve_mcu_inputmux_entry(
        dx=17, dy=9, di=7, sx=13,
        clean_pair=None, relative_pair=None,
        label="RMUX07 <- InputMUX00 @(17,9)",
    )
    assert source_class == "mcu-entry-inputmux-x13-formula"
    assert predicted is True
    assert entries == [(_mcu_entry_pair(7)[0], selection)
                        for selection in _mcu_entry_pair(7)[1]]


@pytest.mark.parametrize("sx", [0, 1, 12, 14, 17, 20])
def test_resolve_fails_closed_outside_inputmux_at_x13(sx):
    # This is the actual regression this task fixes: the wrong-by-default
    # blind formula must never fire for a source x it has no evidence for. A
    # SystemExit here is a build refusing to guess, not a crash.
    with pytest.raises(SystemExit, match="InputMUX-at-x13"):
        _resolve_mcu_inputmux_entry(
            dx=17, dy=9, di=7, sx=sx,
            clean_pair=None, relative_pair=None,
            label="RMUX07 <- InputMUX00 @(17,9)",
        )
