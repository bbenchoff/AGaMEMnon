"""Movable BRAM entry buffers must retain destination-compatible MCU exits."""
import json
import os
from pathlib import Path
import subprocess
import pytest

from test_native_bram_bridges import address_origin


@pytest.mark.parametrize('memory', ['storage', 'independent_full_depth_memory'])
def test_full_address_bus_routes_without_stealing_entry_escape(tmp_path, memory):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    if not binary or not Path(binary).is_file() or not (devdb/'dev_pips.csv').is_file():
        pytest.skip('configure native executable and strict database')
    cells = {
        memory: dict(type='ALTA_BRAM9K', parameters={'PORTA_WIDTH': '01100', 'PORTB_WIDTH': '00000'},
            attributes={'BEL': 'X13Y4_BRAM'},
            port_directions={'DataOutA': 'output', 'AddressA': 'input', 'Clk0': 'input', 'ClkEn0': 'input'},
            connections={'DataOutA': list(range(100, 118)), 'AddressA': ['1', '1']+list(range(200,211)), 'Clk0': [2], 'ClkEn0': [3]}),
        'clock': dict(type='MCU_BUS_CLOCK', parameters={}, attributes={},
            port_directions={'CLK': 'output'}, connections={'CLK': [2]}),
        'ready': dict(type='MCU_AHB_HREADY', parameters={}, attributes={},
            port_directions={'DIN': 'output'}, connections={'DIN': [3]}),
    }
    for bit in range(11):
        cells[f'mcu_haddr{bit+2}'] = dict(type='MCU_DIN', parameters={}, attributes={},
            port_directions={'DIN': 'output'}, connections={'DIN': [200+bit]})
    for bit in range(4):
        cells[f'mcu_h{bit}'] = dict(type='MCU_DOUT', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': [103+bit]})
    document = {'modules': {'top': dict(attributes={'top': 1}, ports={}, cells=cells,
        netnames={'clock': dict(bits=[2], attributes={}), 'address': dict(bits=list(range(200,211)), attributes={})})}}
    source, routed = tmp_path/'input.json', tmp_path/'routed.json'
    source.write_text(json.dumps(document))
    env = {k: v for k,v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_')) and k != 'LD_PRELOAD'}
    env.update(AGAMEMNON_DATA=os.environ['AGAMEMNON_DATA'], AGRV2K_BRAM_PINPACK='1', AGRV2K_IO_PINPACK='1', AGRV2K_BRAM_HARDCONST='1')
    run = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}', '--json', str(source),
        '--write', str(routed), '--top', 'top', '--placer', 'heap', '--router', 'router2', '--seed', '1'],
        env=env, capture_output=True, text=True, timeout=120)
    transcript = run.stdout+run.stderr
    (tmp_path/'native.log').write_text(transcript)
    assert run.returncode == 0, transcript
    module = json.loads(routed.read_text())['modules']['top']
    addresses = module['cells'][memory]['connections']['AddressA']
    for bit in range(11):
        origin, stages = address_origin(module, addresses[bit+2])
        assert origin == f'mcu_haddr{bit+2}' and stages <= 2
    data = module['cells'][memory]['connections']['DataOutA']
    for bit in range(4):
        observed = module['cells'][f'mcu_h{bit}']['connections']['DOUT'][0]
        visited = set()
        while observed != data[bit+3]:
            assert observed not in visited
            visited.add(observed)
            drivers = [c for c in module['cells'].values() if c['connections'].get('F') == [observed]]
            assert len(drivers) == 1
            cell = drivers[0]
            assert cell['type'] == 'GENERIC_SLICE' and int(cell['parameters']['FF_USED'], 2) == 0
            truth = int(cell['parameters']['INIT'], 2)
            pins = [pin for pin in range(4) if all(((truth >> a) & 1) == ((a >> pin) & 1) for a in range(16))]
            assert len(pins) == 1
            observed = cell['connections']['I'][pins[0]]
