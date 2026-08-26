"""Guard the RMUX -> boundary-mux selector codewords.

routing.py keeps a hand-written fallback (BBMUXS_PAIR / BBMUXE_PAIR) for hops
that have no exact (edge, src) tuple in the chipdb exit-pair tables.  Two of its
entries were transcribed wrong, and nothing caught it: the emitter looked the
codeword up by source index, found one, and wrote a well-formed selector for a
DIFFERENT source's terminal.  bitgen reported ``0 unmapped`` because the
encoding was structurally valid -- it was just the wrong terminal, so the lane
read stuck on silicon.

Two independent invariants pin these values, and both are asserted here:

1. The codeword is a tile-invariant function of the source RMUX index alone.
   Every exit-pair table agrees on this across three boundary-mux families and
   eight edge tiles, so any dict entry that contradicts a witnessed row is a
   transcription error, not a new datum.
2. The south and east boundaries are the same track bank offset by 24:
   ``BBMUXS_PAIR[i] == BBMUXE_PAIR[(i + 24) % 96]``.

Entries with no witnessed row are allowed -- they are qualified by other
evidence -- but they must still satisfy the offset law where it applies.
"""

import csv
import os
import re
import subprocess
import sys
from pathlib import Path

from agamemnon.engine.features.mcu_ahb import EXIT_PAIR_FILES
from agamemnon.engine.features.routing import (
    BBMUXE_PAIR, BBMUXS_PAIR, bbmuxw_edge_admitted, exact_bbmuxw_edges,
)


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
RMUX_PER_TILE = 96


def witnessed_codewords():
    """Map source RMUX index -> {codeword} over every exact exit-pair table."""
    seen = {}
    for filename in EXIT_PAIR_FILES:
        path = CHIPDB / filename
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                edge = re.fullmatch(r"BBMUX[A-Z]+0*[0-9]+", row["edge_res"])
                source = re.fullmatch(r"RMUX0*([0-9]+)", row["src_res"])
                if not edge or not source:
                    continue
                codeword = tuple(
                    int(item) for item in row["selectors"].split(";") if item
                )
                seen.setdefault(int(source.group(1)), {}).setdefault(
                    codeword, set()
                ).add(filename)
    return seen


def test_the_selector_codeword_is_a_function_of_the_source_rmux_index():
    seen = witnessed_codewords()
    assert len(seen) >= 24

    contradictions = {
        index: sorted(codewords)
        for index, codewords in seen.items() if len(codewords) > 1
    }
    assert not contradictions, (
        "a source RMUX index carries more than one witnessed codeword, so the "
        "tile-invariant model behind the routing.py fallback is wrong: %r"
        % contradictions
    )

    for codewords in seen.values():
        (codeword,) = codewords
        assert len(codeword) == 2
        assert codeword[0] in (0, 1, 2, 3)
        assert codeword[1] in (4, 5, 6, 7)


def test_every_fallback_entry_agrees_with_the_chipdb_witnesses():
    seen = witnessed_codewords()
    wrong = []
    for name, table in (("BBMUXS_PAIR", BBMUXS_PAIR), ("BBMUXE_PAIR", BBMUXE_PAIR)):
        for index, codeword in table.items():
            if index not in seen:
                continue
            (witness,) = seen[index]
            if codeword != witness:
                wrong.append((name, index, codeword, witness,
                              sorted(seen[index][witness])))
    assert not wrong, (
        "routing.py fallback contradicts the chipdb exit-pair tables; the "
        "emitter would write a valid-looking codeword for another source's "
        "terminal and still report 0 unmapped: %r" % wrong
    )


def test_the_south_and_east_boundaries_are_the_same_bank_offset_by_24():
    for index, codeword in BBMUXS_PAIR.items():
        east = BBMUXE_PAIR.get((index + 24) % RMUX_PER_TILE)
        assert east == codeword, (
            "BBMUXS_PAIR[%d]=%r has no matching BBMUXE_PAIR[%d]=%r"
            % (index, codeword, (index + 24) % RMUX_PER_TILE, east)
        )


