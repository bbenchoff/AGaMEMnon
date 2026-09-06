"""Routed controller ownership, ingress selection and configuration negatives."""
from copy import deepcopy
import pytest

from agamemnon.engine.features.async_control_plan import AsyncControl, GROUND
from agamemnon.engine.features.async_control_routes import plan_routed_async_controls


def _binary(value):
    return format(value, '032b')


def _route(root, edges):
    fields = [root, '', '1']
    for source, destination in edges:
        fields.extend([destination, source + '.' + destination, '5'])
    return ';'.join(fields)


def _module(slot=0, mux=0, sx=14, rmux=4):
    ctrl = 'X14Y8_CtrlMUX%02d' % mux
    incoming = 'X14Y8_TileAsyncMUX%02d' % slot
    root = 'X14Y8_alta_asyncctrl%02d' % slot
    source = 'X%dY8_RMUX%02d' % (sx, rmux)
    return {'cells': {
        'source': {'type': 'GENERIC_SLICE', 'parameters': {'FF_USED': _binary(0)},
                   'attributes': {'NEXTPNR_BEL': 'X14Y8_SLICE3'},
                   'connections': {'F': [7]}, 'port_directions': {'F': 'output'}},
        'controller': {'type': 'AGRV2K_ASYNCCTRL', 'parameters': {'MODE': _binary(2)},
                       'attributes': {'NEXTPNR_BEL': 'X14Y8_ASYNCCTRL%d' % slot},
                       'connections': {'DIN': [7], 'DOUT': [40]},
                       'port_directions': {'DIN': 'input', 'DOUT': 'output'}},
        'state': {'type': 'GENERIC_SLICE', 'parameters': {'FF_USED': _binary(1)},
                  'attributes': {'NEXTPNR_BEL': 'X14Y8_SLICE0',
                                 'AGRV2K_SHARED_CONTROL_MODE': 'ASYNC_CLEAR_POS_ZERO',
                                 'AGRV2K_ASYNC_CONTROLLER_INDEX': _binary(slot)},
                  'connections': {'ARST': [40]}, 'port_directions': {'ARST': 'input'}},
    }, 'netnames': {
        'input': {'bits': [7], 'attributes': {'ROUTING': _route('X14Y8_alta_slice03', [
            ('X14Y8_alta_slice03', source), (source, ctrl), (ctrl, incoming)])}},
        'output': {'bits': [40], 'attributes': {'ROUTING': _route(root, [(root, 'X14Y8_AsyncMUX00')])}},
    }}


@pytest.mark.parametrize('slot,mux,sx,rmux', [(0, 0, 14, 4), (0, 1, 14, 5),
                                           (1, 2, 15, 0), (1, 3, 15, 6)])
def test_routed_selection_preserves_allocated_slot_and_original_din(slot, mux, sx, rmux):
    module = _module(slot, mux, sx, rmux)
    original = deepcopy(module)
    result = plan_routed_async_controls(module)
    tile = result.tiles[14, 8]
    assert tile.controls[slot] == AsyncControl(2, 7)  # DIN, never DOUT bit 40
    assert tile.ctrlmuxes[slot] == mux
    assert tile.selections == ((0, slot),)
    assert result.ctrlmux_inputs == {(14, 8): {mux: (sx, 8, rmux)}}
    assert len(result.writes) == 21  # 8 controller, 1 slice, 12 input selector bits
    assert module == original


def test_inactive_register_reserves_ground_and_shared_reset_fans_out():
    module = _module()
    cells = module['cells']
    cells['ground'] = deepcopy(cells['controller'])
    cells['ground']['attributes']['NEXTPNR_BEL'] = 'X14Y8_ASYNCCTRL1'
    cells['ground']['parameters']['MODE'] = _binary(0)
    cells['ground']['connections'] = {'DIN': [], 'DOUT': [41]}
    cells['idle'] = {'type': 'GENERIC_SLICE', 'parameters': {'FF_USED': _binary(1)},
                     'attributes': {'NEXTPNR_BEL': 'X14Y8_SLICE1',
                                    'AGRV2K_ASYNC_CONTROLLER_INDEX': _binary(1)},
                     'connections': {}, 'port_directions': {}}
    cells['second'] = deepcopy(cells['state'])
    cells['second']['attributes']['NEXTPNR_BEL'] = 'X14Y8_SLICE2'
    module['netnames']['output']['attributes']['ROUTING'] += ';X14Y8_AsyncMUX02;X14Y8_alta_asyncctrl00.X14Y8_AsyncMUX02;5'
    result = plan_routed_async_controls(module)
    assert result.tiles[14, 8].controls == (AsyncControl(2, 7), GROUND)
    assert result.tiles[14, 8].selections == ((0, 0), (1, 1), (2, 0))
    cells['idle']['attributes']['AGRV2K_ASYNC_CONTROLLER_INDEX'] = _binary(0)
    with pytest.raises(ValueError, match='inactive register requires'):
        plan_routed_async_controls(module)


