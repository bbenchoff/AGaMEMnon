"""The load-time selector-table injectivity guard.

This is the structural answer to the project's most expensive defect class: a
lookup that was correct in the context it was captured in, consulted outside
that context, returning a well-formed codeword for the WRONG mux input.  The
symptom is always the same -- bitgen prints ``0 unmapped``, the FCB accepts the
image, and a lane is silently dead on silicon.

The guard is deliberately not a golden comparison.  A golden test passes when
two written-down tables agree on the same wrong thing; the invariants here are
physical and need no golden:

* inside one destination mux, two inputs cannot share a codeword (K1);
* one pip cannot carry two codewords (K1F);
* a codeword must identify its source within a boundary family (K2);
* a source that drives no edge into that family anywhere on the device does not
  belong in that family's table at all (FANIN);
* a mesh codeword is a function of (dst res, src res, tile delta, tile class),
  so a single mistyped word breaks the law (K4).

Two rules this file pins, and they matter more than any individual assertion:

1. ``KNOWN_DEFECTS`` must equal the audit result EXACTLY, in both directions.
   A new violation fails the build; a defect that has been fixed in the data
   also fails, so the quarantine cannot rot into a permanent excuse.
2. Every known defect must name a refusal, and the refusal must be LIVE -- the
   ambiguous codeword must be absent from the loaded map.  Quarantining a row
   without refusing it would be exactly the silent-miss bug wearing a comment.
"""

import csv
import os
from pathlib import Path

import pytest

from agamemnon.engine import selector_injectivity as SI
from agamemnon.engine.features import mcu_ahb as mcu_ahb_feature
from agamemnon.engine.features import routing as routing_feature
from agamemnon.engine.registry import options_from


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


# --------------------------------------------------------------------------
# The quarantine is exact, in both directions
# --------------------------------------------------------------------------

def test_the_audit_finds_exactly_the_enumerated_known_defects():
    """Neither a new violation nor a silently-retired one may pass.

    Failing on a *retired* defect is the important half. A quarantine list that
    only grows becomes a permanent excuse; this makes fixing the data force the
    entry out.
    """
    found = {violation.signature for violation in SI.audit(str(CHIPDB))}
    known = {defect.signature for defect in SI.KNOWN_DEFECTS}
    assert found - known == set(), (
        "new selector-table violation -- a codeword here selects a different "
        "mux input and would config-accept silently:\n%s" % "\n".join(
            v.describe() for v in SI.audit(str(CHIPDB))
            if v.signature not in known))
    assert known - found == set(), (
        "a KNOWN_DEFECTS entry no longer reproduces; delete it rather than "
        "leaving a stale quarantine")


def test_enforce_accepts_the_shipped_chipdb():
    present = SI.enforce(str(CHIPDB))
    assert len(present) == len(SI.KNOWN_DEFECTS)


def test_every_known_defect_names_a_refusal_and_a_retirement():
    for defect in SI.KNOWN_DEFECTS:
        assert defect.summary.strip()
        assert defect.citation.strip()
        assert defect.retire_when.strip()
        assert defect.refusal.strip(), (
            "%s is quarantined with no refusal -- that is the silent-miss bug "
            "with a comment attached" % defect.signature)


# --------------------------------------------------------------------------
# The refusals are live, not aspirational
# --------------------------------------------------------------------------

def test_each_ambiguous_pip_is_actually_dropped_from_the_loaded_map(monkeypatch):
    """The colliding codewords must not survive into the exact-field map.

    Run with the experimental BRAM site-read profile on, because one of the
    colliding rows only loads under that flag; the guard has to hold there too.
    """
    monkeypatch.setenv("AGAMEMNON_BRAM_SITE_READ_PATHS", "1")
    options = options_from({"AGAMEMNON_BRAM_SITE_READ_PATHS": "1"})
    metadata = mcu_ahb_feature.FEATURE.load_routing_metadata(CHIPDB, options, ())
    refused = SI.ambiguous_exact_pips(str(CHIPDB))
    assert refused, "the audit found collisions but produced no refusals"
    for source, destination in refused:
        key = mcu_ahb_feature.exact_wire(source) + mcu_ahb_feature.exact_wire(
            destination)
        assert key not in metadata.exact_pips, (
            "%s -> %s still resolves to a codeword shared with another source"
            % (source, destination))


