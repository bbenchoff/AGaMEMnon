import json

import pytest

from agamemnon.engine import qualified_bram_tmux9 as bram


@pytest.mark.parametrize('profile', sorted(bram.PROFILES))
def test_source_reservations_match_final_qualified_trees(tmp_path, profile):
    nets = {name: {'bits': [i], 'attributes': {'keep': 1}}
            for i, name in enumerate(bram.expected_routes(profile))}
    nets['unrelated'] = {'bits': [100], 'attributes': {}}
    source = tmp_path / 'source.json'
    blackbox = {'attributes': {'blackbox': 1}, 'ports': {}}
    source.write_text(json.dumps({'modules': {'top': {'netnames': nets,
        'cells': {'consumer': {'connections': {'I': ['0']}},
                  'src_d1': {'type': 'GENERIC_SLICE', 'connections': {'F': [200]},
                             'parameters': {'INIT': '1'*16 if '-i0-d1-' in profile else '0'*16,
                                            'FF_USED': '0'}}}}, 'MCU_DIN': blackbox}}))
    bram.prepare_route_reservations(source, profile)
    result = json.loads(source.read_text())['modules']['top']['netnames']
    assert json.loads(source.read_text())['modules']['MCU_DIN'] == blackbox
    for name, expected in bram.expected_routes(profile).items():
        assert result[name]['attributes']['AGAMEMNON_REQUIRED_ROUTE'] == expected
        assert result[name]['attributes']['keep'] == 1
        assert result[name]['bits'] == nets[name]['bits']
    assert result['unrelated'] == nets['unrelated']
    assert result['$PACKER_GND_NET']['attributes']['AGAMEMNON_REQUIRED_ROUTE'] == bram.GROUND_ROUTES[profile]


def test_missing_required_net_leaves_source_unchanged(tmp_path):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'modules': {'top': {'netnames': {'h0': {}}}}}))
    before = source.read_bytes()
    with pytest.raises(ValueError, match='lost nets'):
        bram.prepare_route_reservations(source, 'bram-tmux9-i0-d1-we1')
    assert source.read_bytes() == before


@pytest.mark.parametrize('mutation', ['absent', 'init', 'register', 'wrong_bel', 'occupied'])
def test_data_source_placement_rejects_ambiguous_or_changed_source(tmp_path, mutation):
    profile = 'bram-tmux9-i1-d0-we0'
    cells = {'src_d1': {'type': 'GENERIC_SLICE', 'connections': {'F': [200], 'I': ['0']},
                       'parameters': {'INIT': '0'*16, 'FF_USED': '0'}, 'attributes': {}}}
    if mutation == 'absent':
        cells = {'consumer': {'connections': {'I': ['0']}}}
    elif mutation == 'init':
        cells['src_d1']['parameters']['INIT'] = '1'*16
    elif mutation == 'register':
        cells['src_d1']['parameters']['FF_USED'] = '1'
    elif mutation == 'wrong_bel':
        cells['src_d1']['attributes']['BEL'] = 'X1Y1_SLICE0'
    else:
        cells['foreign'] = {'attributes': {'BEL': bram.DATA_SOURCE_BELS[profile]}}
    nets = {name: {'bits': [i+300]} for i,name in enumerate(bram.expected_routes(profile))}
    source = tmp_path/'source.json'
    source.write_text(json.dumps({'modules': {'top': {'netnames': nets, 'cells': cells}}}))
    before = source.read_bytes()
    with pytest.raises(ValueError, match='data source'):
        bram.prepare_route_reservations(source, profile)
    assert source.read_bytes() == before
