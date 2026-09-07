"""Shared data and constant-address trees must survive corridor negotiation."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from test_native_bram_unassigned_output import _design


def test_shared_data_tree_can_be_rerouted_for_dynamic_address(tmp_path):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    database = os.environ.get('AGAMEMNON_UARCH_DEVDB')
    if not binary or not database:
        pytest.skip('requires isolated native executable and devdb')
    design = _design('X13Y4_BRAM')
    module = design['modules']['top']
    del module['cells']['sink']
    ram = module['cells']['ram']
    ram['parameters'] = {'PORTA_WIDTH': '00000', 'PORTB_WIDTH': '00000'}
    for name, bit, bel, registered in (
        ('address', 10, 'X14Y4_SLICE0', False),
        ('even_data', 11, 'X14Y4_SLICE2', False),
        ('odd_data', 12, 'X14Y4_SLICE5', False),
        ('write_enable', 13, 'X15Y4_SLICE0', True),
    ):
        module['cells'][name] = dict(type='GENERIC_SLICE', attributes={'BEL': bel},
            parameters={'K': '100', 'INIT': format(0xaaaa, '016b'), 'FF_USED': str(int(registered))},
            port_directions={'I': 'input', 'F': 'output', 'Q': 'output', 'CLK': 'input'},
            connections={'I': ['x']*4, 'F': [] if registered else [bit],
                         'Q': [bit] if registered else [], 'CLK': [3] if registered else []})
        module['netnames'][name] = dict(bits=[bit], attributes={})
    for lane in range(18):
        pin = f'DataInA[{lane}]'
        ram['connections'][pin] = [11 + lane % 2]
        ram['port_directions'][pin] = 'input'
    for lane in range(13):
        pin = f'AddressA[{lane}]'
        # x18 lowering presents the four ignored suffix bits high; grounding
        # them instead creates extra live corridors and a different problem.
        ram['connections'][pin] = [10 if lane == 4 else ('1' if lane < 4 else '0')]
        ram['port_directions'][pin] = 'input'
    ram['connections']['WeA'] = [13]
    ram['port_directions']['WeA'] = 'input'
    # All readback lanes are live. Omitting lanes 3/4 removes their mandatory
    # output escapes and allows address routes that evade the contention.
    for lane in range(18):
        bit = 100 + lane
        pin = f'DataOutA[{lane}]'
        ram['connections'][pin] = [bit]
        ram['port_directions'][pin] = 'output'
        module['cells'][f'mcu_h{lane}'] = dict(type='MCU_DOUT', attributes={},
            parameters={}, port_directions={'DOUT': 'input'}, connections={'DOUT': [bit]})
    source, output = tmp_path/'input.json', tmp_path/'packed.json'
    source.write_text(json.dumps(design))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGRV2K_', 'AGAMEMNON_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_BRAM_HARDCONST='1',
               AGRV2K_TRACE_BRAM_CORRIDORS='1',
               AGAMEMNON_DATA=str(Path(__file__).resolve().parents[1]/'agamemnon/chipdb'))
    run = subprocess.run([binary, '--uarch', 'agrv2k', '-o', 'chipdb='+database,
        '--json', str(source), '--write', str(output), '--top', 'top', '--pack-only'],
        env=env, capture_output=True, text=True, timeout=120)
    log = run.stdout + run.stderr
    (tmp_path/'native.log').write_text(log)
    assert run.returncode == 0, log
    assert 'evicted generic BRAM DataInA[1]' in log
    for port in ['DataInA[0]', 'DataInA[1]'] + [f'AddressA[{i}]' for i in range(4, 13)]:
        assert f'BRAM trace verified {port} ' in log
    packed = json.loads(output.read_text())['modules']['top']
    data = packed['cells']['ram']['connections']['DataInA']
    assert len(data) == 18
    assert len(set(data[::2])) == len(set(data[1::2])) == 1
    assert data[0] != data[1]
