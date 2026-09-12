"""The resolver's family-level L2 tier is inference, not evidence, and must never name a
codeword.  Its classes are non-uniform at X13Y4 (IMUX<-IMUX same-tile, src index 12 mod 16:
(4,11), (5,11) and (6,9) among five exact rows) and no routed pip in the 4,023 tracked
netlists ever took a codeword from it.  An L2 key may still admit an edge to the graph,
but only where the edge was observed at that exact coordinate; bitgen then emits the
observation (AG32-Docs docs/BRAM_RESOLVER_L2_INFERENCE_20260911.md)."""
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
        "L0": {}, "L1": {}, "L2": {"IMUX|IMUX|0|0|12": [6, 9]}, "CTRL": {}})


def test_an_l2_only_key_names_no_codeword():
    state = _state()
    assert BramFeature._resolve(state, "IMUX", 27, "IMUX", 28, 0, 0) is None
    assert BramFeature._resolve_level(state, "IMUX", 27, "IMUX", 28, 0, 0) is None


def test_l0_and_l1_still_resolve():
    state = _state()
    state.resolver["L1"]["IMUX|3|IMUX|28|0|0"] = [5, 11]
    assert BramFeature._resolve(state, "IMUX", 27, "IMUX", 28, 0, 0) == [36 + 5, 36 + 11]
    assert BramFeature._resolve_level(state, "IMUX", 27, "IMUX", 28, 0, 0) == "L1"


def test_exact_observation_is_emitted_where_only_l2_would_have_answered(cells, capsys):
    state = _state()
    sets = []
    ok = BramFeature().resolve_route(state, (13, 4, "IMUX", 28), (13, 4, "IMUX", 27), cells, NPG,
                                     sets, route_clears=[], exact_pair=(5, 11))
    assert ok
    block = (27 % 4) * 12
    assert sorted(sets) == sorted([cells[(13, 4, "CFG_IMUX6", block + 5)], cells[(13, 4, "CFG_IMUX6", block + 11)]])
    assert "overruled" not in capsys.readouterr().out  # nothing to overrule: L2 was silent


def test_without_an_observation_the_pip_is_refused(cells):
    state = _state()
    sets = []
    ok = BramFeature().resolve_route(state, (13, 4, "IMUX", 28), (13, 4, "IMUX", 27), cells, NPG,
                                     sets, route_clears=[])
    assert not ok and sets == []


def test_shipped_resolver_keeps_its_l2_keys_for_admission_only():
    import json
    resolver = json.loads((CHIPDB / "bram_resolver.json").read_text(encoding="utf-8"))
    assert resolver["L2"], "L2 keys are the admission whitelist; withdrawing them prunes observed edges"
    assert "RMUX|22|RMUX|25|0|-1" not in resolver["L0"], "contradicted at X13Y3 by the site-read observation"
