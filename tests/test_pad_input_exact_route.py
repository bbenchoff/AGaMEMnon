"""An exact first-hop selector must still activate its physical input pad."""
from types import SimpleNamespace

import pytest

from agamemnon.engine.features.physical_io import PhysicalIoState
from agamemnon.engine.features.routing import FEATURE
from agamemnon.engine.registry import options_from


def resolve(physical):
    source = (18, 13, "InputMUX", 7)
    destination = (18, 9, "RMUX", 56)
    return FEATURE.prepare(
        pips=["X18Y13_InputMUX07.X18Y9_RMUX56"],
        cell={(18, 9, "CFG_RMUX9", 26): (300, 1),
              (18, 9, "CFG_RMUX9", 29): (301, 2)},
        options=options_from({"AGAMEMNON_PHYSICAL_IO": "1"}),
        tables=SimpleNamespace(admission_binding={}, admitted_edge={}),
        physical_io_state=physical,
        exact_mcu_pips={source + destination: ("logic", "CFG_RMUX9", (), (26, 29))},
        mcu_cells={}, mcu_exit_pairs={},
        bram_feature=SimpleNamespace(resolve_route=lambda *args, **kwargs: None),
        bram_state=SimpleNamespace(), slice_config={}, left_vendor_slices=set(),
    )


def test_exact_first_hop_keeps_selector_and_pad_enable_codewords():
    physical = PhysicalIoState()
    key = (18, 13, 7, 18, 9, 56)
    physical.pad_input_edge[key] = ("CFG_RMUX9", [26, 29], [(92, 64)], [])
    state = resolve(physical)
    assert (state.mapped, state.unmapped) == (1, 0)
    assert state.sets == [(300, 1), (301, 2)]
    assert physical.pad_input_used == {(key, ((92, 64),), ())}


def test_exact_selector_cannot_bypass_missing_pad_activation_metadata():
    with pytest.raises(SystemExit, match="perimeter pad-input route has no silicon-verified encoding"):
        resolve(PhysicalIoState())
