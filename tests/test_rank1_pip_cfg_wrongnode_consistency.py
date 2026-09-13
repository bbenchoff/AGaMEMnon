"""Generalized guard for the VP-AGM-018 / bram_pip_cfg-506-507 wrong-node defect
class: a rank-1 *_pip_cfg (or *_corridors) table row that bitgen consults by
precedence must write config cells inside its DESTINATION node's own selector
block. A row whose selectors fall in a neighbour's block config-accepts and
SILENTLY programs a different mux -- a P0 silently-wrong image with no observable.

Ad-hoc per-table checks already existed for bram_pip_cfg.csv, bram_site_read_pip_cfg.csv,
bram_route_codewords.csv and pad_input_L48.csv. This test generalizes the check to
EVERY table of the (dst_wire, cfg_group, set/clear_selectors, cell_table) shape, so
the defect class cannot be reintroduced in a new table without a test firing.

FOUR layers, all passing with 0 violations as of 2026-09-13 (60 tables):
  1. block check -- standard-fabric RMUX/IMUX: selectors inside the destination's
     own [ (idx%NPI)*BS, +BS ) block, with cells (the exact VP-AGM-018 signature);
  2. family-match -- ALL 1518 rows / EVERY family: cfg_group family == dst-wire family;
  3. cell-existence -- cell_table in {fabric,mcu,bram}: every selector is a real cell;
  4. index-relation -- ALL families with a derived NPI (RMUX/IMUX + MCU-edge
     BBMUXE/S/W/InputMUX, NPI in NPI_ALL): cfg index == dst idx // NPI, which closes
     the same-family-different-index sub-class for the MCU-edge families too.
Excluded (documented, not defects): rows with empty cfg_group and no selectors (pure
routing links); the x=0/22 IO border columns (their own layout, per
AFEXE_CONFIG_COVERAGE_GAP -- the only same-family-different-index gap left); and the
cell-existence layer skips cell_table='io' (border_edge_partial_cells.csv is a
different schema). The NPI_ALL map was derived from the tables' own self-consistency
excluding border, with 0 exceptions.
"""
import csv
import re
from pathlib import Path

CHIPDB = Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb"
NPI = {"RMUX": 6, "IMUX": 4}    # config groups per family (idx // NPI -> group index)
BS = {"RMUX": 10, "IMUX": 12}   # selectors per group block
# Wires-per-config-group for EVERY family that appears as a rank-1 destination,
# derived 2026-09-13 from the tables' own self-consistency excluding the x=0/22
# border columns (0 exceptions): RMUX 6, IMUX 4, and the MCU-edge families
# BBMUXE/BBMUXS/BBMUXW/InputMUX are group-per-wire (NPI=1). The index-relation
# test below enforces cfg_idx == dst_idx // NPI for all of these, which closes
# the same-family-different-index wrong-node sub-class for the MCU-edge families
# too (not just RMUX/IMUX). Only x=0/22 border tiles (own layout) remain excluded.
NPI_ALL = {"RMUX": 6, "IMUX": 4, "BBMUXE": 1, "BBMUXS": 1, "BBMUXW": 1, "InputMUX": 1}
WIRE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z]+?)(\d+)$")


def _cfg_index(cfg):
    core = cfg[4:] if cfg.startswith("CFG_") else cfg
    m = re.match(r"[A-Za-z]+?(\d+)$", core)
    return int(m.group(1)) if m else None


def _cells(name, selcol):
    cells = set()
    path = CHIPDB / name
    if path.exists():
        with path.open(newline="", encoding="utf-8") as stream:
            for r in csv.DictReader(stream):
                if selcol in r and r.get(selcol, "").strip():
                    cells.add((int(r["x"]), int(r["y"]), r["mux"], int(r[selcol])))
    return cells


def _fabric_cells():
    return _cells("pips_full.csv", "sel")


# Cell maps per cell_table column. 'io' border cells live in a different schema
# (border_edge_partial_cells.csv: resource/word_row/bank_col), so the universal
# cell-existence layer below skips cell_table='io' (documented gap).
def _cell_maps():
    return {"fabric": _cells("pips_full.csv", "sel"),
            "bram":   _cells("bram_cell.csv", "sel"),
            "mcu":    _cells("pips_mcuedge.csv", "sel_index")}


def _family(name):
    """Letter-prefix family of a mux/cfg_group name (minus a CFG_ prefix)."""
    core = name[4:] if name.startswith("CFG_") else name
    m = re.match(r"([A-Za-z]+?)\d+$", core)
    return m.group(1) if m else None


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


