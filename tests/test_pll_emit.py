import pytest

from agamemnon.engine import pll_emit


# Vendor 100/8 divider bytes 144..150 -- the constant canvas for every sweep point (only these seven
# preamble bytes vary with (SYSCLK,HSE)).
BASELINE_144_150 = "fd010052490000"

# The 53-point AG32-Docs vendor PLL sweep (tools/pll_sweep_20260812), decoded preamble bytes 144..150.
# The closed-form emitter must reproduce every one byte-exact; this is the promoted RE result, embedded
# so the regression is self-contained (no vendor file dependency).
SWEEP_144_150 = {
    (100, 8): "fd010052490000", (50, 8): "fc804052490000", (25, 8): "fd40a052490000",
    (10, 8): "fce07052490000", (60, 8): "fc818052490000", (100, 16): "fd010052491008",
    (100, 12): "fd010052491010", (4, 8): "fd492452490000", (5, 8): "fd70b852490000",
    (6, 8): "fc301852490000", (8, 8): "fc904852290000", (12, 8): "fc61d052490000",
    (14, 8): "fca05032690000", (15, 8): "fd209052490000", (16, 8): "fd211052290000",
    (20, 8): "fdc16052490000", (24, 8): "fcc1a032190000", (30, 8): "fc402052490000",
    (32, 8): "fc402072390000", (36, 8): "fc41c00a790000", (40, 8): "fd80c072390000",
    (45, 8): "fd80c01a0d0000", (48, 8): "fd81404a250000", (55, 8): "fd80c0361b0000",
    (64, 8): "fc818072390000", (70, 8): "fc804016730000", (72, 8): "fc81801a0d0000",
    (75, 8): "fd008052490000", (80, 8): "fd008072390000", (84, 8): "fd00804a250000",
    (90, 8): "fd00801a0d0000", (96, 8): "fd00807a3d0000", (110, 8): "fd0080361b0000",
    (120, 8): "fd01001a0d0000", (125, 8): "fd00803e6f0000", (133, 8): "fd008021608000",
    (140, 8): "fd010016730000", (150, 8): "fc000052490000", (160, 8): "fc000072390000",
    (168, 8): "fc00004a250000", (180, 8): "fc00001a0d0000", (200, 8): "fc000046230000",
    (220, 8): "fc0000361b0000", (240, 8): "fc00006e370000", (248, 8): "fc00005e2f0000",
    (72, 12): "fc81801a0d1010", (48, 16): "fd81404a251008", (64, 16): "fc818072391008",
    (80, 16): "fd008072391008", (50, 25): "fc804062310804", (100, 25): "fd010062310804",
    (75, 24): "fd008052490804", (48, 12): "fd81404a251010",
}


def test_closed_form_reproduces_every_vendor_sweep_divider_encoding():
    # One closed-form equation (no per-ratio byte table) must reproduce all 53 vendor sweep points
    # byte-exact on the only bytes that vary. This is the ungated encoding, exercised over every point
    # including the byte-exact-but-unqualified HSE!=8 ones.
    assert len(SWEEP_144_150) == 53
    base = bytes.fromhex(BASELINE_144_150)
    for (sysclk, hse), expected in SWEEP_144_150.items():
        raw = bytearray(200)
        raw[144:151] = base
        fields, _ = pll_emit.divider_fields(sysclk, hse)
        assert pll_emit.apply_fields(raw, fields) == []
        assert raw[144:151].hex() == expected, (sysclk, hse, raw[144:151].hex(), expected)
    # every shipped profile is one of the sweep points (and therefore covered above)
    for ratio in pll_emit.PROFILE_RATIOS:
        assert ratio in SWEEP_144_150


def test_supported_ratios_are_explicit_and_fully_representable():
    expected = set(pll_emit.PROFILE_RATIOS) | {(sysclk, 8) for sysclk in pll_emit.SILICON_QUALIFIED_HSE8}
    assert set(pll_emit.SUPPORTED_RATIOS) == expected
    assert len(pll_emit.SUPPORTED_RATIOS) == 45

    # HSE=8 is the silicon-qualified surface (38 sweep rates + the 5 HSE=8 profiles); the only HSE!=8
    # members are the two preamble-only profiles.
    assert {ratio for ratio in pll_emit.SUPPORTED_RATIOS if ratio[1] != 8} == {(100, 16), (100, 12)}
    assert set(pll_emit.PROFILE_RATIOS).isdisjoint({(s, 8) for s in pll_emit.SILICON_QUALIFIED_HSE8})

    # Every supported ratio is a complete, representable overlay onto the shipped 100/8 baseline.
    for sysclk, hse in pll_emit.SUPPORTED_RATIOS:
        raw = bytearray(pll_emit.RAWLEN)
        raw[144:151] = bytes.fromhex(BASELINE_144_150)
        assert pll_emit.apply_ratio(raw, sysclk, hse) == []
        assert raw[144:151].hex() == SWEEP_144_150[(sysclk, hse)]

    # (10,8) divider 30 is reproduced by the general encoding: the retired per-ratio byte override
    # ({144:0xFC, 145:0xE0, 146:0x70}) is subsumed exactly.
    raw = bytearray(pll_emit.RAWLEN)
    raw[144:151] = bytes.fromhex(BASELINE_144_150)
    pll_emit.apply_ratio(raw, 10, 8)
    assert {offset: raw[offset] for offset in (144, 145, 146)} == {144: 0xFC, 145: 0xE0, 146: 0x70}


