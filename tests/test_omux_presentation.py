"""OMUX(3z) presentation: the default OMUXPRES pips and their encoding owners."""

import csv
from pathlib import Path

from agamemnon.engine.features.bram import (
    BRAM_FIXED_PRESENTATION, BRAM_TMUX9_QUALIFIED_PROFILES, FEATURE as BRAM_FEATURE, BramState,
)
from agamemnon.engine.features.mcu_ahb import MCU_OUTPUT_BRIDGE_SITES

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "agamemnon" / "chipdb" / "omux3z_presentation_evidence.csv"


def _resolve(profile):
    source, destination = BRAM_FIXED_PRESENTATION
    return BRAM_FEATURE.resolve_route(
        BramState(qualified_profile=profile), source, destination, {}, {}, [])


def test_fixed_bram_presentation_is_an_ordinary_omuxpres_pip_without_a_source_profile():
    # 2026-09-24: lfsr16x6_kat routed an F net through X14Y8_OMUX08 -> OMUX06 and bitgen
    # refused the image because the BRAM feature reported the pair unencodable. Without a
    # TMUX09 source profile it is the slice's OMUXPRES pip, so the BRAM feature must defer.
    assert _resolve(None) is None


def test_fixed_bram_presentation_stays_owned_under_a_source_profile():
    assert _resolve(sorted(BRAM_TMUX9_QUALIFIED_PROFILES)[0]) is True
    assert _resolve("not-a-qualified-profile") is False


def test_evidence_table_gates_2061_default_pips():
    with EVIDENCE.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == ["x", "y", "z", "witnessed_pips"]
    slices = {(int(r["x"]), int(r["y"]), int(r["z"])) for r in rows
              if int(r["witnessed_pips"]) > 0}
    assert len(rows) == len(slices) == 2068
    assert all(0 <= z < 16 for _, _, z in slices)
    assert set(MCU_OUTPUT_BRIDGE_SITES) <= slices
    assert len(slices - set(MCU_OUTPUT_BRIDGE_SITES)) == 2061
