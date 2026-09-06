"""Placement must account for capacity-one entries shared by ordinary logic nets."""
import pytest
from test_native_endpoint_legality import _run, _slice


@pytest.mark.parametrize('mode', ['conflict', 'same_net', 'alternate_sink'])
def test_logic_entry_cut_ownership(tmp_path, mode):
    cells = {}
    for name, bel, bit in [('source_a', 'X4Y3_SLICE14', 2),
                           ('source_b', 'X9Y1_SLICE10', 3)]:
        cell = _slice(bel=bel, output_bit=bit)
        cell['parameters']['INIT'] = format(0, '016b')
        cell['connections']['I'] = ['x'] * 4
        cells[name] = cell
    for name, bel, bit in [('sink_a', 'X1Y1_SLICE12', 2),
                           ('sink_b', 'X9Y1_SLICE8' if mode == 'alternate_sink'
                            else 'X1Y1_SLICE14', 2 if mode == 'same_net' else 3)]:
        cell = _slice(bel=bel)
        cell['connections'] = {'I': [bit, 'x', 'x', 'x'], 'F': [], 'Q': []}
        cells[name] = cell
    if mode == 'same_net':
        del cells['source_b']
    design = {'modules': {'top': {
        'attributes': {'top': 1}, 'ports': {}, 'cells': cells,
        'netnames': {'a': {'bits': [2], 'attributes': {}},
                     'b': {'bits': [3], 'attributes': {}}},
    }}}
    result, log, _ = _run(tmp_path, mode, design,
                          '--no-pack', '--no-route', '--placer', 'heap',
                          condplace=False, pinpack=False)
    if mode == 'conflict':
        assert result.returncode != 0, log
        assert 'require shared entry X2Y1_RMUX48' in log
    else:
        assert result.returncode == 0, log