def test_75_8_is_promoted_from_rejected_to_silicon_qualified():
    # 75/8 was previously fail-closed (it only *calculated*); it is now silicon-qualified and must emit
    # its vendor-exact divider bytes.
    assert (75, 8) in pll_emit.SUPPORTED_RATIOS
    fields, _ = pll_emit.emit_fields(75, 8)
    raw = bytearray(200)
    raw[144:151] = bytes.fromhex(BASELINE_144_150)
    pll_emit.apply_fields(raw, fields)
    assert raw[144:151].hex() == SWEEP_144_150[(75, 8)]


@pytest.mark.parametrize("sysclk,hse", [
    (35, 8),    # HSE=8 rate check_pll solves but which has no silicon/oracle record
    (72, 12),   # HSE!=8 byte-exact sweep point -- byte-exactness is NOT sufficient for admission
    (50, 25),   # HSE!=8 byte-exact sweep point
])
def test_rejects_unvalidated_ratio_even_when_encoding_would_fit(sysclk, hse):
    # check_pll can solve it (so the divider fields would fit), yet emission stays fail-closed.
    assert pll_emit.check_pll(sysclk, hse)["clkout_div"][0] > 0
    with pytest.raises(pll_emit.UnsupportedPLLConfiguration) as excinfo:
        pll_emit.emit_fields(sysclk, hse)
    message = str(excinfo.value)
    assert "unsupported PLL ratio SYSCLK/HSE=%d/%d MHz" % (sysclk, hse) in message
    assert "100/8" in message
    assert "50/8" in message


def test_matched_controls_disentangle_output_input_and_feedback_divider_fields():
    assert pll_emit.MAP["CLKOUT0_HIGH"] == [(146, 7), (146, 6), (146, 5), (146, 4), (146, 3), (146, 2)]
    assert pll_emit.MAP["CLKOUT0_LOW"] == [(144, 0), (145, 7), (145, 6), (145, 5), (145, 4), (145, 3)]
    assert pll_emit.MAP["CLKFB_HIGH"] == [(148, 5), (148, 4), (148, 3), (148, 2), (148, 1), (148, 0), (149, 7)]
    assert pll_emit.MAP["CLKFB_LOW"] == [(147, 6), (147, 5), (147, 4), (147, 3), (147, 2), (147, 1), (147, 0)]
    assert pll_emit.MAP["CLKIN_HIGH"] == [(150, 3), (150, 2)]
    assert pll_emit.MAP["CLKIN_LOW"] == [(149, 4), (149, 3)]
    assert pll_emit.MAP["CLKIN_TRIM"] == [(150, 4)]

    raw_60_8 = bytearray(pll_emit.RAWLEN)
    raw_60_8[144:151] = bytes.fromhex(BASELINE_144_150)
    pll_emit.apply_ratio(raw_60_8, 60, 8)
    assert bytes(raw_60_8[144:151]) == bytes.fromhex("fc818052490000")

    # a fast rate exercises the CLKFB high bit that spills into byte 149
    raw_133_8 = bytearray(pll_emit.RAWLEN)
    raw_133_8[144:151] = bytes.fromhex(BASELINE_144_150)
    pll_emit.apply_ratio(raw_133_8, 133, 8)
    assert bytes(raw_133_8[144:151]) == bytes.fromhex("fd008021608000")

    raw_100_12 = bytearray(pll_emit.RAWLEN)
    raw_100_12[144:151] = bytes.fromhex(BASELINE_144_150)
    pll_emit.apply_ratio(raw_100_12, 100, 12)
    assert bytes(raw_100_12[144:151]) == bytes.fromhex("fd010052491010")


@pytest.mark.parametrize("edit", [
    lambda fields: fields.__setitem__("CLKOUT0_HIGH", 64),   # exceeds the 6-bit CLKOUT0 DIVH field
    lambda fields: fields.pop("CLKIN_LOW"),
])
def test_field_overlay_fails_atomically_when_encoding_is_incomplete(edit):
    fields, _ = pll_emit.emit_fields(100, 8)
    edit(fields)
    raw = bytearray([0xA5]) * pll_emit.RAWLEN
    before = bytes(raw)

    with pytest.raises(pll_emit.UnsupportedPLLConfiguration, match="incomplete PLL encoding"):
        pll_emit.apply_fields(raw, fields)

    assert bytes(raw) == before


def test_emit_bin_rejects_before_reading_baseline_or_creating_output(tmp_path):
    output = tmp_path / "unsupported.bin"
    with pytest.raises(pll_emit.UnsupportedPLLConfiguration):
        pll_emit.emit_bin(35, 8, output, baseline="missing-baseline.bin")
    assert not output.exists()
