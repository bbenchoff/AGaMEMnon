"""Board-witnessed additional approaches into qualified pad-feed sources (pipwit, 2026-09-19)."""
import csv
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "agamemnon" / "chipdb"


def _rows(name):
    with (DATA / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_every_approach_targets_a_qualified_feed_and_is_not_the_qualified_approach():
    qualified = _rows("pad_output_qualified_L48.csv")
    feeds = {(q["src_res"], q["src_x"], q["src_y"]): (q["approach_res"], q["approach_x"], q["approach_y"])
             for q in qualified}
    rows = _rows("pad_output_approaches_L48.csv")
    assert rows, "the table must carry at least the 2026-09-19 PIN_17 witnesses"
    seen = set()
    for r in rows:
        feed = (r["feed_res"], r["feed_x"], r["feed_y"])
        approach = (r["approach_res"], r["approach_x"], r["approach_y"])
        assert feed in feeds, r
        assert approach != feeds[feed], r
        assert re.fullmatch(r"CFG_RMUX\d+\[\d+,\d+\]", r["cfg"]), r
        assert r["evidence"].startswith("pipwit-pad/"), r
        assert (feed, approach) not in seen, r
        seen.add((feed, approach))


def test_every_approach_is_an_rrg_edge_with_that_codeword_and_not_convicted():
    rrg = {(e["src_res"], e["src_x"], e["src_y"], e["dst_res"], e["dst_x"], e["dst_y"]): e["cfg"]
           for e in _rows("rrg_edges_full.csv")}
    pat = re.compile(r"(\w+)@(-?\d+),(-?\d+)->(\w+)@(-?\d+),(-?\d+)")
    dead = {pat.fullmatch(row["edge"]).groups() for row in _rows("dead_edges_silicon.csv")}
    for r in _rows("pad_output_approaches_L48.csv"):
        key = (r["approach_res"], r["approach_x"], r["approach_y"], r["feed_res"], r["feed_x"], r["feed_y"])
        assert rrg.get(key) == r["cfg"], r
        assert key not in dead, r


def test_pin17_has_the_eight_witnessed_approaches():
    rows = _rows("pad_output_approaches_L48.csv")
    pin17 = {(r["approach_res"], r["approach_x"], r["approach_y"]) for r in rows
             if (r["feed_res"], r["feed_x"], r["feed_y"]) == ("RMUX85", "18", "9")}
    assert {("RMUX92", "18", "5"), ("RMUX44", "18", "12"), ("RMUX20", "20", "9"), ("RMUX68", "17", "9"),
            ("RMUX92", "18", "8"), ("RMUX92", "18", "6"), ("RMUX92", "18", "7"), ("RMUX68", "14", "9")} <= pin17
    # The two silent candidates stay out (they are convicted in dead_edges_silicon.csv).
    assert not {("RMUX68", "19", "9"), ("RMUX44", "18", "9")} & pin17


def test_routing_admits_the_table_beside_the_qualified_approach():
    source = (ROOT / "agamemnon" / "engine" / "features" / "routing.py").read_text(encoding="utf-8")
    assert '"pad_output_approaches_L48.csv"' in source.split("chipdb_files=(", 1)[1].split(")", 1)[0]
    denied = source.split("def _pad_composition_denied(r):", 1)[1].split("# ---- EXIT-FEEDER WHITELIST", 1)[0]
    assert "_extra_approach.get((r[\"dst_res\"], dst_tile[0], dst_tile[1]), ())" in denied
    assert "_qual_approach.get(" in denied            # the qualified approach is still the first key
