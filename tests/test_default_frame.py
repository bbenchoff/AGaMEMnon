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


def test_generator_reaches_full_byte_exact_body():
    report = default_frame.diff_against_canvas()
    # With the promoted LogicTile template (reserved-reset fill) AND the promoted
    # border/edge partial-cell table, the whole config body reconstructs 100%
    # byte-exact (was 99.77% before the border/edge phase, 71.15% before either).
    assert report["body_exact_fraction"] == 1.0
    assert report["preamble_exact"] is True
    assert report["body_matched"] == 99768
    assert report["body_total"] == agasc.CRC_OFFSET - preamble.PREAMBLE_LENGTH
    assert report["ff_outside_reserved"] == 0
    fams = report["families"]
    # Regenerated-clean families are fully matched.
    assert fams["zero_default"] == {"total": 70168, "matched": 70168, "gap": 0}
    assert fams["border_named"] == {"total": 327, "matched": 327, "gap": 0}
    assert fams["framing_col58"] == {"total": 476, "matched": 476, "gap": 0}
    # The reserved routing/seam SRAM region is emitted from the promoted template.
    assert fams["reserved_sram_fill"] == {"total": 28570, "matched": 28570, "gap": 0}
    # The former residual (35 border-named + 192 region-edge partial bytes) is now
    # emitted from the promoted border/edge partial-cell table -- zero gap.
    assert fams["border_named_partial"] == {"total": 35, "matched": 35, "gap": 0}
    assert fams["region_edge_partial"] == {"total": 192, "matched": 192, "gap": 0}
    assert report["body_total"] - report["body_matched"] == 0


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
    # The from-scratch image is byte-identical to the decoded canvas across the
    # preamble + full config body [0:99932]; it differs ONLY in the trailing
    # 4-byte CRC, which we recompute to a VALID value (the vendor canvas ships a
    # stale CRC).  Byte-exact vs the decoded canvas is a STATIC result, not a
    # silicon boot proof -- see docs/FABRIC_DEFAULT_CANVAS.md.
    _, canvas_raw = _decoded_canvas()
    assert bytes(image[:agasc.CRC_OFFSET]) == bytes(canvas_raw[:agasc.CRC_OFFSET])
    differing = [i for i in range(agasc.RAW_LEN) if image[i] != canvas_raw[i]]
    assert differing == list(range(agasc.CRC_OFFSET, agasc.RAW_LEN))
    stored = struct.unpack(">I", bytes(image[agasc.CRC_OFFSET:]))[0]
    assert stored == agasc.crc32_bzip2(
        default_frame.header() + bytes(image[:agasc.CRC_OFFSET])
    )


def test_border_edge_fill_is_transform_and_template_bound(tmp_path):
    rows = default_frame.load_border_edge_cells()
    assert len(rows) == 423
    named = [r for r in rows if r["resource"]]
    spare = [r for r in rows if not r["resource"]]
    assert len(named) == 408
    assert len(spare) == 15
    # Every named cell resolves through the validated geometry transform to its
    # recorded (raw_off, bit) and matches the promoted LogicTile template.
    cells, _ = default_frame.load_logictile_template()
    for r in named:
        offset, bit = default_frame._cell_to_offset_bit(
            int(r["x"]), int(r["y"]), int(r["word_row"]), int(r["bank_col"])
        )
        assert (offset, bit) == (int(r["raw_off"]), int(r["bit"]))
        assert cells[(int(r["word_row"]), int(r["bank_col"]))] == r["resource"]
    # Every spare bit lands on a template-blank cell (position known, meaning
    # unproven): bank_col 33, word_rows 9/57.
    for r in spare:
        assert (int(r["word_row"]), int(r["bank_col"])) not in cells
        assert int(r["bank_col"]) == 33 and int(r["word_row"]) in (9, 57)

    # Fail closed: a row whose transform disagrees with its recorded offset is
    # rejected rather than emitting an unbacked bit.
    stub = tmp_path / "chipdb"
    stub.mkdir()
    (stub / default_frame.LOGICTILE_TEMPLATE).write_text(
        (CHIPDB / default_frame.LOGICTILE_TEMPLATE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (stub / default_frame.BORDER_EDGE_TABLE).write_text(
        "x,y,word_row,bank_col,bit,resource,raw_off,note\n"
        "21,13,46,0,4,CFG_RMUX9[17],999,bogus offset\n",
        encoding="utf-8",
    )
    with pytest.raises(agasc.AgascError):
        default_frame.border_edge_fill(bytearray(agasc.RAW_LEN), chipdb_root=stub)
