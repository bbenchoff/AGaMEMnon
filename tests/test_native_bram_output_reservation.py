"""A saved BRAM output path may reserve only its actual source and consumer."""
import json
import os
from pathlib import Path
import subprocess

import pytest


def fixture(width, endpoint, site=4, shared=False, memory_name='ram'):
    cells = {
        memory_name: dict(type='ALTA_BRAM9K', parameters={'PORTA_WIDTH': format(width, '05b')},
            attributes={'BEL': f'X13Y{site}_BRAM'},
            port_directions={'DataOutA': 'output', 'Clk0': 'input'},
            connections={'DataOutA': list(range(100, 118)), 'Clk0': [3]}),
        'clock': dict(type='MCU_BUS_CLOCK', parameters={}, attributes={},
            port_directions={'CLK': 'output'}, connections={'CLK': [3]}),
    }
    for lane, output in ((13, endpoint), (14, 5)):
        cells[f'mcu_h{output}'] = dict(type='MCU_DOUT', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': [100 + lane]})
    if shared:
        cells['unrelated_sink'] = dict(type='GENERIC_SLICE', parameters={'K': '100',
            'INIT': '1010101010101010', 'FF_USED': '0'}, attributes={},
            port_directions={'I': 'input', 'F': 'output', 'Q': 'output'},
            connections={'I': [113, 'x', 'x', 'x'], 'F': [], 'Q': []})
    return {'modules': {'top': dict(attributes={'top': 1}, ports={}, cells=cells,
            netnames={'clock': dict(bits=[3], attributes={}),
                      'output_bus': dict(bits=list(range(100, 118)), attributes={})})}}


@pytest.mark.parametrize('width,endpoint,site,shared,reserve', [
    (8, 4, 4, False, True),
    (0, 4, 4, False, True),
    (8, 13, 4, False, False),
    (0, 13, 4, False, False),
    (8, 4, 3, False, False),
    (8, 4, 4, True, False),
])
@pytest.mark.parametrize('memory_name', ['ram', 'independently_renamed'])
def test_saved_output_path_requires_actual_endpoint(tmp_path, width, endpoint, site, shared, reserve, memory_name):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    data = Path(os.environ.get('AGAMEMNON_DATA', str(Path(__file__).resolve().parents[1] / 'agamemnon/chipdb')))
    if not binary or not Path(binary).is_file() or not (devdb / 'dev_pips.csv').is_file():
        pytest.skip('set isolated native binary and strict devdb')
    source, output = tmp_path / 'input.json', tmp_path / 'packed.json'
    source.write_text(json.dumps(fixture(width, endpoint, site, shared, memory_name)))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_IO_PINPACK='1')
    env['AGAMEMNON_DATA'] = str(data)
    result = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}',
        '--json', str(source), '--write', str(output), '--top', 'top', '--pack-only'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = result.stdout + result.stderr
    (tmp_path / 'native.log').write_text(transcript)
    assert result.returncode == 0, transcript
    assert ('pre-routed simultaneous x9 q4 over' in transcript) == reserve
