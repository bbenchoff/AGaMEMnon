"""Automatic output bridges must obey normal native placement rules."""
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('memory', ['memory_a', 'renamed_storage'])
def test_bridge_chooses_legal_site_before_placement(tmp_path, memory):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    if not binary or not Path(binary).is_file() or not (devdb/'dev_pips.csv').is_file():
        pytest.skip('configure native executable and database')
    cells = {
        memory: dict(type='ALTA_BRAM9K', parameters={'PORTA_WIDTH': '01000'},
            attributes={'BEL': 'X13Y4_BRAM'}, port_directions={'DataOutA': 'output', 'Clk0': 'input', 'AddressA': 'input'},
            connections={'DataOutA': list(range(100, 118)), 'Clk0': [3], 'AddressA': ['x']*12+['0']}),
        'clock': dict(type='MCU_BUS_CLOCK', parameters={}, attributes={},
            port_directions={'CLK': 'output'}, connections={'CLK': [3]}),
        'mcu_h3': dict(type='MCU_DOUT', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': [112]}),
    }
    document = {'modules': {'top': dict(attributes={'top': 1}, ports={}, cells=cells,
        netnames={'clock': dict(bits=[3], attributes={}), 'data': dict(bits=list(range(100,118)), attributes={})})}}
    source, routed = tmp_path/'source.json', tmp_path/'routed.json'
    source.write_text(json.dumps(document))
    env = {k: v for k,v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_')) and k != 'LD_PRELOAD'}
    env.update(AGAMEMNON_DATA=os.environ['AGAMEMNON_DATA'], AGRV2K_BRAM_PINPACK='1', AGRV2K_IO_PINPACK='1')
    run = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}', '--json', str(source),
        '--write', str(routed), '--top', 'top', '--router', 'router2'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = run.stdout+run.stderr
    (tmp_path/'native.log').write_text(transcript)
    assert run.returncode == 0, transcript
    module = json.loads(routed.read_text())['modules']['top']
    sink = module['cells']['mcu_h3']['connections']['DOUT']
    bridges = [c for c in module['cells'].values() if c['type'] == 'GENERIC_SLICE' and c['connections'].get('F') == sink]
    assert len(bridges) == 1
    bridge = bridges[0]
    assert int(bridge['attributes']['NEXTPNR_BEL'].split('_SLICE')[1]) % 2 == 0
    original = module['cells'][memory]['connections']['DataOutA'][12]
    pin = bridge['connections']['I'].index(original)
    assert bridge['connections']['F'] == module['cells']['mcu_h3']['connections']['DOUT']
    truth = int(bridge['parameters']['INIT'], 2)
    assert all(((truth >> a) & 1) == ((a >> pin) & 1) for a in range(16))
