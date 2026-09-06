import pytest

from agamemnon.engine.features.async_control_plan import (
    AsyncControl, GROUND, TileAsyncPlan, async_control_bit_plan,
    plan_module_async_controls, plan_tile_async_controls, write_async_control_plans,
)


@pytest.mark.parametrize('mode,bits', [(0, (3,)), (1, ()), (2, (2,)), (3, (2, 3))])
@pytest.mark.parametrize('index', [0, 1])
def test_controller_encoding(mode, bits, index):
    control = AsyncControl(mode, 42 if mode >= 2 else None)
    assert control.field_bits(index) == tuple(bit + index * 4 for bit in bits)


@pytest.mark.parametrize('mode,bits', [(0, (3,)), (1, ()), (2, (1,)), (3, (1, 3))])
@pytest.mark.parametrize('index', [0, 1])
def test_controller_alternate_ingress_encoding(mode, bits, index):
    control = AsyncControl(mode, 42 if mode >= 2 else None)
    expected = tuple(bit + index * 4 for bit in bits)
    assert control.field_bits(index, ctrlmux=2 * index) == expected
    controls = (None,) * index + (control,)
    plan = TileAsyncPlan(controls, ((0, index),), (None,) * index + (2 * index,))
    assert plan.field_value == sum(1 << bit for bit in expected)


def test_physical_plan_distinguishes_ingress_without_changing_slice_selector():
    control = AsyncControl(2, 42)
    a = async_control_bit_plan((15, 10), TileAsyncPlan((control,), ((0, 0),), (0,)))
    b = async_control_bit_plan((15, 10), TileAsyncPlan((control,), ((0, 0),), (1,)))
    assert a.keys() == b.keys()
    assert sum(a[key] != b[key] for key in a) == 2
    with pytest.raises(ValueError, match='unsupported async controller'):
        async_control_bit_plan((15, 10), TileAsyncPlan((control,), ((0, 0),), (3,)))
    with pytest.raises(ValueError, match='ingress count'):
        async_control_bit_plan((15, 10), TileAsyncPlan((control,), ((0, 0),), (0, 1)))


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


def test_physical_plan_includes_clears_and_only_allocated_slice_selectors():
    plan = plan_tile_async_controls({0: AsyncControl(2, 7), 3: GROUND})
    bits = async_control_bit_plan((14, 10), plan)
    assert len(bits) == 10  # Eight controller bits and two slice selectors.
    assert sum(bits.values()) == 3  # Din, grounded controller, and slice 3 index.
    assert async_control_bit_plan((14, 10), plan_tile_async_controls({})) == {}


def test_physical_plan_preserves_sparse_controller_one_assignment():
    plan = TileAsyncPlan((None, GROUND), ((3, 1),))
    assert plan.field_value == 0x80 and plan.slice_selector_value == 8
    bits = async_control_bit_plan((16, 10), plan)
    assert len(bits) == 9 and sum(bits.values()) == 2
    with pytest.raises(ValueError, match='absent controller'):
        async_control_bit_plan((16, 10), TileAsyncPlan((None, GROUND), ((3, 0),)))


def test_physical_mapping_covers_each_supported_tile_without_aliasing():
    import json
    from agamemnon.engine import default_frame
    anchors = json.loads((default_frame.CHIPDB_ROOT / 'logictile_asyncmux3.json').read_text())
    plan = plan_tile_async_controls({i: GROUND for i in range(16)})
    occupied = set()
    for name, anchor in anchors.items():
        tile = tuple(map(int, name.split(',')))
        bits = async_control_bit_plan(tile, plan)
        assert len(bits) == 24 and bits[tuple(anchor)]
        assert not occupied.intersection(bits)
        occupied.update(bits)


@pytest.mark.parametrize('tile', [(13, 4), (0, 0), (14, '10')])
def test_physical_plan_rejects_invalid_tile(tile):
    with pytest.raises(ValueError):
        async_control_bit_plan(tile, plan_tile_async_controls({0: GROUND}))


def test_physical_plan_rejects_forged_selector_and_duplicate_fields(monkeypatch):
    from agamemnon.engine import default_frame
    with pytest.raises(ValueError, match='absent controller'):
        async_control_bit_plan((14, 10), TileAsyncPlan((GROUND,), ((0, 1),)))
    cells, families = default_frame.load_logictile_template()
    cells = dict(cells)
    cells[(999, 0)] = 'CFG_TILEASYNCMUX[0]'
    monkeypatch.setattr(default_frame, 'load_logictile_template', lambda root: (cells, families))
    with pytest.raises(ValueError, match='duplicate asynchronous field'):
        async_control_bit_plan((14, 10), plan_tile_async_controls({0: GROUND}))


def test_writer_validates_later_tile_before_mutating_earlier_tile():
    from agamemnon.engine import default_frame
    image = bytearray([0xA5]) * default_frame.RAW_LEN
    original = bytes(image)
    plans = {(14, 10): plan_tile_async_controls({0: GROUND}),
             (99, 99): plan_tile_async_controls({0: GROUND})}
    with pytest.raises(ValueError, match='supported logic tile'):
        write_async_control_plans(image, plans)
    assert bytes(image) == original


def test_writer_preserves_unrelated_bits_header_and_checksum_region():
    from agamemnon.engine import default_frame
    image = bytearray([0xA5]) * default_frame.RAW_LEN
    original = bytes(image)
    plan = plan_tile_async_controls({0: AsyncControl(2, 7), 3: GROUND})
    bits = async_control_bit_plan((14, 10), plan)
    assert write_async_control_plans(image, {(14, 10): plan}) == len(bits)
    masks = {}
    for (offset, mask), value in bits.items():
        masks[offset] = masks.get(offset, 0) | mask
        assert bool(image[offset] & mask) == value
    assert all((before ^ after) & ~masks.get(i, 0) == 0
               for i, (before, after) in enumerate(zip(original, image)))
    assert image[:default_frame.BODY_START] == original[:default_frame.BODY_START]
    assert image[default_frame.CRC_OFFSET:] == original[default_frame.CRC_OFFSET:]
    with pytest.raises(ValueError, match='complete mutable'):
        write_async_control_plans(image[:-1], {(14, 10): plan})
