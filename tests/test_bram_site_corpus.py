import csv
from pathlib import Path

from tools.harvest_bram_site_corpus import EDGE_HEADER, parse_route


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
