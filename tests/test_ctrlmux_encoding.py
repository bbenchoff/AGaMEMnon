import pytest

from agamemnon.engine.features.ctrlmux_encoding import ctrlmux_source_bits, ctrlmux_input_bit_plan


@pytest.mark.parametrize('mux,source,dx,bits', [
    (0, 40, 0, (6, 10)), (0, 36, 1, (3, 9)),
    (0, 70, 0, (3, 11)), (0, 94, 0, (7, 11)),
    (1, 11, 0, (13, 22)), (1, 42, 1, (15, 21)),
    (1, 59, 0, (13, 23)), (1, 95, 0, (19, 23)),
    (2, 0, 1, (24, 33)), (3, 66, 1, (41, 45)),
    (3, 71, 0, (39, 47)),
])
def test_source_geometry_observations(mux, source, dx, bits):
    assert ctrlmux_source_bits(mux, source, dx) == bits


def test_all_supported_inputs_are_injective_and_mux_fields_are_disjoint():
    fields = []
    for mux in range(4):
        choices = []
        for dx in (0, 1):
            for source in range(96):
                try:
                    choices.append(ctrlmux_source_bits(mux, source, dx))
                except ValueError:
                    pass
        assert len(choices) == len(set(choices)) == 24
        bits = {bit for choice in choices for bit in choice}
        assert all(12 * mux <= bit < 12 * (mux + 1) for bit in bits)
        assert all(not bits.intersection(other) for other in fields)
        fields.append(bits)


@pytest.mark.parametrize('args', [
    (4, 40), (0, 96), (0, -1), (True, 40), (0, 40, True),
    (0, 40, 0, 1), (0, 40, -1), (0, 40, 2),
    (0, 41), (1, 40), (0, 6, 1), (1, 0, 1),
])
def test_unsupported_geometry_is_not_encoded(args):
    with pytest.raises(ValueError):
        ctrlmux_source_bits(*args)


def test_physical_plan_owns_only_selected_muxes_and_excludes_controller_mode():
    from agamemnon.engine.features.async_control_plan import (
        AsyncControl, TileAsyncPlan, async_control_bit_plan,
    )
    tile = (14, 10)
    a = ctrlmux_input_bit_plan(tile, {0: (15, 10, 48)})
    b = ctrlmux_input_bit_plan(tile, {1: (14, 10, 53)})
    combined = ctrlmux_input_bit_plan(tile, {0: (15, 10, 48), 1: (14, 10, 53)})
    controller = async_control_bit_plan(tile, TileAsyncPlan((AsyncControl(2, 7),), ((0, 0),)))
    assert len(a) == len(b) == 12 and sum(a.values()) == sum(b.values()) == 2
    assert not a.keys() & b.keys()
    assert combined == {**a, **b}
    assert not combined.keys() & controller.keys()
    assert ctrlmux_input_bit_plan(tile, {}) == {}


@pytest.mark.parametrize('tile,inputs', [
    ((13, 4), {0: (14, 4, 0)}), ((14, 10), {0: (13, 4, 0)}),
    ((True, 10), {}), ((14, 10), {0: (14, 10, True)}),
    ((14, 10), {0: (14, 10, 95)}),
])
def test_physical_plan_rejects_wrong_tile_or_source(tile, inputs):
    with pytest.raises(ValueError):
        ctrlmux_input_bit_plan(tile, inputs)
