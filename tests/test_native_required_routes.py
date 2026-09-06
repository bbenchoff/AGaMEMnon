"""Exercise required-route imports against a compiled architecture and graph."""
import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('case,error', [
    ('valid', None),
    ('missing_wire', 'required route wire'),
    ('missing_pip', 'required route pip'),
    ('wrong_root', 'differs from its placed driver'),
    ('duplicate_parent', 'disconnected or has multiple parents'),
])
def test_required_route_import(tmp_path, case, error):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    database = os.environ.get('AGAMEMNON_UARCH_DEVDB')
    if not binary or not database:
        pytest.skip('requires compiled native binary and strict database')
    root, dst = 'X13Y4_BufMUX03', 'X14Y4_RMUX08'
    pip = root + '.' + dst
    route = root + ';;1;' + dst + ';' + pip + ';1'
    if case == 'missing_wire':
        route = 'NONEXISTENT;;1'
    elif case == 'missing_pip':
        route = root + ';;1;' + dst + ';NONEXISTENT;1'
    elif case == 'wrong_root':
        route = dst + ';;1'
    elif case == 'duplicate_parent':
        route += ';' + dst + ';' + pip + ';1'
    cells = {
        'ram': dict(type='ALTA_BRAM9K', parameters={'PORTA_WIDTH': '01111'},
            attributes={'BEL': 'X13Y4_BRAM'},
            port_directions={'DataOutA': 'output', 'Clk0': 'input'},
            connections={'DataOutA': list(range(100, 118)), 'Clk0': [3]}),
        'clock': dict(type='MCU_BUS_CLOCK', parameters={}, attributes={},
            port_directions={'CLK': 'output'}, connections={'CLK': [3]}),
        'mcu_h3': dict(type='MCU_DOUT', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': [103]}),
    }
    source, output = tmp_path / 'source.json', tmp_path / 'routed.json'
    source.write_text(json.dumps({'modules': {'top': dict(attributes={'top': 1},
        ports={}, cells=cells, netnames={'readback': dict(bits=[103],
            attributes={'AGAMEMNON_REQUIRED_ROUTE': route})})}}))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_BRAM_HARDCONST='1',
        AGAMEMNON_DATA=str(Path(__file__).resolve().parents[1] / 'agamemnon/chipdb'))
    run = subprocess.run([binary, '--uarch', 'agrv2k', '-o', 'chipdb=' + database,
        '--json', str(source), '--write', str(output), '--top', 'top', '--router', 'router2'],
        env=env, capture_output=True, text=True, timeout=60)
    log = run.stdout + run.stderr
    (tmp_path / 'native.log').write_text(log)
    if error:
        assert run.returncode != 0, log
        assert error in log
        assert not output.exists()
    else:
        assert run.returncode == 0, log
        assert 'reserved 1 required route tree(s)' in log
        net = json.loads(output.read_text())['modules']['top']['netnames']['readback']
        assert pip in net['attributes']['ROUTING']
