"""Open LZW codec: decode + byte-exact encode round-trip on a real on-silicon fixture.

These pin the codec contract that was validated byte-for-byte against af.exe (and on real
silicon, 2026-06-30): the fabric .bin is an 8-byte header followed by a variable-width LZW
codestream that decodes to a fixed 99936-byte raw config image, and re-encoding that raw image
reproduces the original .bin exactly.
"""
import pytest

from agamemnon import cli
from agamemnon.engine import lzw_codec as L

RAW_LEN = 99936


def test_fixture_is_expected_size(blinky_bin_bytes):
    # The vendored module + project facts assume this exact 2921-byte real .bin.
    assert len(blinky_bin_bytes) == 2921


def test_header_constant():
    # DEVICE_ID 0x40200001 | max_index 0x0000ffff -> the fixed 8-byte .bin header.
    assert cli.HDR == bytes.fromhex("40200001") + bytes.fromhex("0000ffff")
    assert len(cli.HDR) == 8


def test_decode_yields_fixed_raw_length(blinky_bin_bytes):
    raw = cli._decode_to_raw(blinky_bin_bytes)
    assert isinstance(raw, (bytes, bytearray))
    assert len(raw) == RAW_LEN


def test_cli_decode_matches_lzw_codec_decode(blinky_bin_bytes):
    # The CLI's length-bounded decoder and the codec's decode() agree for the first RAW_LEN bytes.
    raw_cli = cli._decode_to_raw(blinky_bin_bytes)
    raw_codec = L.decode(blinky_bin_bytes[8:])
    assert raw_codec[:RAW_LEN] == raw_cli


def test_byte_exact_round_trip(blinky_bin_bytes):
    # HDR(8) + lzw_codec.encode(raw) reproduces the original .bin byte-for-byte.
    raw = cli._decode_to_raw(blinky_bin_bytes)
    rebuilt = cli.HDR + L.encode(raw)
    assert rebuilt == blinky_bin_bytes


def test_encode_then_decode_is_identity(blinky_bin_bytes):
    # Decoding the re-encoded image yields the same raw image (decode/encode are inverse here).
    raw = cli._decode_to_raw(blinky_bin_bytes)
    rebuilt = cli.HDR + L.encode(raw)
    assert cli._decode_to_raw(rebuilt) == raw


def test_decode_fails_closed_on_an_invalid_code():
    # A malformed/corrupted LZW codestream must be rejected, not silently
    # decoded into wrong bytes. After a literal establishes `prev`, the only
    # code that may legally be absent from the dictionary is exactly `nxt`
    # (the classic KwKwK case, here 258): code 300 is neither a known
    # dictionary entry nor `nxt`, so it can only come from a corrupted or
    # malicious stream.
    bw = L.BitWriter()
    bw.write(65, 9)   # literal 'A'; establishes `prev` for the KwKwK check
    bw.write(300, 9)  # invalid: absent from dict AND != nxt (258)
    payload = bw.flush()

    with pytest.raises(ValueError):
        L.decode(payload)
    # cli._decode_to_raw is a separate decoder implementation (it stops once
    # it has RAW_LEN bytes, to tolerate trailing flash padding) that must
    # enforce the same fail-closed contract as lzw_codec.decode.
    with pytest.raises(ValueError):
        cli._decode_to_raw(cli.HDR + payload)


def test_decode_to_raw_truncates_exactly_to_the_contracted_length(monkeypatch):
    # _decode_to_raw is documented to "Return the fixed ... byte raw image"
    # ("stopping at the target so trailing flash padding is ignored"). Its
    # stop check only looks at len(out) *before* reading the next code, so
    # when the target length falls inside a multi-byte dictionary entry the
    # last code decoded can push the output past the target. The function
    # must still return exactly the contracted length, not the overshoot --
    # an over-long "raw" image silently shifts every fixed absolute offset
    # downstream of it (e.g. cmd_edit_lut recomputes the CRC at the fixed
    # offset agasc.CRC_OFFSET, which would then land on the wrong bytes).
    raw_full = b"A" * 20
    payload = L.encode(raw_full)
    full = cli.HDR + payload

    monkeypatch.setattr(cli, "RAW_LEN", 4)
    out = cli._decode_to_raw(full)
    assert len(out) == 4
    assert out == raw_full[:4]


def test_decode_to_raw_fails_closed_on_a_truncated_stream(monkeypatch):
    # If the codestream runs out before producing the contracted length, that
    # is a truncated or corrupted input and must be rejected -- not silently
    # returned as a short "raw" image (which downstream fixed-offset code,
    # e.g. the CRC field, would then apply to the wrong bytes).
    raw_full = b"A" * 5
    payload = L.encode(raw_full)
    full = cli.HDR + payload

    monkeypatch.setattr(cli, "RAW_LEN", 1000)
    with pytest.raises(ValueError):
        cli._decode_to_raw(full)
