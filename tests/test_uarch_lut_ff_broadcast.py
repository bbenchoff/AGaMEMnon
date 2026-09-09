"""Compiled packing of a shared data function into its consuming registers."""
import json
import pytest
import test_uarch_register_input_legality as support


def design(count=2, *, observer=False, feedback=False, locked=False):
    cells = {'driver': support._raw_dff('driver', 2, 3, 10)}
    inputs = [20 if feedback else 10, '0', '0', '0']
    cells['data'] = support._lut('data', 0x5555, inputs, 11)
    cells['data']['attributes']['module_not_derived'] = '00000000000000000000000000000001'
    if locked:
        cells['data']['attributes']['BEL'] = 'X14Y8_SLICE0'
    for i in range(count):
        cells['state%d' % i] = support._raw_dff('state%d' % i, 2, 11, 20+i)
    if observer:
        cells['observe'] = support._lut('observe', 0xAAAA, [11, '0', '0', '0'], 40)
    return support._design(cells, {'clock': 2, 'driver_d': 3, 'driver_q': 10, 'data': 11})


@pytest.mark.parametrize('count', [2, 4, 16])
def test_broadcast_fuses_each_register_without_a_shared_data_slice(tmp_path, monkeypatch, count):
    document = design(count)
    monkeypatch.delenv('AGRV2K_LUT_FF_BROADCAST', raising=False)
    off, off_log, off_path = support._run(tmp_path, 'off', document, '--pack-only')
    assert off.returncode == 0, off_log
    monkeypatch.setenv('AGRV2K_LUT_FF_BROADCAST', '1')
    on, on_log, on_path = support._run(tmp_path, 'on', document, '--pack-only')
    assert on.returncode == 0, on_log
    before = json.loads(off_path.read_text())['modules']['top']['cells']
    after = json.loads(on_path.read_text())['modules']['top']['cells']
    n_before = sum(c['type'] == 'GENERIC_SLICE' for c in before.values())
    n_after = sum(c['type'] == 'GENERIC_SLICE' for c in after.values())
    assert n_after == n_before - 1
    fused = [c for c in after.values() if c.get('attributes', {}).get(
        'AGRV2K_REGISTER_INPUT_MODE') == 'LUT_COMPUTE_TO_FF']
    assert len(fused) == count
    assert all(int(c['parameters']['INIT'], 2) == 0x5555 for c in fused)
    # Every register retains its own Q, and every fused LUT sees the same
    # original driver. A duplicated F output must not substitute for state Q.
    assert len({tuple(c['connections']['Q']) for c in fused}) == count
    # Unused axes may acquire distinct local constant nets during packing;
    # INIT=0x5555 depends only on I0, whose original signal must be shared.
    assert len({c['connections']['I'][0] for c in fused}) == 1
    assert 'duplicated 1 shared data LUT(s)' in on_log


@pytest.mark.parametrize('boundary', ['observer', 'feedback', 'locked'])
def test_broadcast_preserves_noneligible_compositions(tmp_path, monkeypatch, boundary):
    monkeypatch.setenv('AGRV2K_LUT_FF_BROADCAST', '1')
    result, log, _ = support._run(tmp_path, boundary, design(**{boundary: True}), '--pack-only')
    assert result.returncode == 0, log
    assert 'duplicated 0 shared data LUT(s)' in log


@pytest.mark.parametrize('boundary', ['net_keep', 'ff_keep'])
def test_broadcast_preserves_user_keep_constraints(tmp_path, monkeypatch, boundary):
    document = design()
    top = document['modules']['top']
    if boundary == 'net_keep':
        top['netnames']['data']['attributes']['keep'] = '1'
    else:
        top['cells']['state0']['attributes']['keep'] = '1'
    monkeypatch.setenv('AGRV2K_LUT_FF_BROADCAST', '1')
    result, log, _ = support._run(tmp_path, boundary, document, '--pack-only')
    assert result.returncode == 0, log
    assert 'duplicated 0 shared data LUT(s)' in log


@pytest.mark.parametrize('value', ['0', 'invalid'])
def test_broadcast_switch_is_explicit(tmp_path, monkeypatch, value):
    monkeypatch.setenv('AGRV2K_LUT_FF_BROADCAST', value)
    result, log, _ = support._run(tmp_path, 'switch', design(), '--pack-only')
    if value == '0':
        assert result.returncode == 0, log
        assert 'additional copy/copies' not in log
    else:
        assert result.returncode != 0
        assert 'AGRV2K_LUT_FF_BROADCAST must be 0 or 1' in log
