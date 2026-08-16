import csv
from collections import Counter
from pathlib import Path

from tools.harvest_bram_site_corpus import EDGE_HEADER, parse_route
from tools.harvest_bram_site_read_pip_cfg import EXTRA_EDGES, destination_field, load_cells


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
SITES = {(13, y) for y in range(1, 5)}


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def edge_set(name):
    return {tuple(row[column] for column in EDGE_HEADER) for row in rows(name)}


def test_four_site_structural_tables_are_complete_and_balanced():
    bels = rows("bram9k_bel.csv")
    cells = rows("bram_cell.csv")
    assert len(bels) == 4 * 111
    assert len(cells) == 4 * 2137
    assert {(int(row["x"]), int(row["y"])) for row in bels} == SITES
    assert {(int(row["x"]), int(row["y"])) for row in cells} == SITES


def test_vendor_route_corpus_is_reference_only_not_production_admission():
    corpus = edge_set("bram_site_route_corpus.csv")
    production = edge_set("bram9k_edges.csv")
    known_static = (
        "Bram", "13", "4", "BufMUX13",
        "Logic", "14", "4", "RMUX75",
    )
    assert len(corpus) == 2112
    assert known_static in corpus
    assert known_static not in production
    assert production < corpus


def test_route_parser_does_not_invent_edges_between_flattened_segments(tmp_path):
    decoded = tmp_path / "route_decoded.txt"
    decoded.write_text(
        "\n net : #1 - \"n\"\n"
        "  path : 4\n"
        "   1:0:#1 \"BramTILE(13,1):RMUX01\"\n"
        "   1:0:#2 \"BramTILE(13,1):IMUX01\"\n"
        "   1:0:#3 \"BramTILE(13,2):RMUX02\"\n"
        "   1:0:#4 \"BramTILE(13,2):IMUX02\"\n"
        "  steiner : 2\n"
        "   1:0:#1 \"BramTILE(13,1):RMUX01\"\n"
        "   1:0:#3 \"BramTILE(13,2):RMUX02\"\n"
        "  segment : 2\n"
        "   2\n"
        "   2\n"
        "  reached : 2\n",
        encoding="latin1",
    )
    _, edges = parse_route(decoded)
    assert edges == {
        ("Bram", "13", "1", "RMUX01", "Bram", "13", "1", "IMUX01"),
        ("Bram", "13", "2", "RMUX02", "Bram", "13", "2", "IMUX02"),
    }


def test_full_depth_read_corpus_has_all_sensitized_bus_trees():
    paths = rows("bram_site_read_paths.csv")
    assert len(paths) == 466
    assert Counter(row["class"] for row in paths) == {
        "address": 227,
        "data": 223,
        "clock": 16,
    }
    assert {row["net"] for row in paths if row["class"] == "address"} == {
        f"mem_ahb_haddr[{bit}]" for bit in range(2, 11)
    }
    assert {row["net"] for row in paths if row["class"] == "data"} == {
        f"mem_ahb_hrdata[{bit}]" for bit in range(32)
    }


def test_full_depth_read_selector_table_owns_complete_fields():
    fields = rows("bram_site_read_pip_cfg.csv")
    assert len(fields) == 378
    assert len({(row["src_wire"], row["dst_wire"]) for row in fields}) == 378
    fixed_clock_hops = [row for row in fields if not row["clear_selectors"]]
    assert len(fixed_clock_hops) == 8
    assert all(row["cfg_group"] == "CFG_SeamMUX" for row in fixed_clock_hops)
    assert all(row["src_wire"] == "X13Y0_BufMUX05" for row in fixed_clock_hops)
    control = next(
        row for row in fields
        if (row["src_wire"], row["dst_wire"]) == EXTRA_EDGES[0]
    )
    assert control["cfg_group"] == "CFG_CTRLMUX"
    assert control["clear_selectors"] == ";".join(map(str, range(24, 48)))
    assert control["set_selectors"] == "28;32"

    cells = load_cells(CHIPDB / "pips_full.csv")
    x, y, cfg, selectors = destination_field(control["dst_wire"], cells)
    assert (x, y, cfg, selectors) == (13, 4, "CFG_CTRLMUX", list(range(24, 48)))


def test_uarch_locks_arbitrary_site_address_and_data_trees():
    source = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc").read_text(
        encoding="utf-8"
    )
    assert '"/bram_site_read_paths.csv"' in source
    assert "pre-routed %s over %d exact four-site pip(s)" in source
    assert "pre-routed DataOutA[0] over %d exact four-site pip(s)" in source
    assert "if (bram_loc.y == 1) hrdata_bit = 8;" in source
    assert "if (bram_loc.y == 2) hrdata_bit = 16;" in source
    assert "if (bram_loc.y == 3) hrdata_bit = 24;" in source
