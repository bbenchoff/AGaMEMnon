"""Every bram_pip_cfg.csv row must write the selector cells of its own destination node.

Until 2026-09-11 rows 506-507 (RMUX82 <- RMUX93, ddx -1) carried RMUX64's cells
(CFG_RMUX10 selectors 45/47, the same bits as the RMUX64 <- RMUX13 rows) under
RMUX82's key.  52 of 52 vendor builds that route X13Y4_RMUX82 <- X14Y4_RMUX93 put
RMUX82's codeword at CFG_RMUX13 (5, 7) and leave RMUX64 to its own source; every
open-flow image that used the row left RMUX82 blank and put a third bit on RMUX64
(AG32-Docs docs/BRAM_PIP_CFG_DEFECT_20260911.md).  The table row was consulted
before the exact clean_edge observation, so no rank rule could catch it; this
gate does, and bitgen refuses the whole table rather than drive the wrong mux.
"""
import csv
from pathlib import Path

import pytest

from agamemnon.engine.features.bram import BramFeature, BramState

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb"
ROW = ("RMUX82", "RMUX93", -1, 0)


@pytest.fixture(scope="module")
def cells():
    return BramFeature._selector_cells(CHIPDB)


def _exact_pips(path):
    pips = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = (row["dst_res"], row["src_res"], int(row["ddx"]), int(row["ddy"]))
            pips.setdefault(key, []).append((int(row["byte"]), int(row["mask"])))
    return pips


def test_every_shipped_row_writes_its_own_destination_node(cells):
    pips = _exact_pips(CHIPDB / "bram_pip_cfg.csv")
    assert ROW not in pips, "the withdrawn RMUX82 <- RMUX93 (ddx -1) rows are back"
    assert BramFeature.inconsistent_exact_pips(pips, cells) == []


def test_the_withdrawn_rows_are_named_with_their_true_owner(cells):
    rejected = BramFeature.inconsistent_exact_pips(
        {ROW: [(71446, 32), (71562, 128)]}, cells)
    assert [(key, bit) for key, bit, _owners in rejected] == [
        (ROW, (71446, 32)), (ROW, (71562, 128))]
    assert [owners for _key, _bit, owners in rejected] == [
        [("CFG_RMUX10", 47)], [("CFG_RMUX10", 45)]]


def test_the_observed_codeword_in_the_destinations_own_block_passes(cells):
    # block 40 of CFG_RMUX13 + the observed (5, 7)
    bits = [cells[(13, 4, "CFG_RMUX13", 45)], cells[(13, 4, "CFG_RMUX13", 47)]]
    assert BramFeature.inconsistent_exact_pips({ROW: bits}, cells) == []


def test_a_bit_outside_every_bram_cell_is_rejected(cells):
    rejected = BramFeature.inconsistent_exact_pips({ROW: [(1, 1)]}, cells)
    assert rejected == [(ROW, (1, 1), [])]


def test_bufmux_exit_rows_are_not_judged_by_the_bram_cell_table(cells):
    # ddx 1: the destination is the X14Y4 LogicTile, whose cells are in pips_full.csv
    assert BramFeature.inconsistent_exact_pips(
        {("RMUX5", "BufMUX3", 1, 0): [(1, 1)]}, cells) == []


def test_bufmux_rows_that_stay_inside_x13y4_are_judged(cells):
    rejected = BramFeature.inconsistent_exact_pips(
        {("RMUX15", "BufMUX17", 0, 0): [(1, 1)]}, cells)
    assert rejected == [(("RMUX15", "BufMUX17", 0, 0), (1, 1), [])]


def test_loading_a_table_on_the_wrong_node_refuses(cells):
    state = BramState()
    state.exact_pips[ROW] = [(71446, 32), (71562, 128)]
    with pytest.raises(ValueError, match=r"RMUX82 <- RMUX93 d=\(-1,0\).*CFG_RMUX10.*refusing"):
        BramFeature()._refuse_inconsistent_exact_pips(state, CHIPDB)


def test_loading_the_shipped_table_is_accepted():
    state = BramState()
    state.exact_pips = _exact_pips(CHIPDB / "bram_pip_cfg.csv")
    BramFeature()._refuse_inconsistent_exact_pips(state, CHIPDB)
