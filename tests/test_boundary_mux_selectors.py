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
import re
from pathlib import Path

from agamemnon.engine.features.mcu_ahb import EXIT_PAIR_FILES
from agamemnon.engine.features.routing import BBMUXE_PAIR, BBMUXS_PAIR


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
    assert set(BBMUXS_PAIR) - set(seen) == {2, 9, 19, 25, 32, 39, 55, 62, 92}
