"""From-scratch design-neutral base-image generator (experimental, opt-in).

Verifies that ``default_frame`` reconstructs the expected fraction of the
decoded canvas from shipped data only, that the reserved routing/seam SRAM
region is a declared zeros gap (never copied from the vendor blob), and that
default bitgen is byte-for-byte unchanged (still decodes ``fabric_default.bin``).
"""
import struct
from pathlib import Path

import pytest

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
    # With the promoted LogicTile template driving the reserved-reset fill, the
    # body reconstructs to 99.77% byte-exact (was 71.15% before promotion).
    assert report["body_exact_fraction"] >= 0.997
    assert report["preamble_exact"] is True
    assert report["body_matched"] == 99541
    assert report["body_total"] == agasc.CRC_OFFSET - preamble.PREAMBLE_LENGTH
    fams = report["families"]
    # Regenerated-clean families are fully matched.
    assert fams["zero_default"] == {"total": 70168, "matched": 70168, "gap": 0}
    assert fams["border_named"] == {"total": 327, "matched": 327, "gap": 0}
    assert fams["framing_col58"] == {"total": 476, "matched": 476, "gap": 0}
    # The reserved routing/seam SRAM region is now emitted from the promoted
    # table -- every one of its 28,570 all-ones bytes matches the canvas.
    assert fams["reserved_sram_fill"] == {"total": 28570, "matched": 28570, "gap": 0}
    # Documented residual: partial border/region-edge bit-lines still needing a
    # per-bit decode (35 + 192 = 227 bytes), left at zero and never copied.
    residual = sum(
        fams[name]["gap"] for name in ("border_named_partial", "region_edge_partial")
    )
    assert residual == 227
    assert report["body_total"] - report["body_matched"] == residual


def test_reserved_region_is_emitted_from_table_not_vendor_copied(monkeypatch):
    _, canvas = _decoded_canvas()

    # build() must synthesize the reserved region without ever reading the vendor
    # canvas: force any canvas decode inside default_frame to fail.
    def _boom(*_args, **_kwargs):
        raise AssertionError("build() must not read the vendor canvas")
    monkeypatch.setattr(default_frame, "_decode_canvas", _boom)

    raw = default_frame.build()
    assert len(raw) == agasc.RAW_LEN

    # Every all-ones body byte the scratch image emits lands in a declared
    # reserved rectangle (or is a fully-named byte) -- never a stray copy.
    reserved = default_frame._reserved_offsets()
    _, by_feature = agasc.load_feature_map(str(CHIPDB))
    named = bytearray(agasc.RAW_LEN)
    for (x, y), feats in default_frame.BORDER_NAMED_CONFIG.items():
        for feat in feats:
            byte, mask = by_feature[(x, y, feat)]
            named[byte] |= mask
    for offset in range(default_frame.BODY_START, agasc.CRC_OFFSET):
        if raw[offset] == 0xFF:
            assert offset in reserved or named[offset] == 0xFF, offset

    # The fill is byte-exact vs the decoded canvas and paints only the declared
    # geometry (canvas passed explicitly so no canvas decode is triggered here).
    report = default_frame.diff_against_canvas(canvas_raw=canvas)
    assert report["ff_outside_reserved"] == 0
    assert report["reserved_fill_bytes"] == 28570
    assert report["families"]["reserved_sram_fill"]["gap"] == 0


def test_reserved_fill_is_bound_to_promoted_table(tmp_path):
    cells, families = default_frame.load_logictile_template()
    assert len(cells) == 2244
    for family in default_frame.RESERVED_SELECTOR_FAMILIES:
        assert family in families

    # Fail closed: a chipdb whose template does not decode the selector families
    # is rejected rather than emitting an unbacked reset fill.
    stub = tmp_path / "chipdb"
    stub.mkdir()
    (stub / default_frame.LOGICTILE_TEMPLATE).write_text(
        "netlist,B0\nW0,CFG_LUT[0]\n", encoding="utf-8"
    )
    with pytest.raises(agasc.AgascError):
        default_frame.reserved_reset_fill(bytearray(agasc.RAW_LEN), chipdb_root=stub)


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
