"""Control routes own one source-dependent field, not a family-wide blob."""
import csv
from pathlib import Path

import pytest

from agamemnon.engine.features.bram import BramFeature, BramState

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb"
with (CHIPDB / "bram_control_codewords.csv").open(newline="") as stream:
    ROWS = list(csv.DictReader(stream))


@pytest.fixture
def cells():
    with (CHIPDB / "bram_cell.csv").open(newline="") as stream:
        return {(int(r['x']), int(r['y']), r['mux'], int(r['sel'])):
                (int(r['byte']), int(r['mask'])) for r in csv.DictReader(stream)}


def state_for(dual=False):
    state = BramState(dual_rw=dual, resolver={"CTRL": {"KMUX|3": [29, 34, 40, 43]}})
    BramFeature._load_control_codewords(state, CHIPDB)
    return state


@pytest.mark.parametrize("dual", [False, True])
@pytest.mark.parametrize("row", ROWS)
def test_source_codeword_replaces_only_its_field(row, dual, cells):
    state = state_for(dual)
    df, di, sf, si, ddx, ddy = (row['dst_family'], int(row['dst_index']),
        row['src_family'], int(row['src_index']), int(row['ddx']), int(row['ddy']))
    config, clear, sels = state.exact_codewords[df, di, sf, si, ddx, ddy]
    owned = {cells[13, 4, config, s] for s in clear}
    # Start with every stale field bit set plus unrelated controls.
    neighbor = (999999, 1)
    state.sets = list(owned) + [neighbor]
    sets, clears = [], []
    assert BramFeature().resolve_route(state, (13-ddx, 4-ddy, sf, si),
        (13, 4, df, di), cells, {}, sets, clears)
    assert set(clears) == owned
    assert set(sets) == {cells[13, 4, config, s] for s in sels}
    assert state.sets == [neighbor]
    assert set(sets).issubset(owned)


@pytest.mark.parametrize("dual", [False, True])
def test_unknown_source_cannot_fall_back_to_aggregate_or_dual_blob(dual, cells):
    state = state_for(dual)
    state.sets = [(123, 1)]
    sets, clears = [], []
    assert BramFeature().resolve_route(state, (13, 4, "TMUX", 1),
        (13, 4, "KMUX", 3), cells, {}, sets, clears) is False
    assert state.sets == [(123, 1)] and not sets and not clears


def test_second_source_for_same_control_field_is_rejected_atomically(cells):
    state = state_for()
    sets, clears = [], []
    feature = BramFeature()
    assert feature.resolve_route(state, (13, 4, "TMUX", 9),
        (13, 4, "KMUX", 4), cells, {}, sets, clears)
    before = (list(sets), list(clears), list(state.sets))
    with pytest.raises(SystemExit, match="conflicting BRAM control sources"):
        feature.resolve_route(state, (13, 4, "TMUX", 11),
            (13, 4, "KMUX", 4), cells, {}, sets, clears)
    assert (sets, clears, state.sets) == before


def test_missing_field_cell_fails_before_mutation(cells):
    state = state_for()
    cells.pop((13, 4, "CFG_KMUX", 27))
    sets, clears = [], []
    with pytest.raises(SystemExit, match="has no physical cell"):
        BramFeature().resolve_route(state, (13, 4, "TMUX", 13),
            (13, 4, "KMUX", 3), cells, {}, sets, clears)
    assert not sets and not clears and not state.control_owners


def test_scoped_checkpoint_codeword_has_explicit_precedence():
    state = BramState()
    key = ("TMUX", 9, "RMUX", 86, -2, 0)
    scoped = ("CFG_TMUX", [76, 78, 91, 95], [76, 78])
    state.exact_codewords[key] = scoped
    BramFeature._load_control_codewords(state, CHIPDB)
    assert state.exact_codewords[key] == scoped


def test_source_position_changes_codeword():
    state = state_for()
    assert state.exact_codewords["TMUX", 13, "RMUX", 20, -2, 0][2] == [108, 110]
    assert state.exact_codewords["TMUX", 13, "RMUX", 20, -3, 0][2] == [104, 111]
    assert len(ROWS) == 26


@pytest.mark.parametrize("bad,diagnostic", [
    ("KMUX,3,TMUX,13,0,0,29;40\n", "outside its field"),
    ("KMUX,3,TMUX,13,0,0,29;29\n", "outside its field"),
    ("KMUX,3,TMUX,13,0,0,29;34\n" * 2, "duplicate"),
    ("KMUX,10,TMUX,13,0,0,90;91\n", "invalid BRAM control destination"),
])
def test_invalid_control_table_fails_closed(tmp_path, bad, diagnostic):
    (tmp_path / "bram_control_codewords.csv").write_text(
        "dst_family,dst_index,src_family,src_index,ddx,ddy,set_selections\n" + bad)
    with pytest.raises(ValueError, match=diagnostic):
        BramFeature._load_control_codewords(BramState(), tmp_path)
