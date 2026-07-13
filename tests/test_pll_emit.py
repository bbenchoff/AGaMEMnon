import pytest

from agamemnon.engine import pll_emit


def test_supported_ratios_are_explicit_and_fully_representable():
    assert set(pll_emit.SUPPORTED_RATIOS) == {
        (100, 8),
        (25, 8),
        (100, 16),
        (50, 8),
    }

    for sysclk, hse in pll_emit.SUPPORTED_RATIOS:
        fields, _ = pll_emit.emit_fields(sysclk, hse)
        raw = bytearray(pll_emit.RAWLEN)
        assert pll_emit.apply_fields(raw, fields) == []


def test_rejects_unvalidated_ratio_even_when_current_fields_would_fit():
    # 75/8 produces small divider values, so the old implementation silently overlaid them.
    # It has no byte-exact oracle and must not be promoted merely because those values fit MAP.
    with pytest.raises(pll_emit.UnsupportedPLLConfiguration) as excinfo:
        pll_emit.emit_fields(75, 8)

    message = str(excinfo.value)
    assert "unsupported PLL ratio SYSCLK/HSE=75/8 MHz" in message
    assert "100/8" in message
    assert "50/8" in message


@pytest.mark.parametrize("edit", [
    lambda fields: fields.__setitem__("CLKOUT0_HIGH", 8),
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
        pll_emit.emit_bin(75, 8, output, baseline="missing-baseline.bin")
    assert not output.exists()
