"""A narrow Port-A BRAM WRITE is a silently-wrong image; the emitter refuses it.

A narrow PORTA_WIDTH packs several logical words into one 18-bit physical row
(x9=2, x4=4, x2=9, x1=18 words/row). nextpnr's BRAM packer drives only the lowest
`active_width` DataInA lanes, so a WRITE can only store the packed sub-word those
lanes reach -- every other address silently keeps its old value, with no error and
no unmapped pip. PROVEN for x9 against the vendor alta_bram9k model: odd addresses
(upper 9 bits) never store (AG32-Docs tools/vendor_parity/bram_x9_write_multibit_
20260913; iverilog even 4/4 OK, odd 4/4 read-0). The x9wr2 image (sha f531b54b)
bitgens clean but is silently wrong.

The disconnect is internal to nextpnr and is NOT visible in the routed netlist:
the broken x9 image AND the working x2 SERV register file both present all 18
DataInA lanes as connected nets (measured 2026-09-13). So the only netlist-visible
signal is the width code, and the guard keys on it. The silicon-qualified writable
widths are x18 (R9 single-bit + x18h 2-bit sim) and x2 (the shipped dual-port SERV
register file, PORTA_WIDTH=01110, dynamic WeA, silicon-proven across
serv_rv32i_smoke/blinky/heartbeat). Those are exempt; x9 is proven-broken and
x4/x1 are unqualified/unverified -> refuse. Blast radius on the qualified set is
zero: x2 is the ONLY writable width in any qualified routed netlist.

2026-09-25 correction: narrow writes STORE on silicon. The vendor primitive
instantiated directly per mode passed its board oracle for every narrow write width
(AG32-Docs tools/rando_corpus/results/parity_20260925/, 39/39 modes), and the open
x9/x4/x2/x1 images with the DataIn replication passed the same oracle. The
replication path is therefore ON BY DEFAULT for the (width, port mode) combinations
in BOARD_PROVEN_NARROW_WRITES -- x4 dual-port and x1 single-port passed; x9, x2 and
x1 dual-port FAILED on the board and stay refused as open-flow bugs to find -- still
self-verifying (every address-selected window must be populated in the routed
netlist), and AGAMEMNON_NO_BRAM_NARROW_WRITE=1 restores the blanket refusal. An
unreplicated narrow write (the packer's lowest-window-only DataIn) is refused
exactly as before.
"""
from agamemnon.engine.features.bram import (
    BOARD_PROVEN_NARROW_WRITES,
    BOARD_PROVEN_NARROW_WRITE_WIDTHS,
    QUALIFIED_WRITE_WIDTHS,
    WIDTH_NAMES,
    narrow_write_board_proven,
    narrow_write_refusal,
    narrow_write_silently_wrong,
)
from agamemnon.engine.features import bram as bram_feature

# PORTA_WIDTH thermometer codes (bram_emit): x18=00000, x9=01000, x4=01100,
# x2=01110, x1=01111.
X18, X9, X4, X2, X1 = 0b00000, 0b01000, 0b01100, 0b01110, 0b01111
NET = [12345]          # a dynamically-driven WeA (a real net bit)


def test_qualified_writable_widths_are_exactly_x18_and_x2():
    # x2 is the shipped SERV register-file width; removing it here would make the
    # guard refuse the flagship silicon-proven design.
    assert QUALIFIED_WRITE_WIDTHS == frozenset((X18, X2))


def test_x9_dynamic_write_without_replicated_windows_is_refused():
    # The silently-wrong case: no DataInA replication, so the non-lowest windows
    # would keep their old value (odd-address write dropped vs the vendor model).
    assert narrow_write_silently_wrong(X9, NET)


def test_x2_and_x18_dynamic_write_are_admitted():
    # Flagship safety: SERV writes an x2 dual-port register file on silicon, and
    # x18 is the R9/x18h qualified writable width. Neither may be refused.
    assert not narrow_write_silently_wrong(X2, NET, dual_port=True)
    assert not narrow_write_silently_wrong(X18, NET)


def test_x4_and_x1_dynamic_write_without_replicated_windows_are_refused():
    # Same mechanism at x4/x1: without every address-selected window populated the
    # write is silently wrong and the fail-closed guard refuses it.
    assert narrow_write_silently_wrong(X4, NET)
    assert narrow_write_silently_wrong(X1, NET)