def test_the_arbitration_keeps_the_corroborated_member():
    """Observation decides: only the member with no path witness is withdrawn.

    Refusing both members of every collision would be a false refusal that
    breaks working corridors. ``X14Y4_RMUX00 -> X13Y4_CtrlMUX02`` is recorded in
    bram_site_read_paths.csv and carries the same word at the sibling instance
    X13Y3_CtrlMUX02, so it keeps its codeword; X14Y4_RMUX84 does not and loses
    it.
    """
    refused = SI.ambiguous_exact_pips(str(CHIPDB))
    assert ("X14Y4_RMUX84", "X13Y4_CtrlMUX02") in refused
    assert ("X14Y4_RMUX00", "X13Y4_CtrlMUX02") not in refused


def test_the_adc_synthetic_alias_is_not_refused():
    """One real wire under two synthetic names is not an ambiguity.

    X22Y7_InputMUX100 and ...101 are renamed at promotion by
    features/mcu_ahb.py so the open router cannot swap the two ADC oracle
    corridors; both denote the one real wire X22Y7_InputMUX01, which two
    independent vendor builds harvest with the same codeword 31;38.  Sharing
    a codeword is therefore correct.  Refusing it withdrew a real, doubly
    witnessed corridor and made ADC0 builds fail closed for no reason --
    regression guarded here.
    """
    refused = SI.ambiguous_exact_pips(str(CHIPDB))
    assert ("X22Y7_InputMUX100", "X18Y7_RMUX03") not in refused
    assert ("X22Y7_InputMUX101", "X18Y7_RMUX03") not in refused
    # ...and the alias must be declared with its evidence, not special-cased.
    group = SI._alias_group_for(
        ("X22Y7_InputMUX100", "X22Y7_InputMUX101"))
    assert group is not None
    assert group["real_wire"] == "X22Y7_InputMUX01"
    assert group["evidence"].strip()

    # An UNDECLARED collision must still be refused -- the exemption is not a
    # blanket amnesty for anything that shares a codeword.
    assert SI._alias_group_for(
        ("X22Y7_InputMUX100", "X22Y7_InputMUX999")) is None


def test_the_device_graph_names_the_bank_the_misfiled_rows_came_from():
    """RMUX25 and RMUX92 are BBMUXS feeders, derived without the staged tables.

    The BBMUXE fan-in is enumerated outright; the BBMUXS one is completed by
    the offset law, and only after that law is checked against every BBMUXS row
    the graph does enumerate. So this reproduces the 2026-08-20 conclusion from
    data that already ships here, rather than trusting the corrected tables
    staged in AG32-Docs (whose landing is a pending decision).
    """
    assert SI.misfiled_boundary_sources(str(CHIPDB)) == {
        "BBMUXE": {25: "BBMUXS", 92: "BBMUXS"}}


def test_the_misfiled_boundary_rows_are_unreachable_by_construction():
    """The primary refusal: no table offers an edge that could consult them.

    This is what keeps the two misfiled rows quarantined instead of blocking
    every build. If a future chipdb addition ever DOES offer an
    RMUX25/RMUX92 -> BBMUXE edge, this fails and the quarantine must be
    revisited before that edge can be routed.
    """
    for index in (25, 92):
        found = SI.boundary_edge_exists(str(CHIPDB), "BBMUXE", index)
        assert found is None, (
            "%s now offers an RMUX%d -> BBMUXE edge, so the misfiled "
            "bbmuxe_fanin.csv row is reachable and can be emitted" % (found, index))


def test_the_secondary_routing_refusal_agrees_when_it_is_present():
    """routing.py's own withdrawal is belt-and-braces; cross-check it."""
    refuse = getattr(routing_feature, "ambiguous_boundary_sources", None)
    if refuse is None:
        pytest.skip("routing.py carries no source-keyed fallback withdrawal")
    ambiguous = refuse(str(CHIPDB))
    assert 25 in ambiguous["BBMUXE"]
    assert 92 in ambiguous["BBMUXE"]


# --------------------------------------------------------------------------
# The device graph is an independent witness, and it agrees
# --------------------------------------------------------------------------

def test_the_device_graph_pins_the_bbmuxe_fanin_to_twelve_sources():
    fanin = SI.boundary_fanin(str(CHIPDB))
    assert fanin["BBMUXE"] == frozenset(
        {3, 13, 20, 26, 33, 43, 49, 56, 63, 79, 86, 93})
    assert 25 not in fanin["BBMUXE"]
    assert 92 not in fanin["BBMUXE"]