@pytest.mark.parametrize('fault,reason', [
    ('bypass', 'separate'), ('wrong_slot', 'another controller'),
    ('wrong_bank', 'lane'), ('foreign_leaf', 'local ARST'),
    ('missing_leaf', 'local ARST'), ('foreign_consumer', 'foreign consumers'),
    ('extra_driver', 'another driver'), ('unrouted', 'routed ingress'),
    ('alias', 'aliases disagree'), ('empty_alias', 'aliases disagree'),
    ('constant_alias', 'integer signal'),
    ('cycle', 'disconnected or cyclic'), ('bad_triple', 'triples'),
    ('duplicate', 'multiple route records'), ('orphan', 'orphan'),
    ('mode', 'unsupported'), ('missing_index', 'controller index'),
    ('wrong_index', 'absent controller'), ('unplaced', 'placed'),
])
def test_rejects_forged_or_incomplete_async_composition(fault, reason):
    module = _module()
    cells, nets = module['cells'], module['netnames']
    if fault == 'bypass': cells['controller']['connections']['DIN'] = [40]
    elif fault == 'wrong_slot': nets['input']['attributes']['ROUTING'] = nets['input']['attributes']['ROUTING'].replace('CtrlMUX00', 'CtrlMUX02')
    elif fault == 'wrong_bank': nets['input']['attributes']['ROUTING'] = nets['input']['attributes']['ROUTING'].replace('RMUX04', 'RMUX05')
    elif fault == 'foreign_leaf': nets['output']['attributes']['ROUTING'] = nets['output']['attributes']['ROUTING'].replace('AsyncMUX00', 'AsyncMUX01')
    elif fault == 'missing_leaf': nets['output']['attributes']['ROUTING'] = 'X14Y8_alta_asyncctrl00;;1'
    elif fault == 'foreign_consumer': cells['other'] = {'type': 'OTHER', 'connections': {'I': [40]}, 'port_directions': {'I': 'input'}}
    elif fault == 'extra_driver': cells['source']['connections']['F'] = [40]
    elif fault == 'unrouted': nets['input']['attributes'].clear()
    elif fault == 'alias': nets['alias'] = {'bits': [7], 'attributes': {'ROUTING': 'X14Y8_RMUX04;;1'}}
    elif fault == 'empty_alias': nets['alias'] = {'bits': [7], 'attributes': {'ROUTING': ''}}
    elif fault == 'constant_alias': nets['input']['bits'] = ['0']
    elif fault == 'cycle': nets['input']['attributes']['ROUTING'] = nets['input']['attributes']['ROUTING'].replace('X14Y8_alta_slice03.X14Y8_RMUX04', 'X14Y8_CtrlMUX00.X14Y8_RMUX04')
    elif fault == 'bad_triple': nets['input']['attributes']['ROUTING'] += ';garbage'
    elif fault == 'duplicate': nets['input']['attributes']['ROUTING'] += ';X14Y8_RMUX04;;1'
    elif fault == 'orphan': nets['extra'] = {'bits': [81], 'attributes': {'ROUTING': 'X15Y8_alta_asyncctrl00;;1'}}
    elif fault == 'mode': cells['controller']['parameters']['MODE'] = _binary(3)
    elif fault == 'missing_index': del cells['state']['attributes']['AGRV2K_ASYNC_CONTROLLER_INDEX']
    elif fault == 'wrong_index': cells['state']['attributes']['AGRV2K_ASYNC_CONTROLLER_INDEX'] = _binary(1)
    elif fault == 'unplaced': cells['controller']['attributes'].clear()
    original = deepcopy(module)
    with pytest.raises(ValueError, match=reason):
        plan_routed_async_controls(module)
    assert module == original


def test_clock_and_reset_share_ctrlmux_only_on_the_same_signal():
    module = _module()
    route = module['netnames']['input']['attributes']['ROUTING']
    route += ';X14Y8_TileClkMUX00;X14Y8_CtrlMUX00.X14Y8_TileClkMUX00;5'
    module['netnames']['input']['attributes']['ROUTING'] = route
    assert plan_routed_async_controls(module).writes
    module['netnames']['clock'] = {'bits': [90], 'attributes': {'ROUTING': _route('X14Y8_RMUX10', [
        ('X14Y8_RMUX10', 'X14Y8_CtrlMUX00'), ('X14Y8_CtrlMUX00', 'X14Y8_TileClkMUX01')])}}
    with pytest.raises(ValueError, match='different signals own routed wire'):
        plan_routed_async_controls(module)
