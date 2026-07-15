import os
import struct

import pytest

from agamemnon import cli
from agamemnon.engine import agasc


DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agamemnon", "chipdb")


def test_real_vendor_image_round_trips_byte_exact(blinky_bin_bytes):
    raw = cli._decode_to_raw(blinky_bin_bytes)
    text = agasc.dumps(raw, DATA, header=blinky_bin_bytes[:8])
    header, rebuilt = agasc.loads(text, DATA)

    assert header == blinky_bin_bytes[:8]
    assert rebuilt == raw
    assert ".agasc 1" in text
    assert ".tile " in text
    assert "+CFG_" in text
    assert ".raw " in text       # preserves asserted bits outside the semantic map


def test_removing_a_named_feature_clears_exactly_that_cell():
    _, by_feature = agasc.load_feature_map(DATA)
    key = (20, 13, "CFG_INPUTMUX2[1]")
    byte, mask = by_feature[key]
    raw = bytearray(agasc.RAW_LEN)
    raw[byte] |= mask
    raw[agasc.CRC_OFFSET:] = struct.pack(
        ">I", agasc.crc32_bzip2(cli.HDR + bytes(raw[:agasc.CRC_OFFSET]))
    )

    text = agasc.dumps(raw, DATA, header=cli.HDR)
    assert ".tile 20 13\n+CFG_INPUTMUX2[1]\n.end" in text
    edited = text.replace("+CFG_INPUTMUX2[1]\n", "", 1)
    _, rebuilt = agasc.loads(edited, DATA)

    assert not (rebuilt[byte] & mask)
    assert rebuilt[:agasc.CRC_OFFSET] == bytes(agasc.CRC_OFFSET)
    expected_crc = agasc.crc32_bzip2(cli.HDR + rebuilt[:agasc.CRC_OFFSET])
    assert rebuilt[agasc.CRC_OFFSET:] == struct.pack(">I", expected_crc)


def test_parser_rejects_raw_record_that_sets_a_named_bit():
    by_bit, _ = agasc.load_feature_map(DATA)
    byte, mask = next(iter(by_bit))
    text = """.agasc 1
.device 0x40200001
.max_index 0x0000ffff
.raw_length 99936
.crc auto
.raw %06x %02x
""" % (byte, mask)
    with pytest.raises(agasc.AgascError, match="raw sets a named bit"):
        agasc.loads(text, DATA)


@pytest.mark.parametrize("bad_line, message", [
    (".tile 99 99\n+CFG_DOES_NOT_EXIST[0]\n.end", "unknown feature"),
    (".raw 000000 01\n.raw 000000 00", "overlapping .raw"),
    (".crc mystery", "duplicate .crc"),
])
def test_parser_fails_closed_on_malformed_or_ambiguous_input(bad_line, message):
    prefix = """.agasc 1
.device 0x40200001
.max_index 0x0000ffff
.raw_length 99936
.crc auto
"""
    with pytest.raises(agasc.AgascError, match=message):
        agasc.loads(prefix + bad_line + "\n", DATA)
