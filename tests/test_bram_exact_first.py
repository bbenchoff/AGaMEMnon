"""A clean_edge observation at the exact BramTILE coordinate outranks the
coordinate-less resolver key (physical observation at the coordinate beats a
translation across tiles)."""
import csv
from pathlib import Path

import pytest

from agamemnon.engine.features.bram import BramFeature, BramState

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb"
NPG = {"RMUX": 6, "IMUX": 4}


@pytest.fixture
def cells():
    with (CHIPDB / "bram_cell.csv").open(newline="") as stream:
        return {(int(r["x"]), int(r["y"]), r["mux"], int(r["sel"])):
                (int(r["byte"]), int(r["mask"])) for r in csv.DictReader(stream)}


def _state():
    return BramState(cells=[(13, 4, "X13Y4_BRAM")], resolver={
        "NPI": {"RMUX": 6, "IMUX": 4}, "BS": {"RMUX": 10, "IMUX": 12},
        "L0": {"RMUX|60|RMUX|86|-1|0": [0, 8]}, "L1": {}, "L2": {}, "CTRL": {}})


def test_exact_observation_overrules_a_disagreeing_resolver_key(cells, capsys):
    state = _state()
    sets = []
    assert BramFeature().resolve_route(state, (14, 4, "RMUX", 86), (13, 4, "RMUX", 60),
                                       cells, NPG, sets, [], exact_pair=(5, 7))
    assert set(sets) == {cells[13, 4, "CFG_RMUX10", 5], cells[13, 4, "CFG_RMUX10", 7]}
    assert state.overruled == 1
    assert "overruled by the exact observation at X13Y4" in capsys.readouterr().out


def test_agreeing_exact_observation_is_silent_and_resolver_alone_still_works(cells, capsys):
    state = _state()
    sets = []
    assert BramFeature().resolve_route(state, (14, 4, "RMUX", 86), (13, 4, "RMUX", 60),
                                       cells, NPG, sets, [], exact_pair=(0, 8))
    assert set(sets) == {cells[13, 4, "CFG_RMUX10", 0], cells[13, 4, "CFG_RMUX10", 8]}
    assert state.overruled == 0 and "overruled" not in capsys.readouterr().out
    state, sets = _state(), []
    assert BramFeature().resolve_route(state, (14, 4, "RMUX", 86), (13, 4, "RMUX", 60),
                                       cells, NPG, sets, [])
    assert set(sets) == {cells[13, 4, "CFG_RMUX10", 0], cells[13, 4, "CFG_RMUX10", 8]}


def test_exact_observation_alone_resolves_a_pip_the_resolver_cannot(cells):
    state = _state()
    sets = []
    assert BramFeature().resolve_route(state, (15, 4, "RMUX", 86), (13, 4, "RMUX", 60),
                                       cells, NPG, sets, [], exact_pair=(3, 9))
    assert set(sets) == {cells[13, 4, "CFG_RMUX10", 3], cells[13, 4, "CFG_RMUX10", 9]}
