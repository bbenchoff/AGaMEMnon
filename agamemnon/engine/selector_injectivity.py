"""Load-time injectivity guards for the AGRV2K selector tables.

The single most expensive recurring defect in this project is a *silent lookup
miss*: a table that was correct in the context it was captured in gets consulted
outside that context, returns a structurally valid codeword for the wrong mux
input, bitgen reports ``0 unmapped``, the FCB accepts the image, and the design
misbehaves on silicon with no diagnostic anywhere.  Five instances are on the
record (two transposed ``BBMUXE_PAIR`` rows, the pad ENABLE z-set map, the
``bram_emit`` field drop, the ignored edge blacklist, the zero-padded name
compare) and each was found reactively, months later, from a hardware symptom.

A unit test cannot catch the next one: a test compares two written-down tables
and passes when they agree, *including when they agree on the same wrong thing*.
What has teeth is a physical invariant that needs no golden --

    inside one physical destination mux, two different inputs cannot share a
    codeword, and a source that is not wired to that mux cannot appear in its
    table at all.

Checked at load, that turns the next lossy extraction into a named startup
failure instead of a well-formed wrong bitstream.

Five checks, in decreasing key strength:

``K1``  instance injectivity      (dst instance, cell table, cfg group)
        Two different sources may not share a codeword at one destination mux.
``K1F`` instance functionality    same key, inverted
        One (destination, source) pip may not carry two different codewords.
``K2``  family injectivity        (boundary family, source index)
        For the boundary funnel the codeword is a pure function of the source
        RMUX index, so it must be injective within a family.
``FANIN`` membership              (family, source index) in the device graph
        A row whose source does not drive that destination family anywhere in
        ``rrg_edges_full.csv`` is a MISFILED row, not a spare datum.  This is
        the check that would have caught the 2026-08-20 ``bbmuxe_fanin.csv``
        defect on the day it landed: ``RMUX25`` and ``RMUX92`` are ``BBMUXS``
        feeders and appear in no RMUX->BBMUXE edge anywhere on the device.
``K4``  source law                (dst res, src res, tile delta, tile class)
        A mesh hop's codeword is a pure function of the two resource indices,
        the tile offset between them, and the tile class.  730 of 734 distinct
        keys in the shipped corridor tables already obey it and the remaining
        four are BramTILE-vs-LogicTILE pairs, i.e. a different tile class.
        A single mistyped codeword breaks this immediately.

``rrg_edges_full.csv`` is used as the *independent* witness throughout.  Its
``cfg`` column carries the boundary codeword (``BBMUXE9[2,6]``) and its rows are
device connectivity, extracted from the vendor arch DB rather than from the
design-corpus harvest that produced the fan-in tables -- so agreement between
them is evidence rather than tautology.

Known-defective rows that ship today are enumerated in ``KNOWN_DEFECTS``.  That
list is NOT a way to tolerate them.  Every entry must name a *refusal*: the
mechanism that stops the ambiguous codeword ever reaching a bitstream, so the
build fails closed instead of emitting a wrong terminal.  ``enforce`` refuses to
start if a known defect has no refusal, and ``tests/test_selector_injectivity.py``
fails if an entry no longer reproduces -- so the list cannot rot in either
direction.
"""
from __future__ import annotations

import collections
import csv
import os
import re
from dataclasses import dataclass


CHIPDB_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chipdb")

_WIRE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z]+)(\d+)")
_BOUNDARY = re.compile(r"(BBMUX[A-Z]+)0*([0-9]+)")
_RMUX = re.compile(r"RMUX0*([0-9]+)")
_CFG_GROUP_BASE = re.compile(r"\d+$")


class SelectorTableError(ValueError):
    """A selector table cannot be trusted.  Always fatal: raised at load."""


@dataclass(frozen=True)
class Violation:
    """One broken invariant, with enough detail to fix the data by hand."""

    kind: str
    table: str
    destination: str
    codeword: str
    sources: tuple
    rows: tuple = ()

    @property
    def signature(self):
        """Stable identity, so a known defect can be enumerated exactly."""
        return "%s|%s|%s|%s|%s" % (
            self.kind, self.table, self.destination, self.codeword,
            ",".join(sorted(self.sources)),
        )

    def describe(self):
        return "%s\n      %s at %s: codeword %s shared by %s\n      rows: %s" % (
            self.kind, self.table, self.destination, self.codeword,
            ", ".join(sorted(self.sources)), ", ".join(self.rows),
        )


@dataclass(frozen=True)
class Defect:
    """A violation that ships today, with the refusal that neutralises it."""

    signature: str
    summary: str
    citation: str
    refusal: str
    retire_when: str


