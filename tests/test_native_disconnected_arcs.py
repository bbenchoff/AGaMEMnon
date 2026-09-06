"""Exact logic reachability must reject disconnected placed arcs."""
import json
import pytest
from test_native_endpoint_legality import _run, _slice


@pytest.mark.parametrize('source_bel,sink_bel,pin', [
    ('X3Y4_SLICE4', 'X3Y3_SLICE0', 2),
    ('X4Y4_SLICE4', 'X1Y1_SLICE2', 0),
])
@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('movable', [False, True], ids=['fixed', 'movable'])
def test_disconnected_arc(tmp_path, source_bel, sink_bel, pin, enabled, movable):
    source = _slice(bel=source_bel, output_bit=2)
    source['parameters']['INIT'] = format(0, '016b')
    source['connections']['I'] = ['x'] * 4
    sink = _slice(bel=None if movable else sink_bel)
    sink['parameters']['INIT'] = format(0xf0f0 if pin == 2 else 0xaaaa, '016b')
    inputs = ['x'] * 4
    inputs[pin] = 2
    sink['connections'] = {'I': inputs, 'F': [], 'Q': []}
    design = {'modules': {'top': {'attributes': {'top': 1}, 'ports': {},
                                 'cells': {'source': source, 'sink': sink},
                                 'netnames': {'data': {'bits': [2], 'attributes': {}}}}}}
    result, log, output = _run(tmp_path, 'disconnected', design,
                              '--no-pack', '--no-route', '--placer', 'heap',
                              condplace=False, pinpack=False,
                              env_overrides={'AGRV2K_LOGIC_DOMINATORS': '1' if enabled else None,
                                             'AGRV2K_AUDIT_DOMINATOR_CACHE': '1'})
    assert 'differs from full recomputation' not in log
    if not movable:
        assert result.returncode != 0, log
        assert ('disconnected placed sink' if enabled else 'local output topology cannot conduct') in log
    else:
        assert result.returncode == 0, log
        if enabled:
            cells = json.loads(output.read_text())['modules']['top']['cells']
            assert cells['sink']['attributes']['NEXTPNR_BEL'] != sink_bel
