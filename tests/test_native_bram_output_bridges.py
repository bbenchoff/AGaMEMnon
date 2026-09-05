"""Independent semantic fixtures for graph-driven BRAM output buffering."""
import json
import os
from pathlib import Path
import subprocess

import pytest


def design(lanes, memory_name):
    cells = {
        memory_name: dict(type='ALTA_BRAM9K', parameters={'PORTA_WIDTH': '00000'},
            attributes={'BEL': 'X13Y4_BRAM'}, port_directions={'DataOutA': 'output', 'Clk0': 'input'},
            connections={'DataOutA': list(range(100, 118)), 'Clk0': [3]}),
        'clock': dict(type='MCU_BUS_CLOCK', parameters={}, attributes={},
            port_directions={'CLK': 'output'}, connections={'CLK': [3]}),
    }
    for lane in lanes:
        cells[f'mcu_h{lane}'] = dict(type='MCU_DOUT', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': [100+lane]})
    return {'modules': {'top': dict(attributes={'top': 1}, ports={}, cells=cells,
        netnames={'clock': dict(bits=[3], attributes={}),
                  'data': dict(bits=list(range(100, 118)), attributes={})})}}


@pytest.mark.parametrize('memory_name', ['storage', 'completely_renamed'])
@pytest.mark.parametrize('lanes,expected,disabled', [
    ((12,), 1, False), ((4, 5), 1, False), ((0,), 0, False),
    ((4, 5, 12), 2, False), ((12,), 0, True),
])
def test_output_bridge_preserves_lane_semantics(tmp_path, memory_name, lanes, expected, disabled):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    if not binary or not Path(binary).is_file() or not (devdb/'dev_pips.csv').is_file():
        pytest.skip('configure isolated native binary and strict database')
    source, packed = tmp_path/'input.json', tmp_path/'packed.json'
    source.write_text(json.dumps(design(lanes, memory_name)))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_')) and k != 'LD_PRELOAD'}
    env.update(AGAMEMNON_DATA=os.environ['AGAMEMNON_DATA'], AGRV2K_BRAM_PINPACK='1', AGRV2K_IO_PINPACK='1')
    if disabled: env['AGRV2K_NO_BRAM_OUTPUT_AUTOBRIDGE'] = '1'
    result = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}',
        '--json', str(source), '--write', str(packed), '--top', 'top', '--pack-only'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = result.stdout + result.stderr
    (tmp_path/'native.log').write_text(transcript)
    assert result.returncode == 0, transcript
    module = json.loads(packed.read_text())['modules']['top']
    ram = module['cells'][memory_name]
    identities = [c for c in module['cells'].values() if c['type'] == 'GENERIC_SLICE']
    assert len(identities) == expected
    observed = 0
    for lane in lanes:
        origin = ram['connections']['DataOutA'][lane]
        sink = module['cells'][f'mcu_h{lane}']['connections']['DOUT'][0]
        if origin == sink: continue
        matches = [c for c in identities if c['connections'].get('F') == [sink]]
        assert len(matches) == 1
        cell = matches[0]
        inputs = cell['connections']['I']
        assert inputs.count(origin) == 1
        pin = inputs.index(origin)
        truth = int(cell['parameters']['INIT'], 2)
        assert all(((truth >> address) & 1) == ((address >> pin) & 1) for address in range(16))
        assert int(cell['parameters']['FF_USED'], 2) == 0
        observed += 1
    assert observed == expected
