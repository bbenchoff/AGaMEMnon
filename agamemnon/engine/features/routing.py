"""General data-routing selector loading, resolution, and emission."""

from __future__ import annotations

import collections
import csv
import json
import os
import re
from dataclasses import dataclass, field

from agamemnon.engine import chipdb_schema
from agamemnon.engine import mesh_template as MT
from agamemnon.engine import routing_admission
from agamemnon.engine import routing_selectors
from agamemnon.engine import routing_tiers
from agamemnon.engine import sel_byteexact as SB
from agamemnon.engine import wire_timing

from .physical_io import parse_wire
from .mcu_ahb import EXIT_PAIR_FILES, FEATURE as MCU_AHB_FEATURE
from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


NPG = {"RMUX": 6, "IMUX": 4, "OMUX": 3}
BS = {"RMUX": 10, "IMUX": 12}
NOCFG = ("BufMUX", "InputMUX", "SinkMUXPseudo")
MCU_ENTRY_FIRST_HOP_FILES = (
    "mcu_hwdata_lanes.csv",
    "mcu_ahb_request_controls.csv",
    "mcu_haddr_lanes.csv",
    "mcu_haddr_missing_lanes.csv",
)


def mcu_entry_first_hops(chipdb_root):
    """Return each qualified hard MCU entry root's legal first-hop set.

    Vendor route occupancy can contain other BufMUX-to-InputMUX combinations
    at the same UFMTILE.  Those are not interchangeable hard-port selectors:
    taking HWDATA[1]'s BufMUX03 through InputMUX02, for example, configures and
    routes cleanly but delivers a constant zero on silicon.  The lane tables'
    ``next_res`` column is therefore a source-specific constraint, not merely
    one extra edge to add alongside the generic corpus graph.
    """
    constraints = collections.defaultdict(set)

    def add(source, destination):
        constraints[source].add(destination)

    for filename in MCU_ENTRY_FIRST_HOP_FILES:
        path = os.path.join(str(chipdb_root), filename)
        if not os.path.exists(path):
            raise ValueError("missing qualified MCU entry table %s" % filename)
        for row in csv.DictReader(open(path, newline="", encoding="utf-8")):
            next_res = (row.get("next_res") or "").strip()
            if not next_res:
                continue
            x, y = int(row["entry_x"]), int(row["entry_y"])
            source = "X%dY%d_%s" % (x, y, row["entry_res"])
            destination = "X%dY%d_%s" % (x, y, next_res)
            add(source, destination)
    # The source tables above define the default hard-lane mapping.  Exact
    # silicon-qualified InputMUX rows may add a bounded alternate for the same
    # source.  Read only MCU-family rows from the byte-exact control table: a
    # generic corpus observation is not enough to make hard inputs
    # interchangeable (the HWDATA[1] constant-zero counterexample still
    # applies).  X13Y12 HTRANS1/HSIZE0 is a two-by-two matching choice, not an
    # unrestricted crossbar.
    exact_control = os.path.join(str(chipdb_root), "mcu_ahb_control_pip_cfg.csv")
    if not os.path.exists(exact_control):
        raise ValueError("missing qualified MCU entry table mcu_ahb_control_pip_cfg.csv")
    for row in csv.DictReader(open(exact_control, newline="", encoding="utf-8")):
        if row.get("cell_table") != "mcu":
            continue
        source, destination = row["src_wire"], row["dst_wire"]
        if source in constraints:
            add(source, destination)
    # Typed hard-peripheral outputs use full wire names rather than the AHB
    # tables' split entry columns.  Step zero is nevertheless the same
    # source-specific hard-boundary choice and must be exclusive.  This also
    # covers SPI0 MOSI-OE's direct BufMUX->RMUX first hop.
    for filename in (
        "mcu_uart0_tx_l48_paths.csv",
        "mcu_uart1_tx_l48_paths.csv",
        "mcu_uart2_tx_l48_paths.csv",
        "mcu_spi0_tx_l48_paths.csv",
        "mcu_spi1_tx_l48_paths.csv",
        "mcu_i2c0_l48_paths.csv",
        "mcu_i2c1_l48_paths.csv",
    ):
        peripheral_path = os.path.join(str(chipdb_root), filename)
        if not os.path.exists(peripheral_path):
            raise ValueError("missing qualified MCU entry table %s" % filename)
        for row in csv.DictReader(open(peripheral_path, newline="", encoding="utf-8")):
            if int(row["step"]) != 0:
                continue
            source, destination = row["src_wire"], row["dst_wire"]
            add(source, destination)
    return {source: frozenset(destinations)
            for source, destinations in constraints.items()}


def mcu_entry_first_hop_denied(constraints, source, destination):
    required = constraints.get(source)
    return required is not None and destination not in required


# Fallback selector codeword for an RMUX -> boundary-mux hop that has no exact
# (edge,src) tuple in EXIT_PAIR_FILES.  The codeword is a tile-invariant function
# of the SOURCE RMUX index alone: 24 source indices witnessed across BBMUXS,
# BBMUXE and BBMUXW at eight different edge tiles produce zero contradictions.
# tests/test_boundary_mux_selectors.py enforces that against the chipdb, because
# two entries here were hand-transcribed wrong and silently mis-encoded a lane
# (bitgen still reported 0 unmapped -- it emitted a well-formed WRONG terminal).
BBMUXS_PAIR = {
    2: (1, 4), 9: (1, 5), 19: (1, 6), 25: (0, 4), 32: (0, 5),
    39: (0, 6), 55: (3, 4), 62: (3, 5), 69: (3, 6), 92: (2, 6),
    # 75 and 85 complete the south bank's twelve feeders. They were absent, so
    # every route entering BBMUXS through them was refused for want of a
    # codeword we can in fact derive twice over:
    #   * the offset law asserted below for all ten entries above --
    #     BBMUXS_PAIR[i] == BBMUXE_PAIR[(i + 24) % 96] -- gives 75 -> BBMUXE[3]
    #     = (2,4) and 85 -> BBMUXE[13] = (2,5), from shipped, witnessed east rows;
    #   * the 2026-08-20 boundary-table audit (AG32-Docs
    #     tools/bbmuxe_injectivity/) independently recovers exactly those two
    #     values from vendor bitstreams, and its family-keyed table validates
    #     439/439 byte-exact across twelve vendor builds.
    # Recorded honestly: the bitstream witness is that audit's, not re-measured
    # here, and its corrected chipdb tables are staged but NOT landed. What is
    # verified here is that the audit's south table agrees with all ten existing
    # entries and adds only these two, and that both satisfy the offset law
    # against already-shipped east rows.
    75: (2, 4), 85: (2, 5),
}
BBMUXE_PAIR = {
    93: (3, 6), 26: (1, 4), 20: (2, 6), 49: (0, 4), 56: (0, 5),
    33: (1, 5), 63: (0, 6), 79: (3, 4), 86: (3, 5), 13: (2, 5),
    # 3 and 43 were transposed against the chipdb: 43's witnessed codeword (1;6)
    # sat under key 3, and 43 carried 63's (0;6) -- a 43/63 digit swap.  Both are
    # corrected here from bram_x9_data{3,4}_mcu_exit.csv,
    # mcu_ahb_control_exit_pairs.csv and mcu_edge_feeder_exit_pairs.csv, and both
    # corrections are independently required by the BBMUXS/BBMUXE offset law
    # (BBMUXS_PAIR[i] == BBMUXE_PAIR[(i + 24) % 96], exact for all ten BBMUXS
    # entries): the old 43 -> (0,6) collided with 63 and broke S[19].
    # 25 and 92 are the only entries here with no witnessed row anywhere in
    # EXIT_PAIR_FILES; they are grandfathered and pinned by the test, so the
    # residue cannot grow.  A terminal number is per-mux-instance, so their
    # sharing a codeword with 49/20 is not itself a contradiction -- which is
    # precisely why the 43/63 swap above survived review for so long.
    3: (2, 4), 43: (1, 6), 25: (0, 4), 92: (2, 6),
}


def _ambiguous_boundary_sources(table, witnessed=()):
    """Source indices whose fallback codeword does not identify them uniquely.

    ``BBMUXE_PAIR`` lists fourteen sources but only twelve distinct ``(lo, hi)``
    words: ``RMUX20``/``RMUX92`` share ``(2,6)`` and ``RMUX49``/``RMUX25`` share
    ``(0,4)``.

    The 2026-08-20 boundary-table audit (AG32-Docs ``tools/bbmuxe_injectivity/``)
    established why, and it is not what it looks like. ``bbmuxe_fanin.csv``,
    which these two entries came from, aggregates a harvest of BBMUXE **and**
    BBMUXS with the family field discarded; ``RMUX25`` and ``RMUX92`` are SOUTH
    feeders misfiled into an east-keyed table. Keyed by family the boundary
    tables are injective and reproduce 439/439 vendor codewords byte-exactly.
    So neither codeword is wrong -- the *key* was. Source index alone cannot
    name a boundary input, because two families reuse the index space.

    That makes refusing the guess strictly correct here for a sharper reason
    than a suspected transcription error: ``RMUX25`` and ``RMUX92`` are not in
    the BBMUXE fan-in at all, so no east route should ever consult them, and if
    one did, the word we would write is the word that selects a *different*
    input of that mux. Twelve observations back ``RMUX20`` and ``RMUX49``; none
    back the other two.

    Hence: when exactly one member of a colliding group is witnessed, that
    member keeps its codeword and only the unwitnessed member(s) lose the
    fallback. Refusing all four would be tidier and wrong -- it breaks
    ``qualification/dual_carry3_routed.json``, which routes
    ``X14Y12_RMUX49 -> X13Y12_BBMUXE05`` through a word twelve observations
    support. A group with no witnessed member, or with two, is refused entirely,
    because then nothing can arbitrate; ``witnessed`` defaults to empty so a
    caller without the exact tables gets that conservative reading.

    An exact witnessed tuple still resolves any source normally; only the guess
    is withdrawn. Measured blast radius: zero -- no ``source=="observed"`` RRG
    row into a BBMUXE uses either index without an exact tuple.

    The durable fix is upstream of this function: land the family-keyed tables
    and delete the two misfiled rows from ``BBMUXE_PAIR`` outright. That is a
    chipdb data change and is not made here, because
    ``tests/test_boundary_mux_selectors.py`` deliberately pins this dict to the
    shipped CSV -- editing one without the other would break the very guard that
    exists to catch code/data drift on this table.
    """
    witnessed = set(witnessed)
    groups = collections.defaultdict(set)
    for source_index, pair in table.items():
        groups[tuple(pair)].add(source_index)
    refused = set()
    for indices in groups.values():
        if len(indices) < 2:
            continue
        backed = indices & witnessed
        refused |= (indices - backed) if len(backed) == 1 else indices
    return frozenset(refused)


def witnessed_boundary_sources(chipdb_root, family):
    """RMUX source indices with at least one exact ``family`` tuple on record."""
    indices = set()
    for filename in EXIT_PAIR_FILES:
        path = os.path.join(chipdb_root, filename)
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if not str(row.get("edge_res", "")).startswith(family):
                    continue
                match = re.fullmatch(r"RMUX0*([0-9]+)", str(row.get("src_res", "")))
                if match:
                    indices.add(int(match.group(1)))
    return frozenset(indices)


def ambiguous_boundary_sources(chipdb_root):
    """``{family: refused source indices}`` for the source-keyed fallbacks."""
    return {
        "BBMUXE": _ambiguous_boundary_sources(
            BBMUXE_PAIR, witnessed_boundary_sources(chipdb_root, "BBMUXE")),
        "BBMUXS": _ambiguous_boundary_sources(
            BBMUXS_PAIR, witnessed_boundary_sources(chipdb_root, "BBMUXS")),
    }


MCU_ENTRY = {
    (14, 10, 14): [("CFG_RMUX2", 22), ("CFG_RMUX2", 28)],
    (14, 12, 73): [("CFG_RMUX12", 12), ("CFG_RMUX12", 18)],
    (14, 12, 21): [("CFG_RMUX3", 32), ("CFG_RMUX3", 38)],
}


# Exact physical InputMUX-entry selector observations recovered from retained
# vendor routes and their bound AGRV2KL48 images.  Unlike MCU_ENTRY (three
# earlier curated destination rows), this table includes both endpoints so an
# observation can never silently authorize a different InputMUX source that
# happens to target the same RMUX.
#
# The RMUX92 value is independently identical in run_b1234, run_bx31337 and
# run_bx7777.  Its local (3,8) pair disproves the blind _mcu_entry_pair (2,8)
# formula at this exact edge.  RMUX34 has one retained witness in run_bx31337;
# its local (2,8) pair agrees with the formula, but is registered as the exact
# observation rather than inheriting the formula's broader claim.  Evidence:
# AG32-Docs/tools/vendor_parity/evidence/witness_bucket1_mcu_entry/selectors.json
_VENDOR_OBSERVED_EXACT_MCU_ENTRY = {
    (15, 10, 92, 13, 10, 11): ("CFG_RMUX15", (23, 28)),
    (14, 10, 34, 13, 10, 5): ("CFG_RMUX5", (42, 48)),
}


def exact_boundary_edges(chipdb_root, family):
    """Return RMUX->``family`` edges with an exact bitgen selector tuple."""
    edges = set()
    for filename in EXIT_PAIR_FILES:
        path = os.path.join(chipdb_root, filename)
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if not str(row.get("edge_res", "")).startswith(family):
                    continue
                edges.add(
                    "X%sY%s_%s.X%sY%s_%s" %
                    (row["src_x"], row["src_y"], row["src_res"],
                     row["edge_x"], row["edge_y"], row["edge_res"])
                )
    return edges


def exact_bbmuxw_edges(chipdb_root):
    """Return RMUX->BBMUXW edges with an exact bitgen selector tuple."""
    return exact_boundary_edges(chipdb_root, "BBMUXW")


def bbmuxw_edge_admitted(edge, exact_edges, research_unsafe=False):
    """Whether a west-boundary entrance may appear in this graph profile."""
    return bool(research_unsafe or edge in exact_edges)


def _add_admitted_iotile_pips(*, ctx, Loc, wire_name, wireset, seen_pip,
                               rows, delay_for, is_blacklisted=None):
    """Add only the exact IOTILE pips supplied by authenticated rows.

    Authenticated does not mean unbannable. Every loader that adds a pip has to
    consult the blacklist, or a ban on one of these edges quietly does nothing.
    """
    count = 0
    for row in rows:
        if not routing_admission.supplies_architecture_pip(row):
            continue
        source = row["route"]["source"]
        destination = row["route"]["destination"]
        record = {
            "src_tile": source["tile"],
            "src_x": str(source["x"]), "src_y": str(source["y"]),
            "src_res": "%s%02d" % (source["family"], source["index"]),
            "dst_tile": destination["tile"],
            "dst_x": str(destination["x"]), "dst_y": str(destination["y"]),
            "dst_res": "%s%02d" % (
                destination["family"], destination["index"]
            ),
            "source": "experimental-row-admission",
        }
        if is_blacklisted is not None and is_blacklisted(record):
            continue
        source_wire = wire_name(
            record["src_x"], record["src_y"], record["src_res"]
        )
        destination_wire = wire_name(
            record["dst_x"], record["dst_y"], record["dst_res"]
        )
        if source_wire not in wireset or destination_wire not in wireset:
            raise ValueError(
                "authenticated experimental routing row has absent endpoint wire: %s"
                % row["edge_id"]
            )
        name = "%s.%s" % (source_wire, destination_wire)
        if name in seen_pip:
            continue
        ctx.addPip(
            name=name, type="EXPERIMENTAL_ROUTE",
            srcWire=source_wire, dstWire=destination_wire,
            delay=delay_for(record),
            loc=Loc(destination["x"], destination["y"], 0),
        )
        seen_pip.add(name)
        count += 1
    return count


@dataclass
class RoutingSelectorTables:
    chipdb_root: object
    archival_legacy: bool
    dir_bank: dict
    clean_edge: dict
    relative_edge: dict
    admitted_edge: dict
    admission_binding: dict | None
    lut: object
    conflicted_edge: dict = field(default_factory=dict)
    #: {"BBMUXE"/"BBMUXS": frozenset(source indices)} whose source-keyed fallback
    #: codeword cannot identify them; see _ambiguous_boundary_sources.
    ambiguous_boundary: dict = field(default_factory=dict)
    geom_rmux: dict | None = None
    absolute: dict | None = None
    group_context: dict | None = None

    @classmethod
    def load(cls, chipdb_root, options):
        selector_map = json.loads((chipdb_root / "sel_map.json").read_text(encoding="utf-8"))
        dir_bank = {
            tuple(int(value) for value in key.split(",")): bank
            for key, bank in selector_map["RMUX_from_RMUX_hi_bank_by_dxdy"].items()
        }
        clean_edge = {}
        relative_edge = {}
        edge_file = chipdb_root / "sel_edge_pairs.agdb"
        if not edge_file.exists():
            raise ValueError(
                "routing requires chipdb/sel_edge_pairs.agdb; refusing to "
                "continue without release selector evidence"
            )
        clean_edge = routing_selectors.load_clean_edges(str(chipdb_root))
        print("loaded %d block-clean physical edge sel pairs" % len(clean_edge))
        relative_edge, conflicts = routing_selectors.relative_edges(clean_edge)
        print("derived %d unanimous tile-relative sel pairs (%d conflicting keys rejected)"
              % (len(relative_edge), len(conflicts)))
        try:
            admitted_edge = routing_admission.selected_edge_map(options, chipdb_root)
            admission_binding = routing_admission.selected_binding(
                options, chipdb_root, admitted_edge.values()
            )
        except routing_admission.RoutingAdmissionError as exc:
            raise ValueError(str(exc)) from exc
        conflicted_edge = {}
        conflict_file = chipdb_root / "selector_conflict_atlas.agdb"
        if options.enabled("AGAMEMNON_RESEARCH_UNSAFE"):
            if not conflict_file.exists():
                raise ValueError(
                    "research-unsafe requires chipdb/selector_conflict_atlas.agdb"
                )
            conflicts, metadata = chipdb_schema.load(
                str(conflict_file), expected=("conflicted_edge",)
            )
            conflicted_edge = conflicts["conflicted_edge"]
            print(
                "loaded %d vendor-derived conflicted physical selector rows "
                "(research-unsafe; source %s)"
                % (len(conflicted_edge), metadata.get("source_sha256", "unknown"))
            )
        return cls(
            chipdb_root=chipdb_root,
            archival_legacy=options.enabled("AGAMEMNON_ALLOW_UNMAPPED"),
            dir_bank=dir_bank,
            clean_edge=clean_edge,
            relative_edge=relative_edge,
            admitted_edge=admitted_edge,
            admission_binding=admission_binding,
            lut=SB.train_lut("__none__", chipdb_root),
            conflicted_edge=conflicted_edge,
            ambiguous_boundary=ambiguous_boundary_sources(str(chipdb_root)),
        )

    def _build_geom_rmux(self, dataset):
        groups = collections.defaultdict(list)
        with dataset.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                groups[(row["build"], row["dst_x"], row["dst_y"], row["cfg_group"])].append(row)
        geom = collections.defaultdict(collections.Counter)
        for rows in groups.values():
            edges = {
                (row["dst_idx"], row["src_idx"], row["src_fam"], row["dx"], row["dy"])
                for row in rows
            }
            if len(edges) != 1:
                continue
            first = rows[0]
            selections = sorted(int(row["sel"]) for row in rows)
            if len(selections) != 2 or first["dst_fam"] != "RMUX" or first["src_fam"] != "RMUX":
                continue
            block = 10 * int(first["dst_group_offset"])
            geom[(int(first["src_idx"]), int(first["dx"]), int(first["dy"]))][selections[0] - block] += 1
        return {key: counts.most_common(1)[0][0] for key, counts in geom.items()}

    def _build_absolute(self, dataset):
        groups = collections.defaultdict(list)
        with dataset.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                groups[(row["build"], row["dst_x"], row["dst_y"], row["cfg_group"])].append(row)
        accumulated = collections.defaultdict(collections.Counter)
        for rows in groups.values():
            edges = {
                (row["dst_idx"], row["src_idx"], row["src_fam"], row["dx"], row["dy"])
                for row in rows
            }
            if len(edges) != 1:
                continue
            first = rows[0]
            family = first["dst_fam"]
            selections = sorted(int(row["sel"]) for row in rows)
            if family not in BS or len(selections) != 2:
                continue
            block = BS[family] * int(first["dst_group_offset"])
            key = (
                int(first["dst_x"]), int(first["dst_y"]), family, int(first["dst_idx"]),
                first["src_fam"], int(first["src_x"]), int(first["src_y"]), int(first["src_idx"]),
            )
            accumulated[key][(selections[0] - block, selections[1] - block)] += 1
        return {key: counts.most_common(1)[0][0] for key, counts in accumulated.items()}

    def _build_group_context(self, dataset):
        groups = collections.defaultdict(list)
        with dataset.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if row["dst_fam"] in ("RMUX", "IMUX"):
                    groups[(row["build"], int(row["dst_x"]), int(row["dst_y"]), row["cfg_group"])].append(row)
        accumulated = collections.defaultdict(collections.Counter)
        for (_build, dx, dy, cfg), rows in groups.items():
            edges = frozenset(
                (int(row["dst_idx"]), row["src_fam"], int(row["src_x"]),
                 int(row["src_y"]), int(row["src_idx"]))
                for row in rows
            )
            selections = frozenset(int(row["sel"]) for row in rows)
            accumulated[(dx, dy, cfg, edges)][selections] += 1
        return {key: counts.most_common(1)[0][0] for key, counts in accumulated.items()}

    def ensure_legacy(self):
        if self.geom_rmux is not None:
            return
        dataset = self.chipdb_root / "sel_dataset.csv"
        cache = self.chipdb_root / "sel_tables.agdb"
        if cache.exists() and (not dataset.exists() or cache.stat().st_mtime >= dataset.stat().st_mtime):
            tables, _metadata = chipdb_schema.load(
                str(cache), expected=("geom_rmux", "absolute", "group_context")
            )
            self.geom_rmux = tables["geom_rmux"]
            self.absolute = tables["absolute"]
            self.group_context = tables["group_context"]
            print("loaded fallback sel tables: %d geom, %d abs, %d group-ctx"
                  % (len(self.geom_rmux), len(self.absolute), len(self.group_context)))
            return
        self.geom_rmux = self._build_geom_rmux(dataset)
        self.absolute = self._build_absolute(dataset)
        self.group_context = self._build_group_context(dataset)
        chipdb_schema.dump(
            str(cache),
            {"geom_rmux": self.geom_rmux, "absolute": self.absolute,
             "group_context": self.group_context},
            metadata={"source": "sel_dataset.csv"},
        )
        print("built + cached fallback sel tables: %d geom, %d abs, %d group-ctx"
              % (len(self.geom_rmux), len(self.absolute), len(self.group_context)))


