"""Distinct logical memories must retain distinct physical terminals in packing."""
import copy

import pytest

from test_native_bram_bridges import run
from test_native_bram_unassigned_output import _design


def memories(count, explicit=None):
    fixture = _design(None)
    module = fixture['modules']['top']
    ram = module['cells'].pop('ram')
    sink = module['cells'].pop('sink')
    for index in range(count):
        memory, consumer = copy.deepcopy(ram), copy.deepcopy(sink)
        bit = 10 + index
        memory['connections']['DataOutA[0]'] = [bit]
        consumer['connections']['I'][0] = bit
        if explicit and index in explicit:
            memory['attributes']['BEL'] = explicit[index]
        module['cells'][f'storage_{index}'] = memory
        module['cells'][f'consumer_{index}'] = consumer
    module['netnames'].pop('read')
    return fixture


@pytest.mark.parametrize('count', [1, 2, 4])
def test_live_memories_receive_distinct_sites(tmp_path, count):
    result, transcript, packed = run(tmp_path, memories(count))
    assert result.returncode == 0, transcript
    for index in range(count):
        assert f"assigned BRAM 'storage_{index}' to distinct site X13Y{4-index}_BRAM" in transcript
        assert f'storage_{index}' in packed['cells']


def test_requested_site_is_reserved_before_unconstrained_memory(tmp_path):
    result, transcript, packed = run(tmp_path, memories(2, {1: 'X13Y4_BRAM'}))
    assert result.returncode == 0, transcript
    assert "assigned BRAM 'storage_0' to distinct site X13Y3_BRAM" in transcript
    assert 'storage_1' in packed['cells']


def test_conflicting_explicit_sites_fail_instead_of_aliasing(tmp_path):
    result, transcript, packed = run(tmp_path, memories(2, {0: 'X13Y4_BRAM', 1: 'X13Y4_BRAM'}))
    assert result.returncode > 0 and packed is None
    assert 'requested BRAM site X13Y4_BRAM is already occupied' in transcript


def test_capacity_exhaustion_fails_before_reserving_duplicate_terminals(tmp_path):
    result, transcript, packed = run(tmp_path, memories(5))
    assert result.returncode > 0 and packed is None
    assert 'insufficient distinct BRAM sites' in transcript
