"""The other exact BRAM tables bitgen consults by precedence must be self-consistent
with the cell map, so a row cannot drive a mux other than its destination (the
defect class of bram_pip_cfg.csv rows 506-507 and the pad-input rows, VP-AGM-018).

bram_site_read_pip_cfg.csv (opt-in, AGAMEMNON_BRAM_SITE_READ_PATHS): every row
names a config group that is the destination's own, sets a 2-hot codeword inside
the destination's selector block, clears exactly that block, and every selector
has a cell in the table the row's coordinate belongs to.
bram_route_codewords.csv: every selector exists at all four BRAM sites.
"""
import csv
import re
from pathlib import Path

import pytest

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb"
NPI = {"RMUX": 6, "IMUX": 4}
BS = {"RMUX": 10, "IMUX": 12}
WIRE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z]+?)(\d+)$")


def _cells(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return {(int(r["x"]), int(r["y"]), r["mux"], int(r["sel"])): (int(r["byte"]), int(r["mask"]))
                for r in csv.DictReader(stream)}


@pytest.fixture(scope="module")
def bram_cells():
    return _cells("bram_cell.csv")


@pytest.fixture(scope="module")
def fabric_cells():
    return _cells("pips_full.csv")


def _rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _sels(text):
    return [int(s) for s in text.split(";") if s]


def test_site_read_rows_write_their_own_destination(bram_cells, fabric_cells):
    rows = _rows("bram_site_read_pip_cfg.csv")
    assert len(rows) >= 400
    violations = []
    for row in rows:
        x, y, family, index = WIRE.match(row["dst_wire"]).groups()
        x, y, index = int(x), int(y), int(index)
        assert (x, y) == (int(row["x"]), int(row["y"])), row
        sets, clears, config = _sels(row["set_selectors"]), _sels(row["clear_selectors"]), row["cfg_group"]
        table = bram_cells if (x == 13 and 1 <= y <= 4) else fabric_cells
        if family in NPI:
            block = (index % NPI[family]) * BS[family]
            if config != "CFG_%s%d" % (family, index // NPI[family]):
                violations.append(("config group is not the destination's", row["dst_wire"], config))
            if len(sets) != 2 or not all(block <= s < block + BS[family] for s in sets):
                violations.append(("codeword outside the destination block", row["dst_wire"], sets))
            if clears and set(clears) != set(range(block, block + BS[family])):
                violations.append(("clear list is not the destination block", row["dst_wire"], clears))
        for sel in sets + clears:
            if (x, y, config, sel) not in table and (x, y, config.replace("CTRLMUX", "CtrlMUX"), sel) not in table:
                violations.append(("selector has no cell", row["dst_wire"], config, sel))
    assert violations == []


def test_site_read_table_has_one_codeword_per_source(bram_cells):
    rows = _rows("bram_site_read_pip_cfg.csv")
    keys = [(row["src_wire"], row["dst_wire"]) for row in rows]
    assert len(keys) == len(set(keys)), "duplicate (src, dst) rows"
    by_destination = {}
    for row in rows:
        if not row["set_selectors"]:
            continue
        by_destination.setdefault(row["dst_wire"], {}).setdefault(row["set_selectors"], set()).add(row["src_wire"])
    collisions = [(dst, codeword, sorted(srcs)) for dst, m in by_destination.items()
                  for codeword, srcs in m.items() if len(srcs) > 1]
    # a real mux cannot give two sources the same codeword (the RMUX00/RMUX84 -> CtrlMUX02 case)
    assert collisions == []


def test_route_codewords_exist_at_every_bram_site(bram_cells):
    rows = _rows("bram_route_codewords.csv")
    assert rows
    for row in rows:
        sels = set(_sels(row["clear_selections"]) + _sels(row["set_selections"]))
        assert sels
        missing = [(y, s) for y in (1, 2, 3, 4) for s in sels if (13, y, row["config"], s) not in bram_cells]
        assert missing == [], (row["dst_family"], row["dst_index"], missing)
