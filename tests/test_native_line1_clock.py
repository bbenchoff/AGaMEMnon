"""Clock companion fields for a validated native control line 1."""

from __future__ import annotations

from pathlib import Path

import pytest

from agamemnon.engine import control_encode
from agamemnon.engine.features.clock_validate import ClockValidationResult
from agamemnon.engine.features.clocks import FEATURE
from agamemnon.engine.registry import options_from


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
TILE = (14, 8)


def _validation(*, tiles=frozenset({TILE}), profile="MCU_BUS_DEFAULT_V1",
                source_class="MCU_BUS"):
    return ClockValidationResult(
        owner_bit=1,
        source_profile=profile,
        source_class=source_class,
        clocked_tiles=tiles,
        active_slice_leaves=frozenset({"X14Y8_ClkMUX03"}),
        bram_edges=frozenset(), quarantined_extra_leaves=frozenset(),
        quarantined_bitstream_sha256=None,
        catalog_sha256="0" * 64, topology_sha256="0" * 64,
    )


def _selectors():
    return {
        (14, 8, "CFG_SEAMMUX", 5): (5000, 1),
        (14, 8, "CFG_SEAMMUX", 11): (5001, 2),
    }


def _prepare(lines=None, *, validation=None, options=None, selectors=None):
    return FEATURE.prepare(
        {TILE}, [], [], _selectors() if selectors is None else selectors,
        CHIPDB, options_from({"AGAMEMNON_SYSCLK": "100", "AGAMEMNON_HSE": "8"})
        if options is None else options,
        _validation() if validation is None else validation,
        slice_lines=lines,
    )


def test_native_line1_emits_template_clock4_and_observed_seam11_only_for_its_tile():
    state = _prepare({(14, 8, 3): 1})
    assert control_encode.bit_position(14, 8, 35, 30) in state.sets
    assert (5001, 2) in state.sets
    assert (5000, 1) in state.sets       # ordinary line-0 tile clock seam


def test_native_line0_preserves_the_existing_clock_byte_sequence():
    baseline = _prepare()
    line0 = _prepare({(14, 8, 3): 0})
    assert line0.sets == baseline.sets
    assert control_encode.bit_position(14, 8, 35, 30) not in line0.sets
    assert (5001, 2) not in line0.sets


@pytest.mark.parametrize(
    "lines, validation, match",
    [
        ({(14, 8, 16): 1}, None, "invalid line"),
        ({(15, 8, 3): 1}, _validation(), "outside the validated GCLK0"),
        ({(14, 8, 2): 1}, None, "no validated GCLK0 active leaf"),
        ({(14, 8, 3): 1}, _validation(profile="HSE_PLL_CLKIN_V1",
                                       source_class="HSE_PLL"),
         "requires qualified GCLK0 profile"),
    ],
)
def test_native_line1_rejects_malformed_unowned_or_unqualified_consumers(
        lines, validation, match):
    with pytest.raises(SystemExit, match=match):
        _prepare(lines, validation=validation)


def test_native_line1_requires_both_declared_companion_fields():
    selectors = _selectors()
    del selectors[(14, 8, "CFG_SEAMMUX", 11)]
    with pytest.raises(SystemExit, match="CFG_SEAMMUX sel 11"):
        _prepare({(14, 8, 3): 1}, selectors=selectors)
