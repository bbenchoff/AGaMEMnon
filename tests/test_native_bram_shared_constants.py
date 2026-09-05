"""Shared constant sources use graph reach, not incompatible dynamic-pin slots."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_native_bram_unassigned_output import _design


def _run(tmp_path, width=15, port='A', count=5, source_kind='literal', bel=None, family='Address'):
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
        ram['connections']['DataOutB[0]'] = ram['connections'].pop('DataOutA[0]')
        ram['port_directions']['DataOutB[0]'] = ram['port_directions'].pop('DataOutA[0]')
    source_bit = '0'
    if source_kind != 'literal':
        source_bit = 9
        registered = source_kind == 'registered'
        init = 'x' * 16 if source_kind == 'unknown' else format(
            0xAAAA if source_kind == 'dynamic' else 0, '016b')
        module['cells']['arbitrary_source_name'] = {
            'type': 'GENERIC_SLICE',
            'attributes': {'BEL': bel} if bel else {},
            'parameters': {'K': '100', 'INIT': init, 'FF_USED': str(int(registered))},
            'port_directions': {'I': 'input', 'F': 'output', 'Q': 'output', 'CLK': 'input'},
            'connections': {'I': ['x'] * 4, 'F': [] if registered else [9],
                            'Q': [9] if registered else [], 'CLK': [3] if registered else []},
        }
        module['netnames']['renamed_shared_source'] = {'bits': [9], 'attributes': {}}
    for index in range(count):
        pin = f'{family}{port}[{index}]'
        ram['connections'][pin] = [source_bit]
        ram['port_directions'][pin] = 'input'
    ram['connections']['We' + port] = [11] if family == 'DataIn' else ['0']
    if family == 'DataIn':
        # A real registered write-enable source, not the global clock wire:
        # clock fabric is not a routable data/control source for WeA.
        module['cells']['write_enable'] = {
            'type': 'GENERIC_SLICE', 'attributes': {},
            'parameters': {'K': '100', 'INIT': format(0xAAAA, '016b'), 'FF_USED': '1'},
            'port_directions': {'I': 'input', 'F': 'output', 'Q': 'output', 'CLK': 'input'},
            'connections': {'I': ['x'] * 4, 'F': [], 'Q': [11], 'CLK': [3]},
        }
        module['netnames']['write_enable'] = {'bits': [11], 'attributes': {}}
    ram['port_directions']['We' + port] = 'input'
    source = tmp_path / 'input.json'
    output = tmp_path / 'packed.json'
    source.write_text(json.dumps(design))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGRV2K_', 'AGAMEMNON_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_BRAM_HARDCONST='1')
    proc = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}',
        '--json', str(source), '--write', str(output), '--top', 'top', '--pack-only'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = proc.stdout + proc.stderr
    (tmp_path / 'native.log').write_text(transcript)
    return proc, transcript, output


@pytest.mark.parametrize('width', [0, 8, 12, 14, 15])
@pytest.mark.parametrize('port', ['A', 'B'])
@pytest.mark.parametrize('count', [5, 13])
def test_shared_required_address_zeros_pack(tmp_path, width, port, count):
    proc, transcript, output = _run(tmp_path, width, port, count)
    assert proc.returncode == 0, transcript
    packed = json.loads(output.read_text())['modules']['top']
    bits = packed['cells']['ram']['connections']['Address' + port]
    assert len(bits) == count and len(set(bits)) == 1
    drivers = [c for c in packed['cells'].values() if c['type'] == 'GENERIC_SLICE'
               and bits[0] in c['connections'].get('F', [])]
    assert len(drivers) == 1
    assert int(drivers[0]['parameters']['INIT'], 2) == 0
    assert int(drivers[0]['attributes'].get('AGRV2K_BRAM_PINPACKED', '0'), 2) == 1
    assert 'AGRV2K_OMUX_SEL' not in drivers[0]['attributes']


@pytest.mark.parametrize('port', ['A', 'B'])
def test_active_zero_data_lanes_share_a_constant_source(tmp_path, port):
    proc, transcript, output = _run(tmp_path, width=14, port=port, count=2, family='DataIn')
    assert proc.returncode == 0, transcript
    packed = json.loads(output.read_text())['modules']['top']
    bits = packed['cells']['ram']['connections']['DataIn' + port]
    assert len(bits) == 2 and len(set(bits)) == 1
    driver = next(c for c in packed['cells'].values()
                  if c['type'] == 'GENERIC_SLICE' and bits[0] in c['connections'].get('F', []))
    assert int(driver['parameters']['INIT'], 2) == 0
    assert int(driver['attributes'].get('AGRV2K_BRAM_PINPACKED', '0'), 2) == 1
    assert 'AGRV2K_OMUX_SEL' not in driver['attributes']


@pytest.mark.parametrize('bel', [None, 'X14Y4_SLICE0'])
def test_constant_identity_is_semantic_and_respects_requested_bel(tmp_path, bel):
    proc, transcript, output = _run(tmp_path, source_kind='zero', bel=bel)
    assert proc.returncode == 0, transcript
    cell = json.loads(output.read_text())['modules']['top']['cells']['arbitrary_source_name']
    assert int(cell['attributes'].get('AGRV2K_BRAM_PINPACKED', '0'), 2) == 1
    assert 'AGRV2K_OMUX_SEL' not in cell['attributes']
    assert "driver 'arbitrary_source_name'.F" in transcript
    if bel:
        assert '-> ' + bel in transcript
        assert 'BEL' not in cell['attributes']  # Consumed exactly once by packing.


@pytest.mark.parametrize('source_kind', ['dynamic', 'registered', 'unknown'])
def test_nonconstant_or_unproven_source_keeps_dynamic_constraints(tmp_path, source_kind):
    proc, transcript, output = _run(tmp_path, source_kind=source_kind)
    assert proc.returncode > 0, transcript
    assert 'shared BRAM driver' in transcript and 'no BEL reaching all' in transcript
    assert not output.exists()
