import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "qualification" / "random_rtl_campaign.py"
SPEC = importlib.util.spec_from_file_location("random_rtl_campaign", SCRIPT)
CAMPAIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMPAIGN)


@pytest.mark.parametrize("mode", ["lfsr", "xorshift", "mixed"])
def test_generated_random_rtl_is_deterministic_and_observable(mode):
    first = CAMPAIGN.generate(7, 16, mode)
    assert first == CAMPAIGN.generate(7, 16, mode)
    assert first != CAMPAIGN.generate(8, 16, mode)
    assert "module top(input clk);" in first
    assert "MCU_DOUT mcu_h0" in first and "MCU_DOUT mcu_h1" in first
    assert "always @(posedge clk) state <= next_state;" in first


def test_seed_range_parser_and_input_validation():
    assert CAMPAIGN._parse_range("1,3:6,0xa") == [1, 3, 4, 5, 10]
    with pytest.raises(ValueError, match="width"):
        CAMPAIGN.generate(0, 3, "lfsr")
    with pytest.raises(ValueError, match="mode"):
        CAMPAIGN.generate(0, 8, "unknown")


def test_ahb_step_variant_uses_fixed_lane_names_and_gated_state_update():
    source = CAMPAIGN.generate_ahb_step(3, 32, "mixed")
    assert "MCU_DIN mcu_hwdata0" in source
    assert "MCU_DIN mcu_hwrite" in source
    assert "MCU_DIN mcu_htrans1" in source
    assert "wr_ph <= hwrite & htrans1;" in source
    assert "if (wr_ph) state <= next_state;" in source


def test_uarch_switches_to_scalable_regional_placement_above_tiny_designs():
    source = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8")
    assert 'cells.size() > 16 || std::getenv("AGRV2K_CONDPLACE_REGIONAL")' in source
    assert 'std::getenv("AGRV2K_CONDPLACE_EXACT")' in source
    assert '(unsigned(a) ^ cond_seed) * 2654435761u' in source
