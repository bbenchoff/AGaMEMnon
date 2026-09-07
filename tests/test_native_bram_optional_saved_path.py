"""Unavailable optional paths fall back; a disconnected graph still fails."""
import csv
import json
import os
from pathlib import Path
import subprocess
import pytest
from test_native_bram_bridges import address_origin


@pytest.mark.parametrize('memory', ['storage', 'renamed_memory'])
@pytest.mark.parametrize('fault', ['original', 'absent', 'discontinuous', 'disconnected'])
def test_optional_address_path(tmp_path, memory, fault):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    devdb = Path(os.environ.get('AGAMEMNON_UARCH_DEVDB', 'missing'))
    if not binary or not Path(binary).is_file() or not (devdb/'dev_pips.csv').is_file():
        pytest.skip('configure native executable and strict database')
    data = Path(os.environ['AGAMEMNON_DATA'])
    cells = {
        memory: dict(type='ALTA_BRAM9K', parameters={'PORTA_WIDTH': '01000', 'PORTB_WIDTH': '00000'},
            attributes={'BEL': 'X13Y4_BRAM'},
            port_directions={'DataOutA': 'output', 'AddressA': 'input', 'Clk0': 'input', 'ClkEn0': 'input'},
            connections={'DataOutA': list(range(100,118)), 'AddressA': ['1']*3+list(range(200,210)), 'Clk0': [2], 'ClkEn0': [3]}),
        'clock': dict(type='MCU_BUS_CLOCK', parameters={}, attributes={},
            port_directions={'CLK': 'output'}, connections={'CLK': [2]}),
        'ready': dict(type='MCU_AHB_HREADY', parameters={}, attributes={},
            port_directions={'DIN': 'output'}, connections={'DIN': [3]}),
        'mcu_h0': dict(type='MCU_DOUT', parameters={}, attributes={},
            port_directions={'DOUT': 'input'}, connections={'DOUT': [109]}),
    }
    for bit in range(10):
        cells[f'mcu_haddr{bit+2}'] = dict(type='MCU_DIN', parameters={}, attributes={},
            port_directions={'DIN': 'output'}, connections={'DIN': [200+bit]})
    document = {'modules': {'top': dict(attributes={'top': 1}, ports={}, cells=cells,
        netnames={'clock': dict(bits=[2], attributes={}), 'address': dict(bits=list(range(200,210)), attributes={})})}}
    if fault in ('absent', 'discontinuous'):
        overlay = tmp_path/'data'
        overlay.mkdir()
        filename = 'bram_x9_haddr_paths.csv'
        for child in data.iterdir():
            if child.name != filename:
                (overlay/child.name).symlink_to(child.resolve(), target_is_directory=child.is_dir())
        with (data/filename).open(newline='') as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        changed = 0
        for row in rows:
            if row['bram_bit'] == '7' and row['step'] == '0' and fault == 'absent':
                row['dst_wire'] = 'NONEXISTENT_OPTIONAL_WIRE'
                changed += 1
            if row['bram_bit'] == '7' and row['step'] == '1' and fault == 'discontinuous':
                row['src_wire'] = 'NONEXISTENT_OPTIONAL_WIRE'
                changed += 1
        assert changed == 1
        with (overlay/filename).open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        data = overlay
    if fault == 'disconnected':
        isolated = tmp_path/'devdb'
        isolated.mkdir()
        for child in devdb.iterdir():
            if child.name != 'dev_pips.csv':
                (isolated/child.name).symlink_to(child.resolve(), target_is_directory=child.is_dir())
        with (devdb/'dev_pips.csv').open(newline='') as stream:
            reader = csv.reader(stream)
            rows = list(reader)
        retained = [row for row in rows if 'X13Y12_BufMUX16' not in row]
        assert len(retained) < len(rows)
        with (isolated/'dev_pips.csv').open('w', newline='') as stream:
            csv.writer(stream).writerows(retained)
        devdb = isolated
    source, routed = tmp_path/'input.json', tmp_path/'routed.json'
    source.write_text(json.dumps(document))
    env = {k: v for k,v in os.environ.items() if not k.startswith(('AGAMEMNON_', 'AGRV2K_')) and k != 'LD_PRELOAD'}
    env.update(AGAMEMNON_DATA=str(data), AGRV2K_BRAM_PINPACK='1', AGRV2K_IO_PINPACK='1', AGRV2K_BRAM_HARDCONST='1')
    run = subprocess.run([binary, '--uarch', 'agrv2k', '-o', f'chipdb={devdb}', '--json', str(source),
        '--write', str(routed), '--top', 'top', '--placer', 'heap', '--router', 'router2', '--seed', '1'],
        env=env, capture_output=True, text=True, timeout=120)
    transcript = run.stdout+run.stderr
    (tmp_path/'native.log').write_text(transcript)
    if fault == 'disconnected':
        assert run.returncode != 0 and not routed.exists(), transcript
        assert f'no available two-stage graph bridge for {memory}$bridge$AddressA[7]' in transcript
        return
    assert run.returncode == 0, transcript
    if fault == 'discontinuous':
        assert 'discontinuous saved AddressA[7]' in transcript
    else:
        assert 'saved AddressA[7] pip absent' in transcript
    module = json.loads(routed.read_text())['modules']['top']
    addresses = module['cells'][memory]['connections']['AddressA']
    for bit in range(10):
        origin, stages = address_origin(module, addresses[bit+3])
        assert origin == f'mcu_haddr{bit+2}' and stages <= 2
