"""Recovery keeps a complete placement and still applies final architecture checks."""
import json
import pytest
from test_native_endpoint_legality import _run, _slice


@pytest.mark.parametrize('recover', [False, True])
def test_restore_complete_placement_after_refinement_budget(tmp_path, recover):
    source = _slice(bel='X4Y3_SLICE14', output_bit=2)
    source['parameters']['INIT'] = format(0, '016b')
    source['connections']['I'] = ['x'] * 4
    cells = {'source': source}
    for name in ['a', 'b']:
        sink = _slice()
        sink['connections'] = {'I': [2, 'x', 'x', 'x'], 'F': [], 'Q': []}
        cells[name] = sink
    design = {'modules': {'top': {'attributes': {'top': 1}, 'ports': {}, 'cells': cells,
                                 'netnames': {'data': {'bits': [2], 'attributes': {}}}}}}
    result, log, output = _run(tmp_path, 'retention', design,
                              '--no-pack', '--no-route', '--placer', 'heap',
                              condplace=False, pinpack=False,
                              env_overrides={'AGRV2K_HEAP_RETAIN_BEST': '1' if recover else None,
                                             'AGRV2K_HEAP_REFINEMENT_BUDGET': '1' if recover else None})
    assert result.returncode == 0, log
    assert ('restoring earlier complete placement for final validation' in log) == recover
    placed = json.loads(output.read_text())['modules']['top']['cells']
    assert len({c['attributes']['NEXTPNR_BEL'] for c in placed.values()}) == 3
    assert placed['source']['attributes']['NEXTPNR_BEL'] == 'X4Y3_SLICE14'