# --------------------------------------------------------------------------
# Synthetic source aliases: several names, ONE real wire.
#
# These are NOT defects and must never be refused.  ``features/mcu_ahb.py``
# (see its comment at the analog hard-block promotion) deliberately renames one
# real source wire to several distinct synthetic names so the open router
# cannot swap two isolated oracle corridors.  A duplicate-codeword violation
# between members of one alias group is therefore expected and correct: they
# are one mux input, so they share one codeword.
#
# Declared here rather than in mcu_ahb.py because that module imports this one;
# keep the two in step by citing the creator in every entry.
#
# Do NOT add an entry to make a failing check pass.  An entry asserts that the
# members are provably the same physical wire -- cite the evidence.
# --------------------------------------------------------------------------
SYNTHETIC_SOURCE_ALIASES = (
    {
        "members": frozenset({"X22Y7_InputMUX100", "X22Y7_InputMUX101"}),
        "real_wire": "X22Y7_InputMUX01",
        "created_by": "features/mcu_ahb.py, analog hard-block promotion",
        "evidence": (
            "Two independent vendor af.exe builds (tools/oracle_adc0_db0 and "
            "tools/oracle_adc0_db1 in AG32-Docs, distinct route.tx and .bin "
            "sha256 pinned in qualification/analog_adc0_db{0,1}_route_evidence"
            ".jsonl) both harvest X22Y7_InputMUX01 -> X18Y7_RMUX03 with "
            "codeword 31;38.  The un-renamed workbench tables "
            "AG32-Docs/tools/agamemnon/chipdb/analog_adc0_db{0,1}_pip_cfg.csv "
            "record the real wire and carry no -typed-source suffix.  "
            "mcu_ahb.py's own comment states it: 'DB1 also uses InputMUX01'."
        ),
    },
)


def _alias_group_for(sources):
    """The alias group covering every source in ``sources``, or ``None``."""
    for alias in SYNTHETIC_SOURCE_ALIASES:
        if sources and set(sources) <= alias["members"]:
            return alias
    return None


# --------------------------------------------------------------------------
# The defects that ship today.  Read the module docstring before adding one.
# --------------------------------------------------------------------------

