"""Open LZW codec: decode + byte-exact encode round-trip on a real on-silicon fixture.

These pin the codec contract that was validated byte-for-byte against af.exe (and on real
silicon, 2026-06-30): the fabric .bin is an 8-byte header followed by a variable-width LZW
codestream that decodes to a fixed 99936-byte raw config image, and re-encoding that raw image
reproduces the original .bin exactly.
"""
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
