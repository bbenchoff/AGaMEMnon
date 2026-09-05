"""Semantic x1/x18 ROM admission: no image, source or content allowlist."""
from copy import deepcopy
from pathlib import Path

import pytest

from agamemnon.engine.features.bram import FEATURE
from agamemnon.engine.registry import options_from

CHIPDB = Path(__file__).resolve().parents[1] / 'agamemnon/chipdb'


def rom_module(name='memory', contents='10010110', width=15):
    return {'attributes': {'AGAMEMNON_CLOCK_SOURCE_PROFILE': 'MCU_BUS_DEFAULT_V1',
                           'AGAMEMNON_CLOCK_CLASS': 'GCLK0'},
            'cells': {name: {
                'type': 'ALTA_BRAM9K', 'attributes': {'NEXTPNR_BEL': 'X13Y4_BRAM'},
                'parameters': {'PORTA_WIDTH': format(width, '05b'), 'PORTB_WIDTH': '00000',
                               'CLKMODE': '00', 'PORTB_CLKIN_EN': '1',
                               'PORTB_CLKOUT_EN': '1', 'INIT_VAL': contents},
                'connections': {'AddressA': list(range(100, 113)), 'DataOutA': [17],
                                'DataOutB': [18], 'Clk0': [2], 'Clk1': [],
                                'ClkEn0': [3], 'ClkEn1': [], 'WeA': [], 'WeB': [],
                                'ReA': [], 'ReB': []}},
                'sink': {'type': 'GENERIC_SLICE', 'parameters': {},
                         'connections': {'I[0]': [17]}}}}


@pytest.mark.parametrize('name', ['rom', 'renamed_arbitrary_memory'])
@pytest.mark.parametrize('contents', ['1', '101001', '10' * 4608, '1' * 9216])
@pytest.mark.parametrize('width', [15, 0])
def test_supported_rom_is_not_name_or_content_bound(name, contents, width):
    state = FEATURE.prepare(rom_module(name, contents, width), CHIPDB, options_from({}))
    assert state.cells == [(13, 4, width, 0, 0)]
    assert not state.dual_rw and not state.portb_read


@pytest.mark.parametrize('change', [
    'site', 'clock_mode', 'clock_profile', 'clock_class',
    'write_a', 'write_b', 'second_clock', 'read_enable', 'port_b_sink',
    'port_b_module_output', 'multiple_memories', 'outreg', 'clock_enable_param',
    'missing_clock', 'address_shape',
])
@pytest.mark.parametrize('width', [15, 0])
def test_unqualified_modes_stay_fenced(change, width):
    module = rom_module(width=width)
    ram = module['cells']['memory']
    if change == 'site': ram['attributes']['NEXTPNR_BEL'] = 'X13Y3_BRAM'
    elif change == 'clock_mode': ram['parameters']['CLKMODE'] = '01'
    elif change == 'clock_profile': module['attributes']['AGAMEMNON_CLOCK_SOURCE_PROFILE'] = 'OTHER'
    elif change == 'clock_class': module['attributes']['AGAMEMNON_CLOCK_CLASS'] = 'GCLK1'
    elif change == 'write_a': ram['connections']['WeA'] = [19]
    elif change == 'write_b': ram['connections']['WeB'] = [19]
    elif change == 'second_clock': ram['connections']['Clk1'] = [2]
    elif change == 'read_enable': ram['connections']['ReA'] = [3]
    elif change == 'port_b_sink': module['cells']['sink']['connections']['I[1]'] = [18]
    elif change == 'port_b_module_output': module['ports'] = {'out': {'direction': 'output', 'bits': [18]}}
    elif change == 'multiple_memories': module['cells']['another'] = deepcopy(ram)
    elif change == 'outreg': ram['parameters']['PORTA_OUTREG'] = '1'
    elif change == 'clock_enable_param': ram['parameters']['PORTA_CLKIN_EN'] = '1'
    elif change == 'missing_clock': ram['connections']['Clk0'] = []
    elif change == 'address_shape': ram['connections']['AddressA'] = [100]
    with pytest.raises(SystemExit, match='VP-AGM-006'):
        FEATURE.prepare(module, CHIPDB, options_from({}))


@pytest.mark.parametrize('settings', [
    {'AGAMEMNON_SYSCLK': '20'}, {'AGAMEMNON_HSE': '12'},
    {'AGAMEMNON_DEVICE': 'AGRV2KQ48'},
    {'AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG': '1'},
    {'AGAMEMNON_BRAM_SITE_READ_PATHS': '1'},
])
@pytest.mark.parametrize('width', [15, 0])
def test_other_clock_package_contexts_stay_fenced(settings, width):
    with pytest.raises(SystemExit, match='VP-AGM-006'):
        FEATURE.prepare(rom_module(width=width), CHIPDB, options_from(settings))