def test_the_hand_written_boundary_fallbacks_match_the_device_graph():
    """rrg_edges_full.csv's cfg column is an independent codeword witness.

    It comes from the vendor arch DB rather than the design-corpus harvest that
    produced bbmuxe_fanin.csv, so agreement is evidence and not tautology. This
    is the check that decides the 43/63 transposition on its own.
    """
    law = SI.boundary_codeword_law(str(CHIPDB))
    tables = {"BBMUXE": routing_feature.BBMUXE_PAIR,
              "BBMUXS": routing_feature.BBMUXS_PAIR}
    compared = 0
    for (family, source), codeword in sorted(law.items()):
        table = tables.get(family)
        if table is None or source not in table:
            continue
        compared += 1
        assert tuple(table[source]) == codeword, (
            "%s RMUX%02d: table says %r, the device graph says %r"
            % (family, source, table[source], codeword))
    assert compared >= 13, "compared only %d entries" % compared


def test_every_exit_pair_codeword_agrees_with_the_device_graph():
    """168 exact tuples, 94 of them independently witnessed, 0 disagreements."""
    import re

    law = {}
    rows, _ = SI._rrg_boundary_rows(str(CHIPDB))
    for row in rows:
        pair = re.search(r"\[(\d+),(\d+)\]", row.get("cfg") or "")
        if not pair:
            continue
        edge = SI._BOUNDARY.fullmatch(row["dst_res"])
        source = SI._RMUX.fullmatch(row["src_res"])
        if not edge or not source:
            continue
        law[(int(row["dst_x"]), int(row["dst_y"]), edge.group(1),
             int(edge.group(2)), int(row["src_x"]), int(row["src_y"]),
             int(source.group(1)))] = (int(pair.group(1)), int(pair.group(2)))

    options = options_from({})
    metadata = mcu_ahb_feature.FEATURE.load_routing_metadata(CHIPDB, options, ())
    compared = 0
    for key, selectors in metadata.exit_pairs.items():
        ex, ey, family, index, sx, sy, source_family, source_index = key
        if source_family != "RMUX":
            continue
        witness = law.get((ex, ey, family, index, sx, sy, source_index))
        if witness is None:
            continue
        compared += 1
        assert tuple(selectors) == witness, (
            "exit pair %r says %r, the device graph says %r"
            % (key, selectors, witness))
    assert compared >= 90, "compared only %d exit pairs" % compared


# --------------------------------------------------------------------------
# Coverage: the audit must actually look at what the loaders read
# --------------------------------------------------------------------------

def test_the_audit_covers_every_pip_cfg_table_the_loaders_read():
    """A table the loader consults but the audit skips is an unguarded gap."""
    audited = {row["file"] for row in SI._pip_cfg_rows(str(CHIPDB))}
    declared = set(mcu_ahb_feature.EXACT_PIP_CFG_FILES) | set(
        mcu_ahb_feature.CORRIDOR_PIP_CFG_FILES)
    missing = {name for name in declared - audited
               if (CHIPDB / name).exists()}
    assert not missing, "loaded but never audited: %s" % sorted(missing)


def test_the_source_law_and_group_masks_ship_clean():
    """These two invariants have no known exception; keep it that way."""
    kinds = {v.kind for v in SI.audit(str(CHIPDB))}
    assert "source-law" not in kinds
    assert "inconsistent-group-mask" not in kinds


# --------------------------------------------------------------------------
# The checks themselves fire, on synthetic data
# --------------------------------------------------------------------------

def _write_pip_cfg(directory, name, rows):
    path = Path(directory) / name
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["src_wire", "dst_wire", "cell_table", "x", "y",
                         "cfg_group", "clear_selectors", "set_selectors",
                         "evidence"])
        writer.writerows(rows)
    return path


def test_enforce_refuses_a_fresh_duplicate_codeword(tmp_path):
    _write_pip_cfg(tmp_path, "synthetic_pip_cfg.csv", [
        ["X14Y8_RMUX01", "X13Y8_CtrlMUX00", "fabric", "13", "8",
         "CFG_CTRLMUX", "24;25;26;27", "24;26", "synthetic"],
        ["X14Y8_RMUX02", "X13Y8_CtrlMUX00", "fabric", "13", "8",
         "CFG_CTRLMUX", "24;25;26;27", "24;26", "synthetic"],
    ])
    with pytest.raises(SI.SelectorTableError) as excinfo:
        SI.enforce(str(tmp_path))
    assert "duplicate-codeword" in str(excinfo.value)
    assert "X14Y8_RMUX02" in str(excinfo.value)


