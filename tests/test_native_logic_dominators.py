"""Internal shared routing cuts must be accounted for during placement."""
import json
import pytest
from test_native_endpoint_legality import _run, _slice


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('same_net', [False, True])
@pytest.mark.parametrize('movable', [False, True], ids=['fixed', 'movable'])
def test_internal_shared_dominator(tmp_path, enabled, same_net, movable):
    cells = {}
    for name, bel, bit in [('source_a', 'X1Y2_SLICE4', 2), ('source_b', 'X1Y3_SLICE4', 3)]:
        cell = _slice(bel=bel, output_bit=bit)
        cell['parameters']['INIT'] = format(0, '016b')
        cell['connections']['I'] = ['x'] * 4
        cells[name] = cell
    sink_a = _slice(bel='X2Y2_SLICE12')
    sink_a['parameters']['INIT'] = format(0xf0f0, '016b')  # Connected input I2.
    sink_a['connections'] = {'I': ['x', 'x', 2, 'x'], 'F': [], 'Q': []}
    cells['sink_a'] = sink_a
    sink_b = _slice(bel=None if movable else 'X1Y3_SLICE0')
    sink_b['connections'] = {'I': [2 if same_net else 3, 'x', 'x', 'x'], 'F': [], 'Q': []}
    cells['sink_b'] = sink_b
    if same_net:
        del cells['source_b']
    design = {'modules': {'top': {
        'attributes': {'top': 1}, 'ports': {}, 'cells': cells,
        'netnames': {'a': {'bits': [2], 'attributes': {}}, 'b': {'bits': [3], 'attributes': {}}},
    }}}
    result, log, output = _run(tmp_path, 'internal_cut', design,
                         '--no-pack', '--no-route', '--placer', 'heap',
                         condplace=False, pinpack=False,
                         env_overrides={'AGRV2K_LOGIC_DOMINATORS': '1' if enabled else None,
                                        'AGRV2K_AUDIT_DOMINATOR_CACHE': '1'})
    assert 'differs from full recomputation' not in log
    if enabled and not same_net and not movable:
        assert result.returncode != 0, log
        assert 'shared dominator X1Y4_RMUX68' in log
    else:
        assert result.returncode == 0, log
        if enabled and not same_net and movable:
            placed = json.loads(output.read_text())['modules']['top']['cells']['sink_b']
            assert placed['attributes']['NEXTPNR_BEL'] != 'X1Y3_SLICE0'