def test_bbmuxe_pair_is_exactly_the_shipped_feeder_harvest():
    """The dict must equal bbmuxe_fanin.csv row for row.

    bbmuxe_fanin.csv is the corpus harvest of the boundary funnel (a clean
    4x3 = 12-input mux) and has shipped in chipdb, declared on this very
    feature, the whole time -- while the code used a hand-typed copy that
    disagreed with it on two feeders.  Nothing compared them.  This does.

    Insurance, not discovery: today the two provenances agree on all 14
    entries, so this test currently finds nothing and proves nothing new
    about whether BBMUXE_PAIR is the electrically correct encoding -- that
    question is board territory (see A1b), not something a desk comparison
    of two written-down tables can settle. A green run here means only that
    the hand dict has not silently drifted from the corpus harvest since the
    last time someone checked; it must not be read as boundary-encoding
    proof. The value is entirely prospective: the next time a hand edit to
    BBMUXE_PAIR (or a new "exact" tuple that contradicts this harvest) is
    made, this is what turns it into a loud, named failure here instead of a
    silent "0 unmapped" on the boundary mux that burned this project twice.
    """
    rows = list(csv.DictReader((CHIPDB / "bbmuxe_fanin.csv").open(newline="")))
    assert len(rows) == 14

    harvested = {}
    for row in rows:
        assert int(row["n_variants"]) == 1, (
            "feeder %s has more than one observed codeword, so the "
            "source-keyed model is wrong: %r" % (row["feeder_res"], row)
        )
        assert int(row["n_obs"]) >= 1
        harvested[int(re.fullmatch(r"RMUX0*([0-9]+)", row["feeder_res"]).group(1))] = (
            int(row["lo"]), int(row["hi"])
        )

    assert BBMUXE_PAIR == harvested


def test_the_unwitnessed_bbmuxs_residue_is_pinned_and_does_not_grow():
    """No new BBMUXS source may be added without a chipdb witness.

    A terminal number is per-mux-instance, so two sources sharing a codeword is
    not by itself a contradiction -- which is exactly why the 43/63
    transposition survived review.  The guard that does work is provenance.
    BBMUXS has no shipped harvest of its own, so its eight south-boundary-only
    feeders are pinned by name here; the offset law above ties them to the
    harvested east table.
    """
    seen = witnessed_codewords()
    # Updated 2026-08-20: 75 and 85 added. They are NOT a relaxation of this
    # guard -- they are the two feeders whose absence was refusing routes we can
    # encode. Both are required by the offset law asserted above from shipped,
    # witnessed BBMUXE rows (75 -> BBMUXE[3], 85 -> BBMUXE[13]), and both are
    # independently recovered from vendor bitstreams by the boundary-table audit
    # in AG32-Docs tools/bbmuxe_injectivity/, whose south table agrees with all
    # ten pre-existing entries and adds only these two. They join the pinned
    # residue because chipdb carries no witness row for them yet; when the
    # audit's family-keyed tables land, they should leave it.
    assert set(BBMUXS_PAIR) - set(seen) == {
        2, 9, 19, 25, 32, 39, 55, 62, 75, 85, 92}


def test_bbmuxw_graph_gate_matches_exact_bitgen_tuples():
    """Observation alone must not put an unencodable west exit in strict RRG."""
    edges = exact_bbmuxw_edges(CHIPDB)
    assert len(edges) >= 40
    assert "X14Y11_RMUX90.X13Y11_BBMUXW03" in edges
    assert "X14Y11_RMUX42.X13Y11_BBMUXW03" not in edges

    bad = "X14Y11_RMUX42.X13Y11_BBMUXW03"
    assert not bbmuxw_edge_admitted(bad, edges)
    assert bbmuxw_edge_admitted(bad, edges, research_unsafe=True)


def test_emitted_strict_devdb_excludes_unencodable_bbmuxw_edge(tmp_path):
    """The release graph itself, not just its evidence set, must fail closed."""
    engine = ROOT / "agamemnon" / "engine"
    output = tmp_path / "devdb"
    env = os.environ.copy()
    env.pop("AGAMEMNON_RESEARCH_UNSAFE", None)
    command = [
        sys.executable, str(engine / "emit_uarch_db.py"),
        "--arch", str(engine / "arch.py"),
        "--data", str(CHIPDB),
        "--out", str(output),
    ]
    for setting in (
            "AGAMEMNON_CONDUCTION_GATE=1", "AGAMEMNON_HW_CARRY=1",
            "AGAMEMNON_LEDPADS=1", "AGAMEMNON_STRICT_GATE=1",
            "AGAMEMNON_XBAR_CONDUCT=1", "AGAMEMNON_CLEAN_SEL_GATE=1"):
        command.extend(("--env", setting))
    subprocess.run(command, cwd=ROOT, env=env, check=True,
                   capture_output=True, text=True, timeout=120)
    names = {
        row["name"]
        for row in csv.DictReader(
            (output / "dev_pips.csv").open(newline="", encoding="utf-8"))
    }
    assert "X14Y11_RMUX90.X13Y11_BBMUXW03" in names
    assert "X14Y11_RMUX42.X13Y11_BBMUXW03" not in names
    # The regular clean-selector corpus is silent about hard-boundary sources.
    # Keep the exact AHB32 corridor hop, but do not confuse a vendor-observed
    # topology edge (or the x=13 InputMUX predictor) with an exact codeword.
    assert "X13Y10_BufMUX17.X14Y10_RMUX69" in names
    assert "X13Y10_BufMUX17.X14Y10_RMUX50" not in names
    assert "X13Y10_InputMUX05.X16Y10_RMUX44" not in names