def test_no_rank1_row_names_a_config_group_of_a_different_family():
    """Family-agnostic wrong-node guard: a row's cfg_group must be the SAME mux
    family as its destination wire (e.g. dst ...RMUX8 -> CFG_RMUX*, dst ...InputMUX01
    -> InputMUX*). A cross-family group programs an unrelated mux. Covers ALL families
    (RMUX/IMUX/OMUX/KMUX/BufMUX/InputMUX/BBMUX*/SeamMUX/IOMUX...), 0 as of 2026-09-13."""
    tables = _rank1_tables()
    violations = []
    for name in tables:
        with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                match = WIRE.match(row.get("dst_wire", ""))
                cfg = row.get("cfg_group", "")
                if not match or not cfg:
                    continue
                dst_fam = match.group(3)
                cfg_fam = _family(cfg)
                if cfg_fam and cfg_fam != dst_fam:
                    violations.append((name, row["dst_wire"], cfg,
                                       "dst family %s != cfg family %s" % (dst_fam, cfg_fam)))
    assert not violations, (
        "cross-family rank-1 rows (would drive an unrelated mux family):\n"
        + "\n".join("  %s: %s cfg=%s (%s)" % v for v in violations[:30])
    )


def test_every_rank1_selector_has_a_cell(cell_table_maps=None):
    """Universal: every set/clear selector in a rank-1 row must correspond to a real
    config cell at (x,y,cfg_group,sel) in the destination's cell map. A selector with
    no cell references a config position that does not exist for that group -> a bad
    codeword. Runs for cell_table in {fabric,mcu,bram}; 'io' border cells use a
    different schema (border_edge_partial_cells.csv) and are a documented gap. 0 as of 2026-09-13."""
    maps = cell_table_maps or _cell_maps()
    tables = _rank1_tables()
    checked = 0
    violations = []
    for name in tables:
        with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                match = WIRE.match(row.get("dst_wire", ""))
                cfg = row.get("cfg_group", "")
                if not match or not cfg:
                    continue
                x, y = int(match.group(1)), int(match.group(2))
                cell_table = row.get("cell_table", "fabric") or "fabric"
                cells = maps.get(cell_table)
                if cells is None:          # 'io' etc.: different-schema map, skip (gap)
                    continue
                selectors = _sels(row.get("set_selectors")) + _sels(row.get("clear_selectors"))
                for s in selectors:
                    checked += 1
                    if (x, y, cfg, s) not in cells:
                        violations.append((name, cell_table, row["dst_wire"], cfg, s))
    assert checked >= 1000, "expected to cell-check the rank-1 selectors"
    assert not violations, (
        "rank-1 selectors with no config cell (bad codeword / wrong node):\n"
        + "\n".join("  %s [%s]: %s cfg=%s sel=%s" % v for v in violations[:30])
    )


def test_config_group_index_matches_destination_for_all_known_families():
    """Same-family-different-index wrong-node guard, extended to every family with a
    derived NPI (RMUX/IMUX + MCU-edge BBMUXE/S/W/InputMUX). For a dst wire of index
    `idx`, cfg_group's index must equal idx // NPI[family]. A row pointing at a
    different index of the same family programs a sibling mux -- the VP-AGM-018
    sub-class. Excludes x in {0,22} border columns (own layout). 0 as of 2026-09-13."""
    tables = _rank1_tables()
    checked = 0
    violations = []
    for name in tables:
        with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                match = WIRE.match(row.get("dst_wire", ""))
                cfg = row.get("cfg_group", "")
                if not match or not cfg:
                    continue
                x, family, idx = int(match.group(1)), match.group(3), int(match.group(4))
                if family not in NPI_ALL or x in (0, 22):
                    continue
                ci = _cfg_index(cfg)
                if ci is None:
                    continue
                checked += 1
                expected = idx // NPI_ALL[family]
                if ci != expected:
                    violations.append((name, row["dst_wire"], cfg,
                                       "cfg index %d != idx//%d = %d" % (ci, NPI_ALL[family], expected)))
    assert checked >= 1000, "expected to index-check the known-NPI families"
    assert not violations, (
        "same-family wrong-index rank-1 rows (would drive a sibling mux):\n"
        + "\n".join("  %s: %s cfg=%s (%s)" % v for v in violations[:30])
    )
