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
from agamemnon.engine import sel_byteexact as SB
from agamemnon.engine import wire_timing

from .physical_io import parse_wire
from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


NPG = {"RMUX": 6, "IMUX": 4, "OMUX": 3}
BS = {"RMUX": 10, "IMUX": 12}
NOCFG = ("BufMUX", "InputMUX", "SinkMUXPseudo")
BBMUXS_PAIR = {
    2: (1, 4), 9: (1, 5), 19: (1, 6), 25: (0, 4), 32: (0, 5),
    39: (0, 6), 55: (3, 4), 62: (3, 5), 69: (3, 6), 92: (2, 6),
}
BBMUXE_PAIR = {
    93: (3, 6), 26: (1, 4), 20: (2, 6), 49: (0, 4), 56: (0, 5),
    33: (1, 5), 63: (0, 6), 79: (3, 4), 86: (3, 5), 13: (2, 5),
    3: (1, 6), 43: (0, 6), 25: (0, 4), 92: (2, 6),
}
MCU_ENTRY = {
    (14, 10, 14): [("CFG_RMUX2", 22), ("CFG_RMUX2", 28)],
    (14, 12, 73): [("CFG_RMUX12", 12), ("CFG_RMUX12", 18)],
    (14, 12, 21): [("CFG_RMUX3", 32), ("CFG_RMUX3", 38)],
}


