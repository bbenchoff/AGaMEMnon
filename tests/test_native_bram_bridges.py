"""Native graph-derived BRAM bridges and protected joint corridor allocation."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_native_bram_unassigned_output import _design


def design(addresses, explicit=False, shared=None, memory_name='ram'):
    fixture = _design('X13Y4_BRAM')
    module = fixture['modules']['top']
    ram = module['cells'].pop('ram')
    module['cells'][memory_name] = ram
    ram['parameters'].update(PORTA_WIDTH='01111', PORTB_WIDTH='01111')
    # Declare the complete bus, as a synthesized BRAM does. Sparse scalar
    # port declarations are compacted by nextpnr's pack-only JSON writer.
    ram['connections']['AddressA'] = ['0'] * 13
    ram['port_directions']['AddressA'] = 'input'
    for bit in addresses:
        source = 200 + bit
        name = f'mcu_haddr{bit + 2}'
        module['cells'][name] = dict(type='MCU_DIN', parameters={}, attributes={},
            port_directions={'DIN': 'output'}, connections={'DIN': [source]})
        module['netnames'][name] = dict(bits=[source], attributes={})
        if explicit and bit in (5, 9):
            slot = 9 if bit == 5 else 13
            module['cells'][f'identity_{bit}'] = dict(type='GENERIC_SLICE',
                attributes={'BEL': f'X14Y4_SLICE{slot}'},
                parameters={'K': '100', 'INIT': '1010101010101010', 'FF_USED': '0'},
                port_directions={'I': 'input', 'F': 'output', 'Q': 'output'},
                connections={'I': [source, 'x', 'x', 'x'], 'F': [100 + bit], 'Q': []})
            source = 100 + bit
            module['netnames'][f'identity_{bit}'] = dict(bits=[source], attributes={})
        ram['connections']['AddressA'][bit] = source
    if shared is not None:
        bit = (100 if explicit else 200) + shared
        module['cells']['additional_consumer'] = dict(type='GENERIC_SLICE', attributes={},
            parameters={'K': '100', 'INIT': '1010101010101010', 'FF_USED': '0'},
            port_directions={'I': 'input', 'F': 'output', 'Q': 'output'},
            connections={'I': [bit, 'x', 'x', 'x'], 'F': [], 'Q': []})
    return fixture


def run(tmp_path, fixture, **options):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing-devdb'))
    if not binary or not Path(binary).is_file() or not (devdb / 'dev_pips.csv').is_file():
        pytest.skip('set the isolated native executable and strict devdb')
    source, output = tmp_path / 'input.json', tmp_path / 'packed.json'
    source.write_text(json.dumps(fixture))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGRV2K_', 'AGAMEMNON_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_BRAM_HARDCONST='1')
    env.update(options)
    proc = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}',
        '--json', str(source), '--write', str(output), '--top', 'top', '--pack-only'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = proc.stdout + proc.stderr
    (tmp_path / 'native.log').write_text(transcript)
    return proc, transcript, json.loads(output.read_text())['modules']['top'] if output.exists() else None


def address_origin(module, bit):
    stages = 0
    seen = set()
    while True:
        assert bit not in seen
        seen.add(bit)
        drivers = [(name, cell, port) for name, cell in module['cells'].items()
                   for port in ('F', 'Q', 'DIN') if cell['connections'].get(port) == [bit]]
        assert len(drivers) == 1
        name, cell, port = drivers[0]
        if cell['type'] == 'MCU_DIN':
            return name, stages
        assert cell['type'] == 'GENERIC_SLICE' and port == 'F'
        assert int(cell['parameters']['FF_USED'], 2) == 0
        truth = int(cell['parameters']['INIT'], 2)
        inputs = [pin for pin in range(4) if truth == sum(
            ((assignment >> pin) & 1) << assignment for assignment in range(16))]
        assert len(inputs) == 1
        bit = cell['connections']['I'][inputs[0]]
        stages += 1


@pytest.mark.parametrize('addresses', [(5,), (6,), (9,), (5, 6, 9)])
@pytest.mark.parametrize('memory_name', ['ram', 'independent_memory_name'])
def test_default_bridges_disconnected_inputs_without_name_rules(tmp_path, addresses, memory_name):
    proc, transcript, packed = run(tmp_path, design(addresses, memory_name=memory_name))
    assert proc.returncode == 0, transcript
    for bit in addresses:
        root, stages = address_origin(packed, packed['cells'][memory_name]['connections']['AddressA'][bit])
        assert root == f'mcu_haddr{bit + 2}' and stages == 2


def test_reachable_input_stays_direct(tmp_path):
    proc, transcript, packed = run(tmp_path, design((0,)))
    assert proc.returncode == 0, transcript
    assert address_origin(packed, packed['cells']['ram']['connections']['AddressA'][0]) == ('mcu_haddr2', 0)
    assert 'inserted graph-disconnected' not in transcript


def test_original_source_keeps_its_other_consumer(tmp_path):
    proc, transcript, packed = run(tmp_path, design((5,), shared=5))
    assert proc.returncode == 0, transcript
    direct = packed['cells']['additional_consumer']['connections']['I'][0]
    assert address_origin(packed, direct) == ('mcu_haddr7', 0)
    assert address_origin(packed, packed['cells']['ram']['connections']['AddressA'][5]) == ('mcu_haddr7', 2)


def test_default_joint_allocator_negotiates_independent_generic_branches(tmp_path):
    proc, transcript, packed = run(tmp_path, design((5, 9, 11), explicit=True))
    assert proc.returncode == 0, transcript
    assert 'evicted generic BRAM AddressA[5]' in transcript


def test_joint_allocator_does_not_evict_multi_sink_branches(tmp_path):
    # Shared requesters may now displace a recorded single-sink branch; the
    # protected-victim case remains a refusal. See test_native_bram_shared_requests.
    proc, transcript, packed = run(tmp_path, design((5, 9, 11), explicit=True, shared=5))
    assert proc.returncode > 0 and 'no simultaneous strict-graph' in transcript
    assert 'evicted generic BRAM' not in transcript
    assert packed is None


def test_bridge_bisection_switch_preserves_old_refusal(tmp_path):
    proc, transcript, packed = run(tmp_path, design((5,)), AGRV2K_NO_BRAM_AUTOBRIDGE='1')
    assert proc.returncode > 0 and 'no simultaneous strict-graph' in transcript
    assert packed is None
