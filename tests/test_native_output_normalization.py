"""Compiled packing of ordinary wires and shared logic into typed pad owners."""
import json

import pytest

import test_uarch_special_routes as support


@pytest.fixture(autouse=True)
def physical_cli_environment(monkeypatch):
    monkeypatch.setenv('AGRV2K_IO_PINPACK', '1')
    monkeypatch.setenv('AGAMEMNON_DATA', str(support.CHIPDB))


def iob(bel, port, bit):
    return dict(hide_name=0, type='GENERIC_IOB', parameters={},
        attributes={'NEXTPNR_BEL': bel},
        port_directions={'PAD': 'inout', port: 'output' if port == 'O' else 'input'},
        connections={'PAD': [], port: [bit]})


def logic(init, input_bit, output_bit):
    return dict(hide_name=0, type='GENERIC_SLICE', attributes={},
        parameters={'K': f'{4:032b}', 'FF_USED': f'{0:032b}', 'INIT': f'{init:016b}'},
        port_directions={'I': 'input', 'F': 'output', 'Q': 'output', 'CLK': 'input'},
        connections={'I': [input_bit, '0', '0', '0'], 'F': [output_bit], 'Q': [], 'CLK': []})


@pytest.mark.parametrize('shared_logic', [False, True])
def test_shared_source_gets_one_dedicated_identity_per_pad(tmp_path, shared_logic):
    cells = {'input': iob('X20Y13_IPAD1', 'O', 10)}
    source_bit = 10
    if shared_logic:
        cells['producer'] = logic(0x5555, 10, 20)
        source_bit = 20
    for lane in range(2):
        cells['pad%d' % lane] = iob('X0Y4_IOB%d' % lane, 'I', source_bit)
    document = dict(modules={'top': dict(attributes={'top': '1'}, ports={}, cells=cells,
        netnames={'input_net': {'bits': [10], 'attributes': {}},
                  'source_net': {'bits': [source_bit], 'attributes': {}}})})
    result, log, output = support._run(tmp_path, 'shared_source', document, '--no-route')
    assert result.returncode == 0, log
    module = json.loads(output.read_text())['modules']['top']
    cells = module['cells']
    source = cells['producer']['connections']['F'][0] if shared_logic else cells['input']['connections']['O'][0]
    drivers = []
    for lane in range(2):
        bit = cells['pad%d' % lane]['connections']['I'][0]
        matching = [c for c in cells.values() if c['type'] == 'GENERIC_SLICE'
                    and c['connections'].get('F') == [bit]]
        assert len(matching) == 1
        driver = matching[0]
        assert driver['attributes']['NEXTPNR_BEL'] == 'X14Y11_SLICE%d' % (4+lane)
        assert int(driver['parameters']['FF_USED'], 2) == 0
        assert not driver['connections']['Q']
        inputs = driver['connections']['I']
        assert source in inputs
        position = inputs.index(source)
        init = int(driver['parameters']['INIT'], 2)
        assert all(((init >> i) & 1) == ((i >> position) & 1) for i in range(16))
        assert bit != source
        drivers.append(bit)
    assert len(set(drivers)) == 2
    if shared_logic:
        assert cells['producer']['connections']['F'] == [source]
        assert cells['producer']['attributes'].get('NEXTPNR_BEL') not in ('X14Y11_SLICE4', 'X14Y11_SLICE5')


def test_existing_dedicated_lut_driver_needs_no_presentation_buffer(tmp_path):
    cells = {'input': iob('X20Y13_IPAD1', 'O', 10),
             'producer': logic(0x5555, 10, 20), 'pad0': iob('X0Y4_IOB0', 'I', 20)}
    document = dict(modules={'top': dict(attributes={'top': '1'}, ports={}, cells=cells,
        netnames={'input_net': {'bits': [10], 'attributes': {}},
                  'source_net': {'bits': [20], 'attributes': {}}})})
    result, log, output = support._run(tmp_path, 'dedicated', document, '--no-route')
    assert result.returncode == 0, log
    cells = json.loads(output.read_text())['modules']['top']['cells']
    assert cells['producer']['attributes']['NEXTPNR_BEL'] == 'X14Y11_SLICE4'
    assert cells['producer']['connections']['F'] == cells['pad0']['connections']['I']
    assert 'inserted dedicated PIN_' not in log
