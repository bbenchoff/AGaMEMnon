"""Independent OMUX round-trip expectations for inactive and active registers."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from roundtrip_omux import compare_omux_selections


def fixture(selection, init, registered=False):
    port = 'Q' if registered else 'F'
    return {
        'cells': {'lut': {
            'type': 'GENERIC_SLICE',
            'parameters': {'FF_USED': '1' if registered else '0', 'INIT': f'{init:016b}'},
            'attributes': {'NEXTPNR_BEL': 'X4Y5_SLICE0', 'AGRV2K_OMUX_SEL': f'{selection:b}',
                           'AGRV2K_BRAM_PINPACKED': '1'},
            'connections': {port: [10], ('F' if registered else 'Q'): []},
        }},
        'netnames': {'output': {'bits': [10], 'attributes': {
            'ROUTING': f'X4Y5_OMUX{selection};;1'}}},
    }


@pytest.mark.parametrize('selection', range(3))
@pytest.mark.parametrize('init', (0x0000, 0xaaaa, 0xffff))
def test_combinational_bram_hint_does_not_select_an_inactive_register(selection, init):
    design = fixture(selection, init)
    bits = {(4, 5, f'CFG_OMUX0[{selection}]'): (0, 1 << selection)}
    assert compare_omux_selections(design, b'\x00', bits) == (1, [], 0)
    compared, mismatches, unowned = compare_omux_selections(design, bytes([1 << selection]), bits)
    assert compared == 1 and unowned == 0 and len(mismatches) == 1
    assert mismatches[0]['expected'] == 0 and mismatches[0]['actual'] == 1


@pytest.mark.parametrize('selection', range(3))
def test_registered_bram_hint_still_requires_its_exact_selector(selection):
    design = fixture(selection, 0xaaaa, registered=True)
    bits = {(4, 5, f'CFG_OMUX0[{selection}]'): (0, 1 << selection)}
    assert compare_omux_selections(design, bytes([1 << selection]), bits) == (1, [], 0)
    compared, mismatches, unowned = compare_omux_selections(design, b'\x00', bits)
    assert compared == 1 and unowned == 0 and len(mismatches) == 1
    assert mismatches[0]['expected'] == 1 and mismatches[0]['actual'] == 0


@pytest.mark.parametrize('mutation', ('missing_marker', 'wrong_selector', 'inactive_q'))
def test_combinational_fix_does_not_relax_invalid_owner_or_mode_checks(mutation):
    design = fixture(2, 0xaaaa, registered=mutation == 'inactive_q')
    cell = design['cells']['lut']
    if mutation == 'missing_marker':
        cell['attributes'].pop('AGRV2K_BRAM_PINPACKED')
    elif mutation == 'wrong_selector':
        cell['attributes']['AGRV2K_OMUX_SEL'] = '1'
    else:
        cell['parameters']['FF_USED'] = '0'
    with pytest.raises(ValueError):
        compare_omux_selections(design, b'\x00', {(4, 5, 'CFG_OMUX0[2]'): (0, 4)})