def _add_admitted_iotile_pips(*, ctx, Loc, wire_name, wireset, seen_pip,
                               rows, delay_for):
    """Add only the exact IOTILE pips supplied by authenticated rows."""
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
        if edge_file.exists():
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
    block = BS["RMUX"] * (destination_index % NPG["RMUX"])
    return "CFG_RMUX%d" % (destination_index // NPG["RMUX"]), (block + 3, block + 9)


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
            "wire_timing_exact_safe_manifest.json", "wires.csv", "pip_usage.csv",
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
        _dead_csv = os.path.join(DATA, "dead_edges_silicon.csv")
        if os.path.exists(_dead_csv):
            for _dead_row in csv.DictReader(open(_dead_csv)):
                _match = re.fullmatch(_dead_edge_re, _dead_row.get("edge", "").strip())
                if not _match:
                    raise ValueError("malformed silicon-dead edge: %r" % _dead_row)
                EDGE_BLACKLIST.add(_match.groups())
        if EDGE_BLACKLIST:
            print("AGRV2K arch: SILICON-DEAD EDGE BLACKLIST active (%d edge(s)): %s"
                  % (len(EDGE_BLACKLIST), sorted(EDGE_BLACKLIST)))
        def _blacklisted(r):
            return (r["src_res"], r["src_x"], r["src_y"],
                    r["dst_res"], r["dst_x"], r["dst_y"]) in EDGE_BLACKLIST

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
        _dead_positive_conflicts = CONDUCT.intersection(EDGE_BLACKLIST)
        if _dead_positive_conflicts:
            print("AGRV2K arch: negative evidence overrides %d conflicting positive edge(s)"
                  % len(_dead_positive_conflicts))
            CONDUCT.difference_update(EDGE_BLACKLIST)
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
        STRICT_GATE = bool(os.environ.get("AGAMEMNON_STRICT_GATE"))
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
        def _wire_delay_ns(resource):
            family = fam(resource)
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
            if df not in ("RMUX", "IMUX") or sf not in ("RMUX", "OMUX"):
                return True
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
                # SEPARATELY (global-clock nets + GCLK_SRC/GCLK_TAP pips in section 3b; bitgen emits
                # CFG_SEAMMUX/CFG_TILECLKMUX independently), so dropping these here does NOT remove the clock
                # model -- the slice CLK wire (ClkMUX%02d) is still reached via the GCLK_TAP pips.
                if any(fam(r[k]).endswith(("CtrlMUX", "TileSyncMUX", "TileAsyncMUX",
                                           "AsyncMUX", "ClkMUX", "SeamMUX")) for k in ("src_res", "dst_res")):
                    skipped += 1; continue
                # MCU-edge crossing muxes (BBMUXS/W/E) reachable ONLY via the encodable pips in
                # pips_mcuedge_routing.csv (RMUX19->BBMUXS02) or a source="observed" RRG row (a real
                # af.exe route hop, e.g. the wide_boundary_witness feeder bank): drop harvested
                # (enumerated-guess) BBMUX fan-in so the router can't pick an RMUX->BBMUX whose
                # sel-encoding we don't have (autonomous route must stay encodable). An observed row's
                # selector may still be unresolved (no exact mcu_exit_pairs tuple and no BBMUXE_PAIR/
                # BBMUXS_PAIR fallback hit); prepare() then reports it unmapped and bitgen fails closed
                # -- it is never silently mis-encoded.
                if fam(r["dst_res"]).startswith("BBMUX") and r.get("source") != "observed":
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
                if TRUSTED and not is_trusted(r, fn):
                    dropped_enum += 1; continue
                s = W(r["src_x"], r["src_y"], r["src_res"])
                t = W(r["dst_x"], r["dst_y"], r["dst_res"])
                if s not in wireset or t not in wireset:
                    skipped += 1; continue
                nm = "%s.%s" % (s, t)
                if nm in seen_pip:
                    continue
                ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                           delay=pip_delay(r, fn), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                seen_pip.add(nm); n_pip += 1
        admitted_supplements = _add_admitted_iotile_pips(
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

        # ---- 4b. Dense ripple-register local feedback -----------------------------------------------
        # In ripple mode pinC is occupied by Cin, so a counter bit cannot use the normal Qin/pinC
        # self-feedback path.  The vendor instead presents that slice's Q on OMUX[3z+1] and routes it to
        # the same slice's B input, IMUX[4z+1].  The route is present in the vendor 24-bit counter and the
        # block-clean selector corpus is unanimous at every slice index across all 132 logic tiles.  A few
        # coordinates (including the X1Y1 inter-tile-carry site) were nevertheless absent from the topology
        # union, which made a correctly placed chain unroutable.  Replicate this exact local topology only
        # for hard-carry builds; the ordinary Q presentation bridge below supplies OMUX[3z+1], while the
        # normal bitgen resolver emits the observed IMUX selector pair.
        if os.environ.get("AGAMEMNON_HW_CARRY"):
            _cfd = ctx.getDelayFromNS(0.05)
            n_cf = 0
            for (x, y), tt in tile_type.items():
                if tt != "LogicTILE":
                    continue
                for z in range(16):
                    s = W(x, y, "OMUX%02d" % (3 * z + 1))
                    t = W(x, y, "IMUX%02d" % (4 * z + 1))
                    nm = "%s.%s" % (s, t)
                    if s in wireset and t in wireset and nm not in seen_pip:
                        ctx.addPip(name=nm, type="CARRY_QFB", srcWire=s, dstWire=t,
                                   delay=_cfd, loc=Loc(int(x), int(y), 0))
                        seen_pip.add(nm); n_cf += 1
            print("AGRV2K arch: added %d replicated ripple Q->B feedback pips" % n_cf)

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
                    s = W(x, y, "OMUX%02d" % (3 * z + 2)); t = W(x, y, "OMUX%02d" % (3 * z + 1))
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
                s = W(x, y, "OMUX%02d" % (3*z + 1))
                t = W(x, y, "IMUX%02d" % (4*z + 3))
                nm = "%s.%s" % (s, t)
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
            n_pf = 0
            for _pf_name in ("padfeed_L48_top.csv", "padfeed_L48_left.csv"):
                pf = os.path.join(DATA, _pf_name)
                if not os.path.exists(pf):
                    continue
                for r in csv.DictReader(open(pf)):
                    if _only and (int(r["padtile_x"]), int(r["padtile_y"]), int(r["iomux_z"])) != _only:
                        continue
                    s = W(str(r["src_x"]), str(r["src_y"]), r["src_res"])
                    t = W(str(r["padtile_x"]), str(r["padtile_y"]), "RMUX%02d" % int(r["padfeed_rmux"]))
                    if s not in wireset or t not in wireset:
                        continue
                    nm = "%s.%s" % (s, t)
                    if nm in seen_pip:
                        continue
                    ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                               delay=_wire_delay(r["src_res"]),
                               loc=Loc(int(r["padtile_x"]), int(r["padtile_y"]), 0))
                    seen_pip.add(nm); n_pf += 1
                    # The same vendor record identifies the fixed terminal from the
                    # destination pad-feed RMUX to this package pad's IOMUX slot.
                    u = W(str(r["padtile_x"]), str(r["padtile_y"]),
                          "IOMUX%02d" % int(r["iomux_z"]))
                    tnm = "%s.%s" % (t, u)
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

            # Complete vendor-routed left-bank corridors.  The broad route corpus did
            # not yet include every pintest5 hop, so a strict graph could reach the
            # correct pad feeder over a different, selector-clean but nonconducting
            # path.  These are literal consecutive nodes from that vendor route; the
            # block-clean selector table independently carries every configurable
            # upstream codeword, while PADFEED_EXACT handles the final IOTILE fields.
            _lp = os.path.join(DATA, "padout_L48_left_corridors.csv")
            _nlp = 0
            _left_exact = [_lp, os.path.join(DATA, "pad_oe_L48_left_corridors.csv")]
            if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
                for _left_path in _left_exact:
                    if not os.path.exists(_left_path):
                        continue
                    for _r in csv.DictReader(open(_left_path)):
                        _s, _t = _r["src_wire"], _r["dst_wire"]
                        _nm = "%s.%s" % (_s, _t)
                        if _s not in wireset or _t not in wireset or _nm in seen_pip:
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
                cx, cy, cfg, selections = physical_oe
                field_map = physical_io_state.io_cells.get((cx, cy, cfg), {})
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
                for selection in clear_selections:
                    bit = lookup.get((dx, dy, cfg, selection))
                    if bit is None:
                        missing.append(("clear", selection))
                    else:
                        state.clears.append(bit)
                for selection in set_selections:
                    bit = lookup.get((dx, dy, cfg, selection))
                    if bit is None:
                        missing.append(("set", selection))
                    else:
                        state.sets.append(bit)
                if missing:
                    state.unmapped += 1
                    if debug:
                        print("  UNMAPPED[exact-ahb32] %s%d <- %s%d @(%d,%d): %s" %
                              (df, di, sf, si, dx, dy, missing))
                else:
                    state.mapped += 1
                continue

            if sf == "OMUX" and si % 3 != 2:
                bit = cell.get((sx, sy, "CFG_OMUX%d" % (si // 3), si % 3))
                if bit:
                    state.sets.append(bit)
            bram_mapped = bram_feature.resolve_route(
                bram_state, source, destination, cell, NPG, state.sets, debug=debug
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
                    if df == "BBMUXS":
                        pair = BBMUXS_PAIR.get(si)
                    elif df == "BBMUXE":
                        pair = BBMUXE_PAIR.get(si)
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
                found = 0
                for selection in pair:
                    bit = mcu_cells.get((dx, dy, mux_name, selection))
                    if bit:
                        state.sets.append(bit)
                        found += 1
                if found == len(pair):
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
                pair = None if tables.archival_legacy else tables.clean_edge.get(edge_key)
                if pair is None and not tables.archival_legacy:
                    pair = tables.relative_edge.get(relative_key)
                if pair is not None:
                    block = BS["RMUX"] * (di % NPG["RMUX"])
                    cfg = "CFG_RMUX%d" % (di // NPG["RMUX"])
                    entries = [(cfg, block + selection) for selection in pair]
                else:
                    entries = MCU_ENTRY.get((dx, dy, di))
                    if entries is None:
                        cfg, selections = _mcu_entry_pair(di)
                        entries = [(cfg, selection) for selection in selections]
                found = 0
                for cfg, selection in entries:
                    bit = cell.get((dx, dy, cfg, selection))
                    if bit:
                        state.sets.append(bit)
                        found += 1
                if found:
                    state.mapped += 1
                else:
                    state.unmapped += 1
                    if debug:
                        print("  UNMAPPED[inputmux-entry] %s%d <- %s%d @(%d,%d)" %
                              (df, di, sf, si, dx, dy))
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
            padfeed_key = (dx, di, sx, sy, sf, si)
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

        exact_groups = clean_count = relative_count = absolute_count = 0
        provenance = collections.Counter()
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
                for selection in group:
                    bit = cell.get((dx, dy, cfg, selection))
                    if bit:
                        state.sets.append(bit)
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
                        edge_key not in tables.absolute):
                    state.predicted += 1
                provenance[source_class] += 1
                found = 0
                for local_selection in pair:
                    bit = cell.get((dx, dy, cfg, block + local_selection))
                    if bit:
                        state.sets.append(bit)
                        found += 1
                if found:
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

        print("data pips: %d total, %d mapped (%d groups exact, %d block-clean, %d relative-clean, "
              "%d legacy-abs, %d predicted), %d unmapped -> %d bits" %
              (len(pips), state.mapped, exact_groups, clean_count, relative_count,
               absolute_count, state.predicted, state.unmapped, len(state.sets)))
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
