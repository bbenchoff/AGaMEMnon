"""Desk check: byte-exact BRAM output exits can be admitted as encoding-certain (opt-in).

The BRAM tile model gives Port-B lane 0 (X13Y4_BufMUX16) and lane 1 (BufMUX17) several
exits each, but the clean-selector encodability gate accepted a BufMUX -> RMUX exit only
when the MCU corridor map listed it, so both lanes kept ONE admitted exit -- the same
wire, X13Y4_RMUX08 -- and no two-lane Port-B read could route (bram_fifo_kat,
2026-09-19).  chipdb/bram_pip_cfg.csv holds byte-exact rows for RMUX15 <- BufMUX17 and
RMUX3 <- BufMUX18 whose cells sit in the destinations' own selector blocks, so bitgen can
encode them.  AGAMEMNON_BRAM_EXIT_CFG_ADMIT=1 makes those rows encoding-certain (tier 2)
at X13Y4 without touching the pinned default identities.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTING = ROOT / "agamemnon" / "engine" / "features" / "routing.py"
CHIPDB = ROOT / "agamemnon" / "chipdb"


def test_bram_exit_admission_is_opt_in_and_keyed_on_byte_exact_rows():
    source = ROUTING.read_text(encoding="utf-8")
    build = source.index("BRAM_EXIT_CFG_KEYS = set()")
    assert 'os.environ.get("AGAMEMNON_BRAM_EXIT_CFG_ADMIT")' in source[build:build + 800]
    assert '"bram_pip_cfg.csv"' in source[build:build + 800]
    gate = source.index('if (sf == "BufMUX" and df == "RMUX" and (si, di) in BRAM_EXIT_CFG_KEYS')
    assert build < gate
    assert "== (13, 4)" in source[gate:gate + 400]
    # the Port-B silicon corridor whitelist is the filter that kept one exit per lane
    corridor = source.index("if BRAM_EXIT_CFG_KEYS:")
    assert build < gate < corridor   # keys built first; the corridor whitelist is loaded after the gate
    assert '_BRAM_CORRIDOR_OK.add((13, 4, _padres("BufMUX%d" % _si)) + (13, 4, _padres("RMUX%d" % _di)))' in source[corridor:corridor + 600]


def test_port_b_lane_0_and_1_have_byte_exact_alternatives_to_the_shared_exit():
    rows = list(csv.DictReader((CHIPDB / "bram_pip_cfg.csv").open(newline="", encoding="utf-8")))
    exits = {}
    for row in rows:
        if row["src_res"].startswith("BufMUX") and row["dst_res"].startswith("RMUX") \
                and int(row["ddx"]) == 0 and int(row["ddy"]) == 0:
            exits.setdefault(row["src_res"], set()).add(row["dst_res"])
    # lanes 0 and 1 share RMUX8; lane 1 also has RMUX15, lane 2 has RMUX3 and RMUX20
    assert "RMUX8" in exits["BufMUX16"] and "RMUX8" in exits["BufMUX17"]
    assert "RMUX15" in exits["BufMUX17"]
    assert {"RMUX3", "RMUX20"} <= exits["BufMUX18"]
