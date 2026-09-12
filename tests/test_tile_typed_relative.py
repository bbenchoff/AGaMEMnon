"""Opt-in tile-typed relative keying (AGAMEMNON_TILE_TYPED_RELATIVE=1).

A BramTILE destination may no longer USE a LogicTile-derived tile-relative
selector; it consults a BRAM-scoped table built from BramTILE observations
only, which must agree across at least two BramTILEs. Off by default: the
option admits BRAM-derived keys as well as refusing LogicTile-derived ones.
"""
from agamemnon.engine import routing_selectors as rs
from agamemnon.engine.routing_tiers import SelectorCertainty


LOGIC_OBS = {(x, 7, "RMUX", 85, "RMUX", x, 6, 92): (5, 9) for x in (2, 5, 9, 14, 20)}
BRAM_OBS = {(13, 2, "RMUX", 85, "RMUX", 13, 1, 92): (6, 9),
            (13, 3, "RMUX", 85, "RMUX", 13, 2, 92): (6, 9)}
KEY = ("RMUX", 85, "RMUX", 92, 0, 1)


def test_bram_table_is_built_from_bram_destinations_only_and_needs_two_tiles():
    logic, _ = rs.relative_edges({**LOGIC_OBS, **BRAM_OBS})
    assert logic[KEY] == (5, 9)                      # LogicTile table unchanged by BRAM rows
    bram, conflicts = rs.bram_relative_edges({**LOGIC_OBS, **BRAM_OBS})
    assert bram == {KEY: (6, 9)} and not conflicts
    single = {k: v for k, v in BRAM_OBS.items() if k[1] == 2}
    assert rs.bram_relative_edges({**LOGIC_OBS, **single}) == ({}, frozenset())


def test_conflicting_bram_observations_are_withdrawn_not_averaged():
    obs = dict(BRAM_OBS)
    obs[(13, 4, "RMUX", 85, "RMUX", 13, 3, 92)] = (4, 9)
    bram, conflicts = rs.bram_relative_edges(obs)
    assert KEY not in bram and KEY in conflicts


def test_nonportable_keys_stay_withdrawn_in_the_bram_table():
    obs = {(13, y, "RMUX", 59, "RMUX", 13, y - 1, 87): (2, 9) for y in (2, 3)}
    bram, conflicts = rs.bram_relative_edges(obs)
    assert ("RMUX", 59, "RMUX", 87, 0, 1) in conflicts and not bram


def test_relative_table_for_switches_only_bram_destinations_when_typed():
    logic, bram = {"L": 1}, {"B": 2}
    assert rs.relative_table_for(logic, bram, 13, 4, True) is bram
    assert rs.relative_table_for(logic, bram, 13, 9, True) is logic     # MCU column, not a BramTILE
    assert rs.relative_table_for(logic, bram, 14, 4, True) is logic
    assert rs.relative_table_for(logic, bram, 13, 4, False) is logic    # off by default


def test_tile_typed_flag_reads_the_environment():
    assert not rs.tile_typed_enabled({})
    assert rs.tile_typed_enabled({rs.TILE_TYPED_ENV: "1"})
    assert not rs.tile_typed_enabled({rs.TILE_TYPED_ENV: "0"})


def _row(dx, dy):
    return {"dst_res": "RMUX85", "dst_x": str(dx), "dst_y": str(dy),
            "src_res": "RMUX92", "src_x": str(dx), "src_y": str(dy - 1)}


def _family(res):
    return res.rstrip("0123456789")


def test_classifier_refuses_logic_key_at_bram_when_typed_and_admits_bram_key():
    logic, logic_conf = rs.relative_edges(LOGIC_OBS)
    off = SelectorCertainty({}, logic, logic_conf, allow_closed_form=False)
    assert off.classify(_row(13, 4), _family)["sel"] == (5, 9)   # today: LogicTile key leaks onto BRAM
    on = SelectorCertainty({}, logic, logic_conf, allow_closed_form=False,
                           relative_edge_bram={}, tile_typed=True)
    assert on.classify(_row(13, 4), _family) is None             # refused: no BRAM evidence
    assert on.classify(_row(14, 7), _family)["sel"] == (5, 9)     # LogicTiles untouched
    bram, bram_conf = rs.bram_relative_edges(BRAM_OBS)
    on_with = SelectorCertainty({}, logic, logic_conf, allow_closed_form=False,
                                relative_edge_bram=bram, relative_conflicts_bram=bram_conf,
                                tile_typed=True)
    assert on_with.classify(_row(13, 4), _family)["sel"] == (6, 9)
