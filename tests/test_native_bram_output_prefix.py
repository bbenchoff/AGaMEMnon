"""Mandatory memory-output wires must remain owned after the packer exits."""
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('memory_name', ['ram', 'unrelated_storage_name'])
@pytest.mark.parametrize('shared_address_ground', [False, True])
def test_mandatory_readback_prefix_is_bound_for_router(tmp_path, memory_name, shared_address_ground):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    database = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    if not binary or not Path(binary).is_file() or not (database / 'dev_pips.csv').is_file():
        pytest.skip('configure isolated native executable and strict database')
    cells = {
        memory_name: dict(type='ALTA_BRAM9K', parameters={'PORTA_WIDTH': '01111'},
            attributes={'BEL': 'X13Y4_BRAM'},
            port_directions={'DataOutA': 'output', 'Clk0': 'input'},
            connections={'DataOutA': list(range(100, 118)), 'Clk0': [3]}),
        'clock': dict(type='MCU_BUS_CLOCK', parameters={}, attributes={},
            port_directions={'CLK': 'output'}, connections={'CLK': [3]}),
        'mcu_h3': dict(type='MCU_DOUT', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': [103]}),
        'mcu_hresp': dict(type='MCU_AHB_HRESP', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': ['0']}),
    }
    if shared_address_ground:
        cells[memory_name]['port_directions']['AddressA'] = 'input'
        cells[memory_name]['connections']['AddressA'] = ['0'] * 13
    document = {'modules': {'top': dict(attributes={'top': 1}, ports={}, cells=cells,
        netnames={'readback': dict(bits=[103], attributes={}),
                  'clock': dict(bits=[3], attributes={})})}}
    source, output = tmp_path / 'source.json', tmp_path / 'packed.json'
    source.write_text(json.dumps(document))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_BRAM_HARDCONST='1',
        AGAMEMNON_DATA=str(Path(__file__).resolve().parents[1] / 'agamemnon/chipdb'))
    run = subprocess.run([binary, '--uarch', 'agrv2k', '-o', 'chipdb=' + str(database),
        '--json', str(source), '--write', str(output), '--top', 'top', '--router', 'router2'],
        env=env, capture_output=True, text=True, timeout=60)
    (tmp_path / 'native.log').write_text(run.stdout + run.stderr)
    assert run.returncode == 0, run.stdout + run.stderr
    nets = json.loads(output.read_text())['modules']['top']['netnames']
    routing = nets['readback']['attributes']['ROUTING']
    assert 'X13Y4_BufMUX03.X14Y4_RMUX08' in routing
    for name, net in nets.items():
        if net['bits'] != nets['readback']['bits']:
            assert 'X14Y4_RMUX08' not in net['attributes'].get('ROUTING', '')