def test_read_only_narrow_bram_is_not_refused():
    # ROM / read-only (no dynamically-driven WeA) is exactly the case the packer
    # disconnect is CORRECT for, so it must never trip the write guard.
    for width in (X9, X4, X2, X1, X18):
        assert not narrow_write_silently_wrong(width, [])       # unbound
        assert not narrow_write_silently_wrong(width, None)     # absent
        assert not narrow_write_silently_wrong(width, ["0"])    # constant 0
        assert not narrow_write_silently_wrong(width, ["1"])    # constant 1 (ROM-fold, handled upstream)


# --- default DataIn-replication path (self-verifying; kill switch AGAMEMNON_NO_BRAM_NARROW_WRITE) ---
from agamemnon.engine.features.bram import (
    NARROW_WRITE_WINDOWS,
    _narrow_write_windows_populated,
)
from agamemnon.engine import qin_pack

NARROW = (X9, X4, X2, X1)
# X2's legacy exception applies only to the dual-port register-file shape.
NARROW_REFUSED = (X9, X4, X1)
# The board-proven (width, dual_port) combinations and the unproven ones per width.
PROVEN = ((X4, True), (X1, False))
UNPROVEN = ((X9, False), (X9, True), (X4, False), (X1, True))


def _populated_datain(width, drop=None):
    """An 18-entry DataInA where every physical lane the vendor mask can select for
    ``width`` is a real net (int), except optionally ``drop`` (left constant '0').
    Non-selectable lanes (8/17 for x4/x2/x1) are constant '0' don't-cares."""
    w, windows = NARROW_WRITE_WINDOWS[width]
    needed = {base + j for base in windows for j in range(w)}
    if drop is not None:
        needed.discard(drop)
    return [(1000 + i) if i in needed else "0" for i in range(18)]


def test_window_map_matches_qin_pack_transform():
    # The emitter guard and the qin_pack replication transform MUST agree on the
    # per-width physical windows, or a replicated write could pass the guard while a
    # window it left unfilled silently drops (or vice-versa).
    assert NARROW_WRITE_WINDOWS == qin_pack.NARROW_WRITE_WINDOWS


def test_default_admits_a_fully_replicated_board_proven_narrow_write():
    # Default path (kill switch off) AND every address-selected window populated by
    # a real net (what the replication transform produces) AND the (width, port mode)
    # board-proven -> emit-correct, not silently-wrong -> admitted.
    for width in NARROW:
        assert _narrow_write_windows_populated(width, _populated_datain(width))
    for width, dual in PROVEN:
        assert not narrow_write_silently_wrong(
            width, NET, _populated_datain(width), narrow_write_optin=True, dual_port=dual)
    # x2 write-A/read-B is admitted independently of the replication option.
    assert not narrow_write_silently_wrong(X2, NET, _populated_datain(X2),
                                           narrow_write_optin=True, dual_port=True)


def test_single_port_x2_write_is_refused_with_or_without_replication():
    for datain in (None, _populated_datain(X2)):
        for replication in (False, True):
            assert narrow_write_silently_wrong(
                X2, NET, datain, narrow_write_optin=replication, dual_port=False)
    assert "x2 single-port is not board-proven" in narrow_write_refusal(X2, True)


def test_default_refuses_the_modes_that_failed_on_the_board():
    # 2026-09-25 board: x9 single-port, x9-write/x4-read, x1 dual-port (and x2 with
    # replication) FAILED. They are open-flow bugs to find, not to admit: refused
    # even with every window populated.
    for width, dual in UNPROVEN:
        assert not narrow_write_board_proven(width, dual)
        assert narrow_write_silently_wrong(
            width, NET, _populated_datain(width), narrow_write_optin=True, dual_port=dual)


def test_default_still_refuses_a_partially_replicated_narrow_write():
    # Self-verifying + fail-closed: if the replication failed to fill even one
    # address-selected window lane, the write is still silently-wrong and stays
    # refused even though the (width, port mode) is board-proven.
    for width, dual in PROVEN:
        w, windows = NARROW_WRITE_WINDOWS[width]
        # drop the first lane of a NON-lowest window (the exact lane the old packer
        # dropped) -> not fully populated.
        drop_lane = windows[1]  # base of the second window
        datain = _populated_datain(width, drop=drop_lane)
        assert not _narrow_write_windows_populated(width, datain)
        assert narrow_write_silently_wrong(
            width, NET, datain, narrow_write_optin=True, dual_port=dual)