KNOWN_DEFECTS = (
    Defect(
        signature=(
            "duplicate-codeword|bram_site_read_pip_cfg.csv|"
            "X13Y4_CtrlMUX02/fabric/CFG_CTRLMUX|28;32|"
            "X14Y4_RMUX00,X14Y4_RMUX84"
        ),
        summary=(
            "Two real pips share one CtrlMUX codeword.  X14Y4_RMUX00 is "
            "corroborated by bram_site_read_paths.csv:475 and by the same "
            "codeword at the sibling instance X13Y3_CtrlMUX02 (line 191), which "
            "is the tile-class source law; the X14Y4_RMUX84 row at line 248 "
            "appears in no path table and duplicates RMUX00's word."
        ),
        citation="AG32-Docs/docs/GOAL_VENDOR_PARITY.md G25",
        refusal=(
            "features/mcu_ahb.py drops the uncorroborated member of the "
            "colliding group from the exact-field map, so a route through "
            "X14Y4_RMUX84 -> X13Y4_CtrlMUX02 reports UNMAPPED and bitgen fails "
            "closed instead of writing RMUX00's terminal."
        ),
        retire_when=(
            "one af.exe build routes X14Y4_RMUX84 -> X13Y4_CtrlMUX02 and gives "
            "line 248 its own codeword, or the row is deleted"
        ),
    ),
    Defect(
        signature=(
            "duplicate-codeword|bram_site_read_pip_cfg.csv+corridor merge|"
            "X14Y12_RMUX49/fabric/CFG_RMUX8|12;19|"
            "X14Y11_RMUX37,X14Y8_RMUX85"
        ),
        summary=(
            "mcu_scratch3_candidate_pip_cfg.csv gives X14Y11_RMUX37 -> "
            "X14Y12_RMUX49 the codeword that bram_site_read_pip_cfg.csv:320 "
            "witnesses for X14Y8_RMUX85 -> X14Y12_RMUX49.  Its own evidence "
            "string says how it got there: "
            "'candidate-13-clean-same-geometry-occurrences-not-silicon-"
            "qualified' -- a codeword transplanted between sources by "
            "geometric analogy, which is this defect class stated outright.  "
            "RMUX85 is corroborated by bram_site_read_paths.csv:416; RMUX37 by "
            "no path table anywhere."
        ),
        citation="found 2026-08-20 by the merged-view K1 audit; not previously reported",
        refusal=(
            "the file is declared in features/mcu_ahb.py ARCHIVAL_FILES, which "
            "is non-emissive -- it is inventoried but never loaded into the "
            "exact-field map -- and features/mcu_ahb.py additionally drops the "
            "uncorroborated member if it is ever promoted."
        ),
        retire_when=(
            "a vendor route.tx gives X14Y11_RMUX37 -> X14Y12_RMUX49 its own "
            "codeword, or the candidate row is deleted"
        ),
    ),
    Defect(
        signature=(
            "malformed-row|pad_input_L48_left_corridors.csv|"
            "row width != header width|-|-"
        ),
        summary=(
            "Four rows of pad_input_L48_left_corridors.csv (lines 2, 4, 6, 8) "
            "carry 12 fields against a 13-column header, so csv.DictReader "
            "slides the evidence string 'vendor-routed-physical-iob' into the "
            "set_selectors column and leaves evidence as None.  These are the "
            "fixed pad InputMUX -> RMUX hops, which correctly have no "
            "codeword; the row is one comma short of saying so."
        ),
        citation="found 2026-08-20 by the shape-selected selector audit",
        refusal=(
            "features/physical_io.py partitions these rows on an EMPTY "
            "cell_table and only ever reads set_selectors on the "
            "configurable partition, so the mis-slid value is never parsed as "
            "a codeword today.  The audit refuses to treat a malformed row as "
            "data at all -- it is excluded from every injectivity check rather "
            "than silently contributing a garbage codeword."
        ),
        retire_when=(
            "one comma is added to each of lines 2, 4, 6, 8 so the evidence "
            "column lines up (a chipdb edit, so it needs the fingerprint pin "
            "updated with it)"
        ),
    ),
    Defect(
        signature="family-collision|bbmuxe_fanin.csv|BBMUXE|(0, 4)|RMUX25,RMUX49",
        summary=(
            "The K2 face of the misfiled-BBMUXS-row defect below: RMUX25 is a "
            "BBMUXS feeder and carries BBMUXS's (0,4), which collides with "
            "BBMUXE's genuine RMUX49."
        ),
        citation="AG32-Docs/docs/GOAL_VENDOR_PARITY.md G25",
        refusal=(
            "same as the fan-in defect below: no RMUX25 -> BBMUXE edge exists in "
            "any chipdb table, so the colliding row is unreachable; "
            "features/routing.py's ambiguous_boundary_sources() withdraws its "
            "fallback as well."
        ),
        retire_when="the corrected family-keyed tables are landed",
    ),
    Defect(
        signature="family-collision|bbmuxe_fanin.csv|BBMUXE|(2, 6)|RMUX20,RMUX92",
        summary=(
            "The K2 face of the misfiled-BBMUXS-row defect below: RMUX92 is a "
            "BBMUXS feeder and carries BBMUXS's (2,6), which collides with "
            "BBMUXE's genuine RMUX20."
        ),
        citation="AG32-Docs/docs/GOAL_VENDOR_PARITY.md G25",
        refusal=(
            "same as the fan-in defect below: no RMUX92 -> BBMUXE edge exists "
            "in any chipdb table, so the colliding row is unreachable; "
            "features/routing.py's ambiguous_boundary_sources() withdraws its "
            "fallback as well."
        ),
        retire_when="the corrected family-keyed tables are landed",
    ),
    Defect(
        signature="fanin-membership|bbmuxe_fanin.csv|BBMUXE|-|RMUX25,RMUX92",
        summary=(
            "bbmuxe_fanin.csv carries two BBMUXS feeders in an east-keyed "
            "table.  rrg_edges_full.csv shows the BBMUXE fan-in is exactly "
            "{3,13,20,26,33,43,49,56,63,79,86,93}; RMUX25 and RMUX92 appear in "
            "no RMUX->BBMUXE edge anywhere on the device.  The generator "
            "tools/agamemnon/engine_work/harvest_bbmuxe.py accepted both "
            "families and then aggregated with the family field discarded."
        ),
        citation="AG32-Docs/docs/GOAL_VENDOR_PARITY.md G25",
        refusal=(
            "unreachable by construction, and verified so: no table in the "
            "chipdb carries an RMUX25 or RMUX92 -> BBMUXE edge, so the "
            "architecture graph never offers the router a hop that could "
            "consult these rows -- see misfiled_boundary_sources() and "
            "tests/test_selector_injectivity.py. features/routing.py's "
            "ambiguous_boundary_sources() withdraws the source-keyed fallback "
            "for both indices as a second, independent refusal."
        ),
        retire_when=(
            "the corrected family-keyed tables staged at "
            "AG32-Docs/tools/bbmuxe_injectivity/ are landed (a pending decision)"
        ),
    ),
)

