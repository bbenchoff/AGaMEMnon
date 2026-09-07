"""A fixed BRAM consumer may use real MCU paths outside the entry-row bias."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_native_bram_unassigned_output import _design


@pytest.mark.parametrize('memory_name', ['storage', 'renamed_array'])
def test_mcu_command_register_can_reach_fixed_bram_across_rows(tmp_path, memory_name):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    database = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    if not binary or not Path(binary).is_file() or not (database / 'dev_pips.csv').is_file():
        pytest.skip('configure isolated native executable and strict database')
    design = _design('X13Y4_BRAM')
    module = design['modules']['top']
    ram = module['cells'].pop('ram')
    module['cells'][memory_name] = ram
    ram['connections']['WeA'] = [11]
    ram['port_directions']['WeA'] = 'input'
    module['cells']['mcu_haddr5'] = dict(type='MCU_DIN', parameters={}, attributes={},
        port_directions={'DIN': 'output'}, connections={'DIN': [10]})
    module['cells']['command_register'] = dict(type='GENERIC_SLICE', attributes={},
        parameters={'K': '100', 'INIT': format(0xf0f0, '016b'), 'FF_USED': '1'},
        port_directions={'I': 'input', 'F': 'output', 'Q': 'output', 'CLK': 'input'},
        connections={'I': ['x', 'x', 10, 'x'], 'F': [], 'Q': [11], 'CLK': [3]})
    module['netnames'].update(command={'bits': [10], 'attributes': {}},
                             write_request={'bits': [11], 'attributes': {}})
    source, output = tmp_path / 'source.json', tmp_path / 'placed.json'
    source.write_text(json.dumps(design))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_BRAM_HARDCONST='1',
               AGAMEMNON_DATA=str(Path(__file__).resolve().parents[1] / 'agamemnon/chipdb'))
    run = subprocess.run([binary, '--uarch', 'agrv2k', '-o', 'chipdb=' + str(database),
        '--json', str(source), '--write', str(output), '--top', 'top', '--no-route'],
        env=env, capture_output=True, text=True, timeout=120)
    transcript = run.stdout + run.stderr
    (tmp_path / 'native.log').write_text(transcript)
    assert run.returncode == 0, transcript
    placed = json.loads(output.read_text())['modules']['top']['cells']
    assert placed['command_register']['attributes']['NEXTPNR_BEL'] == 'X15Y4_SLICE0'
    assert placed['command_register']['connections']['Q'] == placed[memory_name]['connections']['WeA']
