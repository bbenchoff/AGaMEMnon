"""Strict pad-input admission requires a physically bound typed controller."""
import pytest
from test_native_endpoint_legality import _identity_design, CHIPDB
from agamemnon.engine.features.native_endpoint import validate_module_native_endpoints


def _module():
    module = _identity_design()['modules']['top']
    del module['cells']['fabric']
    module['cells']['controller'] = {
        'type': 'AGRV2K_ASYNCCTRL', 'parameters': {'MODE': format(2, '032b')},
        'attributes': {'NEXTPNR_BEL': 'X14Y8_ASYNCCTRL0'},
        'port_directions': {'DIN': 'input', 'DOUT': 'output'},
        'connections': {'DIN': [3], 'DOUT': [40]},
    }
    module['cells']['state'] = {
        'type': 'GENERIC_SLICE', 'parameters': {'FF_USED': format(1, '032b'), 'K': format(4, '032b'),
                                              'INIT': format(0xAAAA, '016b')},
        'attributes': {'NEXTPNR_BEL': 'X14Y8_SLICE0', 'AGRV2K_SHARED_CONTROL_MODE': 'ASYNC_CLEAR_POS_ZERO',
                       'AGRV2K_ASYNC_CONTROLLER_INDEX': format(0, '032b')},
        'port_directions': {'I': 'input', 'CLK': 'input', 'Q': 'output', 'F': 'output', 'ARST': 'input'},
        'connections': {'I': [6, 'x', 'x', 'x'], 'CLK': [7], 'Q': [8], 'F': [], 'ARST': [40]},
    }
    module['netnames']['controller_output'] = {'bits': [40], 'attributes': {}}
    return module


def test_pad_identity_accepts_typed_controller_and_local_register():
    assert validate_module_native_endpoints(_module(), CHIPDB)['consumer'].mode == 'IOB_INPUT'


@pytest.mark.parametrize('fault', ['mode', 'unplaced', 'foreign_tile', 'wrong_slot', 'combinational',
                                  'untyped', 'bypass', 'direction', 'foreign_consumer'])
def test_pad_identity_rejects_forged_controller_binding(fault):
    module = _module()
    controller, state = module['cells']['controller'], module['cells']['state']
    if fault == 'mode': controller['parameters']['MODE'] = format(3, '032b')
    elif fault == 'unplaced': controller['attributes'].clear()
    elif fault == 'foreign_tile': state['attributes']['NEXTPNR_BEL'] = 'X15Y8_SLICE0'
    elif fault == 'wrong_slot': state['attributes']['AGRV2K_ASYNC_CONTROLLER_INDEX'] = format(1, '032b')
    elif fault == 'combinational': state['parameters']['FF_USED'] = format(0, '032b')
    elif fault == 'untyped': state['attributes']['AGRV2K_SHARED_CONTROL_MODE'] = 'NONE'
    elif fault == 'bypass': controller['connections']['DOUT'] = [3]
    elif fault == 'direction': controller['port_directions']['DOUT'] = 'input'
    else:
        module['cells']['other'] = {'type': 'MCU_DOUT', 'connections': {'DOUT': [40]},
                                    'port_directions': {'DOUT': 'input'}}
    with pytest.raises(SystemExit, match='validated async controller DIN'):
        validate_module_native_endpoints(module, CHIPDB)