KNOWN_BY_SIGNATURE = {defect.signature: defect for defect in KNOWN_DEFECTS}


# --------------------------------------------------------------------------
# Check primitives.  Each takes already-parsed rows and returns violations.
# --------------------------------------------------------------------------

def check_instance_injectivity(rows, table):
    """K1 -- inside one physical destination mux, no codeword may repeat.

    ``rows`` is an iterable of ``(destination, source, codeword, origin)``.
    A repeat means one of the two rows encodes the OTHER input's terminal, and
    nothing in the table can say which; emitting either config-accepts.
    """
    per = collections.defaultdict(lambda: collections.defaultdict(dict))
    for destination, source, codeword, origin in rows:
        per[destination][codeword][source] = origin
    violations = []
    for destination, words in per.items():
        for codeword, sources in words.items():
            if len(sources) > 1:
                # Several synthetic names for ONE real wire are one mux input,
                # so sharing a codeword is correct, not a collision.  Skipped
                # here rather than at the refusal stage so the defect ledger
                # never has to enumerate a non-defect.
                if _alias_group_for(sources) is not None:
                    continue
                violations.append(Violation(
                    kind="duplicate-codeword", table=table,
                    destination=destination, codeword=codeword,
                    sources=tuple(sorted(sources)),
                    rows=tuple(sources[s] for s in sorted(sources)),
                ))
    return violations


def check_instance_functionality(rows, table):
    """K1F -- one (destination, source) pip may not carry two codewords."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for destination, source, codeword, origin in rows:
        per[(destination, source)][codeword].append(origin)
    violations = []
    for (destination, source), words in per.items():
        if len(words) > 1:
            violations.append(Violation(
                kind="ambiguous-codeword", table=table,
                destination=destination,
                codeword=" vs ".join(sorted(words)),
                sources=(source,),
                rows=tuple(sorted(o for group in words.values() for o in group)),
            ))
    return violations


def check_family_injectivity(table_map, table):
    """K2 -- within one boundary family, codeword -> source is one-to-one."""
    reverse = collections.defaultdict(set)
    for (family, source), codeword in table_map.items():
        reverse[(family, codeword)].add(source)
    return [
        Violation(kind="family-collision", table=table,
                  destination=family, codeword=str(codeword),
                  sources=tuple("RMUX%02d" % s for s in sorted(sources)))
        for (family, codeword), sources in sorted(reverse.items(), key=str)
        if len(sources) > 1
    ]


def check_fanin_membership(table_map, fanin, table):
    """A row whose source does not drive that family is misfiled, not spare."""
    misfiled = collections.defaultdict(list)
    for family, source in sorted(table_map):
        if source in fanin.get(family, frozenset()):
            continue
        elsewhere = sorted(f for f in fanin if source in fanin[f]) or ["nowhere"]
        misfiled[(family, tuple(elsewhere))].append(source)
    return [
        Violation(kind="fanin-membership", table=table, destination=family,
                  codeword="-",
                  sources=tuple("RMUX%02d" % s for s in sorted(sources)),
                  rows=("belongs to %s" % ("/".join(elsewhere),),))
        for (family, elsewhere), sources in sorted(misfiled.items(), key=str)
    ]


def check_source_law(rows, table):
    """K4 -- codeword is a function of (dst res, src res, delta, tile class)."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, codeword, origin in rows:
        per[key][codeword].append(origin)
    violations = []
    for key, words in per.items():
        if len(words) > 1:
            violations.append(Violation(
                kind="source-law", table=table, destination=str(key),
                codeword=" vs ".join(sorted(words)), sources=(str(key[2:4]),),
                rows=tuple(sorted(o for group in words.values() for o in group)),
            ))
    return violations


# --------------------------------------------------------------------------
# Shipped-data readers.  rrg_edges_full.csv is the independent witness.
# --------------------------------------------------------------------------

def _rrg_boundary_rows(chipdb_root):
    """RMUX -> BBMUX* rows of rrg_edges_full.csv, prefiltered by raw scan.

    A full csv parse of the 292k-row file costs 0.3 s; the substring prefilter
    brings the whole check to about 50 ms, which is what makes it affordable on
    the load path rather than only in a test.
    """
    path = os.path.join(chipdb_root, "rrg_edges_full.csv")
    if not os.path.exists(path):
        return [], []
    with open(path, encoding="utf-8", newline="") as stream:
        header = stream.readline()
        wanted = [line for line in stream if "BBMUX" in line]
    return list(csv.DictReader([header] + wanted)), wanted