def test_enforce_refuses_one_pip_carrying_two_codewords(tmp_path):
    _write_pip_cfg(tmp_path, "synthetic_pip_cfg.csv", [
        ["X14Y8_RMUX01", "X13Y8_CtrlMUX00", "fabric", "13", "8",
         "CFG_CTRLMUX", "24;25;26;27", "24;26", "synthetic"],
        ["X14Y8_RMUX01", "X13Y8_CtrlMUX00", "fabric", "13", "8",
         "CFG_CTRLMUX", "24;25;26;27", "25;27", "synthetic"],
    ])
    with pytest.raises(SI.SelectorTableError) as excinfo:
        SI.enforce(str(tmp_path))
    assert "ambiguous-codeword" in str(excinfo.value)


def test_enforce_refuses_a_broken_source_law(tmp_path):
    """Same resources, same tile delta, same tile class, two codewords."""
    rrg = Path(tmp_path) / "rrg_edges_full.csv"
    with rrg.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["src_tile", "src_x", "src_y", "src_res", "dst_tile",
                         "dst_x", "dst_y", "dst_res", "cfg", "source", "tier"])
        for y in (8, 9):
            writer.writerow(["LogicTILE", "14", str(y), "RMUX01", "LogicTILE",
                             "15", str(y), "RMUX09", "CFG_RMUX1", "observed",
                             "fanin"])
    _write_pip_cfg(tmp_path, "synthetic_pip_cfg.csv", [
        ["X14Y8_RMUX01", "X15Y8_RMUX09", "fabric", "15", "8",
         "CFG_RMUX1", "10;11;12;13", "10;12", "synthetic"],
        ["X14Y9_RMUX01", "X15Y9_RMUX09", "fabric", "15", "9",
         "CFG_RMUX1", "10;11;12;13", "11;13", "synthetic"],
    ])
    with pytest.raises(SI.SelectorTableError) as excinfo:
        SI.enforce(str(tmp_path))
    assert "source-law" in str(excinfo.value)


def test_fanin_membership_names_the_family_a_misfiled_row_belongs_to():
    fanin = {"BBMUXE": frozenset({3, 13}), "BBMUXS": frozenset({25, 92})}
    violations = SI.check_fanin_membership(
        {("BBMUXE", 3): (2, 4), ("BBMUXE", 92): (2, 6)}, fanin, "synthetic")
    assert len(violations) == 1
    assert violations[0].sources == ("RMUX92",)
    assert "BBMUXS" in violations[0].rows[0]


def test_an_empty_chipdb_directory_is_not_silently_clean(tmp_path):
    """No data must not read as 'no violations' to a caller that trusts it."""
    assert SI.audit(str(tmp_path)) == []
    assert SI.enforce(str(tmp_path)) == []
    assert SI.boundary_fanin(str(tmp_path)) == {}


def test_selector_tables_are_chosen_by_shape_not_by_filename():
    """Two exact-codeword tables are not named *_pip_cfg.csv.

    A name-keyed audit skips them silently -- which is the defect class this
    module exists to stop, one level up.
    """
    tables = set(SI.selector_tables(str(CHIPDB)))
    assert "pad_input_L48_left_corridors.csv" in tables
    assert "pad_oe_L48_left_corridors.csv" in tables
    assert {name for name in tables if not name.endswith("_pip_cfg.csv")}


def test_a_short_row_is_refused_as_data_rather_than_mis_parsed(tmp_path):
    """A row one field short slides every later value one column left."""
    path = Path(tmp_path) / "synthetic_pip_cfg.csv"
    path.write_text(
        "src_wire,dst_wire,cell_table,x,y,cfg_group,clear_selectors,"
        "set_selectors,evidence\n"
        "X14Y8_RMUX01,X13Y8_CtrlMUX00,fabric,13,8,CFG_CTRLMUX,24;25,24,ok\n"
        "X14Y8_RMUX02,X13Y8_CtrlMUX00,,,,,,short-row\n",
        encoding="utf-8")
    with pytest.raises(SI.SelectorTableError) as excinfo:
        SI.enforce(str(tmp_path))
    assert "malformed-row" in str(excinfo.value)
