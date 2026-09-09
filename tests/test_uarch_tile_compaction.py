"""Compiled safeguards for optional post-placement compaction."""
import json
import pytest
import test_uarch_shared_control_legality as support


def test_compaction_preserves_locked_bel_and_register_function(tmp_path, monkeypatch):
    design = support._design(support._slice(mode='NONE', bel='X14Y8_SLICE0'))
    placements = []
    for value in ('0', '1'):
        monkeypatch.setenv('AGRV2K_TILE_COMPACT', value)
        result, log, output = support._run(tmp_path, 'locked_' + value, design,
                                           '--no-route', '--placer', 'heap')
        assert result.returncode == 0, log
        cell = json.loads(output.read_text())['modules']['top']['cells']['state']
        placements.append((cell['attributes']['NEXTPNR_BEL'], cell['parameters'], cell['connections']))
        if value == '1':
            assert '0 accepted cluster moves' in log
    assert placements[0] == placements[1]
    assert placements[0][0] == 'X14Y8_SLICE0'


@pytest.mark.parametrize('value', ['yes', '-1'])
def test_compaction_rejects_malformed_option(tmp_path, monkeypatch, value):
    monkeypatch.setenv('AGRV2K_TILE_COMPACT', value)
    result, log, _ = support._run(tmp_path, 'bad',
        support._design(support._slice(mode='NONE', bel='X14Y8_SLICE0')),
        '--no-route', '--placer', 'heap')
    assert result.returncode != 0
    assert 'AGRV2K_TILE_COMPACT must be 0 or 1' in log


def test_compaction_does_not_admit_unsupported_control(tmp_path, monkeypatch):
    monkeypatch.setenv('AGRV2K_TILE_COMPACT', '1')
    result, log, _ = support._run(tmp_path, 'unsupported',
        support._design(support._slice(mode='ASYNC_CLEAR_POS_ZERO', control='bound',
                                      bel='X14Y8_SLICE0')),
        '--no-route', '--placer', 'heap')
    assert result.returncode != 0
    assert support.UNSUPPORTED in log
