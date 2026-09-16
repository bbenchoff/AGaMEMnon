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
"""
from agamemnon.engine.features.bram import (
    QUALIFIED_WRITE_WIDTHS,
    narrow_write_silently_wrong,
)

# PORTA_WIDTH thermometer codes (bram_emit): x18=00000, x9=01000, x4=01100,
# x2=01110, x1=01111.
X18, X9, X4, X2, X1 = 0b00000, 0b01000, 0b01100, 0b01110, 0b01111
NET = [12345]          # a dynamically-driven WeA (a real net bit)


def test_qualified_writable_widths_are_exactly_x18_and_x2():
    # x2 is the shipped SERV register-file width; removing it here would make the
    # guard refuse the flagship silicon-proven design.
    assert QUALIFIED_WRITE_WIDTHS == frozenset((X18, X2))


def test_x9_dynamic_write_is_refused():
    # The proven-broken case (odd-address write dropped vs the vendor model).
    assert narrow_write_silently_wrong(X9, NET)


def test_x2_and_x18_dynamic_write_are_admitted():
    # Flagship safety: SERV writes an x2 dual-port register file on silicon, and
    # x18 is the R9/x18h qualified writable width. Neither may be refused.
    assert not narrow_write_silently_wrong(X2, NET)
    assert not narrow_write_silently_wrong(X18, NET)


def test_x4_and_x1_dynamic_write_are_refused_as_unqualified():
    # Not proven-broken like x9, but unqualified/unverified narrow writes -> the
    # fail-closed default refuses them (zero blast radius: unused in every
    # qualified routed netlist).
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


# --- AGAMEMNON_BRAM_NARROW_WRITE: opt-in DataIn-replication path (self-verifying) ---
from agamemnon.engine.features.bram import (
    NARROW_WRITE_WINDOWS,
    _narrow_write_windows_populated,
)
from agamemnon.engine import qin_pack

NARROW = (X9, X4, X2, X1)
# Widths subject to the self-verifying window check: X2 is exempt up front via the
# SERV dual-port QUALIFIED_WRITE_WIDTHS entry, so it is never refused and never
# reaches the window-population logic.
NARROW_REFUSED = (X9, X4, X1)


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


def test_optin_admits_a_fully_replicated_narrow_write():
    # With the opt-in flag AND every address-selected window populated by a real net
    # (what the replication transform produces), the write is emit-correct, not
    # silently-wrong -> admitted.
    for width in NARROW:
        assert _narrow_write_windows_populated(width, _populated_datain(width))
        assert not narrow_write_silently_wrong(
            width, NET, _populated_datain(width), narrow_write_optin=True)


def test_optin_still_refuses_a_partially_replicated_narrow_write():
    # Self-verifying + fail-closed: if the replication failed to fill even one
    # address-selected window lane, the write is still silently-wrong and stays
    # refused EVEN under the opt-in flag.
    for width in NARROW_REFUSED:
        w, windows = NARROW_WRITE_WINDOWS[width]
        # drop the first lane of a NON-lowest window (the exact lane the old packer
        # dropped) -> not fully populated.
        drop_lane = windows[1]  # base of the second window
        datain = _populated_datain(width, drop=drop_lane)
        assert not _narrow_write_windows_populated(width, datain)
        assert narrow_write_silently_wrong(
            width, NET, datain, narrow_write_optin=True)


def test_populated_windows_without_optin_still_refused():
    # The opt-in flag is required: even a fully populated DataInA is refused when the
    # caller did not opt in (default builds keep the fail-closed P0 refusal).
    for width in NARROW_REFUSED:
        assert narrow_write_silently_wrong(
            width, NET, _populated_datain(width), narrow_write_optin=False)


def test_optin_read_only_narrow_bram_still_not_refused():
    # Opt-in never turns a read-only (no dynamic WeA) narrow BRAM into a refusal.
    for width in NARROW:
        assert not narrow_write_silently_wrong(
            width, [], _populated_datain(width), narrow_write_optin=True)
