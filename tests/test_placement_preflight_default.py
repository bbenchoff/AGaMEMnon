"""Ordinary preflight must leave explicit and retained profiles intact."""
from types import SimpleNamespace

import pytest

from agamemnon import cli


@pytest.mark.parametrize("compact", [None, "0", "1"])
def test_preflight_is_independent_of_compaction(compact):
    env = {} if compact is None else {"AGRV2K_TILE_COMPACT": compact}
    cli._set_default_placement_preflight(SimpleNamespace(uarch=True), env)
    assert env["AGRV2K_CONTROL_REPARTITION"] == "1"
    assert env["AGRV2K_CARRY_GRAPH_PREFLIGHT"] == "1"
    assert env.get("AGRV2K_TILE_COMPACT") == compact


@pytest.mark.parametrize("values,env", [
    ({"uarch": False}, {}),
    ({"qualified_checkpoint": "retained"}, {}),
    ({"qualified_bram_write": "retained"}, {}),
    ({"research_unsafe": True}, {}),
    ({}, {"AGRV2K_REPLAY_BELS": "placement.json"}),
    ({}, {"AGRV2K_REPLAY_BELS_HARD": "placement.json"}),
    ({}, {"AGRV2K_DUAL_NATIVE_CONTROL": "1"}),
    ({}, {"AGRV2K_MIXED_NATIVE_CONTROL": "1"}),
    ({}, {"AGRV2K_CONTROL_REPARTITION": "0", "AGRV2K_CARRY_GRAPH_PREFLIGHT": "0"}),
    ({}, {"AGRV2K_CONTROL_REPARTITION": "invalid", "AGRV2K_CARRY_GRAPH_PREFLIGHT": "invalid"}),
])
def test_profile_and_explicit_settings_preserved(values, env):
    original = dict(env)
    cli._set_default_placement_preflight(
        SimpleNamespace(**dict({"uarch": True}, **values)), env)
    assert env == original
