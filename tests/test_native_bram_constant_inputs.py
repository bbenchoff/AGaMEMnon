"""Required constant-low BRAM inputs must retain a real ground driver."""
import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_native_bram_unassigned_output import _design


def _pack_constants(tmp_path, width, port, family, value=0, readonly=False):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', str(
        Path(__file__).resolve().parents[1] / 'agamemnon/engine/uarch/agrv2k/devdb_strict')))
    if not binary or not Path(binary).is_file() or not (devdb / 'dev_pips.csv').is_file():
        pytest.skip('set the isolated native executable and strict devdb')
    design = _design('X13Y4_BRAM')
    module = design['modules']['top']
    ram = module['cells']['ram']
    ram['parameters'].update(PORTA_WIDTH=format(width, '05b'), PORTB_WIDTH=format(width, '05b'))
    if port == 'B':
        ram['connections']['DataOutB[0]'] = [5]
        ram['port_directions']['DataOutB[0]'] = 'output'
        sink = copy.deepcopy(module['cells']['sink'])
        sink['connections']['I'][0] = 5
        module['cells']['sink_b'] = sink
    # A live write enable keeps the data pin semantically active. Its waveform
    # is irrelevant to this packing-only test; no clock routing is performed.
    ram['connections']['We' + port] = ['0'] if readonly else [3]
    ram['port_directions']['We' + port] = 'input'
    indices = (10, 11) if family == 'Address' else (0,)
    for index in indices:
        name = f'{family}{port}[{index}]'
        ram['connections'][name] = [str(value)]
        ram['port_directions'][name] = 'input'
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(design))
    output = tmp_path / 'packed.json'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_'))}
    env['AGRV2K_BRAM_HARDCONST'] = '1'
    result = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}',
        '--json', str(source), '--write', str(output), '--top', 'top', '--pack-only'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = result.stdout + result.stderr
    (tmp_path / 'native.log').write_text(transcript)
    assert result.returncode == 0, transcript
    packed = json.loads(output.read_text())['modules']['top']
    # Native JSON compacts sparse indexed pins into a vector. These fixtures
    # include only the pins being inspected, so no omitted index is inferred.
    bits = packed['cells']['ram']['connections'].get(family + port, [])
    drivers = []
    for cell in packed['cells'].values():
        for pin, nets in cell['connections'].items():
            if cell.get('port_directions', {}).get(pin) == 'output' and any(b in nets for b in bits):
                drivers.append(cell)
    return bits, drivers


@pytest.mark.parametrize('width', [0, 8, 12, 14, 15])
@pytest.mark.parametrize('port', ['A', 'B'])
@pytest.mark.parametrize('family', ['Address', 'DataIn'])
def test_active_constant_zero_bram_inputs_have_ground_driver(tmp_path, width, port, family):
    bits, drivers = _pack_constants(tmp_path, width, port, family)
    assert bits, 'required zero input was disconnected'
    assert len(set(bits)) == 1, 'one ground net can serve all required zero pins'
    assert len(drivers) == 1
    assert int(drivers[0]['parameters']['INIT'], 2) == 0


@pytest.mark.parametrize('width', [0, 8, 12, 14, 15])
@pytest.mark.parametrize('port', ['A', 'B'])
def test_readonly_data_remains_dont_care(tmp_path, width, port):
    bits, drivers = _pack_constants(tmp_path, width, port, 'DataIn', readonly=True)
    assert not bits and not drivers


@pytest.mark.parametrize('port', ['A', 'B'])
def test_active_constant_high_data_keeps_characterized_default(tmp_path, port):
    bits, drivers = _pack_constants(tmp_path, 15, port, 'DataIn', value=1)
    assert not bits and not drivers
