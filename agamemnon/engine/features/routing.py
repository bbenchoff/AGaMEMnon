"""General data-routing selector loading, resolution, and emission."""

from __future__ import annotations

import collections
import csv
import json
import os
from dataclasses import dataclass, field

from agamemnon.engine import chipdb_schema
from agamemnon.engine import mesh_template as MT
from agamemnon.engine import routing_selectors
from agamemnon.engine import sel_byteexact as SB

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


@dataclass
class RoutingSelectorTables:
    chipdb_root: object
    archival_legacy: bool
    dir_bank: dict
    clean_edge: dict
    relative_edge: dict
    lut: object
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
        return cls(
            chipdb_root=chipdb_root,
            archival_legacy=options.enabled("AGAMEMNON_ALLOW_UNMAPPED"),
            dir_bank=dir_bank,
            clean_edge=clean_edge,
            relative_edge=relative_edge,
            lut=SB.train_lut("__none__"),
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
        ),
        chipdb_files=(
            "pips_full.csv", "pips_mcuedge.csv", "sel_map.json",
            "sel_edge_pairs.agdb", "sel_tables.agdb", "train_lut.agdb",
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
        architecture="General routing graph construction remains in arch.py until A-arch.",
        bitstream=(
            "Resolve complete routed edge groups through exact physical, unanimous-relative, "
            "context, template, and predictive selector sources; fail closed when required."
        ),
    )

    def add_architecture(self, context):
        return None

    def load_selector_tables(self, chipdb_root, options):
        return RoutingSelectorTables.load(chipdb_root, options)

    @staticmethod
    def load_cell_map():
        """Load the shared logic-tile selector map and its mux-group index."""
        return SB.load_pips()

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
        general = collections.defaultdict(list)
        debug = bool(os.environ.get("AGAMEMNON_DEBUG"))
        mesh_template = options.enabled("AGAMEMNON_MESH_TEMPLATE")

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
                continue
            for di, sf, sx, sy, si in edges:
                block = BS[df] * (di % NPG[df])
                edge_key = (dx, dy, df, di, sf, sx, sy, si)
                relative_key = (df, di, sf, si, dx - sx, dy - sy)
                pair = None if tables.archival_legacy else tables.clean_edge.get(edge_key)
                if pair is not None:
                    clean_count += 1
                else:
                    pair = None if tables.archival_legacy else tables.relative_edge.get(relative_key)
                    if pair is not None:
                        relative_count += 1
                    else:
                        pair = tables.absolute.get(edge_key)
                        if pair is not None:
                            absolute_count += 1
                if pair is None and mesh_template:
                    resolved = MT.resolve(df, di, sf, si, dx - sx, dy - sy)
                    if resolved is not None:
                        pair = resolved[0] - block, resolved[1] - block
                if pair is None:
                    pair = SB.predict_pair(df, sf, di, si, dx - sx, dy - sy, tables.lut)
                if pair is None and df == "IMUX" and sf == "RMUX" and dx == sx and dy == sy:
                    index = (si // 6 + 11) % 27
                    pair = index % 9, 9 + index // 9
                if pair is None and df == "RMUX" and sf == "RMUX":
                    high = tables.dir_bank.get((dx - sx, dy - sy))
                    low = tables.geom_rmux.get((si, dx - sx, dy - sy))
                    if high is not None and low is not None:
                        pair = low, high
                if pair is None:
                    state.unmapped += 1
                    if debug:
                        print("  UNMAPPED %s%d <- %s%d  d=(%d,%d)" %
                              (df, di, sf, si, dx - sx, dy - sy))
                    continue
                if (edge_key not in tables.clean_edge and
                        relative_key not in tables.relative_edge and
                        edge_key not in tables.absolute):
                    state.predicted += 1
                found = 0
                for local_selection in pair:
                    bit = cell.get((dx, dy, cfg, block + local_selection))
                    if bit:
                        state.sets.append(bit)
                        found += 1
                if found:
                    state.mapped += 1

        print("data pips: %d total, %d mapped (%d groups exact, %d block-clean, %d relative-clean, "
              "%d legacy-abs, %d predicted), %d unmapped -> %d bits" %
              (len(pips), state.mapped, exact_groups, clean_count, relative_count,
               absolute_count, state.predicted, state.unmapped, len(state.sets)))
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
        """Remove coherent duplicate sets already owned by another feature."""
        owner_bits = set(owner_bits)
        before = len(state.sets)
        state.sets = [bit for bit in state.sets if bit not in owner_bits]
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
