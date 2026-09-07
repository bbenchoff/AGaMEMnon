"""Shared BRAM ingress must not steal native direct-D register placement."""
import json
import os
from pathlib import Path
import subprocess

import pytest
from test_uarch_direct_d_fusion import _observed_feedback


@pytest.mark.parametrize('count', [1, 2, 3])
@pytest.mark.parametrize('source_port', ['F', 'Q'])
def test_bram_entries_preserve_native_register_pool(tmp_path, count, source_port):
    binary = os.environ.get('AGAMEMNON_UARCH_NEXTPNR')
    database = os.environ.get('AGAMEMNON_UARCH_DEVDB')
    if not binary or not database:
        pytest.skip('requires isolated native executable and devdb')
    design = _observed_feedback(count)
    module = design['modules']['top']
    connections = {'Clk0': [2], 'WeA': [200], 'DataOutA[0]': [201]}
    for lane in range(18):
        connections[f'DataInA[{lane}]'] = [10 + int(source_port == 'F') + 3*(lane % count)]
    module['cells']['ram'] = dict(type='ALTA_BRAM9K', attributes={'BEL': 'X13Y4_BRAM'},
        parameters={'PORTA_WIDTH': '00000', 'PORTB_WIDTH': '00000'},
        connections=connections, port_directions={k: 'output' if k.startswith('DataOut') else 'input' for k in connections})
    module['cells']['write_enable'] = dict(type='GENERIC_SLICE', attributes={},
        parameters={'K': '100', 'INIT': format(0xaaaa,'016b'), 'FF_USED':'1'},
        port_directions={'CLK':'input','I':'input','Q':'output','F':'output'},
        connections={'CLK':[2],'I':['x']*4,'Q':[200],'F':[]})
    module['cells']['read_sink'] = dict(type='GENERIC_SLICE', attributes={},
        parameters={'K':'100','INIT':format(0xaaaa,'016b'),'FF_USED':'0'},
        port_directions={'I':'input','F':'output','Q':'output'},
        connections={'I':[201,'x','x','x'],'F':[],'Q':[]})
    source, output = tmp_path/'input.json', tmp_path/'packed.json'
    source.write_text(json.dumps(design))
    env={k:v for k,v in os.environ.items() if not k.startswith(('AGAMEMNON_','AGRV2K_'))}
    env.update(AGRV2K_BRAM_PINPACK='1',AGRV2K_BRAM_HARDCONST='1')
    run=subprocess.run([binary,'--uarch','agrv2k','-o','chipdb='+database,'--json',str(source),
        '--write',str(output),'--top','top','--pack-only'],env=env,capture_output=True,text=True,timeout=120)
    log=run.stdout+run.stderr
    (tmp_path/'native.log').write_text(log)
    if source_port == 'Q':
        assert run.returncode != 0
        assert "requires registered Q to be local-only" in log
        assert not output.exists()
        return
    assert run.returncode==0, log
    packed=json.loads(output.read_text())['modules']['top']
    for index in range(count):
        register=packed['cells'][f'feedback{index}_LC']
        assert register['attributes']['AGRV2K_REGISTER_INPUT_MODE']=='DIRECT_D_I3'
        assert 'AGRV2K_BRAM_PINPACKED' not in register['attributes']
        assert 'NEXTPNR_BEL' not in register['attributes']
        f=register['connections']['F'][0]
        entries=[c for n,c in packed['cells'].items() if '$bram_direct_d_bridge' in n
                 and f in c['connections'].get('I',[])]
        assert len(entries)==1
        assert int(entries[0]['parameters']['FF_USED'],2)==0
    assert log.count('source remains placer-owned')==count
