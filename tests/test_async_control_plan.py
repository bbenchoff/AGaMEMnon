import pytest

from agamemnon.engine.features.async_control_plan import (
    AsyncControl, GROUND, plan_module_async_controls, plan_tile_async_controls,
)


@pytest.mark.parametrize('mode,bits', [(0, (3,)), (1, ()), (2, (2,)), (3, (2, 3))])
@pytest.mark.parametrize('index', [0, 1])
def test_controller_encoding(mode, bits, index):
    control = AsyncControl(mode, 42 if mode >= 2 else None)
    assert control.field_bits(index) == tuple(bit + index * 4 for bit in bits)


def test_inactive_registers_consume_a_grounded_controller():
    plan = plan_tile_async_controls({0: AsyncControl(2, 7), 5: GROUND, 9: AsyncControl(2, 7)})
    assert plan.controls == (AsyncControl(2, 7), GROUND)
    assert plan.selections == ((0, 0), (5, 1), (9, 0))
    assert plan.field_value == 0x84
    assert plan.slice_selector_value == 1 << 5


def test_two_sources_fit_but_not_with_an_inactive_register():
    controls = {0: AsyncControl(2, 7), 1: AsyncControl(2, 8)}
    assert plan_tile_async_controls(controls).field_value == 0x44
    with pytest.raises(ValueError, match='including inactive registers'):
        plan_tile_async_controls({**controls, 2: GROUND})


def test_opposite_polarities_are_distinct_and_order_is_stable():
    controls = {2: AsyncControl(3, 7), 0: AsyncControl(2, 7)}
    a = plan_tile_async_controls(controls)
    b = plan_tile_async_controls(dict(reversed(list(controls.items()))))
    assert a == b and len(a.controls) == 2


def test_ground_only_preserves_controller_zero():
    plan = plan_tile_async_controls({i: GROUND for i in range(16)})
    assert plan.field_value == 8 and plan.slice_selector_value == 0
    assert plan_tile_async_controls({}).field_value == 0


@pytest.mark.parametrize('mode,source', [(2, None), (3, None), (0, 7), (1, 7),
                                       (2, True), (2, -1), (4, None), (True, None)])
def test_invalid_control_rejected(mode, source):
    with pytest.raises(ValueError):
        AsyncControl(mode, source)


def register(z, source=None):
    attrs = {'NEXTPNR_BEL': 'X14Y10_SLICE%d' % z}
    connections = {'Q': [100 + z]}
    if source is not None:
        attrs['AGRV2K_SHARED_CONTROL_MODE'] = 'ASYNC_CLEAR_POS_ZERO'
        connections['ARST'] = [source]
    return dict(type='GENERIC_SLICE', parameters={'FF_USED': '1'},
                attributes=attrs, connections=connections)


def test_module_planning_keeps_ground_and_shared_source():
    module = {'cells': {'a': register(0, 7), 'b': register(1, 7), 'c': register(2)}}
    plan = plan_module_async_controls(module)[(14, 10)]
    assert plan.controls == (AsyncControl(2, 7), GROUND)
    assert plan.selections == ((0, 0), (1, 0), (2, 1))


def test_module_rejects_three_control_classes():
    module = {'cells': {'a': register(0, 7), 'b': register(1, 8), 'c': register(2)},
              'netnames': {'a': {'bits': [7]}, 'b': {'bits': [8]}}}
    with pytest.raises(ValueError, match='capacity is 2'):
        plan_module_async_controls(module)


def test_module_rejects_duplicate_placement():
    with pytest.raises(ValueError, match='same async slice'):
        plan_module_async_controls({'cells': {'a': register(0), 'b': register(0)}})

