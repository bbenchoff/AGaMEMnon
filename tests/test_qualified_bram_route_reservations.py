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
    source.write_text(json.dumps({'modules': {'top': {'netnames': nets}, 'MCU_DIN': blackbox}}))
    bram.prepare_route_reservations(source, profile)
    result = json.loads(source.read_text())['modules']['top']['netnames']
    assert json.loads(source.read_text())['modules']['MCU_DIN'] == blackbox
    for name, expected in bram.expected_routes(profile).items():
        assert result[name]['attributes']['AGAMEMNON_REQUIRED_ROUTE'] == expected
        assert result[name]['attributes']['keep'] == 1
        assert result[name]['bits'] == nets[name]['bits']
    assert result['unrelated'] == nets['unrelated']


def test_missing_required_net_leaves_source_unchanged(tmp_path):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'modules': {'top': {'netnames': {'h0': {}}}}}))
    before = source.read_bytes()
    with pytest.raises(ValueError, match='lost nets'):
        bram.prepare_route_reservations(source, 'bram-tmux9-i0-d1-we1')
    assert source.read_bytes() == before