RMUX_PER_TILE = 96
# The south bank's feeders are the east bank's shifted by 24 RMUX tracks:
# BBMUXS_PAIR[i] == BBMUXE_PAIR[(i + 24) % 96].  ``_extend_south_by_offset_law``
# only applies it after checking it against every BBMUXS row the device graph
# does enumerate, so it cannot quietly invent a fan-in that contradicts data.
BBMUXS_OFFSET = 24


def _extend_south_by_offset_law(fanin, law):
    """Complete the sparsely-enumerated BBMUXS fan-in, only if the law holds.

    rrg_edges_full.csv enumerates all twelve BBMUXE feeders but only one
    BBMUXS row, which would make a membership check on a south feeder read as
    'belongs nowhere'.  That is a worse answer than 'belongs to BBMUXS': it
    hides which bank a misfiled row came from.
    """
    east = fanin.get("BBMUXE", frozenset())
    if len(east) != 12:
        return fanin
    derived = frozenset((index - BBMUXS_OFFSET) % RMUX_PER_TILE
                        for index in east)
    for (family, source), codeword in law.items():
        if family != "BBMUXS":
            continue
        if source not in derived:
            return fanin
        east_source = (source + BBMUXS_OFFSET) % RMUX_PER_TILE
        if law.get(("BBMUXE", east_source), codeword) != codeword:
            return fanin
    extended = dict(fanin)
    extended["BBMUXS"] = frozenset(fanin.get("BBMUXS", frozenset())) | derived
    return extended


def boundary_fanin(chipdb_root):
    """``{family: frozenset(source RMUX index)}`` from the device graph."""
    rows, _ = _rrg_boundary_rows(chipdb_root)
    fanin = collections.defaultdict(set)
    for row in rows:
        family = _BOUNDARY.fullmatch(row["dst_res"])
        source = _RMUX.fullmatch(row["src_res"])
        if family and source:
            fanin[family.group(1)].add(int(source.group(1)))
    fanin = {family: frozenset(sources) for family, sources in fanin.items()}
    if not fanin:
        return fanin
    return _extend_south_by_offset_law(fanin, boundary_codeword_law(chipdb_root))


def boundary_codeword_law(chipdb_root):
    """``{(family, source index): (lo, hi)}`` witnessed by the device graph."""
    rows, _ = _rrg_boundary_rows(chipdb_root)
    law = {}
    for row in rows:
        family = _BOUNDARY.fullmatch(row["dst_res"])
        source = _RMUX.fullmatch(row["src_res"])
        pair = re.search(r"\[(\d+),(\d+)\]", row.get("cfg") or "")
        if family and source and pair:
            law[(family.group(1), int(source.group(1)))] = (
                int(pair.group(1)), int(pair.group(2)))
    return law


