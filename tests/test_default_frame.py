"""From-scratch design-neutral base-image generator (experimental, opt-in).

Verifies that ``default_frame`` reconstructs the expected fraction of the
decoded canvas from shipped data only, that the reserved routing/seam SRAM
region is a declared zeros gap (never copied from the vendor blob), and that
default bitgen is byte-for-byte unchanged (still decodes ``fabric_default.bin``).
"""
import struct
from pathlib import Path

from agamemnon.engine import agasc, default_frame, lzw_codec, preamble
from agamemnon.engine.bitgen import base_image
from agamemnon.engine.registry import OPTIONS, EngineOptions


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def _decoded_canvas():
    blob = (CHIPDB / "fabric_default.bin").read_bytes()
    payload = blob[8:]
    raw = payload if len(payload) == agasc.RAW_LEN else lzw_codec.decode(payload)
    return blob[:8], bytes(raw)


def test_option_is_registered_and_off_by_default():
    assert "AGAMEMNON_FROM_SCRATCH_BASE" in OPTIONS
    spec = OPTIONS["AGAMEMNON_FROM_SCRATCH_BASE"]
    assert spec.kind == "flag" and spec.maturity == "experimental"
    assert (ROOT / spec.evidence).exists()
    # Presence semantics: unset means off.
    assert not EngineOptions({}).enabled("AGAMEMNON_FROM_SCRATCH_BASE")


def test_build_is_a_deterministic_99936_byte_image():
    first = default_frame.build()
    assert isinstance(first, bytes) and len(first) == agasc.RAW_LEN
    assert first == default_frame.build()  # deterministic, no canvas read
    assert default_frame.header() == struct.pack(
        ">II", agasc.DEFAULT_DEVICE, agasc.DEFAULT_MAX_INDEX
    )


def test_preamble_and_crc_are_regenerated_ours():
    raw = default_frame.build()
    # Preamble is the declarative idle profile, byte-exact.
    assert raw[:preamble.PREAMBLE_LENGTH] == preamble.IDLE_PROFILE
    # The stored CRC is a freshly computed, valid CRC over our own bytes.
    stored = struct.unpack(">I", raw[agasc.CRC_OFFSET:])[0]
    expected = agasc.crc32_bzip2(default_frame.header() + raw[:agasc.CRC_OFFSET])
    assert stored == expected


def test_generator_reaches_expected_byte_exact_fraction():
    report = default_frame.diff_against_canvas()
    # Task target: ~70%+.  Measured today: 71.15% (zeros+preamble alone = 70.33%).
    assert report["body_exact_fraction"] >= 0.70
    assert report["preamble_exact"] is True
    assert report["body_matched"] == 70983
    assert report["body_total"] == agasc.CRC_OFFSET - preamble.PREAMBLE_LENGTH
    fams = report["families"]
    # Regenerated-clean families are fully matched.
    assert fams["zero_default"] == {"total": 70168, "matched": 70168, "gap": 0}
    assert fams["border_named"] == {"total": 339, "matched": 339, "gap": 0}
    assert fams["framing_col58"] == {"total": 476, "matched": 476, "gap": 0}
    # The single unpromoted table is the dominant remaining gap.
    assert fams["reserved_sram_gap"]["matched"] == 0
    assert fams["reserved_sram_gap"]["gap"] == fams["reserved_sram_gap"]["total"]
    assert fams["reserved_sram_gap"]["total"] >= 28000


def test_reserved_sram_region_is_a_declared_gap_not_vendor_copied():
    report = default_frame.diff_against_canvas()
    # No unnamed all-ones reserved byte is ever copied from the vendor canvas.
    assert report["reserved_bytes_copied"] == 0

    _, canvas = _decoded_canvas()
    raw = default_frame.build()
    named_mask = _named_mask(canvas)
    # Every reserved-column byte the scratch image emits must be attributable to
    # the named border table; the opaque reset-polarity fill stays zero.
    for word_line in default_frame.FRAMING_WORD_LINES:
        base = default_frame.BODY_START + default_frame.WORD_LINE_BYTES * word_line
        for column in default_frame.RESERVED_COLUMNS:
            offset = base + column
            if offset >= agasc.CRC_OFFSET:
                continue
            if canvas[offset] == 0xFF and not named_mask[offset]:
                assert raw[offset] == 0x00, offset
    # Any 0xFF byte the scratch image does contain is a fully-named byte, never
    # a copied reserved-fill byte.
    for offset in range(default_frame.BODY_START, agasc.CRC_OFFSET):
        if raw[offset] == 0xFF:
            assert named_mask[offset] == 0xFF, offset


def _named_mask(canvas):
    by_bit, _ = agasc.load_feature_map(str(CHIPDB))
    mask = bytearray(agasc.RAW_LEN)
    for (byte, m), _key in by_bit.items():
        if byte < agasc.CRC_OFFSET and (canvas[byte] & m):
            mask[byte] |= m
    return mask


def test_default_bitgen_base_image_is_unchanged():
    """Flag off (default): base_image decodes fabric_default.bin verbatim."""
    header, image = base_image(EngineOptions({}))
    canvas_header, canvas_raw = _decoded_canvas()
    assert header == canvas_header
    assert bytes(image) == canvas_raw


def test_opt_in_swaps_in_from_scratch_base():
    header, image = base_image(EngineOptions({"AGAMEMNON_FROM_SCRATCH_BASE": "1"}))
    assert header == default_frame.header()
    assert bytes(image) == default_frame.build()
    # It genuinely differs from the vendor canvas body (the gap is not filled).
    _, canvas_raw = _decoded_canvas()
    assert bytes(image) != canvas_raw
