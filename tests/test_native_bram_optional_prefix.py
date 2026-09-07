"""Optional saved BRAM prefixes must tolerate absent gated-graph edges."""
from collections import defaultdict, deque
import csv
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_native_bram_unassigned_output import _design


def _run(tmp_path, missing):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing-devdb'))
    if not binary or not Path(binary).is_file() or not (devdb / 'dev_pips.csv').is_file():
        pytest.skip('set the isolated native executable and strict devdb')
    with (devdb / 'dev_belpins.csv').open(newline='') as stream:
        pins = {(r['bel'], r['pin']): r['wire'] for r in csv.DictReader(stream)}
    source = pins['X10Y5_MCU_DIN81', 'DIN']
    target = pins['X14Y4_SLICE9', 'I[0]']
    graph = defaultdict(list)
    with (devdb / 'dev_pips.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            graph[row['src']].append(row['dst'])
    predecessor = {source: None}
    queue = deque([source])
    while queue and target not in predecessor:
        wire = queue.popleft()
        for dst in graph[wire]:
            if dst not in predecessor:
                predecessor[dst] = wire
                queue.append(dst)
    assert target in predecessor
    route = []
    cursor = target
    while cursor != source:
        route.append((predecessor[cursor], cursor))
        cursor = predecessor[cursor]
    route.reverse()
    assert len(route) >= 2
    if missing:
        # The first edge is real, but the remaining prefix cannot be looked up.
        # Nothing from this incomplete optional prefix may be bound.
        route = [route[0], (route[0][1], 'TEST_ABSENT_WIRE')]
    data = tmp_path / 'optional-data'
    data.mkdir()
    with (data / 'bram_x9_haddr_paths.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['design', 'port', 'bit', 'step', 'src', 'dst', 'kind'])
        for index, (src, dst) in enumerate(route):
            writer.writerow(['test', 'AddressA', 5, index, src, dst, 'test'])
    design = _design('X13Y4_BRAM')
    module = design['modules']['top']
    ram = module['cells']['ram']
    ram['parameters'].update(PORTA_WIDTH='01111', PORTB_WIDTH='01111')
    ram['connections']['AddressA[5]'] = [9]
    ram['port_directions']['AddressA[5]'] = 'input'
    module['cells']['identity'] = dict(type='GENERIC_SLICE',
        attributes={'BEL': 'X14Y4_SLICE9'},
        parameters={'K': '100', 'INIT': format(0xaaaa, '016b'), 'FF_USED': '0'},
        port_directions={'I': 'input', 'F': 'output', 'Q': 'output'},
        connections={'I': [100, 'x', 'x', 'x'], 'F': [9], 'Q': []})
    module['cells']['mcu_haddr7'] = dict(type='MCU_DIN', parameters={}, attributes={},
        port_directions={'DIN': 'output'}, connections={'DIN': [100]})
    module['netnames']['identity_out'] = dict(bits=[9], attributes={})
    module['netnames']['address_root'] = dict(bits=[100], attributes={})
    input_path = tmp_path / 'input.json'
    output = tmp_path / 'packed.json'
    input_path.write_text(json.dumps(design))
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGRV2K_', 'AGAMEMNON_'))}
    env.update(AGRV2K_BRAM_PINPACK='1', AGRV2K_BRAM_HARDCONST='1', AGAMEMNON_DATA=str(data))
    proc = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}',
        '--json', str(input_path), '--write', str(output), '--top', 'top', '--pack-only'],
        env=env, capture_output=True, text=True, timeout=60)
    transcript = proc.stdout + proc.stderr
    (tmp_path / 'native.log').write_text(transcript)
    return proc, transcript, output, route


@pytest.mark.parametrize('missing', [False, True])
def test_optional_prefix_is_complete_or_not_bound(tmp_path, missing):
    proc, transcript, output, route = _run(tmp_path, missing)
    assert proc.returncode == 0, transcript
    assert 'Assertion failure' not in transcript
    assert output.is_file()
    # Pack-only JSON intentionally omits route attributes. The native prefix
    # completion diagnostic is emitted only after its whole route is bound.
    if missing:
        assert 'pre-routed split AddressA[5] prefix' not in transcript
    else:
        assert 'pre-routed split AddressA[5] prefix' in transcript
        assert f'prefix over {len(route)} exact x9 pip(s)' in transcript