def tile_classes(chipdb_root):
    """``{(x, y): tile type}`` -- the IMUX fan-in order is class-dependent."""
    path = os.path.join(chipdb_root, "rrg_edges_full.csv")
    classes = {}
    if not os.path.exists(path):
        return classes
    with open(path, newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            classes[(int(row["src_x"]), int(row["src_y"]))] = row["src_tile"]
            classes[(int(row["dst_x"]), int(row["dst_y"]))] = row["dst_tile"]
    return classes


SELECTOR_ROW_COLUMNS = frozenset({"src_wire", "dst_wire", "set_selectors"})
EXIT_PAIR_COLUMNS = frozenset({"edge_x", "edge_y", "edge_res",
                               "src_x", "src_y", "src_res", "selectors"})


def _header(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as stream:
        return frozenset(column.strip() for column in
                         next(csv.reader(stream), []))


def selector_tables(chipdb_root, columns=SELECTOR_ROW_COLUMNS):
    """Every CSV carrying selector rows, chosen by SHAPE, not by filename.

    Selecting tables with a ``*_pip_cfg.csv`` glob would itself be an instance
    of the defect this module exists to stop: two of the shipped exact-codeword
    tables are named ``pad_*_corridors.csv`` and a name-keyed audit skips them
    in silence.  Headers are read instead, so a new table is covered the moment
    it has the shape, whatever it is called.
    """
    found = []
    for name in sorted(os.listdir(chipdb_root)):
        if not name.endswith(".csv"):
            continue
        path = os.path.join(chipdb_root, name)
        try:
            if columns <= _header(path):
                found.append(name)
        except OSError:
            continue
    return found


def _pip_cfg_rows(chipdb_root, filenames=None):
    """Parsed selector rows with a destination-instance key."""
    if filenames is None:
        filenames = selector_tables(chipdb_root)
    parsed = []
    for filename in filenames:
        path = os.path.join(chipdb_root, filename)
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as stream:
            for index, row in enumerate(csv.DictReader(stream), start=2):
                if row.get(None) is not None or None in row.values():
                    # A short or long row makes csv.DictReader slide every
                    # later field one column left/right. The value still looks
                    # like a value, so nothing downstream notices -- this is
                    # the same defect class one level down, in the parse.
                    parsed.append({"file": filename, "line": index,
                                   "malformed": True})
                    continue
                if not row.get("set_selectors") or not row.get("dst_wire"):
                    continue
                source = _WIRE.fullmatch(row["src_wire"] or "")
                destination = _WIRE.fullmatch(row["dst_wire"] or "")
                if not source or not destination:
                    continue
                parsed.append({
                    "file": filename,
                    "line": index,
                    "malformed": False,
                    "origin": "%s:%d" % (filename, index),
                    "src": row["src_wire"],
                    "dst": row["dst_wire"],
                    "src_xy": (int(source.group(1)), int(source.group(2))),
                    "dst_xy": (int(destination.group(1)), int(destination.group(2))),
                    "src_res": (source.group(3), int(source.group(4))),
                    "dst_res": (destination.group(3), int(destination.group(4))),
                    "cell_table": row.get("cell_table", ""),
                    "cfg_group": row.get("cfg_group", ""),
                    "clear": row.get("clear_selectors", ""),
                    "set": row.get("set_selectors", ""),
                })
    return parsed


def _exit_pair_rows(chipdb_root):
    """Merged exit-pair rows plus any silent last-wins overwrite between files."""
    rows = []
    seen = {}
    overwrites = []
    for filename in selector_tables(chipdb_root, EXIT_PAIR_COLUMNS):
        path = os.path.join(chipdb_root, filename)
        with open(path, newline="", encoding="utf-8") as stream:
            for index, row in enumerate(csv.DictReader(stream), start=2):
                edge = _BOUNDARY.fullmatch(row["edge_res"] or "")
                source = re.fullmatch(r"([A-Za-z]+)0*([0-9]+)",
                                      row["src_res"] or "")
                if not edge or not source:
                    continue
                destination = "X%sY%s_%s%02d" % (
                    row["edge_x"], row["edge_y"], edge.group(1),
                    int(edge.group(2)))
                src = "X%sY%s_%s%02d" % (
                    row["src_x"], row["src_y"], source.group(1),
                    int(source.group(2)))
                origin = "%s:%d" % (filename, index)
                rows.append((destination, src, row["selectors"], origin))
                key = (destination, src)
                if key in seen and seen[key][0] != row["selectors"]:
                    overwrites.append(Violation(
                        kind="silent-overwrite", table="exit-pair tables",
                        destination=destination,
                        codeword="%s then %s" % (seen[key][0], row["selectors"]),
                        sources=(src,), rows=(seen[key][1], origin)))
                seen[key] = (row["selectors"], origin)
    return rows, overwrites


def _destination_key(row):
    return "%s/%s/%s" % (row["dst"], row["cell_table"], row["cfg_group"])


# --------------------------------------------------------------------------
# The audit
# --------------------------------------------------------------------------

_AUDIT_CACHE = {}


def _chipdb_fingerprint(chipdb_root):
    """(name, size, mtime) over the files the audit reads.  ~5 ms."""
    stamps = []
    for name in sorted(os.listdir(chipdb_root)):
        if not name.endswith(".csv"):
            continue
        info = os.stat(os.path.join(chipdb_root, name))
        stamps.append((name, info.st_size, info.st_mtime_ns))
    return tuple(stamps)


def audit(chipdb_root=CHIPDB_ROOT):
    """Every invariant violation in the shipped selector tables (memoised)."""
    chipdb_root = os.path.abspath(chipdb_root)
    key = (chipdb_root, _chipdb_fingerprint(chipdb_root))
    cached = _AUDIT_CACHE.get(key)
    if cached is not None:
        return list(cached)
    violations = _audit_uncached(chipdb_root)
    _AUDIT_CACHE.clear()
    _AUDIT_CACHE[key] = tuple(violations)
    return violations


def _audit_uncached(chipdb_root):
    violations = []
    every = _pip_cfg_rows(chipdb_root)
    rows = [row for row in every if not row["malformed"]]
    broken = collections.defaultdict(list)
    for row in every:
        if row["malformed"]:
            broken[row["file"]].append(row["line"])
    for filename, lines in sorted(broken.items()):
        violations.append(Violation(
            kind="malformed-row", table=filename,
            destination="row width != header width",
            codeword="-", sources=("-",),
            rows=tuple("%s:%d" % (filename, line) for line in lines)))

    # K1 / K1F over the MERGED corridor view.  Per-file is not enough: the
    # bram_site_read collision is intra-file but the ADC one only appears once
    # analog_adc0_db0 and analog_adc0_db1 are loaded into the same dict, which
    # is exactly what load_routing_metadata does on every build.
    merged = [
        (_destination_key(row), row["src"], row["set"], row["origin"])
        for row in rows
    ]
    label = "*_pip_cfg.csv (merged corridor view)"
    for violation in (check_instance_injectivity(merged, label)
                      + check_instance_functionality(merged, label)):
        violations.append(_relabel_to_first_file(violation))

    # The codeword is meaningless without the group mask it is read against,
    # so two rows at one instance disagreeing on clear_selectors would make the
    # K1 comparison above compare incomparable things.  Ships clean today.
    per_mask = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        per_mask[_destination_key(row)][row["clear"]].append(row["origin"])
    for destination, masks in sorted(per_mask.items()):
        if len(masks) > 1:
            violations.append(Violation(
                kind="inconsistent-group-mask", table="*_pip_cfg.csv",
                destination=destination,
                codeword=" vs ".join(sorted(masks)), sources=("-",),
                rows=tuple(sorted(o for g in masks.values() for o in g)),
            ))

    # K4 source law, keyed on tile class because the BramTILE IMUX fan-in order
    # differs from the LogicTILE one.
    classes = tile_classes(chipdb_root)
    law_rows = []
    for row in rows:
        clears = [int(v) for v in row["clear"].split(";") if v]
        sets = [int(v) for v in row["set"].split(";") if v]
        base = min(clears) if clears else 0
        key = (
            row["dst_res"], row["src_res"],
            (row["src_xy"][0] - row["dst_xy"][0],
             row["src_xy"][1] - row["dst_xy"][1]),
            classes.get(row["dst_xy"], "?"), row["cell_table"],
            _CFG_GROUP_BASE.sub("", row["cfg_group"]),
        )
        law_rows.append((key, str(tuple(s - base for s in sets)), row["origin"]))
    violations.extend(check_source_law(law_rows, "*_pip_cfg.csv (source law)"))

    # The exit-pair tables are the other exact-tuple family. They are merged
    # into one runtime dict keyed on the full instance tuple, LAST WINS, with
    # no conflict check at all -- so a disagreement between two files would be
    # resolved by load order. Audit the merged view, both directions.
    exit_rows, overwrites = _exit_pair_rows(chipdb_root)
    label = "exit-pair tables (merged)"
    violations.extend(check_instance_injectivity(exit_rows, label))
    violations.extend(check_instance_functionality(exit_rows, label))
    violations.extend(overwrites)

    # K2 + FANIN over the boundary fan-in table, against the device graph.
    fanin = boundary_fanin(chipdb_root)
    fanin_path = os.path.join(chipdb_root, "bbmuxe_fanin.csv")
    if os.path.exists(fanin_path) and fanin:
        shipped = {}
        with open(fanin_path, newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                source = _RMUX.fullmatch(row["feeder_res"])
                if source:
                    shipped[("BBMUXE", int(source.group(1)))] = (
                        int(row["lo"]), int(row["hi"]))
        violations.extend(check_family_injectivity(shipped, "bbmuxe_fanin.csv"))
        violations.extend(
            check_fanin_membership(shipped, fanin, "bbmuxe_fanin.csv"))

    return violations


def _relabel_to_first_file(violation):
    """Name the file(s) the colliding rows came from, not the merged view."""
    files = sorted({origin.split(":")[0] for origin in violation.rows})
    if not files:
        return violation
    table = files[0] if len(files) == 1 else "%s+corridor merge" % files[0]
    return Violation(
        kind=violation.kind, table=table, destination=violation.destination,
        codeword=violation.codeword, sources=violation.sources,
        rows=violation.rows,
    )


def ambiguous_exact_pips(chipdb_root=CHIPDB_ROOT):
    """``{(src_wire, dst_wire): reason}`` whose exact codeword must be refused.

    Arbitration follows the rule already used for the boundary fallback in
    ``features/routing.py``: observation decides.  A colliding row keeps its
    codeword when it -- and only it -- is corroborated by the sibling path
    table that records the route the codeword was harvested from.  When no
    member is corroborated, or more than one is, nothing can arbitrate and the
    whole group is refused.  Guessing writes a well-formed selection of a
    different mux input.
    """
    chipdb_root = os.path.abspath(chipdb_root)
    witnessed = _path_table_hops(chipdb_root)
    refused = {}
    for violation in audit(chipdb_root):
        if violation.kind != "duplicate-codeword":
            continue
        members = []
        for origin in violation.rows:
            filename, _, line = origin.partition(":")
            members.append((filename, int(line)))
        pips = [_row_pip(chipdb_root, filename, line)
                for filename, line in members]
        pips = [pip for pip in pips if pip]
        backed = [pip for pip in pips if pip in witnessed]
        keep = backed[0] if len(backed) == 1 else None
        for pip in pips:
            if pip == keep:
                continue
            if keep is not None:
                why = "%s is the only member corroborated by a path table" % (
                    keep[0],)
            elif backed:
                why = ("%d members are corroborated by a path table, so "
                       "nothing arbitrates which one owns the codeword"
                       % (len(backed),))
            else:
                why = ("no member is corroborated by any path table, so "
                       "nothing arbitrates which one owns the codeword")
            refused[pip] = (
                "codeword %s at %s is shared with %s; %s" % (
                    violation.codeword, violation.destination,
                    ", ".join(s for s in violation.sources
                              if s != pip[0]) or "another source", why,
                )
            )
    return refused


def _row_pip(chipdb_root, filename, line):
    path = os.path.join(chipdb_root, filename)
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as stream:
        for index, row in enumerate(csv.DictReader(stream), start=2):
            if index == line:
                return (row["src_wire"], row["dst_wire"])
    return None


def _path_table_hops(chipdb_root):
    """Every (src, dst) hop recorded in a ``*_path.csv`` / ``*_paths.csv``."""
    hops = set()
    for name in sorted(os.listdir(chipdb_root)):
        if not (name.endswith("_path.csv") or name.endswith("_paths.csv")):
            continue
        with open(os.path.join(chipdb_root, name), newline="",
                  encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if row.get("src_wire") and row.get("dst_wire"):
                    hops.add((row["src_wire"], row["dst_wire"]))
    return hops


def misfiled_boundary_sources(chipdb_root=CHIPDB_ROOT):
    """``{family: {source index: family it really belongs to}}``.

    Self-contained: derived from the device graph, not from the corpus harvest
    that produced the table being judged, and not from the corrected tables
    staged in AG32-Docs (which are a pending decision).
    """
    chipdb_root = os.path.abspath(chipdb_root)
    fanin = boundary_fanin(chipdb_root)
    misfiled = collections.defaultdict(dict)
    path = os.path.join(chipdb_root, "bbmuxe_fanin.csv")
    if not os.path.exists(path) or not fanin:
        return {}
    with open(path, newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            match = _RMUX.fullmatch(row["feeder_res"])
            if not match:
                continue
            index = int(match.group(1))
            if index in fanin.get("BBMUXE", frozenset()):
                continue
            owners = [f for f in fanin if index in fanin[f]]
            misfiled["BBMUXE"][index] = owners[0] if owners else "nowhere"
    return {family: dict(rows) for family, rows in misfiled.items()}


def boundary_edge_exists(chipdb_root, family, source_index):
    """Whether ANY chipdb table offers a ``RMUX<n> -> family`` edge.

    A misfiled row that no table can reach is refused by construction: the
    architecture graph never presents the hop, so the codeword is never
    consulted.  Proving that is what lets the misfiled rows stay quarantined
    rather than blocking every build.
    """
    chipdb_root = os.path.abspath(chipdb_root)
    needle = re.compile(r"RMUX0*%d" % source_index)
    for name in sorted(os.listdir(chipdb_root)):
        if not name.endswith(".csv"):
            continue
        with open(os.path.join(chipdb_root, name), encoding="utf-8",
                  errors="replace") as stream:
            for line in stream:
                if family in line and needle.search(line):
                    return name
    return None


# --------------------------------------------------------------------------
# The load-time guard
# --------------------------------------------------------------------------

def enforce(chipdb_root=CHIPDB_ROOT, *, report=None):
    """Fail closed unless every selector-table violation is a known defect.

    Returns the known defects that are still present, so the caller can print
    them.  Raises ``SelectorTableError`` on anything else -- there is no policy
    that can recover from it, because one of the colliding rows encodes another
    input terminal and the table cannot say which.
    """
    violations = audit(chipdb_root)
    unknown = [v for v in violations if v.signature not in KNOWN_BY_SIGNATURE]
    if unknown:
        raise SelectorTableError(
            "selector table invariant violated -- a codeword here selects a "
            "DIFFERENT mux input and would config-accept silently:\n  " +
            "\n  ".join(v.describe() for v in unknown) +
            "\n\nFix the data.  Adding a signature to "
            "agamemnon.engine.selector_injectivity.KNOWN_DEFECTS is only "
            "allowed together with a refusal that keeps the ambiguous codeword "
            "out of every bitstream."
        )
    present = [KNOWN_BY_SIGNATURE[v.signature] for v in violations]
    if present and report is not None:
        for defect in present:
            report("selector table: known defect still present -- %s" %
                   defect.summary.split(".")[0])
    return present
