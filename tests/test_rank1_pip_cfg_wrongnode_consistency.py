"""Generalized guard for the VP-AGM-018 / bram_pip_cfg-506-507 wrong-node defect
class: a rank-1 *_pip_cfg (or *_corridors) table row that bitgen consults by
precedence must write config cells inside its DESTINATION node's own selector
block. A row whose selectors fall in a neighbour's block config-accepts and
SILENTLY programs a different mux -- a P0 silently-wrong image with no observable.

Ad-hoc per-table checks already existed for bram_pip_cfg.csv, bram_site_read_pip_cfg.csv,
bram_route_codewords.csv and pad_input_L48.csv. This test generalizes the check to
EVERY table of the (dst_wire, cfg_group, set/clear_selectors, cell_table) shape, so
the defect class cannot be reintroduced in a new table without a test firing.

SCOPE (deliberate, documented): the definitive block check runs on standard-fabric
RMUX/IMUX destinations (cell_table=fabric, x not in {0,22}), whose selector-block
geometry is known exactly (NPI/BS below) and is where VP-AGM-018 actually occurred.
Rows excluded from the block check, and WHY:
  * empty cfg_group with no selectors -> a pure routing link, no config to check;
  * x in {0,22} -> IO border columns have their own layout (AFEXE_CONFIG_COVERAGE_GAP);
  * non-RMUX/IMUX families (BBMUX/OMUX/KMUX/BufMUX/InputMUX/IOMUX/SinkMUX/...) -> their
    per-family NPI/BS are not yet derived here; extending the check to them (by
    deriving each family's block geometry from the cell map) is a tracked follow-up.
As of 2026-09-13 this passes with 0 violations over 1214 standard-fabric RMUX/IMUX
rows across 60 tables.
"""
import csv
import re
from pathlib import Path

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb"
NPI = {"RMUX": 6, "IMUX": 4}    # config groups per family (idx // NPI -> group index)
BS = {"RMUX": 10, "IMUX": 12}   # selectors per group block
WIRE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z]+?)(\d+)$")


def _fabric_cells():
    cells = set()
    with (CHIPDB / "pips_full.csv").open(newline="", encoding="utf-8") as stream:
        for r in csv.DictReader(stream):
            cells.add((int(r["x"]), int(r["y"]), r["mux"], int(r["sel"])))
    return cells


def _rank1_tables():
    tables = []
    for path in sorted(CHIPDB.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as stream:
            header = stream.readline()
        if "set_selectors" in header and "dst_wire" in header:
            tables.append(path.name)
    return tables


def _sels(text):
    return [int(s) for s in (text or "").split(";") if s.strip().lstrip("-").isdigit()]


def test_every_rank1_table_writes_its_own_destination_block():
    fabric = _fabric_cells()
    tables = _rank1_tables()
    assert len(tables) >= 55, "expected the full family of rank-1 pip_cfg tables"

    checked = 0
    violations = []
    for name in tables:
        with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                match = WIRE.match(row.get("dst_wire", ""))
                if not match:
                    continue
                x, y, family, index = (int(match.group(1)), int(match.group(2)),
                                       match.group(3), int(match.group(4)))
                cfg = row.get("cfg_group", "")
                selectors = _sels(row.get("set_selectors")) + _sels(row.get("clear_selectors"))
                cell_table = row.get("cell_table", "fabric") or "fabric"
                # exclusions (documented in the module docstring)
                if cfg == "" and not selectors:
                    continue
                if family not in NPI:
                    continue
                if x in (0, 22):
                    continue
                if cell_table != "fabric":
                    continue
                checked += 1
                own = "CFG_%s%d" % (family, index // NPI[family])
                lo = (index % NPI[family]) * BS[family]
                hi = lo + BS[family]
                if cfg != own:
                    violations.append((name, row["dst_wire"], "cfg_group %r != own %r" % (cfg, own)))
                    continue
                outside = [s for s in selectors if not (lo <= s < hi)]
                if outside:
                    violations.append((name, row["dst_wire"],
                                       "selectors %s outside block [%d,%d)" % (outside, lo, hi)))
                    continue
                missing = [s for s in selectors if (x, y, cfg, s) not in fabric]
                if missing:
                    violations.append((name, row["dst_wire"],
                                       "selectors %s have no cell in pips_full" % missing))

    assert checked >= 1000, "expected to block-check the standard-fabric RMUX/IMUX rows"
    assert not violations, (
        "wrong-node rank-1 rows (VP-AGM-018 class) -- would silently drive the wrong mux:\n"
        + "\n".join("  %s: %s (%s)" % v for v in violations[:30])
    )