def test_kill_switch_refuses_even_populated_windows():
    # AGAMEMNON_NO_BRAM_NARROW_WRITE (narrow_write_optin=False): even a fully
    # populated DataInA in a proven mode is refused -- the switch restores the
    # blanket P0 refusal.
    for width, dual in PROVEN:
        assert narrow_write_silently_wrong(
            width, NET, _populated_datain(width), narrow_write_optin=False, dual_port=dual)


def test_default_read_only_narrow_bram_still_not_refused():
    # The default path never turns a read-only (no dynamic WeA) narrow BRAM into a refusal.
    for width in NARROW:
        for dual in (False, True):
            assert not narrow_write_silently_wrong(
                width, [], _populated_datain(width), narrow_write_optin=True, dual_port=dual)


def test_board_proven_narrow_writes_are_pinned_to_the_evidence():
    # Every entry here has an OPEN image that passed the board oracle with the
    # replication on (qualification/bram_narrow_write_evidence.jsonl, 2026-09-25:
    # bmd_sdp4_4_c00, bmd_tdp4_c10, bmd_sp1_c10_o0). Widening this set is a silicon
    # claim: it needs a new board record.
    assert BOARD_PROVEN_NARROW_WRITES == frozenset(PROVEN)
    assert BOARD_PROVEN_NARROW_WRITE_WIDTHS == frozenset((X4, X1))
    assert BOARD_PROVEN_NARROW_WRITE_WIDTHS.isdisjoint({X18, X2})
    assert set(WIDTH_NAMES) == {X18, X9, X4, X2, X1}


def test_unproven_mode_is_refused_even_when_fully_replicated(monkeypatch):
    # The default path is per (width, port mode): an unproven combination stays
    # refused (fail-closed) no matter how well the windows are populated.
    monkeypatch.setattr(bram_feature, "BOARD_PROVEN_NARROW_WRITES", frozenset(((X4, False),)))
    assert narrow_write_silently_wrong(X4, NET, _populated_datain(X4), narrow_write_optin=True, dual_port=True)
    assert not narrow_write_silently_wrong(X4, NET, _populated_datain(X4), narrow_write_optin=True, dual_port=False)


def test_refusal_names_the_cause_and_the_proven_modes():
    off = narrow_write_refusal(X9, False)
    assert "AGAMEMNON_NO_BRAM_NARROW_WRITE" in off and "x9" in off and "01000" in off
    unproven = narrow_write_refusal(X9, True, dual_port=False)
    assert "x9 single-port is not board-proven in the open flow" in unproven
    unpopulated = narrow_write_refusal(X4, True, dual_port=True)
    assert "does not drive every address-selected DataInA write window" in unpopulated
    assert "x4" in unpopulated
    for text in (off, unproven, unpopulated):
        assert "board-proven open modes: x4 dual-port, x1 single-port" in text
        assert "x18 (00000) and x2 dual-port (01110, the SERV register file) are always admitted" in text


def test_board_proven_bram_modes_pins_the_generalized_evidence_set():
    """2026-09-25 item 4: the generalized (width, port, OUTREG, WRITETHRU,
    PACKEDMODE, CLKMODE) evidence table, distinct from the narrow-write-only
    BOARD_PROVEN_NARROW_WRITES above. Pin the exact set so a regression (or an
    unreviewed addition) is caught -- see the module note in features/bram.py
    for why bmd_sp1_c10_o0 and bmd_byteen18_c10 are deliberately NOT in it
    despite once/nominally being expected to pass."""
    from agamemnon.engine.features.bram import (
        BOARD_PROVEN_BRAM_MODES, bram_mode_board_proven,
    )
    assert BOARD_PROVEN_BRAM_MODES == frozenset((
        (X4, X4, 0b00, 0, 0, 0, 0, 0),  # bmd_sdp4_4_c00
        (X4, X4, 0b10, 0, 0, 0, 0, 0),  # bmd_tdp4_c10
        (X1, X1, 0b10, 1, 0, 0, 0, 0),  # bmd_sp1_c10_o1
    ))
    assert bram_mode_board_proven(X4, X4, 0b00, 0, 0, 0, 0, 0)
    assert bram_mode_board_proven(X1, X1, 0b10, True, False, False, False, False)
    # Not proven: same width/port as a proven row but a different OUTREG.
    assert not bram_mode_board_proven(X1, X1, 0b10, 0, 0, 0, 0, 0)
    # Not proven: the RATE_FAIL/anomalous 2026-09-25 results stay excluded.
    assert not bram_mode_board_proven(X18, X18, 0b10, 0, 0, 0, 0, 0)  # bmd_sp18_c10_o0