@dataclass
class RoutingState:
    sets: list = field(default_factory=list)
    clears: list = field(default_factory=list)
    mapped: int = 0
    unmapped: int = 0
    predicted: int = 0
    admission_binding: dict | None = None
    provenance_counts: dict = field(default_factory=dict)


def _mcu_entry_pair(destination_index):
    """Fallback (lo, hi) selector offsets for an InputMUX-at-x=13 -> RMUX hop.

    Fixed 2026-08-21. The prior ``(block + 3, block + 9)`` was never
    board-tested -- every earlier caller was intercepted upstream by
    ``MCU_ENTRY``, ``clean_edge`` or ``relative_edge``, so this fallback sat
    dormant until a 257-row chipdb addition admitted three new
    InputMUX-at-x13 -> RMUX pips with no such coverage. All three hit this
    formula for the first time and encoded WRONG: ``htrans1``, ``hwdata[0]``,
    ``hwdata[1]`` -- the public16 W1C overlay's gating signals -- failed 3/3
    on L48 silicon (``set_event`` latched permanently).

    ``(block + 2, block + 8)`` matches all three curated ``MCU_ENTRY`` ground
    truth rows exactly (source: InputMUX at x=13 entering the fabric via an
    RMUX destination):

        di=14  CFG_RMUX2  (22, 28)
        di=73  CFG_RMUX12 (12, 18)
        di=21  CFG_RMUX3  (32, 38)

    pinned by ``tests/test_mcu_entry_selector.py``.

    The offset is NOT a universal property of "RMUX destination fallback" --
    the independently verified ``X13Y9_BufMUX14 -> X14Y9_RMUX38`` row (a
    BufMUX source, not InputMUX, resolved through
    ``bufmux_rmux_entry_pip_cfg.csv`` / ``exact_mcu_pips`` well before this
    function is ever reached) uses a completely different, local ``(0, 7)``.
    So this formula is evidenced ONLY for the InputMUX-at-x13 -> RMUX
    fabric-entry mechanism, and the caller must refuse to invoke it for any
    other source x -- see the ``sx == 13`` gate at the one call site.
    """
    block = BS["RMUX"] * (destination_index % NPG["RMUX"])
    return "CFG_RMUX%d" % (destination_index // NPG["RMUX"]), (block + 2, block + 8)


# Exact ordinary-interior InputMUX entry that is outside the x=13 mechanism
# above. It was originally retained only to reproduce a shipped artifact and
# counted `predicted`. On 2026-08-22 it was isolated as the sole uncertain PIP
# in a GPIO4 request/AHB-ack counter vehicle, then qualified on L48 SRAM:
# 512 exact request transitions and a 32-bit host signature passed three times
# with dedicated carry and three times with LUT carry. The known-good public32
# control passed first; every run configured with FCB=0x000f0002; flash was not
# written. See qualification/mcu_gpio4_entry_evidence.jsonl.
#
# This promotes only X11Y5_InputMUX11 -> X11Y4_RMUX93 with its already-retained
# literal codeword. It is not evidence for the x=13 formula or any sibling
# InputMUX/RMUX edge. The closed set and literal value are pinned by
# tests/test_mcu_entry_selector.py; adding another row requires independent
# silicon evidence.
_SILICON_QUALIFIED_UNSCOPED_ENTRY = {
    (11, 4, 93): ("CFG_RMUX15", (33, 39)),
}


def _resolve_mcu_inputmux_entry(*, dx, dy, di, sx, clean_pair, relative_pair,
                                label, sy=None, si=None):
    """Resolve one InputMUX -> RMUX fabric-entry hop to a codeword.

    Pulled out of ``RoutingFeature.prepare`` so the fail-closed scope guard
    around ``_mcu_entry_pair`` -- the actual 2026-08-21 fix -- is a pure
    function testable without constructing a full routed design. Precedence,
    highest evidence first:

    1. ``clean_pair`` -- an exact per-physical-edge observation.
    2. ``relative_pair`` -- an unanimous tile-relative observation.
    3. ``_VENDOR_OBSERVED_EXACT_MCU_ENTRY[(dx,dy,di,sx,sy,si)]`` -- an exact
       physical vendor route/bitstream observation.
    4. ``MCU_ENTRY[(dx, dy, di)]`` -- a curated, board-verified ground-truth
       row (see the module docstring above ``MCU_ENTRY``).
    5. ``_SILICON_QUALIFIED_UNSCOPED_ENTRY[(dx, dy, di)]`` -- a closed set
       of exact, independently board-qualified interior entries (see its own
       comment and qualification evidence).
    6. ``_mcu_entry_pair(di)`` -- the blind formula, but ONLY when
       ``sx == 13``, because that formula is evidenced solely for the
       InputMUX-at-x13 -> RMUX fabric-entry mechanism (see its docstring).
       Any other source x refuses rather than guesses.

    Returns ``(entries, source_class, predicted)`` where ``entries`` is a
    list of ``(cfg, selection)`` pairs ready for ``resolve_selector_cells``,
    and ``predicted`` is True only for case 5, which has no direct per-edge
    or curated evidence.
    """
    if clean_pair is not None:
        block = BS["RMUX"] * (di % NPG["RMUX"])
        cfg = "CFG_RMUX%d" % (di // NPG["RMUX"])
        return ([(cfg, block + selection) for selection in clean_pair],
                "conflict-free-physical-observation", False)
    if relative_pair is not None:
        block = BS["RMUX"] * (di % NPG["RMUX"])
        cfg = "CFG_RMUX%d" % (di // NPG["RMUX"])
        return ([(cfg, block + selection) for selection in relative_pair],
                "unanimous-relative-observation", False)
    observed = _VENDOR_OBSERVED_EXACT_MCU_ENTRY.get((dx, dy, di, sx, sy, si))
    if observed is not None:
        cfg, selections = observed
        return ([(cfg, selection) for selection in selections],
                "mcu-entry-vendor-observed-exact", False)
    entries = MCU_ENTRY.get((dx, dy, di))
    if entries is not None:
        return entries, "mcu-entry-curated-observation", False
    qualified = _SILICON_QUALIFIED_UNSCOPED_ENTRY.get((dx, dy, di))
    if qualified is not None:
        cfg, selections = qualified
        return ([(cfg, selection) for selection in selections],
                "mcu-entry-silicon-qualified-interior", False)
    if sx == 13:
        cfg, selections = _mcu_entry_pair(di)
        return ([(cfg, selection) for selection in selections],
                "mcu-entry-inputmux-x13-formula", True)
    raise SystemExit(
        "MCU/InputMUX entry %s has no exact edge, no curated MCU_ENTRY row, "
        "and source x=%d is outside the InputMUX-at-x13 -> RMUX fabric-entry "
        "mechanism the fallback formula is evidenced for. Refusing to guess "
        "a codeword for an unevidenced source family (see MCU_ENTRY / "
        "_mcu_entry_pair in routing.py)." % (label, sx)
    )


_WIRE_ENDPOINT = re.compile(r"X(-?\d+)Y(-?\d+)_(.+)")


def wire_endpoint(wire):
    """``"X14Y8_RMUX21"`` -> ``("RMUX21", "14", "8")``, or None if unnameable.

    One parse for every wire-name-keyed loader. The MCU/BRAM corridor tables
    carry whole wire names while the edge blacklist is keyed by resource and
    tile, and because there was no shared translation those loaders never
    consulted the ban at all -- so ``AGAMEMNON_EDGE_BLACKLIST[_FILE]`` was
    documented to remove an edge and, for every hop that arrives through one of
    those tables, silently did not.

    A name that does not parse cannot be spelled in the ban syntax
    (``<res>@<x>,<y>``) either, so None means genuinely unbannable rather than
    silently skipped.
    """
    match = _WIRE_ENDPOINT.fullmatch(wire or "")
    return None if not match else (match.group(3), match.group(1), match.group(2))


def resolve_selector_cells(lookup, keys, table, what):
    """Resolve every selector key to a physical cell, or fail closed.

    A routed mux hop is programmed by a COMPLETE codeword -- for the RMUX/IMUX
    mesh that is a (lo, hi) pair in the destination node's block. Emitting the
    subset that happened to resolve is not a smaller version of the right
    answer, it is a well-formed codeword for a DIFFERENT mux input: the image
    config-accepts (FCB 0x000f0002) and the hop does not carry the signal. The
    general path used to count such an edge as ``mapped`` on ``if found:``, so
    the "refusing to emit a partial bitstream" gate never saw it, and a
    codeword whose cells were ALL absent was counted as neither mapped nor
    unmapped -- silently dropped with no diagnostic at any verbosity.

    Raise instead, naming the table and the exact missing keys.
    """
    bits = []
    missing = []
    for key in keys:
        bit = lookup.get(key)
        if bit is None:
            missing.append(key)
        else:
            bits.append(bit)
    if missing:
        raise SystemExit(
            "%s: %s has no config cell for %s; refusing to emit a partial "
            "selector codeword (a subset of a codeword selects a different mux "
            "input, which config-accepts and does not conduct)"
            % (what, table, ", ".join(repr(key) for key in missing))
        )
    return bits


class RoutingFeature:
    descriptor = FeatureDescriptor(
        feature_id="routing",
        options=(
            "AGAMEMNON_MESH_TEMPLATE",
            "AGAMEMNON_ALLOW_UNMAPPED",
            "AGAMEMNON_CLEAN_SEL_GATE",
            "AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT",
            "AGAMEMNON_BRAM_ALL_EDGES",
            "AGAMEMNON_BRAM_APPROACH",
            "AGAMEMNON_BRAM_PORTB_EXIT",
            "AGAMEMNON_BRAM_PORTB_MCU_EXIT",
            "AGAMEMNON_CLEAN_SEL_PENALTY",
            "AGAMEMNON_CLEAN_SEL_PREFER",
            "AGAMEMNON_CONDUCTION_GATE",
            "AGAMEMNON_EDGE_BLACKLIST",
            "AGAMEMNON_FBRESTRICT",
            "AGAMEMNON_FB_OFFSET3",
            "AGAMEMNON_HARDEN_PADFEED",
            "AGAMEMNON_HW_CARRY",
            "AGAMEMNON_MCU_ENTRY",
            "AGAMEMNON_NO_BRAM_WL",
            "AGAMEMNON_NO_EXIT_WL",
            "AGAMEMNON_NO_FFBRIDGE",
            "AGAMEMNON_NO_INTRA_RMUX",
            "AGAMEMNON_OBSERVED_ONLY",
            "AGAMEMNON_ROUTING_ADMISSION",
            "AGAMEMNON_OBS_IMUX",
            "AGAMEMNON_PADFEED_ONLY",
            "AGAMEMNON_PADFEED_TOP",
            "AGAMEMNON_PHYSICAL_IO",
            "AGAMEMNON_SOFT_PENALTY",
            "AGAMEMNON_SOFT_PREFER",
            "AGAMEMNON_SPAN_DELAY",
            "AGAMEMNON_SPAN_STEP",
            "AGAMEMNON_STRICT_GATE",
            "AGAMEMNON_TRUE_TOPO",
            "AGAMEMNON_TRUSTED",
            "AGAMEMNON_WIRE_TIMING_MARGIN",
            "AGAMEMNON_XBAR_CONDUCT",
            "AGAMEMNON_XBAR_FULL",
        ),
        chipdb_files=(
            "pips_full.csv", "pips_mcuedge.csv", "sel_map.json",
            "sel_edge_pairs.agdb", "sel_tables.agdb", "train_lut.agdb",
            "selector_conflict_atlas.agdb", "research_knowledge_manifest.json",
            "routing_selector_admission.json",
            "rrg_edges_full.csv", "rrg_omux_imux_full.csv",
            "rrg_rmux_imux_full.csv", "dead_edges_silicon.csv",
            "exit_feeder_whitelist.csv", "master_conduction.csv",
            "ff2_conduction.csv", "harvest_conduction.csv",
            "corpus_conduction.csv", "ff_feedback_map.csv",
            "wire_timing_worst.json", "wire_timing_exact_safe.json",
            "wire_timing_exact_safe_manifest.json", "wire_timing_measured.json",
            "wires.csv", "pip_usage.csv", "mcu_region_witness.csv",
            "soft_ripple_region_witness.csv",
            "bbmuxe_fanin.csv", "logictile_config_template.csv",
            "border_edge_partial_cells.csv",
        ),
        writable_regions=(
            WritableRegion("cell_map", "pips_full.csv", "byte", "mask"),
            WritableRegion("cell_map", "pips_mcuedge.csv", "byte", "mask"),
            WritableRegion("selector_database", "sel_edge_pairs.agdb"),
            WritableRegion("selector_database", "sel_tables.agdb"),
            WritableRegion("selector_database", "train_lut.agdb"),
        ),
        phase=EmissionPhase.ROUTING,
        evidence=("qualification/routing_evidence.jsonl",),
        maturity="release",
        evidence_tier="individually_qualified",
        architecture=(
            "Construct the qualified general routing graph, timing, feedback "
            "bridges, and package-edge presentation pips."
        ),
        bitstream=(
            "Resolve complete routed edge groups through exact physical, unanimous-relative, "
            "context, template, and predictive selector sources; fail closed when required."
        ),
    )

    _ROUTED_MUX = re.compile(
        r"X(\d+)Y(\d+)_([A-Za-z][A-Za-z0-9_]*MUX[A-Za-z0-9_]*\d+)"
    )

    def validate_mux_ownership(self, module):
        """Reject routed JSON that assigns one physical mux to two nets.

        A routed edge can be individually encodable while still composing an
        impossible bitstream: two nets may request different inputs of the
        same RMUX, and the union of both otherwise-valid selector codewords is
        a third value.  nextpnr prevents this in normal output, but replay and
        research tools legitimately edit ``ROUTING`` strings after placement,
        so bitgen is the final trust boundary.

        Netname aliases with the same signal-bit vector are one logical owner;
        fanout branches within that owner may repeat a mux safely.
        """
        owners = collections.defaultdict(lambda: collections.defaultdict(set))
        for net_name, net in module.get("netnames", {}).items():
            route = net.get("attributes", {}).get("ROUTING", "")
            if not route:
                continue
            raw_bits = tuple(net.get("bits", ()))
            # Integer bit IDs name one Yosys signal, so netname aliases with
            # the same vector are one owner.  Literal "0"/"1"/"x" bits do
            # not identify a routed signal; keep separately named constant
            # presentations separate so they cannot hide a selector union.
            logical_owner = (
                ("bits", raw_bits)
                if raw_bits and all(isinstance(bit, int) for bit in raw_bits)
                else ("name", net_name)
            )
            for x, y, resource in set(self._ROUTED_MUX.findall(route)):
                owners[(int(x), int(y), resource)][logical_owner].add(net_name)

        conflicts = {
            node: logical for node, logical in owners.items() if len(logical) > 1
        }
        if conflicts:
            rows = []
            for (x, y, resource), logical in sorted(conflicts.items()):
                labels = ["/".join(sorted(names)) for names in logical.values()]
                rows.append("X%dY%d_%s=%s" %
                            (x, y, resource, ",".join(sorted(labels))))
            raise ValueError(
                "cross-net physical mux ownership conflict: " + "; ".join(rows)
            )
        return len(owners)

    def add_architecture(self, context):
        ctx, Loc = context.ctx, context.loc
        OPTIONS, DEV = context.options, context.device
        DATA = str(context.chipdb_root)
        shared = context.shared
        W = shared["wire_name"]
        fam = shared["resource_family"]
        wireset = shared["wires"]
        tile_type = shared["tile_types"]
        K = shared["constants"]["lut_inputs"].value
        try:
            ADMITTED_BY_EDGE = routing_admission.selected_edge_map(OPTIONS, DATA)
        except routing_admission.RoutingAdmissionError as exc:
            raise ValueError(str(exc)) from exc
        ADMITTED_ROWS = tuple(ADMITTED_BY_EDGE.values())

        def _edge_key(r):
            df, sf = fam(r["dst_res"]), fam(r["src_res"])
            try:
                return (
                    int(r["dst_x"]), int(r["dst_y"]), df,
                    int(r["dst_res"][len(df):]), sf,
                    int(r["src_x"]), int(r["src_y"]),
                    int(r["src_res"][len(sf):]),
                )
            except (TypeError, ValueError):
                return None

        # ---- 4. pips: every routing edge (RRG mesh + completed OMUX->IMUX crossbar) ----
        # rrg_edges_full.csv     = enumerated RMUX mesh + observed intra-tile edges.
        # rrg_omux_imux_full.csv = the intra-tile OMUX->IMUX LUT-feedback crossbar completed by cross-tile
        #   union + replication (complete_omux_imux.py). This fills the dense-routing gap: the observed-only
        #   crossbar had 6..110 of the 536 tile-invariant template edges per tile; now every LogicTILE gets
        #   the full 536. Dedup by pip name (observed edges appear in both files).
        # AGAMEMNON_OBSERVED_ONLY=1 restricts routing to OBSERVED edges (real vendor-router connections,
        # gold-standard: physically real + sel-encoding in the training set). Enumerated edges are only
        # ~94% byte-validated and include non-physical inferences — on silicon a route through them
        # config-accepts but does not electrically connect. Observed-only trades coverage for correctness.
        # AGAMEMNON_TRUE_TOPO=1 replaces the enumerated rrg_edges_full.csv with rrg_edges_true.csv, the
        # TRUE physical topology harvested from the vendor router's own routed designs (decoded route.tx
        # path blocks) unioned with the prior observed edges. Every edge is a real vendor-router hop, so a
        # route composed from them physically propagates on silicon (fixes the din-never-reaches-LUT bug
        # whose root cause was non-physical ENUMERATED edges). =2 also loads the tile-invariant replicated
        # set (rrg_edges_true_repl.csv) for extra coverage if real-only is too sparse to route.
        # dead_edges_silicon.csv and AGAMEMNON_EDGE_BLACKLIST exclude specific pips proven
        # NON-CONDUCTING on silicon so
        # nextpnr reroutes around them (e.g. RMUX26@(14,4)->RMUX19@(10,4), the +x/right feed into the MCU
        # dout exit RMUX that config-accepts but is electrically dead, while RMUX74@(6,4)->RMUX19@(10,4)
        # from the left conducts). Format: a list of "<src_res>@<sx>,<sy>-><dst_res>@<dx>,<dy>" edges,
        # separated by comma and/or semicolon (edge coords contain commas, so the parse extracts each edge
        # by pattern rather than splitting).  The checked-in negative evidence is always active and has
        # precedence over observed, vendor-mined, and positive-campaign evidence.  The environment variable
        # adds temporary experiment edges; it cannot remove checked-in negatives.
        # Matched on the raw CSV endpoint fields (res+x+y both ends) in every edge loop below.
        _dead_edge_re = r"(\w+)@(-?\d+),(-?\d+)\s*->\s*(\w+)@(-?\d+),(-?\d+)"
        EDGE_BLACKLIST = set(re.findall(_dead_edge_re, os.environ.get("AGAMEMNON_EDGE_BLACKLIST", "")))
        # AGAMEMNON_EDGE_BLACKLIST_FILE: the same syntax, one edge per line, read
        # from a file.  A conduction campaign has to ban every OTHER crossing of a
        # geometric cut so the edge under test is the only legal one, and a cut
        # between two adjacent tiles carries 4,113-12,489 enumerated crossings --
        # which does not fit in an environment variable on any platform.  Without
        # this the experiment simply cannot be expressed in the shipped tool, and
        # the campaign has to fork the architecture script.  Blank lines and
        # `#` comments are ignored; a line that is not an edge is an error rather
        # than a silent skip, because a typo would otherwise quietly widen the cut.
        _ban_file = os.environ.get("AGAMEMNON_EDGE_BLACKLIST_FILE", "")
        if _ban_file:
            if not os.path.exists(_ban_file):
                raise ValueError(
                    "AGAMEMNON_EDGE_BLACKLIST_FILE=%r does not exist; refusing to "
                    "build with a silently empty cut" % _ban_file)
            _ban_count = 0
            with open(_ban_file, encoding="utf-8") as _ban_stream:
                for _lineno, _raw in enumerate(_ban_stream, 1):
                    _line = _raw.split("#", 1)[0].strip()
                    if not _line:
                        continue
                    _match = re.fullmatch(_dead_edge_re, _line)
                    if not _match:
                        raise ValueError(
                            "%s:%d: not an edge: %r (expected "
                            "<src_res>@<sx>,<sy>-><dst_res>@<dx>,<dy>)"
                            % (_ban_file, _lineno, _line))
                    EDGE_BLACKLIST.add(_match.groups())
                    _ban_count += 1
            print("AGRV2K arch: edge-blacklist file %s contributed %d edge(s)"
                  % (_ban_file, _ban_count))
        _dead_csv = os.path.join(DATA, "dead_edges_silicon.csv")
        if os.path.exists(_dead_csv):
            for _dead_row in csv.DictReader(open(_dead_csv)):
                _match = re.fullmatch(_dead_edge_re, _dead_row.get("edge", "").strip())
                if not _match:
                    raise ValueError("malformed silicon-dead edge: %r" % _dead_row)
                EDGE_BLACKLIST.add(_match.groups())
        if EDGE_BLACKLIST:
            # A cut ban runs to thousands of edges; print a bounded sample so the
            # count stays visible without burying the rest of the build log.
            _shown = sorted(EDGE_BLACKLIST)[:24]
            print("AGRV2K arch: SILICON-DEAD EDGE BLACKLIST active (%d edge(s)): %s%s"
                  % (len(EDGE_BLACKLIST), _shown,
                     " ... (+%d more)" % (len(EDGE_BLACKLIST) - len(_shown))
                     if len(EDGE_BLACKLIST) > len(_shown) else ""))
        def _norm_res(res):
            """RMUX8 and RMUX08 are the same wire. Compare numerically."""
            match = re.fullmatch(r"([A-Za-z]+)0*(\d+)", str(res or ""))
            return "%s%d" % (match.group(1), int(match.group(2))) if match else str(res)

        def _norm_edge(src_res, src_x, src_y, dst_res, dst_x, dst_y):
            return (_norm_res(src_res), str(int(src_x)), str(int(src_y)),
                    _norm_res(dst_res), str(int(dst_x)), str(int(dst_y)))

        # Normalise the blacklist itself once, so every supplemental loader can
        # compare against it on the same key. Raw string comparison silently
        # matched nothing whenever one side zero-padded a resource index, which
        # is a failure that looks exactly like "the ban had no effect".
        EDGE_BLACKLIST = {_norm_edge(*entry) for entry in EDGE_BLACKLIST}
        MCU_ENTRY_FIRST_HOPS = mcu_entry_first_hops(DATA)
        print("AGRV2K arch: qualified MCU entry first-hop constraints active "
              "for %d hard roots" % len(MCU_ENTRY_FIRST_HOPS))

        def _blacklisted(r):
            # One predicate for every loader: the silicon-dead blacklist plus the
            # qualified pad-composition restriction. Folding them together is
            # deliberate -- each loader already consults this, so a pad rule
            # cannot be forgotten in one of them.
            if _norm_edge(r["src_res"], r["src_x"], r["src_y"],
                          r["dst_res"], r["dst_x"], r["dst_y"]) in EDGE_BLACKLIST:
                return True
            source = W(r["src_x"], r["src_y"], r["src_res"])
            destination = W(r["dst_x"], r["dst_y"], r["dst_res"])
            if mcu_entry_first_hop_denied(
                    MCU_ENTRY_FIRST_HOPS, source, destination):
                return True
            return _pad_composition_denied(r)

        def _blacklisted_wires(src_wire, dst_wire):
            """_blacklisted() for tables keyed by WIRE NAME rather than by parts.

            The MCU/BRAM corridor tables carry whole wire names
            (``X14Y8_RMUX21`` -> ``X14Y4_RMUX93``) and there was no wire-name
            form of the predicate, so those loaders simply never called it: they
            added their pips unconditionally. A ban naming one of those edges --
            the documented purpose of AGAMEMNON_EDGE_BLACKLIST[_FILE] -- had no
            effect at all, while sibling edges of the identical shape that
            happen to arrive through the part-keyed RRG loader did respond. That
            is the worst possible signal to debug against, because it looks like
            the ban syntax works.

            A name that does not parse cannot be spelled in the ban syntax
            (``<res>@<x>,<y>``) either, so it is genuinely unbannable rather
            than silently skipped.
            """
            source = wire_endpoint(src_wire)
            destination = wire_endpoint(dst_wire)
            if not source or not destination:
                return False
            return _blacklisted({
                "src_res": source[0], "src_x": source[1], "src_y": source[2],
                "dst_res": destination[0], "dst_x": destination[1],
                "dst_y": destination[2],
            })

        def _edge_blacklisted_wires(src_wire, dst_wire):
            """True only for checked-in or operator-supplied edge bans.

            A complete independently qualified hard-peripheral corridor may be
            an alternate composition through a wire which is also a scalar-pad
            feeder. Such a corridor must still obey absolute negative edge
            evidence without inheriting the scalar pad's narrower source rule.
            """
            source = wire_endpoint(src_wire)
            destination = wire_endpoint(dst_wire)
            if not source or not destination:
                return False
            return _norm_edge(
                source[0], source[1], source[2],
                destination[0], destination[1], destination[2],
            ) in EDGE_BLACKLIST

        # Qualified pad-output compositions, loaded early because both the main
        # RRG loop and the pad-feed loader need them. Each listed pad has ONE
        # silicon-proven composition and the graph admits only that: the exact
        # approach into the pad-feed source, the exact source, the exact
        # pad-tile RMUX and the exact IOMUX terminal. Pads not listed are
        # untouched, so this narrows nothing that was previously working.
        _qualified = {}
        _qpath = os.path.join(DATA, "pad_output_qualified_L48.csv")
        if os.path.exists(_qpath):
            for _qr in csv.DictReader(open(_qpath)):
                _qualified[(int(_qr["pad_x"]), int(_qr["pad_y"]), int(_qr["z"]))] = _qr
        _qual_approach = {
            (_qr["src_res"], int(_qr["src_x"]), int(_qr["src_y"])):
                (_qr["approach_res"], int(_qr["approach_x"]), int(_qr["approach_y"]))
            for _qr in _qualified.values()
        }

        _qual_terminal = {}      # (pad_x, pad_y, z) -> feeder RMUX index
        _qual_feed = {}          # (pad_x, pad_y, feeder) -> (src_res, x, y)
        for _qr in _qualified.values():
            _qual_terminal[(int(_qr["pad_x"]), int(_qr["pad_y"]), int(_qr["z"]))] =                 int(_qr["feeder_rmux"])
            _qual_feed[(int(_qr["pad_x"]), int(_qr["pad_y"]), int(_qr["feeder_rmux"]))] =                 (_qr["src_res"], int(_qr["src_x"]), int(_qr["src_y"]))

        def _pad_composition_denied(r):
            """True when r would give a qualified pad an unproven composition.

            Restricting only the pad-feed table was not enough: the RRG has its
            own edges into the pad tile, and the first restricted build still
            reached PIN_16 through RMUX75@(19,9) -> RMUX04 and PIN_18 through
            RMUX87@(18,10). Every hop of the composition has to be pinned --
            the terminal, the pad-feed source, and the approach into it.
            """
            src = (_norm_res(r["src_res"]), int(r["src_x"]), int(r["src_y"]))
            dst_family, dst_index = None, None
            match = re.fullmatch(r"([A-Za-z]+)0*(\d+)", str(r["dst_res"]))
            if match:
                dst_family, dst_index = match.group(1), int(match.group(2))
            dst_tile = (int(r["dst_x"]), int(r["dst_y"]))

            if dst_family == "IOMUX":
                feeder = _qual_terminal.get((dst_tile[0], dst_tile[1], dst_index))
                if feeder is not None and src != (
                        _norm_res("RMUX%d" % feeder), dst_tile[0], dst_tile[1]):
                    return True
            if dst_family == "RMUX":
                want = _qual_feed.get((dst_tile[0], dst_tile[1], dst_index))
                if want is not None and src != (_norm_res(want[0]), want[1], want[2]):
                    return True
                # The APPROACH into the pad-feed source is pinned too, and it
                # is load-bearing rather than belt-and-braces. Relaxing it was
                # tried: the router explores a much larger space against the same
                # hard bans, and the pair build then fails to route at all at
                # every cap. With it, both nets take the measured chain.
                approach = _qual_approach.get(
                    (r["dst_res"], dst_tile[0], dst_tile[1])
                )
                if approach is not None and src != (
                        _norm_res(approach[0]), approach[1], approach[2]):
                    return True
            return False

        # ---- EXIT-FEEDER WHITELIST (silicon-validated far-routing fix) --------------------------------
        # The 4 forced MCU-dout exit RMUX nodes @ LogicTILE(10,4) (RMUX09/RMUX19/RMUX32/RMUX02 -> GPIO4
        # bits 0/2/4/6) have MOST of their enumerated in-edges electrically DEAD on silicon even though the
        # bitstream config-accepts; only a per-node set of feeders actually conducts (proven by per-feeder
        # isolation bins read back on GPIO4). We restrict the IN-edges of ONLY these 4 dst nodes to the
        # whitelisted live feeders, so nextpnr is forced to route a far-tile toggle out through a conducting
        # feeder. The "top-1 rule" is REFUTED (RMUX32 conducts from a right/self feed, not a westward RMUX74
        # tap), so this is an explicit per-node whitelist, not a global rule. Loaded from
        # chipdb/exit_feeder_whitelist.csv; every OTHER node in the fabric is untouched. Set
        # AGAMEMNON_NO_EXIT_WL=1 to disable (e.g. to reproduce the old dead-feeder behavior).
        EXIT_WL = {}    # (dst_res,dst_x,dst_y) -> set of (src_res,src_x,src_y) live feeders
        if not os.environ.get("AGAMEMNON_NO_EXIT_WL"):
            _wl = os.path.join(DATA, "exit_feeder_whitelist.csv")
            if os.path.exists(_wl):
                for r in csv.DictReader(open(_wl)):
                    EXIT_WL.setdefault((r["dst_res"], r["dst_x"], r["dst_y"]), set()).add(
                        (r["src_res"], r["src_x"], r["src_y"]))
                print("AGRV2K arch: EXIT-FEEDER WHITELIST active for %d exit node(s): %s"
                      % (len(EXIT_WL), sorted(EXIT_WL)))
        def _exit_pruned(r):
            """True if r is an in-edge to a whitelisted exit node that is NOT a listed live feeder."""
            dst = (r["dst_res"], r["dst_x"], r["dst_y"])
            if dst not in EXIT_WL:
                return False
            return (r["src_res"], r["src_x"], r["src_y"]) not in EXIT_WL[dst]

        # CONDUCTION GATE (silicon truth, from the full-fabric sweep_all campaign): chipdb/master_conduction.csv
        # holds every routing edge PROVEN to electrically conduct on silicon (the open flow routed a toggling FF
        # through it and the readout toggled). Loading it here lets is_trusted() promote a silicon-conducting edge
        # to trusted even if it was an ENUMERATED guess (byte-validated by the toggle, not just the sel-encoder).
        # AGAMEMNON_CONDUCTION_GATE=1 turns on trusted-only routing = observed U conducting U validated-closed-form
        # -> the arch offers ONLY edges that work on silicon, so the router auto-avoids the offered-but-dead edges
        # (e.g. the dead intra-tile carry that packs a counter into one tile -> [[counter-freeze]] auto-fixes:
        # nextpnr can't pack it, so it spreads across tiles onto conducting inter-tile carry). This is Phase B of
        # the plan: make the model TRUTHFUL so arbitrary auto-placed RTL routes+runs on silicon-verified edges.
        CONDUCT = set()
        for _cf in ("master_conduction.csv",      # silicon-swept (sweep_all) FF->dout reach edges
                    "ff2_conduction.csv",          # silicon-swept (ff2_sweep) FF->FF INTER-tile directed corridors
                    "harvest_conduction.csv",      # silicon-swept (harvest_sweep) all pips of CONDUCTING designs
                    "corpus_conduction.csv"):      # vendor-route-mined per-position conducting edges (mine_corpus.py A2)
            _cp = os.path.join(DATA, _cf)
            if os.path.exists(_cp):
                _n0 = len(CONDUCT)
                for r in csv.DictReader(open(_cp)):
                    CONDUCT.add((r["src_res"], r["src_x"], r["src_y"], r["dst_res"], r["dst_x"], r["dst_y"]))
                print("AGRV2K arch: loaded %d conducting edges from %s (+%d, total %d)"
                      % (len(CONDUCT) - _n0, _cf, len(CONDUCT) - _n0, len(CONDUCT)))
        # The conduction corpora spell resource indices two-digit padded
        # ("RMUX09") while EDGE_BLACKLIST has already been normalised to bare
        # ("RMUX9"), so a raw set intersection silently missed every
        # single-digit edge -- 7 of the 9 real conflicts matched, and the two
        # that did not (RMUX26@15,4->RMUX09@14,4 and RMUX09@14,4->RMUX28@14,8)
        # stayed in the positive-evidence set while the diagnostic under-reported
        # the count. Compare on the normalised key, but keep CONDUCT itself in the
        # corpus spelling because _cond_key() looks it up that way.
        _conduct_by_norm = collections.defaultdict(set)
        for _ck in CONDUCT:
            _conduct_by_norm[_norm_edge(*_ck)].add(_ck)
        _dead_positive_conflicts = set(_conduct_by_norm).intersection(EDGE_BLACKLIST)
        if _dead_positive_conflicts:
            print("AGRV2K arch: negative evidence overrides %d conflicting positive edge(s)"
                  % len(_dead_positive_conflicts))
            CONDUCT.difference_update(
                _raw
                for _norm in _dead_positive_conflicts
                for _raw in _conduct_by_norm[_norm]
            )
        def _cond_key(r):
            return (r["src_res"], r["src_x"], r["src_y"], r["dst_res"], r["dst_x"], r["dst_y"])

        TRUE_TOPO = os.environ.get("AGAMEMNON_TRUE_TOPO")
        OBSERVED_ONLY = os.environ.get("AGAMEMNON_OBSERVED_ONLY")
        # AGAMEMNON_CONDUCTION_GATE implies TRUSTED (trusted-only routing) but with the conducting set folded in.
        TRUSTED = os.environ.get("AGAMEMNON_TRUSTED") or os.environ.get("AGAMEMNON_CONDUCTION_GATE")
        # AGAMEMNON_STRICT_GATE: trust ONLY per-position silicon/vendor-proven edges (observed U CONDUCT) and DROP
        # the position-agnostic closed-form trust (OMUX->IMUX tile-invariance + OMUX->RMUX closed-form). Those two
        # are trusted at EVERY position without per-position proof, and per-position electrical death (proven) makes
        # a spread design route on paper but FREEZE on silicon. Now that the conducting set covers ~89% of the pip
        # model (silicon sweep U corpus-route mining), we can afford to gate strictly and route only proven edges.
        # CLAIM: per-position-conduction-witness-required (agamemnon.engine.gate_claims) -- that is the live
        # claim this gate actually rests on today. The "per-position electrical death (proven)" phrase above is
        # the retired dead-edge-catalogue-2026 claim; see the ledger entry before assuming that catalogue is
        # still the reason -- it was refuted 2026-08-13, but the admission POLICY beside it was re-confirmed
        # on silicon independently, 2026-08-21.
        STRICT_GATE = bool(os.environ.get("AGAMEMNON_STRICT_GATE"))
        # AGAMEMNON_ROUTING_ADMISSION selects the admission model documented in
        # agamemnon/engine/routing_tiers.py:
        #   release-strict  today's binary gate -- STRICT_GATE's verdict, nothing more
        #   tiered          tier 1 (= the strict bar, unchanged) PLUS tier 2, edges with no
        #                   conduction witness whose selector CODEWORD is nevertheless certain,
        #                   every one of them recorded in a device-database sidecar
        #   tiered-tables   tier 2 restricted to the two observation-backed bases (no closed
        #                   forms); the A/B control for measuring what the closed forms add
        # Tier 3 -- a conflicting or absent selector key -- is refused under every model, because a
        # wrong codeword config-accepts and misbehaves, which is this project's most expensive
        # recurring defect. Tiering is strictly additive: under release-strict the graph is
        # byte-identical to the one this code produced before the model existed.
        ADMISSION = OPTIONS.raw("AGAMEMNON_ROUTING_ADMISSION") or "release-strict"
        if ADMISSION not in ("release-strict", "tiered", "tiered-tables"):
            raise ValueError(
                "AGAMEMNON_ROUTING_ADMISSION must be release-strict, tiered or tiered-tables, "
                "not %r" % ADMISSION)
        TIERED_GATE = ADMISSION != "release-strict"
        def is_trusted(r, fn):
            if _blacklisted(r):
                return False                             # negative silicon evidence has absolute precedence
            if _edge_key(r) in ADMITTED_BY_EDGE:
                return True                              # exact reviewed experimental row
            if r.get("source") == "observed":
                return True                              # real vendor-router edge (per-position)
            if CONDUCT and _cond_key(r) in CONDUCT:
                return True                              # silicon/vendor-PROVEN conducting edge (per-position)
            if STRICT_GATE:
                return False                             # strict: nothing else is trusted (drop closed-form guesses)
            if fn == "rrg_omux_imux_full.csv":
                return True                              # OMUX->IMUX crossbar, tile-invariant validated
            if fam(r["src_res"]) == "OMUX" and fam(r["dst_res"]) == "RMUX":
                return True                              # RMUX<-OMUX is closed-form (100%)
            return False                                 # enumerated RMUX->RMUX / RMUX->IMUX guesses (~94-97%)
        n_pip = 0; skipped = 0; dropped_enum = 0; exit_pruned = 0; seen_pip = set()
        # BBMUXW has no source-index fallback in bitgen: unlike BBMUXS/E, every
        # RMUX->BBMUXW entrance needs an exact tuple from the same exit-pair
        # tables consumed by emission.  Vendor observation proves adjacency,
        # not selector encoding.  Keep the two gates aligned so the "strict"
        # graph never offers a route which strict bitgen must later reject.
        _exact_bbmuxw_edges = exact_bbmuxw_edges(DATA)
        # Same alignment for the two east/south boundary sources whose fallback
        # codeword is ambiguous: bitgen now refuses them, so the graph must not
        # offer them either or the router would spend a corridor on an entrance
        # that bitgen will reject 4,000 lines later.  Exact witnessed tuples are
        # unaffected.
        _exact_bbmux_es_edges = (exact_boundary_edges(DATA, "BBMUXE")
                                 | exact_boundary_edges(DATA, "BBMUXS"))
        _ambiguous_boundary = ambiguous_boundary_sources(DATA)
        if any(_ambiguous_boundary.values()):
            print("AGRV2K arch: boundary fallback withdrawn for unidentifiable source(s): %s"
                  % ", ".join("%s<-RMUX%d" % (family, index)
                              for family, indices in sorted(_ambiguous_boundary.items())
                              for index in sorted(indices)))
        d = ctx.getDelayFromNS(0.1)
        # Conservative vendor routing timing.  The derived table is the maximum of
        # every WORST transition/fanout row across all decoded alta_wire PVT inputs.
        # Until every physical wire index has a proven native T0/T1/T4/TG class, use
        # the maximum for its driving mux family across classes.  Unknown families use
        # the global maximum rather than an optimistic synthetic default.
        _wt_path = os.path.join(DATA, "wire_timing_worst.json")
        _wt_source = {}; _wt_fallback = 0.1
        if os.path.exists(_wt_path):
            with open(_wt_path, encoding="utf-8") as _wt_handle:
                _wt = json.load(_wt_handle)
            _wt_source = {str(k): float(v) for k, v in _wt.get("source_max_ns", {}).items()}
            _wt_fallback = float(_wt.get("fallback_max_ns", max(_wt_source.values()) if _wt_source else 0.1))
        _wt_margin = max(1.0, OPTIONS.number("AGAMEMNON_WIRE_TIMING_MARGIN"))
        _wt_exact = {}
        if _wt_source and DEV.name == "AGRV2KL48":
            _omux_bound = max((_wt_source.get(name, 0.0)
                               for name in ("OMUXI", "OMUXL", "OMUXR")), default=0.0)
            try:
                _wt_exact = wire_timing.load_safe_exact(DATA, _omux_bound)
            except wire_timing.ExactWireTimingError as exc:
                print("AGRV2K arch: exact wire timing disabled; conservative fallback active (%s)" % exc)
        elif _wt_source:
            print("AGRV2K arch: exact local wire timing is L48-scoped; conservative fallback active for %s"
                  % DEV.name)
        # Measured per-family delays (RMUX/ClkMUX/BufMUX only) fitted against
        # Reference-backend STA, replacing a worst-case charge with evidence for
        # exactly the families this project has attributed data for.
        # CLAIM: fitted-wire-timing-rmux-clkmux-bufmux-2026
        # Same L48 scope and fail-closed shape as the OMUX->IMUX exact table
        # above: a missing/malformed/non-improving table falls back to the
        # untouched worst-case model, never to something more optimistic than
        # certified.
        _wt_measured = {}
        if _wt_source and DEV.name == "AGRV2KL48":
            try:
                _wt_measured = wire_timing.load_measured_families(DATA, _wt_source)
            except wire_timing.MeasuredWireTimingError as exc:
                print("AGRV2K arch: measured per-family wire timing disabled; conservative fallback active (%s)" % exc)
        def _wire_delay_ns(resource):
            family = fam(resource)
            if family in _wt_measured:
                return _wt_measured[family] * _wt_margin
            if family in _wt_source:
                return _wt_source[family] * _wt_margin
            folded = family.lower()
            aliases = [value for name, value in _wt_source.items()
                       if name.lower().startswith(folded) or folded.startswith(name.lower())]
            return (max(aliases) if aliases else _wt_fallback) * _wt_margin
        def _wire_delay(resource):
            return ctx.getDelayFromNS(_wire_delay_ns(resource))
        if _wt_source:
            print("AGRV2K arch: conservative vendor wire timing for %d source families "
                  "(unknown fallback %.3f ns, margin %.3fx)" %
                  (len(_wt_source), _wt_fallback, _wt_margin))
        if _wt_exact:
            print("AGRV2K arch: certified exact local timing for %d OMUX->IMUX pairs; "
                  "conservative fallback for all other routing edges" % len(_wt_exact))
        if _wt_measured:
            print("AGRV2K arch: measured per-family wire timing (one design/one part/one "
                  "PVT corner evidence, NOT a characterisation) active for %d families: %s"
                  % (len(_wt_measured),
                     ", ".join("%s=%.3fns" % (k, _wt_measured[k]) for k in sorted(_wt_measured))))
        # SOFT conducting-PREFERENCE (AGAMEMNON_SOFT_PREFER=1): instead of the hard conduction GATE (which
        # route-fails when the proven set lacks a resource-level path), keep the full mesh routable but make
        # TRUSTED edges (observed U conducting U closed-form) CHEAP and enumerated guesses EXPENSIVE. The router
        # then prefers silicon-conducting edges and falls back to an enumerated edge only when no proven path
        # exists -> most hops land on conducting edges (silicon-correct) without a hard failure. The remaining
        # enumerated fallbacks are exactly the edges to prove/blacklist next (reactive convergence). Penalty is
        # tunable (AGAMEMNON_SOFT_PENALTY ns, default 30) and is ADDED to the edge's base wire delay. Replacing
        # the base delay with the penalty would invert the preference whenever a characterized trusted wire is
        # slower than the penalty. No-op unless SOFT is set.
        SOFT = bool(os.environ.get("AGAMEMNON_SOFT_PREFER"))
        _soft_penalty_ns = OPTIONS.number("AGAMEMNON_SOFT_PENALTY")
        # SPAN-DELAY (AGAMEMNON_SPAN_DELAY=1): give trusted edges a geometric cost = base + step*(|dx|+|dy|), so
        # intra-tile hops are ~free and inter-tile hops cost with distance. This hands nextpnr-generic's placer a
        # real WIRELENGTH GRADIENT (cluster connected cells, pull them toward their exits) instead of the flat
        # 0.1ns that made native placement scatter. Delays don't affect emitted bytes, but they change routing
        # choices -> gated OFF by default so the byte-exact regression + working flows are untouched.
        SPAN_DELAY = bool(os.environ.get("AGAMEMNON_SPAN_DELAY"))
        _span_step = OPTIONS.number("AGAMEMNON_SPAN_STEP")
        def pip_delay(r, fn):
            if SPAN_DELAY:
                try:
                    span = abs(int(r["dst_x"]) - int(r["src_x"])) + abs(int(r["dst_y"]) - int(r["src_y"]))
                except Exception:
                    span = 0
                base_ns = 0.05 + _span_step * span
            else:
                conservative_ns = (_wire_delay_ns(r["src_res"]) / _wt_margin
                                   if _wt_source else 0.1)
                base_ns = wire_timing.select_routing_delay_ns(
                    _wt_exact, r["src_res"], r["dst_res"],
                    conservative_ns, _wt_margin,
                )
            if SOFT and not is_trusted(r, fn):
                base_ns += _soft_penalty_ns
            if CLEAN_SEL_PREFER and not _clean_sel_encodable(r):
                base_ns += CLEAN_SEL_PENALTY_NS
            return ctx.getDelayFromNS(base_ns)
        if TRUE_TOPO:
            _base = "rrg_edges_true_repl.csv" if TRUE_TOPO == "2" else "rrg_edges_true.csv"
            edge_files = (_base, "rrg_omux_imux_full.csv")
            print("AGRV2K arch: TRUE-TOPO mode -> loading %s" % _base)
        else:
            # The enumerated RRG is incomplete: vendor routes have exposed additional
            # physical inter-tile edges.  corpus_conduction.csv is therefore both
            # positive conduction evidence and a topology supplement.  `seen_pip`
            # below makes the large overlap with rrg_edges_full.csv free of duplicate
            # pips while retaining vendor-only links.
            edge_files = ("rrg_edges_full.csv", "rrg_omux_imux_full.csv",
                          "corpus_conduction.csv")
        if os.environ.get("AGAMEMNON_PHYSICAL_IO") and DEV.name == "AGRV2KL48":
            edge_files = tuple(edge_files) + ("physical_iob_edges_L48.csv",)
        # XBAR-FULL (AGAMEMNON_XBAR_FULL=1): add the COMPLETED intra-tile RMUX->IMUX input crossbar (union+
        # replicate the tile-invariant template -> every RMUX source reaches its full ~32 IMUX targets per tile).
        # Widens high-fanout control/select routing (mux sel, freeze) that the observed-only crossbar (566..625
        # of 1013 pairs/tile) starves. Same tile-invariance justification + silicon caveat as rrg_omux_imux_full
        # (some completed pairs may be electrically dead -> gate with CONDUCTION_GATE/SOFT_PREFER). See
        # complete_rmux_imux.py / OBSERVABILITY_FINDINGS.md. Opt-in until silicon-validated.
        if os.environ.get("AGAMEMNON_XBAR_FULL"):
            edge_files = tuple(edge_files) + ("rrg_rmux_imux_full.csv",)
            print("AGRV2K arch: XBAR-FULL -> adding completed RMUX->IMUX input crossbar")
        # RES-NAME NORMALIZER: rrg_omux_imux_full.csv uses UNPADDED res names (OMUX1/IMUX0) while wires.csv +
        # rrg_edges_full.csv use 2-digit PADDED (OMUX01/IMUX00). Without normalizing, W() builds "X..Y.._OMUX1"
        # which is NOT in wireset -> the ENTIRE OMUX->IMUX feedback crossbar (70752 edges) was silently dropped
        # as "endpoint absent" -> registered cells had NO intra-slice feedback path (THE counter-freeze root
        # cause). Pad the numeric suffix so both formats match. Harmless for already-padded names.
        def _padres(res):
            m = re.match(r"([A-Za-z]+)(\d+)$", res)
            return "%s%02d" % (m.group(1), int(m.group(2))) if m else res

        def _slice_qfb_signature(record):
            """Return the slice index for the exact local ripple Q->B edge.

            These 2,112 edges are already present in the admitted physical
            graph.  They used to enter that graph as ordinary ``ROUTE`` pips,
            after which the feedback block below could not retype them
            because ``seen_pip`` quite correctly suppressed the duplicate.
            Classify the original graph edge at first admission so router
            ownership can distinguish Q self-feedback from ordinary data.
            """
            if not os.environ.get("AGAMEMNON_HW_CARRY"):
                return None
            if (int(record["src_x"]) != int(record["dst_x"])
                    or int(record["src_y"]) != int(record["dst_y"])):
                return None
            source = re.fullmatch(r"OMUX(\d{2})", record["src_res"])
            destination = re.fullmatch(r"IMUX(\d{2})", record["dst_res"])
            if source is None or destination is None:
                return None
            source_index = int(source.group(1))
            if source_index % 3 != 1:
                return None
            z = (source_index - 1) // 3
            return z if 0 <= z < 16 and int(destination.group(1)) == 4 * z + 1 else None

        # CONFIG-ENCODING GATE (AGAMEMNON_CLEAN_SEL_GATE=1): electrical adjacency and selector encoding are
        # separate qualifications.  A route can use only conducting edges yet still program the wrong mux input
        # if bitgen has to guess a selector pair.  The block-clean corpus table attributes active bits within each
        # destination node's independent 10-bit RMUX / 12-bit IMUX block and includes only physical edge keys
        # consistent across every observation.  In strict mode, prune uncertain mesh edges before nextpnr sees
        # them, so the router finds another route instead of bitgen silently using an 84--98% predictor.
        CLEAN_SEL_GATE = bool(os.environ.get("AGAMEMNON_CLEAN_SEL_GATE"))
        CLEAN_SEL_PREFER = bool(os.environ.get("AGAMEMNON_CLEAN_SEL_PREFER"))
        CLEAN_SEL_PENALTY_NS = OPTIONS.number("AGAMEMNON_CLEAN_SEL_PENALTY")
        CLEAN_SEL_EDGE = {}
        CLEAN_SEL_REL = {}
        EXACT_HARD_BOUNDARY = {}
        _csr_conflict = frozenset()
        _cse = os.path.join(DATA, "sel_edge_pairs.agdb")
        if CLEAN_SEL_GATE or CLEAN_SEL_PREFER:
            if not os.path.exists(_cse):
                raise ValueError("AGAMEMNON_CLEAN_SEL_GATE requires chipdb/sel_edge_pairs.agdb")
            from agamemnon.engine import routing_selectors
            CLEAN_SEL_EDGE = routing_selectors.load_clean_edges(DATA)
            CLEAN_SEL_REL, _csr_conflict = routing_selectors.relative_edges(CLEAN_SEL_EDGE)
            _csm = "gate" if CLEAN_SEL_GATE else "prefer +%.1f ns" % CLEAN_SEL_PENALTY_NS
            print("AGRV2K arch: CLEAN-SEL encoding %s ON (%d physical + %d unanimous relative keys; "
                  "%d conflicting relative keys rejected)"
                  % (_csm, len(CLEAN_SEL_EDGE), len(CLEAN_SEL_REL), len(_csr_conflict)))
            # The ordinary clean-selector corpus covers the regular RMUX/IMUX
            # mesh.  Hard-boundary sources (BufMUX/InputMUX) are encoded by the
            # exact corridor tables instead.  Load the SAME merged, ambiguity-
            # withdrawn map that bitgen consults so the architecture cannot
            # offer a conducting vendor-observed hop that emission will later
            # reject as UNMAPPED.  This is especially important after widening
            # corpus_conduction.csv: topology evidence is not a codeword.
            EXACT_HARD_BOUNDARY = MCU_AHB_FEATURE.load_routing_metadata(
                context.chipdb_root, OPTIONS).exact_pips
        # Tier 2 rests on the SAME two tables the clean-sel gate already trusts for emission, and on
        # nothing else: an exact conflict-free physical observation, or a tile-relative key that every
        # physical occurrence agrees on. Majority votes, mesh-template predictions, trained predictions
        # and closed forms are all excluded -- those are precisely the classes bitgen counts as
        # `predicted`, and a `predicted` edge is refused at emission time anyway.
        SELECTOR_CERTAINTY = None
        if TIERED_GATE:
            if not (STRICT_GATE and CLEAN_SEL_GATE and TRUSTED):
                # Without all three the tier labels would be lies, and the failure
                # would be silently PERMISSIVE rather than loud: with no trust gate
                # running, every enumerated edge is admitted and the manifest
                # truthfully reports zero tier-2 edges for a graph that never
                # gated anything.
                raise ValueError(
                    "AGAMEMNON_ROUTING_ADMISSION=%s requires AGAMEMNON_STRICT_GATE, " % ADMISSION +
                    "AGAMEMNON_CLEAN_SEL_GATE and a trust gate "
                    "(AGAMEMNON_CONDUCTION_GATE or AGAMEMNON_TRUSTED); tier 1 is defined as the "
                    "strict bar and tier 3 by the clean-sel prune, so without all three the tier "
                    "labels do not mean what they say"
                )
            SELECTOR_CERTAINTY = routing_tiers.SelectorCertainty(
                CLEAN_SEL_EDGE, CLEAN_SEL_REL, _csr_conflict,
                allow_closed_form=ADMISSION == "tiered")
        _tier2_rows = []
        _tier2_seen = set()
        _witnessed_pips = set()
        _tier_counts = collections.Counter()
        def _clean_sel_encodable(r):
            if _edge_key(r) in ADMITTED_BY_EDGE:
                return True
            # A small number of package-boundary hops are explicitly recovered as
            # fixed wires.  They have no selector by construction, so asking the
            # configurable RMUX corpus to encode them incorrectly prunes the only
            # physical OE feeder from the strict graph.
            if not r.get("cfg") and str(r.get("tier", "")).endswith("-fixed"):
                return True
            df, sf = fam(r["dst_res"]), fam(r["src_res"])
            di = int(r["dst_res"][len(df):]); si = int(r["src_res"][len(sf):])
            key = (int(r["dst_x"]), int(r["dst_y"]), df, di, sf,
                   int(r["src_x"]), int(r["src_y"]), si)
            if key in CLEAN_SEL_EDGE:
                return True
            if (df, di, sf, si, int(r["dst_x"]) - int(r["src_x"]),
                    int(r["dst_y"]) - int(r["src_y"])) in CLEAN_SEL_REL:
                return True
            # Two byte-exact closed forms remain safe outside the corpus table.
            if df == "RMUX" and sf == "OMUX":
                return True
            if df == "IMUX" and sf == "OMUX" and r["src_x"] == r["dst_x"] \
               and r["src_y"] == r["dst_y"] and (si - 1) % 3 == 0:
                return True
            if df in ("RMUX", "IMUX") and sf in ("BufMUX", "InputMUX"):
                exact_key = (
                    int(r["src_x"]), int(r["src_y"]), sf, si,
                    int(r["dst_x"]), int(r["dst_y"]), df, di,
                )
                if exact_key in EXACT_HARD_BOUNDARY:
                    return True
                # A few InputMUX entries predate the unified corridor CSVs but
                # are still exact bitgen inputs: vendor-observed physical rows,
                # curated board-qualified MCU_ENTRY rows, and the closed set of
                # independently qualified interior entries.  The x=13 formula
                # is deliberately absent here because bitgen marks it predicted
                # and release emission refuses it.
                if sf == "InputMUX":
                    if (int(r["dst_x"]), int(r["dst_y"]), di,
                            int(r["src_x"]), int(r["src_y"]), si) in \
                            _VENDOR_OBSERVED_EXACT_MCU_ENTRY:
                        return True
                    if (int(r["dst_x"]), int(r["dst_y"]), di) in MCU_ENTRY:
                        return True
                    if (int(r["dst_x"]), int(r["dst_y"]), di) in \
                            _SILICON_QUALIFIED_UNSCOPED_ENTRY:
                        return True
                return False
            if df not in ("RMUX", "IMUX") or sf not in ("RMUX", "OMUX"):
                return True
            return False
        # FEEDBACK-TARGET RESTRICTION: the OMUX[3z+1]->IMUX crossbar (enum_xbar) offers MANY legal targets but
        # only VENDOR-USED (source,target) pairs actually CONDUCT (silicon: OMUX01->IMUX00 is legal, sel resolves,
        # but is DEAD; OMUX01->IMUX07 conducts). Restrict OMUX->IMUX feedback pips to the vendor-observed pairs
        # harvested in chipdb/ff_feedback_map.csv (tile-invariant (src_res,dst_res)); bitgen resolves their sels
        # byte-exact via the mesh template. This forces the router onto conducting feedback targets = the
        # counter-freeze fix. Empty map -> no restriction (safe).
        FB_ALLOWED = set()
        _fbm = os.path.join(DATA, "ff_feedback_map.csv")
        # OPT-IN (AGAMEMNON_FBRESTRICT=1): the map is a partial 30-edge sample, so restricting the whole OMUX->IMUX
        # crossbar to it would route-fail designs whose feedback target isn't sampled. Keep OFF by default until
        # the bel LUT-input fix lands + the map is complete (see COUNTER_FREEZE_HANDOFF.md). Enable only for the
        # counter-freeze fix experiments.
        if os.path.exists(_fbm) and os.environ.get("AGAMEMNON_FBRESTRICT"):
            for r in csv.DictReader(open(_fbm)):
                FB_ALLOWED.add((_padres(r["omux_src"]), _padres(r["imux_fb"])))
            print("AGRV2K arch: FEEDBACK-TARGET restriction ON (%d vendor OMUX->IMUX pairs)" % len(FB_ALLOWED))
        # SILICON intra-tile crossbar conduction prune (AGAMEMNON_XBAR_CONDUCT): drop the PHYSICAL OMUX->IMUX pips
        # PROVEN DEAD on silicon (chipdb/xbar_dead_pips.csv, from xbar_pip_sweep.py -- the TRUE src->dst pip per
        # placement, not the placement label). A tile-invariant BLACKLIST (res-level): with the dead pips removed,
        # nextpnr's OWN placer+router pack cells densely and use only conducting intra-tile links -- no hand-packer.
        XBAR_DEAD = set()
        _xd = os.path.join(DATA, "xbar_dead_pips.csv")
        if os.path.exists(_xd) and os.environ.get("AGAMEMNON_XBAR_CONDUCT"):
            for r in csv.DictReader(open(_xd)):
                if r.get("omux") and r.get("imux"): XBAR_DEAD.add((_padres(r["omux"]), _padres(r["imux"])))
            print("AGRV2K arch: XBAR conduction prune ON (%d dead intra-tile OMUX->IMUX pips blacklisted)" % len(XBAR_DEAD))
        # BRAM coverage prune (default ON): a BramTile IMUX/RMUX-dst mesh edge is kept only if bitgen can emit
        # its config (chipdb/bram_pip_cfg.csv). Forces nextpnr to route BRAM data/addr through configurable
        # edges -> silicon-correct. Non-BRAM designs are unaffected (no BramTile-dst edges). Disable with
        # AGAMEMNON_BRAM_ALL_EDGES=1 (to route freely at the cost of unemittable BRAM pips).
        BRAM_COV_ONLY = not os.environ.get("AGAMEMNON_BRAM_ALL_EDGES")
        # BRAM address-APPROACH whitelist (opt-in with AGAMEMNON_BRAM_APPROACH when the file is present): a
        # RMUX that (per the vendor) feeds a BramTile IMUX may only be driven by the vendor's conducting approach
        # source -- else nextpnr detours into the boundary via dead edges and the address never reaches the BRAM
        # (silicon: reads word 0). chipdb/bram_approach.csv from harvest_bram_approach.py. Mirrors exit-feeder wl.
        _BAP_ALLOWED = {}                 # (dx,dy,dr) boundary-RMUX -> set of allowed (sx,sy,sr) vendor sources
        _bram_bnd_rmux = set()
        _bap = os.path.join(DATA, "bram_approach.csv")
        if os.environ.get("AGAMEMNON_BRAM_APPROACH") and os.path.exists(_bap):   # opt-in (can route-fail if too tight)
            _er = list(csv.DictReader(open(_bap)))
            for r in _er:                 # boundary RMUX = a RMUX whose output feeds a BramTile(13,4) IMUX
                if r["dst_res"].startswith("IMUX") and r["dst_x"] == "13" and r["dst_y"] == "4":
                    _bram_bnd_rmux.add((r["src_x"], r["src_y"], r["src_res"]))
            for r in _er:
                k = (r["dst_x"], r["dst_y"], r["dst_res"])
                if k in _bram_bnd_rmux:
                    _BAP_ALLOWED.setdefault(k, set()).add((r["src_x"], r["src_y"], r["src_res"]))
            print("AGRV2K arch: BRAM address-approach whitelist: %d boundary RMUX(es)" % len(_bram_bnd_rmux))
        # SILICON-PROVEN BRAM final-hop whitelist (chipdb/bram_wl.csv from build_bram_wl.py, sourced from the
        # bram_conduction_campaign per-bit toggling paths + vendor route.tx fallback): restrict each
        # BramTILE(13,4) address IMUX to ONLY its conduction-proven feeder RMUX. Stops nextpnr choosing
        # config-accepting-but-DEAD entry pips (e.g. RMUX12->IMUX03, RMUX58->IMUX06-in-context) that pinned the
        # open read to a partial address width. Default ON when the file is present; disable AGAMEMNON_NO_BRAM_WL=1.
        _BRAM_FINAL_DST = set(); _BRAM_FINAL_OK = set()
        _bwl = os.path.join(DATA, "bram_wl.csv")
        if os.path.exists(_bwl) and not os.environ.get("AGAMEMNON_NO_BRAM_WL"):
            for r in csv.DictReader(open(_bwl)):
                if r["dst_res"].startswith("IMUX") and r["dst_x"] == "13" and r["dst_y"] == "4":
                    dk = (r["dst_x"], r["dst_y"], _padres(r["dst_res"]))
                    _BRAM_FINAL_DST.add(dk)
                    _BRAM_FINAL_OK.add((r["src_x"], r["src_y"], _padres(r["src_res"])) + dk)
            print("AGRV2K arch: BRAM final-hop whitelist: %d IMUX terminals restricted to proven feeders"
                  % len(_BRAM_FINAL_DST))
        import json as _json
        _BRES = None
        _brj4 = os.path.join(DATA, "bram_resolver.json")
        if BRAM_COV_ONLY and os.path.exists(_brj4):
            _BRES = _json.load(open(_brj4))
        _BRAM_EXACT_CFG = set()
        _bpc_exact = os.path.join(DATA, "bram_pip_cfg.csv")
        if os.path.exists(_bpc_exact):
            for _r in csv.DictReader(open(_bpc_exact)):
                _BRAM_EXACT_CFG.add((_r["dst_res"], _r["src_res"], int(_r["ddx"]), int(_r["ddy"])))
        def _bram_resolvable(dres, sres, ddx, ddy):
            """True if the BramTile sel resolver can emit config for this edge (else prune so nextpnr reroutes)."""
            dm = re.match(r"(IMUX|RMUX)(\d+)", dres); sm = re.match(r"([A-Za-z]+)(\d+)", sres)
            if dm and sm and ((dm.group(1) + str(int(dm.group(2))), sm.group(1) + str(int(sm.group(2))),
                               ddx, ddy) in _BRAM_EXACT_CFG):
                return True
            # Bitgen deliberately requires a byte-exact table row for a BRAM
            # BufMUX -> RMUX exit; the generalized BramTile resolver is only
            # archival evidence for that boundary. Do not offer an edge that
            # release-strict can route but must later refuse to encode.
            if dm and sm and dm.group(1) == "RMUX" and sm.group(1) == "BufMUX":
                return False
            if _BRES is None: return True
            if not (dm and sm): return True
            dfam, didx, sfam, sidx = dm.group(1), int(dm.group(2)), sm.group(1), int(sm.group(2))
            go = didx % _BRES["NPI"][dfam]
            for k in ("|".join(map(str, (dfam, didx, sfam, sidx, ddx, ddy))),
                      "|".join(map(str, (dfam, go, sfam, sidx, ddx, ddy))),
                      "|".join(map(str, (dfam, sfam, ddx, ddy, sidx % 16)))):
                if k in _BRES["L0"] or k in _BRES["L1"] or k in _BRES["L2"]: return True
            return False
        # Port B has multiple graph-adjacent choices for some terminal muxes, but only
        # one route has been exercised with a dynamic, address-swept x2 vendor image.
        # Restrict both the final input hop and first output hop to that checked-in
        # corridor.  This applies to every edge source, including generic-RRG rows and
        # the BRAM supplement, so an alternate cannot leak in through their union.
        _BRAM_CORRIDOR_DST = set(); _BRAM_CORRIDOR_SRC = set(); _BRAM_CORRIDOR_OK = set()
        _bcor = os.path.join(DATA, "bram_portb_corridors.csv")
        if os.path.exists(_bcor):
            for _r in csv.DictReader(open(_bcor)):
                _s = (int(_r["src_x"]), int(_r["src_y"]), _padres(_r["src_res"]))
                _d = (int(_r["dst_x"]), int(_r["dst_y"]), _padres(_r["dst_res"]))
                _BRAM_CORRIDOR_OK.add(_s + _d)
                if _r["port"] == "AddressB": _BRAM_CORRIDOR_DST.add(_d)
                if _r["port"] == "DataOutB": _BRAM_CORRIDOR_SRC.add(_s)
            print("AGRV2K arch: Port-B silicon corridor: %d input + %d output terminals restricted"
                  % (len(_BRAM_CORRIDOR_DST), len(_BRAM_CORRIDOR_SRC)))
        _BRAM_EXIT_SRC = set(); _BRAM_EXIT_OK = set()
        _bxcor = os.path.join(DATA, "bram_portb_exit_corridors.csv")
        # This table is an MCU-readback route, not a universal fabric-read corridor.
        # Applying it to ordinary BRAM consumers strands local DataOutB sinks after
        # the qualified BufMUX->RMUX terminal.  Enable it only for the matching
        # probe/readback transport; normal Port-B builds retain the strict general
        # graph beyond the silicon-qualified first output hop.
        if os.environ.get("AGAMEMNON_BRAM_PORTB_MCU_EXIT") and os.path.exists(_bxcor):
            for _r in csv.DictReader(open(_bxcor)):
                _s = (int(_r["src_x"]), int(_r["src_y"]), _padres(_r["src_res"]))
                _d = (int(_r["dst_x"]), int(_r["dst_y"]), _padres(_r["dst_res"]))
                _BRAM_EXIT_SRC.add(_s); _BRAM_EXIT_OK.add(_s + _d)
            print("AGRV2K arch: Port-B full exit corridor: %d source nodes restricted"
                  % len(_BRAM_EXIT_SRC))
        _BRAM_ENTRY_DST = set(); _BRAM_ENTRY_OK = set()
        _becor = os.path.join(DATA, "bram_portb_entry_corridors.csv")
        if os.environ.get("AGAMEMNON_BRAM_PORTB_EXIT") and os.path.exists(_becor):
            for _r in csv.DictReader(open(_becor)):
                _s = (int(_r["src_x"]), int(_r["src_y"]), _padres(_r["src_res"]))
                _d = (int(_r["dst_x"]), int(_r["dst_y"]), _padres(_r["dst_res"]))
                _BRAM_ENTRY_DST.add(_d); _BRAM_ENTRY_OK.add(_s + _d)
            print("AGRV2K arch: Port-B full entry corridor: %d destination nodes restricted"
                  % len(_BRAM_ENTRY_DST))
        def _outside_bram_corridor(r):
            _s = (int(r["src_x"]), int(r["src_y"]), _padres(r["src_res"]))
            _d = (int(r["dst_x"]), int(r["dst_y"]), _padres(r["dst_res"]))
            if (_d in _BRAM_CORRIDOR_DST or _s in _BRAM_CORRIDOR_SRC) and _s + _d not in _BRAM_CORRIDOR_OK:
                return True
            if _d in _BRAM_ENTRY_DST and _s + _d not in _BRAM_ENTRY_OK:
                return True
            return _s in _BRAM_EXIT_SRC and _s + _d not in _BRAM_EXIT_OK
        _bram_epr = 0
        _sel_pruned = 0
        _PHYS_PAD_TERM = {}
        _PHYS_INPUT_ENTRY = {}
        _PHYS_INPUT_CONT = {}
        for _pf_name in ("padfeed_L48_top.csv", "padfeed_L48_left.csv"):
            _pf_phys = os.path.join(DATA, _pf_name)
            if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_pf_phys):
                for _r in csv.DictReader(open(_pf_phys)):
                    _PHYS_PAD_TERM.setdefault((int(_r["padtile_x"]), int(_r["padtile_y"]),
                                               int(_r["iomux_z"])), set()).add(
                        "RMUX%02d" % int(_r["padfeed_rmux"]))
        # A characterized dynamic-output pad owns two independent terminals:
        # fabric data and output-enable.  Preserve the ordinary scalar-output
        # terminal choices above, and add the exact hard-peripheral pair rather
        # than letting the generic physical-pad whitelist prune either route.
        _oepad_phys = os.path.join(DATA, "physical_oepad_L48.csv")
        if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_oepad_phys):
            for _r in csv.DictReader(open(_oepad_phys)):
                _px, _py = int(_r["x"]), int(_r["y"])
                _PHYS_PAD_TERM.setdefault(
                    (_px, _py, int(_r["data_iomux"])), set()
                ).add("RMUX%02d" % int(_r["data_rmux"]))
                _PHYS_PAD_TERM.setdefault(
                    (_px, _py, int(_r["oe_iomux"])), set()
                ).add("RMUX%02d" % int(_r["oe_rmux"]))
        # A captured implicit IOMUX hop is stronger evidence than a route.tx terminal alone: without the
        # hop's selector bits the image is accepted but the physical pad may be static. Where one or more
        # vendor-hop rows exist for a pad, expose only those feeders to physical-PCF routing.
        _hop_phys = os.path.join(DATA, "iomux_hop_vendor.csv")
        if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_hop_phys):
            _verified_top = {}
            for _r in csv.DictReader(_line for _line in open(_hop_phys)
                                     if not _line.lstrip().startswith("#")):
                _verified_top.setdefault((int(_r["pad_x"]), int(_r["pad_y"]), int(_r["z"])), set()).add(
                    "RMUX%02d" % int(_r["feeder_R"]))
            _PHYS_PAD_TERM.update(_verified_top)
        _pi_phys = os.path.join(DATA, "pad_input_L48.csv")
        if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_pi_phys):
            for _r in csv.DictReader(open(_pi_phys)):
                _PHYS_INPUT_ENTRY.setdefault(
                    (int(_r["pad_x"]), int(_r["pad_y"]), "InputMUX%02d" % int(_r["inputmux"])), set()
                ).add((int(_r["dst_x"]), int(_r["dst_y"]), "RMUX%02d" % int(_r["dst_rmux"])))
        _pir_phys = os.path.join(DATA, "pad_input_route_L48.csv")
        if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_pir_phys):
            for _r in csv.DictReader(open(_pir_phys)):
                _sk = (int(_r["src_x"]), int(_r["src_y"]), _r["src_res"])
                _PHYS_INPUT_CONT.setdefault(_sk, set()).add(
                    (int(_r["dst_x"]), int(_r["dst_y"]), _r["dst_res"]))
        _slice_qfb_pips = set()
        for fn in edge_files:
            path = os.path.join(DATA, fn)
            if not os.path.exists(path):
                continue
            for r in csv.DictReader(open(path)):
                r["src_res"] = _padres(r["src_res"]); r["dst_res"] = _padres(r["dst_res"])
                # The compact conduction corpus omits tile-type columns; infer them
                # from the already loaded wire database so it can serve as a topology
                # supplement without duplicating hundreds of thousands of strings.
                if "src_tile" not in r:
                    # ``tile_type`` is keyed with the CSV's string coordinates.  An
                    # integer lookup silently classified every supplemental perimeter
                    # edge as LogicTILE and could re-add a physical-IO edge that the
                    # enumerated RRG pass had correctly rejected.
                    r["src_tile"] = tile_type.get((r["src_x"], r["src_y"]), "LogicTILE")
                    r["dst_tile"] = tile_type.get((r["dst_x"], r["dst_y"]), "LogicTILE")
                _qfb_z = _slice_qfb_signature(r)
                if _outside_bram_corridor(r):
                    _bram_epr += 1; continue
                if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
                    if r["dst_tile"] == "IOTILE" \
                       and fam(r["dst_res"]) == "IOMUX" and fam(r["src_res"]) == "RMUX":
                        _z = int(r["dst_res"][5:])
                        _want = _PHYS_PAD_TERM.get((int(r["dst_x"]), int(r["dst_y"]), _z))
                        if _want and r["src_res"] not in _want:
                            skipped += 1; continue
                    if r["src_tile"] == "IOTILE" and fam(r["src_res"]) == "InputMUX":
                        _ik = (int(r["src_x"]), int(r["src_y"]), r["src_res"])
                        _iwant = _PHYS_INPUT_ENTRY.get(_ik)
                        if _iwant and (int(r["dst_x"]), int(r["dst_y"]), r["dst_res"]) not in _iwant:
                            skipped += 1; continue
                    _ck = (int(r["src_x"]), int(r["src_y"]), r["src_res"])
                    _cwant = _PHYS_INPUT_CONT.get(_ck)
                    if _cwant and (int(r["dst_x"]), int(r["dst_y"]), r["dst_res"]) not in _cwant:
                        skipped += 1; continue
                if (BRAM_COV_ONLY and _BRES and r["dst_x"] == "13" and r["dst_y"] == "4"
                        and fam(r["dst_res"]) in ("IMUX", "RMUX")
                        and not _bram_resolvable(r["dst_res"], r["src_res"], int(r["dst_x"]) - int(r["src_x"]),
                                                 int(r["dst_y"]) - int(r["src_y"]))):
                    _bram_epr += 1; continue          # BramTile edge the resolver can't emit -> prune (reroute)
                _bnd = (r["dst_x"], r["dst_y"], r["dst_res"])   # BRAM address-approach whitelist
                if _bnd in _bram_bnd_rmux and (r["src_x"], r["src_y"], r["src_res"]) not in _BAP_ALLOWED.get(_bnd, ()):
                    _bram_epr += 1; continue          # feeding a BRAM-feeder RMUX from a non-vendor (dead) source
                # SILICON-PROVEN final-hop restriction: into a characterized (13,4) address IMUX ONLY via its
                # conduction-proven feeder (bram_wl.csv). Drops dead entry pips so nextpnr routes the conducting one.
                _fk = (r["dst_x"], r["dst_y"], r["dst_res"])
                if _fk in _BRAM_FINAL_DST and (r["src_x"], r["src_y"], r["src_res"]) + _fk not in _BRAM_FINAL_OK:
                    _bram_epr += 1; continue
                # FEEDBACK-TARGET restriction: OMUX->IMUX (feedback crossbar) only to vendor-conducting pairs.
                if FB_ALLOWED and fam(r["src_res"]) == "OMUX" and fam(r["dst_res"]) == "IMUX" \
                   and (r["src_res"], r["dst_res"]) not in FB_ALLOWED:
                    skipped += 1; continue
                # SILICON dead-pair blacklist: drop intra-tile OMUX->IMUX edges proven non-conducting by the sweep.
                if XBAR_DEAD and fam(r["src_res"]) == "OMUX" and fam(r["dst_res"]) == "IMUX" \
                   and (r["src_res"], r["dst_res"]) in XBAR_DEAD:
                    skipped += 1; continue
                # EXPERIMENT (AGAMEMNON_FB_OFFSET3=1): restrict the OMUX->IMUX crossbar to IMUX OFFSET-3 targets
                # (dst_idx%4==3 = input D) -- the offset the vendor uses for conducting cell-to-cell reads. Tests
                # whether "route cell-to-cell reads to offset-3" alone makes shift/FSM read correct.
                if os.environ.get("AGAMEMNON_FB_OFFSET3") and fam(r["src_res"]) == "OMUX" \
                   and fam(r["dst_res"]) == "IMUX" and int(r["dst_res"][4:]) % 4 != 3:
                    skipped += 1; continue
                # BLACKLIST: checked-in silicon-negative evidence plus any temporary experiment edges.
                # This runs before the trust gate and therefore overrides every positive evidence source.
                if _blacklisted(r):
                    skipped += 1; continue
                # EXIT-FEEDER WHITELIST: for the 4 forced MCU-dout exit RMUX nodes, drop every in-edge that
                # is not a silicon-confirmed live feeder (guarded: only those dst nodes are affected).
                if EXIT_WL and _exit_pruned(r):
                    exit_pruned += 1; continue
                # CORRECTNESS: a routing pip must not pass THROUGH a LUT. IMUX is a slice INPUT (sink only)
                # and OMUX is a slice OUTPUT (source only); an IMUX->x or x->OMUX edge is the LUT's internal
                # function (observed in real designs as logic), NOT a routing wire. Routing to/from a LUT is
                # via the bel's I[]/F/Q pins. Allowing these lets the router thread nets through unconfigured
                # slices -> the bitstream config-accepts but is electrically dead (silicon: dout stuck).
                if fam(r["src_res"]) == "IMUX" or fam(r["dst_res"]) == "OMUX":
                    skipped += 1; continue
                # CONTROL/CLOCK/ASYNC NETWORK is not data routing: CtrlMUX/TileSyncMUX/TileAsyncMUX carry FF
                # set/reset/enable + clock-control, and AsyncMUX/ClkMUX/SeamMUX (incl. TileClkMUX) are the
                # async-set/reset + clock-tree muxes -- all encoded (if at all) by the clock/async path, NOT by
                # the data-pip encoder. If the router threads a DATA net through them the bitstream config-
                # accepts but the hop is electrically DEAD on silicon (a cause of dout-stuck). Keep them out of
                # the data mesh so data stays in the RMUX/IMUX/OMUX fabric. NOTE: the clock TREE is modeled
                # SEPARATELY (typed GCLK0 spine/entry/leaf/BRAM pips in section 3b; bitgen emits
                # CFG_SEAMMUX/CFG_TILECLKMUX independently), so dropping these here does NOT remove the clock
                # model -- the slice CLK wire (ClkMUX%02d) is still reached via typed GCLK0 leaves.
                if any(fam(r[k]).endswith(("CtrlMUX", "TileSyncMUX", "TileAsyncMUX",
                                           "AsyncMUX", "ClkMUX", "SeamMUX")) for k in ("src_res", "dst_res")):
                    skipped += 1; continue
                # MCU-edge crossing muxes (BBMUXS/W/E) reachable ONLY via the encodable pips in
                # pips_mcuedge_routing.csv (RMUX19->BBMUXS02) or a source="observed" RRG row (a real
                # af.exe route hop, e.g. the wide_boundary_witness feeder bank): drop harvested
                # (enumerated-guess) BBMUX fan-in so the router can't pick an RMUX->BBMUX whose
                # sel-encoding we don't have (autonomous route must stay encodable). An observed row's
                # BBMUXW has no fallback, so even an observed row is pruned unless
                # its exact tuple is present in EXIT_PAIR_FILES.  BBMUXS/E retain
                # their independently pinned source-index fallback.
                if fam(r["dst_res"]).startswith("BBMUX") and r.get("source") != "observed":
                    skipped += 1; continue
                _dfam = fam(r["dst_res"])
                if (_dfam in _ambiguous_boundary and fam(r["src_res"]) == "RMUX"
                        and int(r["src_res"][4:]) in _ambiguous_boundary[_dfam]):
                    _boundary_edge = "%s.%s" % (
                        W(r["src_x"], r["src_y"], r["src_res"]),
                        W(r["dst_x"], r["dst_y"], r["dst_res"]),
                    )
                    if _boundary_edge not in _exact_bbmux_es_edges:
                        skipped += 1; continue
                if fam(r["dst_res"]) == "BBMUXW":
                    _boundary_edge = "%s.%s" % (
                        W(r["src_x"], r["src_y"], r["src_res"]),
                        W(r["dst_x"], r["dst_y"], r["dst_res"]),
                    )
                    if not bbmuxw_edge_admitted(
                            _boundary_edge, _exact_bbmuxw_edges,
                            research_unsafe=bool(os.environ.get(
                                "AGAMEMNON_RESEARCH_UNSAFE"))):
                        skipped += 1; continue
                # HARDEN pad-feed (LED builds): only an OBSERVED edge may drive an IOTILE pad-feed RMUX. The
                # enumerated fan-in sels into the pad tile (0,4) config-accept but do NOT conduct on silicon
                # (LEDs stay dark); the interior of the design still routes on the full mesh. This forces the
                # LED nets through the real vendor-router (4,4)->(0,4) feeder edges (whose harvested sels bitgen
                # reproduces via ABS_LUT), which is the whole point of "hardening the feeder sels".
                if os.environ.get("AGAMEMNON_HARDEN_PADFEED") and r["dst_tile"] == "IOTILE" \
                   and fam(r["dst_res"]) == "RMUX" and r.get("source") != "observed":
                    skipped += 1; continue
                # AGAMEMNON_MCU_ENTRY: force the din ENTRY through the encodable pips_mcuedge chain
                # (BufMUX10->InputMUX11->RMUX93) by dropping harvested BufMUX/InputMUX fan-out. Guarded so it
                # only applies to the MCU-edge loopback flow (general IO designs still need InputMUX edges).
                if os.environ.get("AGAMEMNON_MCU_ENTRY") and \
                   (fam(r["src_res"]).startswith("BufMUX") or fam(r["src_res"]).startswith("InputMUX")):
                    skipped += 1; continue
                # AGAMEMNON_NO_INTRA_RMUX: drop intra-tile RMUX->RMUX (a signal hopping RMUX->RMUX inside one
                # tile is the enumerated class most prone to wrong sel-bits); forces inter-tile physical wires.
                if os.environ.get("AGAMEMNON_NO_INTRA_RMUX") and r["src_x"] == r["dst_x"] and \
                   r["src_y"] == r["dst_y"] and fam(r["src_res"]) == "RMUX" and fam(r["dst_res"]) == "RMUX":
                    skipped += 1; continue
                if CLEAN_SEL_GATE and not _clean_sel_encodable(r):
                    _sel_pruned += 1; continue
                # AGAMEMNON_OBS_IMUX: LUT-input crossbar (x->IMUX) only from OBSERVED edges — the RMUX->IMUX
                # sel-encoding is table-coverage-limited, so enumerated guesses drop the signal before the LUT.
                if os.environ.get("AGAMEMNON_OBS_IMUX") and fam(r["dst_res"]) == "IMUX" \
                   and fn == "rrg_edges_full.csv" and r.get("source") != "observed":
                    skipped += 1; continue
                if OBSERVED_ONLY and r.get("source") != "observed":
                    dropped_enum += 1; continue
                _tier = None
                _basis = None
                if TRUSTED:
                    # All 2,112 exact local QFB rows have one unanimous
                    # block-clean selector and are a typed same-site resource,
                    # not generic fabric routing.  Preserve them in strict as
                    # well as tiered databases; the owner-aware uarch decides
                    # whether a net may use them.  This also retains the direct
                    # HIL-positive autonomous-feedback path present in the
                    # packaged strict snapshot.
                    if _qfb_z is not None:
                        pass
                    elif is_trusted(r, fn):
                        _tier = routing_tiers.TIER_WITNESSED
                    elif SELECTOR_CERTAINTY is None:
                        dropped_enum += 1; continue
                    else:
                        # Negative evidence keeps absolute precedence over every tier. Blacklisted
                        # rows already `continue` above; re-asserting it here means a future reorder
                        # of the loop cannot quietly let one through the new admission path.
                        _basis = (None if _blacklisted(r)
                                  else SELECTOR_CERTAINTY.classify(r, fam))
                        if _basis is None:
                            dropped_enum += 1
                            # Count only edges whose endpoints actually exist, so the reported
                            # tier-3 total is comparable with the admitted tiers rather than
                            # inflated by rows the graph could never have carried anyway.
                            if (W(r["src_x"], r["src_y"], r["src_res"]) in wireset
                                    and W(r["dst_x"], r["dst_y"], r["dst_res"]) in wireset):
                                _tier_counts[routing_tiers.TIER_AMBIGUOUS] += 1
                            continue
                        _tier = routing_tiers.TIER_ENCODING_CERTAIN
                s = W(r["src_x"], r["src_y"], r["src_res"])
                t = W(r["dst_x"], r["dst_y"], r["dst_res"])
                if s not in wireset or t not in wireset:
                    skipped += 1; continue
                nm = "%s.%s" % (s, t)
                # The same pip can be reached by several rows across the edge
                # files -- typically an enumerated row followed by a witnessed
                # one in corpus_conduction.csv. Record the witness BEFORE the
                # duplicate check, or a pip whose witnessed row happens to come
                # second gets filed as tier 2 and the manifest tells the user an
                # edge is unproven when we hold proof of it.
                if _tier == routing_tiers.TIER_WITNESSED:
                    _witnessed_pips.add(nm)
                if nm in seen_pip:
                    continue
                ctx.addPip(name=nm, type=("SLICE_QFB" if _qfb_z is not None else "ROUTE"), srcWire=s, dstWire=t,
                           delay=pip_delay(r, fn), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                seen_pip.add(nm); n_pip += 1
                if _qfb_z is not None:
                    _slice_qfb_pips.add(nm)
                if _tier is not None:
                    _tier_counts[_tier] += 1
                if _basis is not None and nm not in _tier2_seen:
                    _tier2_seen.add(nm)
                    _tier2_rows.append({
                        "pip": nm, "tier": _tier, "basis": _basis["basis"],
                        "src_x": r["src_x"], "src_y": r["src_y"], "src_res": r["src_res"],
                        "dst_x": r["dst_x"], "dst_y": r["dst_y"], "dst_res": r["dst_res"],
                        "sel_lo": _basis["sel"][0], "sel_hi": _basis["sel"][1],
                        "support": _basis["support"],
                        "witness_positions": "|".join(_basis["positions"]),
                    })
        admitted_supplements = _add_admitted_iotile_pips(
            is_blacklisted=_blacklisted,
            ctx=ctx, Loc=Loc, wire_name=W, wireset=wireset,
            seen_pip=seen_pip, rows=ADMITTED_ROWS,
            delay_for=lambda record: pip_delay(
                record, routing_admission.FILENAME
            ),
        )
        n_pip += admitted_supplements
        if ADMITTED_ROWS:
            print(
                "AGRV2K arch: selected %d exact experimental routing row(s); "
                "%d supplied an authenticated IOTILE destination pip"
                % (len(ADMITTED_ROWS), admitted_supplements)
            )
        _mode = " [OBSERVED-ONLY]" if OBSERVED_ONLY else (
                " [CONDUCTION-GATE: observed U conducting U closed-form]"
                if os.environ.get("AGAMEMNON_CONDUCTION_GATE") else (" [TRUSTED]" if TRUSTED else ""))
        if SOFT: _mode += " [SOFT-PREFER conducting, penalty=%sns]" % os.environ.get("AGAMEMNON_SOFT_PENALTY", "30")
        print("AGRV2K arch: added %d pips (%d skipped: endpoint absent; %d dropped: enumerated%s; "
              "%d exit in-edges pruned by whitelist; %d uncertain selector encodings pruned)"
              % (n_pip, skipped, dropped_enum, _mode, exit_pruned, _sel_pruned))
        if TIERED_GATE:
            # A pip whose WITNESSED row happened to come later in the edge-file
            # order was still admitted on a witness, not on encoding certainty.
            _tier2_rows = [row for row in _tier2_rows
                           if row["pip"] not in _witnessed_pips]
            _promoted = _tier_counts[routing_tiers.TIER_ENCODING_CERTAIN] - len(_tier2_rows)
            _tier_counts[routing_tiers.TIER_WITNESSED] += _promoted
            _tier_counts[routing_tiers.TIER_ENCODING_CERTAIN] -= _promoted
            # From here on, every membership test against seen_pips is a later
            # architecture block declaring it would have supplied that edge
            # itself. Those blocks run in every admission model, so anything they
            # claim is not something --release-strict would refuse and must not
            # appear in the manifest. archgen applies the filter and reports the
            # final counts once every feature has run, so no intermediate tier
            # total is printed here to be mistaken for the answer.
            # See routing_tiers.ClaimRecordingPipSet.
            seen_pip = routing_tiers.ClaimRecordingPipSet(seen_pip)
            shared["routing_tier_records"] = (
                _tier2_rows, seen_pip,
                {"schema": 1,
                 "tier_1_witnessed": _tier_counts[routing_tiers.TIER_WITNESSED],
                 # Tier 3 is counted at both places it can be refused: the
                 # clean-sel prune earlier in the loop (which drops an edge with
                 # no usable selector evidence whatever its conduction record)
                 # and the admission gate. Reporting only the second would
                 # understate it by three orders of magnitude and make the model
                 # look like it refuses nothing.
                 "tier_3_refused": _sel_pruned + _tier_counts[routing_tiers.TIER_AMBIGUOUS],
                 "tier_3_refused_at_clean_sel_prune": _sel_pruned,
                 "tier_3_refused_at_admission_gate":
                     _tier_counts[routing_tiers.TIER_AMBIGUOUS],
                 "clean_sel_physical_keys": len(CLEAN_SEL_EDGE),
                 "clean_sel_unanimous_relative_keys": len(CLEAN_SEL_REL),
                 "clean_sel_conflicting_relative_keys": len(_csr_conflict),
                 "admission_model": ADMISSION,
                 "device": DEV.name},
            )

        # ---- 4b. Dense ripple-register local feedback -----------------------------------------------
        # In ripple mode pinC is occupied by Cin, so a counter bit cannot use the normal Qin/pinC
        # self-feedback path.  The architecture instead presents that slice's Q on OMUX[3z+1] and routes it to
        # the same slice's B input, IMUX[4z+1].  The edge is present in retained carry and HIL-positive ordinary
        # registered-slice checkpoints, and the
        # block-clean selector corpus is unanimous at every slice index across all 132 logic tiles.  The
        # admitted graph already contains the complete 132-by-16 set; the main admission loop now types those
        # original edges as SLICE_QFB while retaining their graph-derived conservative delay.  This resource is
        # shared by semantically owned same-site Q -> I[1] feedback in carry and ordinary registered slices; do
        # not make it carry-exclusive.  Do not append a
        # synthetic 0.05ns duplicate here: doing so both loses the original timing evidence and, historically,
        # failed to change the type because seen_pip had already claimed the name.
        if os.environ.get("AGAMEMNON_HW_CARRY"):
            _expected_qfb = set()
            for (x, y), tt in tile_type.items():
                if tt != "LogicTILE":
                    continue
                for z in range(16):
                    _sr, _dr = "OMUX%02d" % (3 * z + 1), "IMUX%02d" % (4 * z + 1)
                    s = W(x, y, _sr)
                    t = W(x, y, _dr)
                    nm = "%s.%s" % (s, t)
                    if s in wireset and t in wireset:
                        _expected_qfb.add(nm)
            _missing_qfb = _expected_qfb - _slice_qfb_pips
            _extra_qfb = _slice_qfb_pips - _expected_qfb
            if _missing_qfb or _extra_qfb:
                raise ValueError(
                    "hard-carry graph requires the complete typed local Q->B set "
                    "(expected %d, typed %d, missing %d, extra %d)" %
                    (len(_expected_qfb), len(_slice_qfb_pips),
                     len(_missing_qfb), len(_extra_qfb)))
            print("AGRV2K arch: typed %d graph-derived ripple Q->B feedback pips" %
                  len(_slice_qfb_pips))

        # ---- 4c. FF-FEEDBACK BRIDGE (fixes counter-freeze for wide sequential) --------------------------------
        # DATA-PROVEN root cause: the ONLY intra-slice FF-Q->own-LUT feedback wire is OMUX[3z+1] (OMUX[3z+1]->IMUX
        # = 70752 edges; OMUX[3z+0]/[3z+2] have ZERO IMUX edges -- they only reach RMUX/mesh). But the bel presents
        # Q on OMUX[3z+2] (a mesh-output wire), so a registered cell's self-feedback had NO intra-slice path and the
        # router detoured it inter-tile (dead) -> every counter/accumulator interior bit froze. FIX: add a bridge
        # pip OMUX[3z+2]->OMUX[3z+1] per slice so nextpnr can route Q to the feedback wire; the existing
        # OMUX[3z+1]->IMUX pips then carry it to the slice's own LUT inputs (intra-slice, conducting). Physically
        # this is CFG_OMUX<z> presenting Q on BOTH [3z+1] (feedback) and [3z+2] (external mesh) -- the vendor
        # multi-hot pattern (AGAMEMNON_VENDOR_OUT_SLICE proves sels {0,1}); bitgen emits sel=1 for this bridge.
        # AGAMEMNON_NO_FFBRIDGE=1 disables (A/B). Zero regression for combinational designs (no self-feedback net).
        if not os.environ.get("AGAMEMNON_NO_FFBRIDGE"):
            _fbd = ctx.getDelayFromNS(0.05)
            n_fb = 0
            for (x, y), tt in tile_type.items():
                if tt != "LogicTILE": continue
                for z in range(16):
                    _sr, _dr = "OMUX%02d" % (3 * z + 2), "OMUX%02d" % (3 * z + 1)
                    s = W(x, y, _sr); t = W(x, y, _dr)
                    if _blacklisted({"src_res": _sr, "src_x": x, "src_y": y,
                                     "dst_res": _dr, "dst_x": x, "dst_y": y}):
                        continue
                    if s in wireset and t in wireset:
                        nm = "%s.%s" % (s, t)
                        if nm not in seen_pip:
                            ctx.addPip(name=nm, type="OMUXFB", srcWire=s, dstWire=t, delay=_fbd,
                                       loc=Loc(int(x), int(y), 0))
                            seen_pip.add(nm); n_fb += 1
            print("AGRV2K arch: added %d FF-feedback bridge pips (OMUX[3z+2]->OMUX[3z+1])" % n_fb)

        # ---- 4d. DIRECT-D SELF-FEEDBACK --------------------------------------------------------------
        # Silicon ablation at X1Y4 slice2 isolates the vendor branch
        # OMUX07 -> IMUX11 (CFG_IMUX2[37,45]) as necessary for the TFF. qin_pack
        # places own-Q on I[3], and the presentation bridge above makes the default
        # Q wire available on OMUX[3z+1]. Replicate only that relative branch; the
        # older synthetic Q-to-C/Qin arc is deliberately absent (fail closed).
        _dfd = ctx.getDelayFromNS(0.01)
        n_df = 0
        for (x, y), tt in tile_type.items():
            if tt != "LogicTILE": continue
            for z in range(16):
                _sr, _dr = "OMUX%02d" % (3*z + 1), "IMUX%02d" % (4*z + 3)
                s = W(x, y, _sr)
                t = W(x, y, _dr)
                nm = "%s.%s" % (s, t)
                if _blacklisted({"src_res": _sr, "src_x": x, "src_y": y,
                                 "dst_res": _dr, "dst_x": x, "dst_y": y}):
                    continue
                if s in wireset and t in wireset and nm not in seen_pip:
                    ctx.addPip(name=nm, type="DIRECT_D_FB", srcWire=s, dstWire=t,
                               delay=_dfd, loc=Loc(int(x), int(y), z))
                    seen_pip.add(nm); n_df += 1
        print("AGRV2K arch: added %d direct-D feedback pips (OMUX[3z+1]->IMUX[4z+3])" % n_df)

        # ---- 4b. PACKAGE pad-feed pips (LogicTile->IOTile hop into a pad-feed RMUX) ----
        # The RRG enumerates almost none of the vertical LogicTile(y=11|12).RMUX -> IOTILE(y=13).RMUX pad-feed
        # hops (only 1 of the 10 real vendor top-row feeds is present as 'observed'), so nextpnr cannot route a
        # fabric signal INTO a top-row pad-feed RMUX for most pads -> no logic GPIO output on the top edge.
        # We add the exact vendor pad-feed edges (chipdb/padfeed_L48_top.csv, decoded from the vendor pintest2
        # build) as routable ROUTE pips so nextpnr can complete the chain fabric -> feeder RMUX -> IOTILE
        # pad-feed RMUX -> IOMUX{z} -> pad; bitgen emits the matching CFG_RMUX codeword from the same table
        # (PADFEED_TOP). Guarded by AGAMEMNON_PADFEED_TOP so normal builds are byte-identical (no new pips).
        if os.environ.get("AGAMEMNON_PADFEED_TOP"):
            # AGAMEMNON_PADFEED_ONLY="x,y,z": add ONLY that pad's vendor pad-feed pip (so nextpnr routes the
            # exact vendor-proven feeder, not an alternate RMUX->IOMUX that happens to exist in the RRG).
            _only = os.environ.get("AGAMEMNON_PADFEED_ONLY")
            _only = tuple(int(v) for v in _only.split(",")) if _only else None
            # QUALIFIED PAD COMPOSITIONS. A pad listed in pad_output_qualified_L48.csv
            # has ONE silicon-proven composition -- one pad-feed source, one
            # pad-tile RMUX, one IOMUX terminal, one approach into the feed
            # source -- and the graph must admit only that. Left unrestricted the
            # router happily picks another feeder for the same pad: the first
            # production build of the PIN_18/PIN_16 pair took RMUX24 into PIN_16
            # where only RMUX8 is proven, which config-accepts and does not
            # drive. Pads absent from the table are unaffected.
            n_pf = 0
            for _pf_name in ("padfeed_L48_top.csv", "padfeed_L48_left.csv"):
                pf = os.path.join(DATA, _pf_name)
                if not os.path.exists(pf):
                    continue
                for r in csv.DictReader(open(pf)):
                    if _only and (int(r["padtile_x"]), int(r["padtile_y"]), int(r["iomux_z"])) != _only:
                        continue
                    # Supplemental loaders must honour the blacklist. These rows
                    # are added outside the RRG loop, so a ban on a pad-feed edge
                    # used to do nothing at all and the router kept the source the
                    # CSV names -- with a source-dependent hop codeword, that is
                    # the right bits for the wrong mux input.
                    if _blacklisted({
                        "src_res": r["src_res"], "src_x": str(r["src_x"]), "src_y": str(r["src_y"]),
                        "dst_res": "RMUX%02d" % int(r["padfeed_rmux"]),
                        "dst_x": str(r["padtile_x"]), "dst_y": str(r["padtile_y"]),
                    }):
                        continue
                    _qk = (int(r["padtile_x"]), int(r["padtile_y"]), int(r["iomux_z"]))
                    # _PHYS_PAD_TERM is the authoritative per-slot terminal
                    # whitelist once a verified iomux_hop row exists.  The RRG
                    # and iomux_term_vendor loaders already consult it, but this
                    # supplemental padfeed loader did not: it reintroduced
                    # feeder/terminal alternatives that the verified row had
                    # deliberately removed.  Filter the whole row here so its
                    # feed and its terminal cannot bypass the same whitelist.
                    _want = _PHYS_PAD_TERM.get(_qk)
                    _dst_rmux = "RMUX%02d" % int(r["padfeed_rmux"])
                    if _want and _dst_rmux not in _want:
                        continue
                    _q = _qualified.get(_qk)
                    if _q and (r["src_res"], int(r["src_x"]), int(r["src_y"]),
                               int(r["padfeed_rmux"])) != (
                            _q["src_res"], int(_q["src_x"]), int(_q["src_y"]),
                            int(_q["feeder_rmux"])):
                        continue
                    s = W(str(r["src_x"]), str(r["src_y"]), r["src_res"])
                    t = W(str(r["padtile_x"]), str(r["padtile_y"]), "RMUX%02d" % int(r["padfeed_rmux"]))
                    if s not in wireset or t not in wireset:
                        continue
                    nm = "%s.%s" % (s, t)
                    # A pad-feed edge may already have arrived through the main
                    # RRG.  That does NOT make the CSV row redundant: the row
                    # also supplies the separate RMUX->IOMUX terminal below.
                    # The old `continue` here silently dropped that terminal,
                    # making an otherwise exact pad composition unroutable.
                    if nm not in seen_pip:
                        ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                                   delay=_wire_delay(r["src_res"]),
                                   loc=Loc(int(r["padtile_x"]), int(r["padtile_y"]), 0))
                        seen_pip.add(nm); n_pf += 1
                    # The same vendor record identifies the fixed terminal from the
                    # destination pad-feed RMUX to this package pad's IOMUX slot.
                    u = W(str(r["padtile_x"]), str(r["padtile_y"]),
                          "IOMUX%02d" % int(r["iomux_z"]))
                    tnm = "%s.%s" % (t, u)
                    if _blacklisted({
                        "src_res": "RMUX%02d" % int(r["padfeed_rmux"]),
                        "src_x": str(r["padtile_x"]), "src_y": str(r["padtile_y"]),
                        "dst_res": "IOMUX%02d" % int(r["iomux_z"]),
                        "dst_x": str(r["padtile_x"]), "dst_y": str(r["padtile_y"]),
                    }):
                        continue
                    if u in wireset and tnm not in seen_pip:
                        ctx.addPip(name=tnm, type="ROUTE", srcWire=t, dstWire=u,
                                   delay=_wire_delay("RMUX%02d" % int(r["padfeed_rmux"])),
                                   loc=Loc(int(r["padtile_x"]), int(r["padtile_y"]), 0))
                        seen_pip.add(tnm); n_pf += 1
            print("AGRV2K arch: PACKAGE PAD-FEED mode -> added %d feeder/terminal pip(s)" % n_pf)
            # VENDOR IOTILE RMUX->IOMUX TERMINALS: the enumerated RRG has no fan-in into most top-row IOMUX
            # pad wires (only a few IOTILEs were in the corpus), so nextpnr can't route the last hop
            # RMUX{R}->IOMUX{z} into an OPAD bel for those pads. iomux_term_vendor.csv holds the REAL vendor
            # RMUX->IOMUX terminal edges harvested from pintest4/5 route.tx (silicon-conducting). Add them as
            # ROUTE pips so the router can complete fabric->...->RMUX{R}->IOMUX{z}->pad. The IOMUX driver
            # (source-select) is still emitted by io_emit at the config tile; this pip is the routed terminal.
            itv = os.path.join(DATA, "iomux_term_vendor.csv")
            n_it = 0
            if os.path.exists(itv):
                for r in csv.DictReader(open(itv)):
                    if os.environ.get("AGAMEMNON_PHYSICAL_IO") \
                       and fam(r["dst_res"]) == "IOMUX" and fam(r["src_res"]) == "RMUX":
                        _z = int(r["dst_res"][5:])
                        _want = _PHYS_PAD_TERM.get((int(r["dst_x"]), int(r["dst_y"]), _z))
                        if _want and r["src_res"] not in _want:
                            continue
                    # Same rule as the pad-feed rows above: a supplemental edge
                    # that ignores the blacklist lets a forced pad chain escape
                    # through an unintended terminal while the build looks obeyed.
                    if _blacklisted(r):
                        continue
                    s = W(r["src_x"], r["src_y"], r["src_res"]); t = W(r["dst_x"], r["dst_y"], r["dst_res"])
                    if s not in wireset or t not in wireset:
                        continue
                    nm = "%s.%s" % (s, t)
                    if nm in seen_pip:
                        continue
                    ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                               delay=_wire_delay(r["src_res"]), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                    seen_pip.add(nm); n_it += 1
                print("AGRV2K arch: added %d vendor IOTILE RMUX->IOMUX terminal pip(s)" % n_it)

            # Exact top-edge pad-input entry pips.  Most characterized rows
            # also happen to occur in the broad route corpus, but that is not
            # guaranteed: PIN_12's vendor oracle has the observed
            # InputMUX07@(20,13) -> RMUX56@(20,12) edge only in the dedicated
            # physical-input table.  The selector emitter already consumes
            # that same row, so omitting its topology left a configured but
            # disconnected input BEL.  Add each table row literally and let
            # seen_pip collapse rows already present in the general graph.
            _top_input_path = os.path.join(DATA, "pad_input_L48.csv")
            _nti = 0
            if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_top_input_path):
                for _r in csv.DictReader(open(_top_input_path)):
                    _sr = "InputMUX%02d" % int(_r["inputmux"])
                    _dr = "RMUX%02d" % int(_r["dst_rmux"])
                    _s = W(_r["pad_x"], _r["pad_y"], _sr)
                    _t = W(_r["dst_x"], _r["dst_y"], _dr)
                    _nm = "%s.%s" % (_s, _t)
                    if _s not in wireset or _t not in wireset or _nm in seen_pip:
                        continue
                    if _blacklisted({
                            "src_res": _sr, "src_x": _r["pad_x"], "src_y": _r["pad_y"],
                            "dst_res": _dr, "dst_x": _r["dst_x"], "dst_y": _r["dst_y"],
                    }):
                        continue
                    ctx.addPip(name=_nm, type="PADIN", srcWire=_s, dstWire=_t,
                               delay=_wire_delay(_sr),
                               loc=Loc(int(_r["dst_x"]), int(_r["dst_y"]), 0))
                    seen_pip.add(_nm); _nti += 1
                print("AGRV2K arch: added %d exact top-edge input-entry pip(s)" % _nti)

            # Complete vendor-routed left-bank corridors.  The broad route corpus did
            # not yet include every pintest5 hop, so a strict graph could reach the
            # correct pad feeder over a different, selector-clean but nonconducting
            # path.  These are literal consecutive nodes from that vendor route; the
            # block-clean selector table independently carries every configurable
            # upstream codeword, while PADFEED_EXACT handles the final IOTILE fields.
            _lp = os.path.join(DATA, "padout_L48_left_corridors.csv")
            _nlp = 0
            _left_exact = [
                _lp,
                os.path.join(DATA, "pad_oe_L48_left_corridors.csv"),
                os.path.join(DATA, "pad_input_L48_left_corridors.csv"),
            ]
            if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
                for _left_path in _left_exact:
                    if not os.path.exists(_left_path):
                        continue
                    for _r in csv.DictReader(open(_left_path)):
                        _s, _t = _r["src_wire"], _r["dst_wire"]
                        _nm = "%s.%s" % (_s, _t)
                        if _s not in wireset or _t not in wireset or _nm in seen_pip:
                            continue
                        _sm = re.match(r"X(\d+)Y(\d+)_(.+)", _s)
                        _dm0 = re.match(r"X(\d+)Y(\d+)_(.+)", _t)
                        if _sm and _dm0 and _blacklisted({
                            "src_res": _sm.group(3), "src_x": _sm.group(1), "src_y": _sm.group(2),
                            "dst_res": _dm0.group(3), "dst_x": _dm0.group(1), "dst_y": _dm0.group(2),
                        }):
                            continue
                        _dm = re.match(r"X(\d+)Y(\d+)_", _t)
                        if not _dm:
                            continue
                        ctx.addPip(name=_nm, type="PADOUT", srcWire=_s, dstWire=_t,
                                   delay=_wire_delay(_s.rsplit("_", 1)[-1]),
                                   loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                        seen_pip.add(_nm); _nlp += 1
                    print("AGRV2K arch: added %d exact left-bank corridor pip(s)" % _nlp)

        shared.update({
            "edge_blacklist": EDGE_BLACKLIST,
            "is_blacklisted": _blacklisted,
            "is_blacklisted_wires": _blacklisted_wires,
            "is_edge_blacklisted_wires": _edge_blacklisted_wires,
            "seen_pips": seen_pip,
            "wire_delay": _wire_delay,
            "pad_resource": _padres,
            "bram_coverage_only": BRAM_COV_ONLY,
            "bram_resolver": _BRES,
            "bram_resolvable": _bram_resolvable,
            "outside_bram_corridor": _outside_bram_corridor,
            "bram_final_destinations": _BRAM_FINAL_DST,
            "bram_final_edges": _BRAM_FINAL_OK,
        })
        return n_pip

    def load_selector_tables(self, chipdb_root, options):
        return RoutingSelectorTables.load(chipdb_root, options)

    @staticmethod
    def load_cell_map(chipdb_root=None):
        """Load the shared logic-tile selector map and its mux-group index."""
        return SB.load_pips(chipdb_root)

    @staticmethod
    def load_mcu_cells(chipdb_root):
        """Load configurable MCU-edge BBMUX and InputMUX selector cells."""
        cells = {}
        with (chipdb_root / "pips_mcuedge.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            for row in csv.DictReader(stream):
                mux = row["mux"]
                if not mux.startswith(("BBMUXS", "BBMUXE", "BBMUXW", "InputMUX")):
                    continue
                key = (
                    int(row["x"]), int(row["y"]), mux, int(row["sel_index"]),
                )
                cells[key] = (int(row["byte"]), int(row["mask"]))
        return cells

    def prepare(
        self, *, pips, cell, options, tables, physical_io_state, exact_mcu_pips,
        mcu_cells, mcu_exit_pairs, bram_feature, bram_state, slice_config,
        left_vendor_slices,
    ):
        state = RoutingState()
        state.admission_binding = tables.admission_binding
        general = collections.defaultdict(list)
        debug = bool(os.environ.get("AGAMEMNON_DEBUG"))
        mesh_template = options.enabled("AGAMEMNON_MESH_TEMPLATE")
        admitted_edges = tables.admitted_edge
        admitted_owner_use = {}
        admitted_set_bits = collections.Counter()
        admitted_clear_bits = collections.Counter()
        # Declared here (rather than just before the second, `general`-grouped
        # loop below) because the MCU/InputMUX-entry branch inside THIS loop
        # also resolves edges from clean_edge/relative_edge/a blind formula and
        # has to feed the same tallies -- see the 2026-08-21 fix note at
        # ``_mcu_entry_pair`` for why an untallied branch is how a wrong
        # codeword got silently reported as "0 predicted".
        exact_groups = clean_count = relative_count = absolute_count = 0
        provenance = collections.Counter()

        for pip in pips:
            source_text, destination_text = pip.split(".", 1)
            source, destination = parse_wire(source_text), parse_wire(destination_text)
            if not source or not destination:
                continue
            sx, sy, sf, si = source
            dx, dy, df, di = destination
            edge = source + destination
            if sf.startswith("CARRY") or df.startswith("CARRY"):
                continue
            admitted = admitted_edges.get((dx, dy, df, di, sf, sx, sy, si))
            if admitted is not None:
                encoding = admitted["encoding"]
                owner = (
                    encoding["owner_x"], encoding["owner_y"], encoding["cfg"]
                )
                prior = admitted_owner_use.setdefault(owner, admitted["edge_id"])
                if prior != admitted["edge_id"]:
                    raise SystemExit(
                        "experimental routing composition uses multiple rows in owner "
                        "%s: %s, %s" % (owner, prior, admitted["edge_id"])
                    )
                set_entries = routing_admission.emission_entries(admitted)
                clear_entries = routing_admission.clearing_entries(admitted)
                missing = [
                    entry for entry in set_entries + clear_entries if entry not in cell
                ]
                if missing:
                    raise SystemExit(
                        "experimental routing admission has no physical cell(s) for %s: %s"
                        % (admitted["edge_id"], missing)
                    )
                state.clears.extend(cell[entry] for entry in clear_entries)
                state.sets.extend(cell[entry] for entry in set_entries)
                admitted_clear_bits.update(cell[entry] for entry in clear_entries)
                admitted_set_bits.update(cell[entry] for entry in set_entries)
                state.mapped += 1
                continue
            if edge in physical_io_state.physical_fixed_pip:
                state.mapped += 1
                continue
            physical_oe = physical_io_state.physical_oe_pip.get(edge)
            if physical_oe is not None:
                cx, cy, cfg, selections, clear_scope = physical_oe
                field_map = physical_io_state.io_cells.get((cx, cy, cfg), {})
                if clear_scope == "selector_group":
                    groups = {selection // 7 for selection in selections}
                    if len(groups) != 1:
                        raise SystemExit(
                            "physical OE %s%s at (%d,%d) must name one nonempty "
                            "seven-selector group, got %s" %
                            (cfg, selections, cx, cy, sorted(groups))
                        )
                    group = next(iter(groups))
                    field = [bit for selection, bit in field_map.items()
                             if selection // 7 == group]
                else:
                    field = list(field_map.values())
                bits = [field_map.get(selection) for selection in selections]
                if not field or any(bit is None for bit in bits):
                    state.unmapped += 1
                    if debug:
                        print("  UNMAPPED[physical-oe] %s%d <- %s%d @(%d,%d): %s%s" %
                              (df, di, sf, si, dx, dy, cfg, selections))
                else:
                    state.clears.extend(field)
                    state.sets.extend(bits)
                    state.mapped += 1
                continue

            exact = exact_mcu_pips.get(edge)
            if exact is not None:
                table, cfg, clear_selections, set_selections = exact
                if table == "io":
                    # IOTILE terminal hops resolve through the CFG_IOMUX cell
                    # map; its selector index is the codeword's inner key.
                    lookup = {
                        (dx, dy, cfg, selection): bit
                        for selection, bit in physical_io_state.io_cells.get(
                            (dx, dy, cfg), {}
                        ).items()
                    }
                else:
                    lookup = mcu_cells if table == "mcu" else cell
                missing = []
                resolved_clears = []
                resolved_sets = []
                for selection in clear_selections:
                    bit = lookup.get((dx, dy, cfg, selection))
                    if bit is None:
                        missing.append(("clear", selection))
                    else:
                        resolved_clears.append(bit)
                for selection in set_selections:
                    bit = lookup.get((dx, dy, cfg, selection))
                    if bit is None:
                        missing.append(("set", selection))
                    else:
                        resolved_sets.append(bit)
                # Commit the codeword only once it is COMPLETE. Appending the
                # part that resolved and then reporting the edge unmapped still
                # wrote a partial exact-corridor codeword whenever the unmapped
                # gate was relaxed with AGAMEMNON_ALLOW_UNMAPPED.
                if not missing:
                    state.clears.extend(resolved_clears)
                    state.sets.extend(resolved_sets)
                if missing:
                    state.unmapped += 1
                    if debug:
                        print("  UNMAPPED[exact-ahb32] %s%d <- %s%d @(%d,%d): %s" %
                              (df, di, sf, si, dx, dy, missing))
                else:
                    state.mapped += 1
                continue

            if sf == "OMUX" and si % 3 != 2:
                # The slice has to PRESENT its output on this OMUX index or the
                # wire the route starts from is undriven. Dropping the
                # presentation selector silently left the rest of the chain
                # perfectly configured around a dead source.
                state.sets.extend(resolve_selector_cells(
                    cell, [(sx, sy, "CFG_OMUX%d" % (si // 3), si % 3)],
                    "pips_full.csv",
                    "OMUX%d presentation for the route out of X%dY%d" % (si, sx, sy),
                ))
            bram_mapped = bram_feature.resolve_route(
                bram_state, source, destination, cell, NPG, state.sets,
                route_clears=state.clears, debug=debug
            )
            if bram_mapped is not None:
                if bram_mapped:
                    state.mapped += 1
                else:
                    state.unmapped += 1
                continue

            if df in ("BBMUXS", "BBMUXE", "BBMUXW"):
                pair = mcu_exit_pairs.get((dx, dy, df, di, sx, sy, sf, si))
                if pair is None and sf == "RMUX":
                    # The source-keyed fallback is withdrawn for any source whose
                    # codeword is shared with another source (see
                    # _ambiguous_boundary_sources): the word we would write does
                    # not identify this input, and a wrong boundary terminal
                    # config-accepts silently. Falling through to `unmapped` puts
                    # it on the existing refuse-to-emit path with a named
                    # diagnostic instead.
                    _ambiguous = tables.ambiguous_boundary
                    if df == "BBMUXS" and si not in _ambiguous.get("BBMUXS", ()):
                        pair = BBMUXS_PAIR.get(si)
                    elif df == "BBMUXE" and si not in _ambiguous.get("BBMUXE", ()):
                        pair = BBMUXE_PAIR.get(si)
                    elif debug:
                        print("  AMBIGUOUS[bbmux-fallback] %s%d <- %s%d @(%d,%d): "
                              "codeword is shared with another source index"
                              % (df, di, sf, si, dx, dy))
                if pair is None:
                    state.unmapped += 1
                    if debug:
                        print("  UNMAPPED[bbmux] %s%d <- %s%d @(%d,%d)" %
                              (df, di, sf, si, dx, dy))
                    continue
                mux_name = "%s%d" % (df, di)
                state.clears.extend(
                    bit for (x, y, mux, _selection), bit in mcu_cells.items()
                    if (x, y, mux) == (dx, dy, mux_name)
                )
                resolved = [
                    mcu_cells.get((dx, dy, mux_name, selection))
                    for selection in pair
                ]
                found = sum(1 for bit in resolved if bit)
                # Only a complete boundary-terminal codeword is written. The
                # partial one used to be appended before the completeness test
                # decided the edge was unmapped.
                if found == len(pair):
                    state.sets.extend(resolved)
                    state.mapped += 1
                else:
                    state.unmapped += 1
                    if debug:
                        print("  UNMAPPED[bbmux-nosel] %s%d <- %s%d @(%d,%d)" %
                              (df, di, sf, si, dx, dy))
                continue

            if sf == "InputMUX" and df == "RMUX" and (sy in (0, 13) or sx == 0):
                pad_key = (sx, sy, si, dx, dy, di)
                pad_input = physical_io_state.pad_input_edge.get(pad_key)
                if pad_input is None:
                    if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
                        raise SystemExit(
                            "perimeter pad-input route has no silicon-verified encoding: %s" %
                            (pad_key,)
                        )
                    physical_io_state.pad_input_used.add((pad_key, ((97, 64),), ()))
                else:
                    cfg, selections, set_bits, clear_bits = pad_input
                    found = 0
                    for selection in selections:
                        bit = cell.get((dx, dy, cfg, selection))
                        if bit:
                            state.sets.append(bit)
                            found += 1
                    if found != len(selections):
                        raise SystemExit(
                            "pad-input config cells missing for %s: %s%s" %
                            (pad_key, cfg, selections)
                        )
                    physical_io_state.pad_input_used.add(
                        (pad_key, tuple(set_bits), tuple(clear_bits))
                    )
                    state.mapped += 1
                    continue

            if sf == "InputMUX" and df == "RMUX" and not (sy in (0, 13) or sx == 0):
                edge_key = (dx, dy, "RMUX", di, "InputMUX", sx, sy, si)
                relative_key = ("RMUX", di, "InputMUX", si, dx - sx, dy - sy)
                clean_pair = None if tables.archival_legacy else tables.clean_edge.get(edge_key)
                relative_pair = (
                    None if (tables.archival_legacy or clean_pair is not None)
                    else tables.relative_edge.get(relative_key)
                )
                entries, source_class, predicted = _resolve_mcu_inputmux_entry(
                    dx=dx, dy=dy, di=di, sx=sx,
                    clean_pair=clean_pair, relative_pair=relative_pair,
                    label="%s%d <- %s%d @(%d,%d)" % (df, di, sf, si, dx, dy),
                    sy=sy, si=si,
                )
                if source_class == "conflict-free-physical-observation":
                    clean_count += 1
                elif source_class == "unanimous-relative-observation":
                    relative_count += 1
                elif predicted:
                    # Evidenced ONLY for InputMUX-at-x13 -> RMUX; see
                    # _mcu_entry_pair's docstring. state.predicted is
                    # incremented here (and only here) so a build that
                    # silently relies on the blind formula shows up in the "N
                    # predicted" summary instead of reading as fully exact --
                    # the exact bug that let three wrong pips through as
                    # "0 predicted".
                    state.predicted += 1
                    if debug:
                        print("  PREDICTED[MCU/InputMUX] %s%d <- %s%d @(%d,%d) via %s" %
                              (df, di, sf, si, dx, dy, source_class))
                provenance[source_class] += 1
                # ``if found:`` accepted one bit of a two-bit entry codeword and
                # reported the edge mapped.
                state.sets.extend(resolve_selector_cells(
                    cell, [(dx, dy, cfg, selection) for cfg, selection in entries],
                    "pips_full.csv",
                    "MCU/InputMUX entry %s%d <- %s%d @(%d,%d)" % (df, di, sf, si, dx, dy),
                ))
                state.mapped += 1
                continue

            if sf == "OMUX" and df == "OMUX" and (sx, sy) == (dx, dy) and di == si - 1:
                bit = cell.get((dx, dy, "CFG_OMUX%d" % (di // 3), 1))
                if bit:
                    state.sets.append(bit)
                    state.mapped += 1
                else:
                    state.unmapped += 1
                continue
            if (sf == "OMUX" and df == "OMUX" and (sx, sy) == (dx, dy) and
                    si % 3 == 2 and di == si - 2):
                bit = cell.get((dx, dy, "CFG_OMUX%d" % (di // 3), 0))
                if bit:
                    state.sets.append(bit)
                    state.mapped += 1
                else:
                    state.unmapped += 1
                continue
            if (sf == "OMUX" and df == "IMUX" and (sx, sy) == (dx, dy) and
                    di % 4 == 2 and
                    (si == 3 * (di // 4) + 2 or
                     ((sx, sy, di // 4) in left_vendor_slices and si == 3 * (di // 4) + 1))):
                z = di // 4
                bit = slice_config.get((dx, dy, "CFG_LUTCMUX[%d]" % (2 * z)))
                if bit:
                    state.sets.append(bit)
                    state.mapped += 1
                else:
                    state.unmapped += 1
                    if debug:
                        print("  legacy QINFB replay has no LUTCMUX bit for slice z=%d @(%d,%d)" %
                              (z, dx, dy))
                continue
            if (sf == "OMUX" and df == "IMUX" and (sx, sy) == (dx, dy) and
                    si % 3 == 1 and di == 4 * (si // 3) + 3):
                z = di // 4
                selections = MT.resolve("IMUX", di, "OMUX", si, 0, 0)
                mapped = [] if selections is None else [
                    cell.get((dx, dy, "CFG_IMUX%d" % z, selection))
                    for selection in selections
                ]
                mode = slice_config.get((dx, dy, "CFG_LUTCMUX[%d]" % (2 * z)))
                if mapped and all(mapped) and mode:
                    state.sets.extend(mapped)
                    state.sets.append(mode)
                    state.mapped += 1
                else:
                    state.unmapped += 1
                    if debug:
                        print("  DIRECT_D_FB no complete IMUX selector for slice z=%d @(%d,%d)" %
                              (z, dx, dy))
                continue
            if df in NOCFG:
                continue
            padfeed_key = (dx, dy, di, sx, sy, sf, si)
            if df == "RMUX" and padfeed_key in physical_io_state.padfeed_unowned:
                # The row exists (so this branch is taken and the general
                # selector path below is skipped) but carries no codeword, and
                # no other table encodes the hop either. Emitting the empty
                # codeword and counting the edge MAPPED put it past the unmapped
                # gate with zero configuration written: a config-accepted image
                # (FCB 0x000f0002) whose pin is static.
                raise SystemExit(
                    "pad-feed hop %s%d <- %s%d @(%d,%d) is named in "
                    "padfeed_L48_*.csv but has no harvested codeword there, no "
                    "iomux_hop_vendor.csv record and no left-edge companion "
                    "field. Emitting nothing gives a config-accepted image with "
                    "a STATIC pin, so this fails closed instead. Harvest the "
                    "hop codeword for this pad slot from a vendor build first."
                    % (df, di, sf, si, dx, dy)
                )
            if df == "RMUX" and padfeed_key in physical_io_state.padfeed_exact:
                state.sets.extend(tuple(bit) for bit in physical_io_state.padfeed_exact[padfeed_key])
                state.mapped += 1
                if debug:
                    print("  PADFEED %s%d@(%d,%d) <- %s%d : %d codeword bit(s)" %
                          (df, di, dx, dy, sf, si,
                           len(physical_io_state.padfeed_exact[padfeed_key])))
                continue
            if df == "IOMUX" and (dx, dy, di) in physical_io_state.io_pad_hops:
                state.mapped += 1
                continue
            if df not in BS:
                state.unmapped += 1
                if debug:
                    print("  UNMAPPED[df-not-in-BS] %s%d <- %s%d @(%d,%d)" %
                          (df, di, sf, si, dx, dy))
                continue
            general[(dx, dy, "CFG_%s%d" % (df, di // NPG[df]), df)].append(
                (di, sf, sx, sy, si)
            )

        closed_form_count = 0
        # Under the tiered admission model the architecture may offer edges whose
        # codeword comes from a byte-exact closed form rather than a per-edge
        # observation (see docs/ROUTING_ADMISSION.md). Emission has to recognise
        # the same class or the graph and the emitter disagree and the build dies
        # at the selector gate on an edge the graph deliberately admitted. The
        # branch is placed after every observation-backed source (clean, relative,
        # conflicted, corpus-majority) and before the predictors, so it can only
        # rescue an edge that would otherwise have been counted `predicted` -- no
        # already-resolving edge changes value, and no existing artifact can shift
        # a byte. It is also inert unless the tiered model is selected.
        closed_form_ok = options.raw("AGAMEMNON_ROUTING_ADMISSION") == "tiered"
        for (dx, dy, cfg, df), edges in general.items():
            all_block_clean = not tables.archival_legacy and all(
                ((dx, dy, df, di, sf, sx, sy, si) in tables.clean_edge or
                 (df, di, sf, si, dx - sx, dy - sy) in tables.relative_edge)
                for di, sf, sx, sy, si in edges
            )
            if not all_block_clean:
                tables.ensure_legacy()
            group = None if all_block_clean else tables.group_context.get(
                (dx, dy, cfg, frozenset(edges))
            )
            if group is not None:
                # This group codeword covers EVERY edge into the config group at
                # once and then reports all of them mapped. Dropping one cell
                # therefore mis-encoded a whole group while the count still said
                # the group resolved exactly.
                state.sets.extend(resolve_selector_cells(
                    cell, [(dx, dy, cfg, selection) for selection in group],
                    "pips_full.csv",
                    "vendor-corpus context group %s @(%d,%d)" % (cfg, dx, dy),
                ))
                state.mapped += len(edges)
                exact_groups += 1
                provenance["vendor-corpus-context-majority"] += len(edges)
                continue
            for di, sf, sx, sy, si in edges:
                block = BS[df] * (di % NPG[df])
                edge_key = (dx, dy, df, di, sf, sx, sy, si)
                relative_key = (df, di, sf, si, dx - sx, dy - sy)
                pair = None if tables.archival_legacy else tables.clean_edge.get(edge_key)
                if pair is not None:
                    clean_count += 1
                    source_class = "conflict-free-physical-observation"
                else:
                    pair = None if tables.archival_legacy else tables.relative_edge.get(relative_key)
                    if pair is not None:
                        relative_count += 1
                        source_class = "unanimous-relative-observation"
                    else:
                        conflict = tables.conflicted_edge.get(edge_key)
                        if conflict is not None:
                            pair = conflict[0]
                            source_class = "vendor-corpus-conflicted-majority"
                        else:
                            pair = tables.absolute.get(edge_key)
                        if pair is not None:
                            if conflict is None:
                                absolute_count += 1
                                source_class = "vendor-corpus-absolute-majority"
                if pair is None and closed_form_ok:
                    local = routing_tiers.closed_form_selector(
                        df, di, sf, si, dx - sx, dy - sy)
                    if local is not None and routing_tiers.closed_form_is_legal_fanin(
                            df, di, local):
                        pair = local
                        source_class = routing_tiers.BASIS_CLOSED_FORM
                        closed_form_count += 1
                if pair is None and mesh_template:
                    resolved = MT.resolve(df, di, sf, si, dx - sx, dy - sy)
                    if resolved is not None:
                        pair = resolved[0] - block, resolved[1] - block
                        source_class = "decoded-mesh-template-prediction"
                if pair is None:
                    pair = SB.predict_pair(df, sf, di, si, dx - sx, dy - sy, tables.lut)
                    if pair is not None:
                        source_class = "trained-selector-prediction"
                if pair is None and df == "IMUX" and sf == "RMUX" and dx == sx and dy == sy:
                    index = (si // 6 + 11) % 27
                    pair = index % 9, 9 + index // 9
                    source_class = "decoded-crossbar-closed-form"
                if pair is None and df == "RMUX" and sf == "RMUX":
                    high = tables.dir_bank.get((dx - sx, dy - sy))
                    low = tables.geom_rmux.get((si, dx - sx, dy - sy))
                    if high is not None and low is not None:
                        pair = low, high
                        source_class = "vendor-corpus-geometric-majority"
                if pair is None:
                    state.unmapped += 1
                    provenance["unresolved"] += 1
                    if debug:
                        print("  UNMAPPED %s%d <- %s%d  d=(%d,%d)" %
                              (df, di, sf, si, dx - sx, dy - sy))
                    continue
                if (edge_key not in tables.clean_edge and
                        relative_key not in tables.relative_edge and
                        edge_key not in tables.absolute and
                        source_class != routing_tiers.BASIS_CLOSED_FORM):
                    state.predicted += 1
                    if debug:
                        print("  PREDICTED %s%d <- %s%d @(%d,%d) d=(%d,%d) via %s" %
                              (df, di, sf, si, dx, dy, dx - sx, dy - sy,
                               source_class))
                provenance[source_class] += 1
                # The hot path for ordinary RTL. ``if found:`` called a half
                # codeword mapped, and found==0 fell through counting NOTHING,
                # so an edge with no cells at all bypassed the unmapped gate.
                state.sets.extend(resolve_selector_cells(
                    cell,
                    [(dx, dy, cfg, block + local_selection)
                     for local_selection in pair],
                    "pips_full.csv",
                    "%s%d@(%d,%d) <- %s%d@(%d,%d) via %s" %
                    (df, di, dx, dy, sf, si, sx, sy, source_class),
                ))
                state.mapped += 1

        if admitted_owner_use:
            bit_owners = collections.defaultdict(set)
            for (x, y, cfg, _selection), bit in cell.items():
                bit_owners[bit].add((x, y, cfg))
            other_bits = (
                collections.Counter(state.sets) - admitted_set_bits
            ) + (collections.Counter(state.clears) - admitted_clear_bits)
            collisions = sorted({
                owner
                for bit in other_bits
                for owner in bit_owners.get(bit, ())
                if owner in admitted_owner_use
            })
            if collisions:
                raise SystemExit(
                    "experimental routing composition reuses admitted owner field(s): %s"
                    % collisions
                )

        # The closed-form field is appended only when it is non-zero. Two qualified
        # source-to-image replay tests, the SERV evidence gate's regen script, five
        # qualification/audit_*.py scripts and several AG32-Docs oracle builders all
        # match this line as a literal or a regex anchored on "legacy-abs, N
        # predicted), N unmapped". A field that is always present but almost always
        # zero would break every one of them to convey nothing; it appears exactly
        # when it has something to report, and then breaking a strict-replay parse
        # is the correct, loud outcome.
        _closed_form_note = ("%d closed-form, " % closed_form_count) if closed_form_count else ""
        print("data pips: %d total, %d mapped (%d groups exact, %d block-clean, %d relative-clean, "
              "%d legacy-abs, %s%d predicted), %d unmapped -> %d bits" %
              (len(pips), state.mapped, exact_groups, clean_count, relative_count,
               absolute_count, _closed_form_note, state.predicted, state.unmapped,
               len(state.sets)))
        state.provenance_counts = dict(sorted(provenance.items()))
        if state.unmapped and not options.enabled("AGAMEMNON_ALLOW_UNMAPPED"):
            raise SystemExit(
                "refusing to emit a partial bitstream: %d routed data PIP(s) have no exact encoding; "
                "set AGAMEMNON_DEBUG=1 to identify them" % state.unmapped
            )
        if state.predicted and options.enabled("AGAMEMNON_CLEAN_SEL_GATE"):
            raise SystemExit(
                "refusing to emit a selector-uncertain bitstream: %d routed data PIP(s) "
                "needed a legacy or predicted selector encoding" % state.predicted
            )
        return state

    def clear_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.clears:
            if byte < len(context.image):
                context.image[byte] &= (~mask) & 0xFF
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "PIP")
                count += 1
        return count

    def writable_bits(self, state):
        return set(state.clears) | set(state.sets)

    def delegate_bits(self, state, owner_bits):
        """Remove coherent set masks already owned by another feature."""
        owner_masks = collections.defaultdict(int)
        for byte, mask in owner_bits:
            owner_masks[byte] |= mask
        before = len(state.sets)
        delegated = []
        for byte, mask in state.sets:
            remaining = mask & (~owner_masks.get(byte, 0) & 0xFF)
            if remaining:
                delegated.append((byte, remaining))
        state.sets = delegated
        return before - len(state.sets)

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "PIP")
                count += 1
        return count


FEATURE = RoutingFeature()
