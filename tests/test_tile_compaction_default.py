"""Automatic compaction must preserve replay and fail-closed retry boundaries."""
from types import SimpleNamespace

import pytest

from agamemnon import cli
from agamemnon.engine import attempt_ladder as ladder


def args(**values):
    return SimpleNamespace(**dict({'uarch': True}, **values))


def record(log, outcome=ladder.NOT_ROUTED):
    return ladder.AttemptRecord(1, 16, '4', 0, outcome, log)


def test_ordinary_build_compacts_and_fallback_is_one_way():
    env = {}
    assert cli._set_default_tile_compaction(args(), env)
    assert env['AGRV2K_TILE_COMPACT'] == '1'
    disabled = {}
    assert not cli._set_default_tile_compaction(args(_tile_compaction_disabled=True), disabled)
    assert disabled['AGRV2K_TILE_COMPACT'] == '0'
    assert not cli._set_default_tile_compaction(args(_tile_compaction_disabled=True), disabled)


@pytest.mark.parametrize('values', [
    {'uarch': False}, {'qualified_checkpoint': 'fixture'},
    {'qualified_bram_write': 'fixture'}, {'research_unsafe': True},
])
def test_qualified_and_nonordinary_builds_keep_their_placement(values):
    env = {}
    assert not cli._set_default_tile_compaction(args(**values), env)
    assert 'AGRV2K_TILE_COMPACT' not in env


@pytest.mark.parametrize('env', [
    {'AGRV2K_TILE_COMPACT': '0'}, {'AGRV2K_TILE_COMPACT': '1'},
    {'AGRV2K_TILE_COMPACT': 'invalid'}, {'AGRV2K_REPLAY_BELS': 'map.json'},
    {'AGRV2K_REPLAY_BELS_HARD': 'map.json'},
])
def test_explicit_or_replayed_placement_is_not_reinterpreted(env):
    original = dict(env)
    assert not cli._set_default_tile_compaction(args(), env)
    assert env == original


PLACEMENT = record('ERROR: Unable to place cell')
ROUTING = record("ERROR: Failed to route arc 1.0 of net 'state', from X1Y1_RMUX01 to X2Y1_IMUX00.\n")


def test_compact_exhaustion_allows_uncompacted_retry():
    assert cli._tile_compaction_fallback_allowed(True, [PLACEMENT, ROUTING])
    assert not cli._tile_compaction_fallback_allowed(False, [PLACEMENT, ROUTING])
    assert not cli._tile_compaction_fallback_allowed(True, [])


@pytest.mark.parametrize('other', [
    record('unknown implementation failure'), record('timeout after 30 seconds'),
    record('Unable to place cell\nAGaMEMnon place&route time limit exceeded (30 seconds)'),
    record('Routing complete', ladder.SUCCESS),
    record('Routing complete', ladder.TIMING_FAILED),
    record('Unable to place cell', ladder.ABORTED),
    record('Unable to place cell', ladder.NONRETRYABLE),
])
def test_fallback_does_not_hide_unclassified_or_fatal_failures(other):
    assert not cli._tile_compaction_fallback_allowed(True, [PLACEMENT, other])
