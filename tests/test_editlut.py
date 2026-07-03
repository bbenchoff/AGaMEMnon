"""Open LUT editor: a single-LE INIT edit touches exactly one raw byte and survives a codec
round-trip.

Edits LE (x=20, y=12, z=1) to truth table 0x96e9 (a 3-input XOR/MAJ-style mask) on the decoded
fixture, via the same code path the CLI uses (cli.patch_lut + cli._decode_to_raw). Because the
INIT bits for one LE pack into a single raw byte here, flipping that mask must change exactly one
raw byte, and re-encoding + decoding must reproduce the edited image bit-for-bit.
"""
from agamemnon import cli
from agamemnon.engine import lzw_codec as L

LE = (20, 12, 1)
INIT = 0x96E9


def test_edit_changes_exactly_one_raw_byte(blinky_bin_bytes):
    raw = cli._decode_to_raw(blinky_bin_bytes)
    raw2 = cli.patch_lut(raw, *LE, INIT)
    assert len(raw2) == len(raw)
    diffs = [i for i in range(len(raw)) if raw[i] != raw2[i]]
    assert len(diffs) == 1, f"expected 1 changed raw byte, got {len(diffs)}: {diffs}"


def test_edited_bin_decodes_back_to_edited_raw(blinky_bin_bytes):
    raw = cli._decode_to_raw(blinky_bin_bytes)
    raw2 = cli.patch_lut(raw, *LE, INIT)
    edited_bin = cli.HDR + L.encode(raw2)
    assert cli._decode_to_raw(edited_bin) == raw2


def test_edit_is_idempotent(blinky_bin_bytes):
    # Applying the same INIT twice yields the same raw image (patch sets bits, not toggles).
    raw = cli._decode_to_raw(blinky_bin_bytes)
    once = cli.patch_lut(raw, *LE, INIT)
    twice = cli.patch_lut(once, *LE, INIT)
    assert once == twice
