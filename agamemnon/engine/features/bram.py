"""BRAM configuration, control blobs, and BramTile routing resolution."""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from agamemnon.engine import bram_emit

from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


BRAM_TYPES = {"BRAM9K", "ALTA_BRAM9K", "ALTA_BRAM", "$mem", "BRAM"}
BRAM_FAMILIES = {
    "IMUX", "RMUX", "SeamMUX", "CtrlMUX", "TileClkMUX", "TileClkEnMUX",
    "TileAsyncMUX", "KMUX", "TMUX",
}
BRAM_FLAT_FAMILIES = {
    "SeamMUX", "CtrlMUX", "TileClkMUX", "TileClkEnMUX", "TileAsyncMUX",
    "KMUX", "TMUX",
}
BRAM_CONTROL_FAMILIES = {"KMUX", "TMUX"}


def _param_int(params, key, default=None):
    value = params.get(key)
    if value is None:
        return default
    if isinstance(value, int):
        return value
    text = str(value)
    if any(char in "xzXZ" for char in text) and all(char in "01xzXZ" for char in text):
        text = "".join("0" if char in "xzXZ" else char for char in text)
    try:
        if text.lower().startswith("0x"):
            return int(text, 16)
        if all(char in "01" for char in text) and len(text) > 2:
            return int(text, 2)
        return int(text, 0)
    except ValueError:
        return int(text, 2)


@dataclass
class BramState:
    sets: list = field(default_factory=list)
    clears: list = field(default_factory=list)
    cells: list = field(default_factory=list)
    portb_read: bool = False
    portb_dynamic_address: int = 0
    dual_rw: bool = False
    exact_pips: dict = field(default_factory=dict)
    resolver: Optional[dict] = None


class BramFeature:
    descriptor = FeatureDescriptor(
        feature_id="bram",
        options=("AGAMEMNON_BRAM_HSE_INPUT", "AGAMEMNON_X9_Q5_ALT_EXPERIMENT"),
        chipdb_files=(
            "bram_cell.csv",
            "bram_rom_ctrl.csv", "bram_dual_ctrl.csv",
            "bram_portb_read_ctrl.csv", "bram_portb_const_ctrl.csv",
            "bram_pip_cfg.csv", "bram_x9_data5_alt_candidate_pip_cfg.csv",
            "bram_resolver.json", "bram_approach.csv", "bram_wl.csv",
            "bram_portb_corridors.csv", "bram_portb_exit_corridors.csv",
            "bram_portb_entry_corridors.csv",
            "bram9k_edges.csv", "bram9k_bel.csv",
            "bram9k_pinmap.csv", "bram_zero_pip_cfg.csv",
        ),
        writable_regions=(
            WritableRegion("cell_map", "bram_cell.csv", "byte", "mask"),
            WritableRegion("cell_map", "agamemnon/engine/pips_bram_pll.csv", "byte", "mask"),
            WritableRegion("sparse_table", "bram_rom_ctrl.csv", "byte", "mask"),
            WritableRegion("sparse_table", "bram_dual_ctrl.csv", "byte", "mask"),
            WritableRegion("sparse_table", "bram_portb_read_ctrl.csv", "byte", "mask"),
            WritableRegion("sparse_table", "bram_portb_const_ctrl.csv", "byte", "mask"),
            WritableRegion("sparse_table", "bram_pip_cfg.csv", "byte", "mask"),
        ),
        phase=EmissionPhase.BRAM,
        evidence=("qualification/bram_evidence.jsonl",),
        maturity="release",
        architecture="Construct BramTile routing corridors and the ALTA_BRAM9K BEL.",
        bitstream="Emit complete modeled BRAM cells, control blobs, and exact/learned BramTile selectors.",
    )

    def add_architecture(self, context):
        ctx, Loc = context.ctx, context.loc
        DATA = str(context.chipdb_root)
        shared = context.shared
        W = shared["wire_name"]
        wireset = shared["wires"]
        seen_pip = shared["seen_pips"]
        _wire_delay = shared["wire_delay"]
        _outside_bram_corridor = shared["outside_bram_corridor"]
        BRAM_COV_ONLY = shared["bram_coverage_only"]
        _BRES = shared["bram_resolver"]
        _bram_resolvable = shared["bram_resolvable"]
        _padres = shared["pad_resource"]
        _BRAM_FINAL_DST = shared["bram_final_destinations"]
        _BRAM_FINAL_OK = shared["bram_final_edges"]

        # ---- 5b. BRAM routing pips (BramTILE <-> fabric boundary + intra-BRAM crossbar) ----
        # Harvested from the vendor oracle_bram/logic_db/route.tx (decoded) -> chipdb/bram9k_edges.csv (92 edges:
        # 32 BRAM<->LogicTILE(14,4) boundary + clock spine + 60 intra-BRAM IMUX chains). These are the analog of
        # the MCU-edge pips: the RRG does not enumerate the BramTILE boundary, so without them nextpnr cannot
        # route a placed BRAM's data/addr/clock in or its DataOut back to the mesh. INPUTS enter via LogicTILE(14,4)
        # RMUX -> BramTILE IMUX; OUTPUTS leave via BramTILE BufMUX -> (14,4) RMUX; CLOCK via ClkdisTILE(13,0)
        # BufMUX05 -> BramTILE SeamMUX. Loaded as ROUTE pips (guarded on wireset). Guarded: file absent -> skip.
        # Coverage prune: a BramTile IMUX/RMUX-dst crossbar pip is only kept if bitgen can emit its config
        # (chipdb/bram_pip_cfg.csv, harvest_bram_pip_cfg.py). This forces nextpnr to route BRAM data/addr
        # through edges we can configure -- same principle as the LogicTile far-link legal-fanin prune -- so
        # every routed BramTile pip is silicon-correct. Non-crossbar edges (BufMUX/SeamMUX/clock) always kept.
        import re as _re
        _bram_cov = set()
        _bpc = os.path.join(DATA, "bram_pip_cfg.csv")
        if os.path.exists(_bpc):
            for r in csv.DictReader(open(_bpc)):
                _bram_cov.add((r["dst_res"], r["src_res"], int(r["ddx"]), int(r["ddy"])))
        bram_csv = os.path.join(DATA, "bram9k_edges.csv")
        _bram_input_terminals = set()
        _bram_bel_csv = os.path.join(DATA, "bram9k_bel.csv")
        if os.path.exists(_bram_bel_csv):
            for _r in csv.DictReader(open(_bram_bel_csv)):
                if _r["port"] not in {"DataOutA", "DataOutB"}:
                    _bram_input_terminals.add(_r["res"])
        n_bpip = 0; b_skip = 0; b_prune = 0; b_terminal_prune = 0
        if os.path.exists(bram_csv):
            for r in csv.DictReader(open(bram_csv)):
                if _outside_bram_corridor(r):
                    b_prune += 1; continue
                s = W(r["src_x"], r["src_y"], r["src_res"]); t = W(r["dst_x"], r["dst_y"], r["dst_res"])
                if s not in wireset or t not in wireset:
                    b_skip += 1; continue
                # An IMUX terminal is a physical BRAM input, not a general-purpose transit wire.  The vendor
                # selector graph contains terminal->terminal alternatives, but exposing those alternatives to
                # router2 makes one live input's sink path reserve another live input's terminal (dual-port
                # AddressB[1]/AddressB[2] was the first reproducible collision).  Every affected destination has
                # an independently characterized RMUX feeder, which is what simultaneous vendor bus routes use.
                # Keep the selector encodings in bram_pip_cfg.csv for analysis, but do not offer a BRAM input pin
                # as routing fabric for another pin.
                if r["src_res"] in _bram_input_terminals:
                    b_terminal_prune += 1; continue
                if (BRAM_COV_ONLY and _BRES and r["dst_tile"] == "BramTILE"
                        and _re.match(r"(IMUX|RMUX)\d+$", r["dst_res"])
                        and not _bram_resolvable(r["dst_res"], r["src_res"], int(r["dst_x"]) - int(r["src_x"]),
                                                 int(r["dst_y"]) - int(r["src_y"]))):
                    b_prune += 1; continue          # crossbar edge the resolver can't emit -> prune
                # SILICON-PROVEN final-hop restriction: a characterized (13,4) address IMUX is fed ONLY by its
                # conduction-proven feeder (bram_wl.csv) -> drop dead entry pips (e.g. RMUX58->IMUX06) so nextpnr
                # takes the conducting one (RMUX40->IMUX06). Only touches the 9 characterized address terminals.
                _fk = (r["dst_x"], r["dst_y"], _padres(r["dst_res"]))
                if _fk in _BRAM_FINAL_DST and (r["src_x"], r["src_y"], _padres(r["src_res"])) + _fk not in _BRAM_FINAL_OK:
                    b_prune += 1; continue
                nm = "%s.%s" % (s, t)
                if nm in seen_pip:
                    continue
                ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                           delay=_wire_delay(r["src_res"]), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                seen_pip.add(nm); n_bpip += 1
            print("AGRV2K arch: added %d BRAM routing pip(s) (%d skipped, %d pruned:no-config, "
                  "%d pruned:input-terminal-transit)" % (n_bpip, b_skip, b_prune, b_terminal_prune))

        # ---- 5c. BRAM bel: an ALTA_BRAM9K on the BramTILE with each port pin bound to the harvested wire ----
        # chipdb/bram9k_bel.csv (port,bit,x,y,res) = the port->BramTILE-terminal map harvested from the vendor
        # oracle_bram_rw route.tx (harvest_bram_bel.py). Without this bel nextpnr cannot PLACE a BRAM cell; the
        # 5b pips give it something to route to/from. INPUT ports (Address/DataIn/We/Re/ByteEn/Clk/ClkEn) enter
        # via BramTILE IMUX/KMUX/TileClk wires; DataOut leaves via BufMUX. Guarded: file absent -> skip.
        _BRAM_SCALAR = {"WeA", "WeB", "ReA", "ReB", "Clk0", "Clk1", "ClkEn0", "ClkEn1"}
        _BRAM_OUT = {"DataOutA", "DataOutB"}
        bram_bel_csv = os.path.join(DATA, "bram9k_bel.csv")
        if os.path.exists(bram_bel_csv):
            _btpins = {}
            for r in csv.DictReader(open(bram_bel_csv)):
                _btpins.setdefault((int(r["x"]), int(r["y"])), []).append(r)
            n_bram_bel = 0; bb_skip = 0
            for (bx, by), pins in _btpins.items():
                bel = W(bx, by, "BRAM")
                ctx.addBel(name=bel, type="ALTA_BRAM9K", loc=Loc(bx, by, 0), gb=False, hidden=False)
                for r in pins:
                    w = W(r["x"], r["y"], r["res"])
                    if w not in wireset: bb_skip += 1; continue
                    port, bit = r["port"], int(r["bit"])
                    pin = port if port in _BRAM_SCALAR else "%s[%d]" % (port, bit)
                    if port in _BRAM_OUT:
                        ctx.addBelOutput(bel=bel, name=pin, wire=w)
                    else:
                        ctx.addBelInput(bel=bel, name=pin, wire=w)
                n_bram_bel += 1
            print("AGRV2K arch: added %d BRAM bel(s) (%d pins skipped)" % (n_bram_bel, bb_skip))

        return n_bpip

    def load_selector_cells(self, chipdb_root, cell_map):
        """Add BramTile selector cells to the shared physical cell map."""
        table = chipdb_root / "bram_cell.csv"
        if not table.exists():
            return 0
        count = 0
        with table.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (
                    int(row["x"]), int(row["y"]), row["mux"], int(row["sel"]),
                )
                cell_map[key] = (int(row["byte"]), int(row["mask"]))
                count += 1
        print("loaded %d BramTile config cells (bram_cell.csv)" % count)
        return count

    @staticmethod
    def _read_bits(path):
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as stream:
            return [(int(row["byte"]), int(row["mask"])) for row in csv.DictReader(stream)]

    def prepare(self, module, chipdb_root, options):
        state = BramState()
        net_refs = Counter()
        for cell in module["cells"].values():
            for bits in cell.get("connections", {}).values():
                net_refs.update(bit for bit in bits if isinstance(bit, int))

        for cell in module["cells"].values():
            cell_type = str(cell.get("type", "")).upper()
            bel = cell.get("attributes", {}).get("NEXTPNR_BEL", "")
            match = re.match(r"X(\d+)Y(\d+)_BRAM", bel or "")
            if cell_type not in BRAM_TYPES and not match:
                continue
            x, y = ((int(match.group(1)), int(match.group(2))) if match else (13, 4))
            parameters = cell.get("parameters", {})
            portb_read = any(
                net_refs[bit] > 1
                for bit in cell.get("connections", {}).get("DataOutB", [])
                if isinstance(bit, int)
            )
            state.portb_read |= portb_read
            state.dual_rw |= portb_read and bool(cell.get("connections", {}).get("WeA", []))
            state.portb_dynamic_address = max(
                state.portb_dynamic_address,
                sum(
                    net_refs[bit] > 1
                    for bit in cell.get("connections", {}).get("AddressB", [])
                    if isinstance(bit, int)
                ),
            )
            init_value = _param_int(parameters, "INIT_VAL", 0)
            width = _param_int(parameters, "PORTA_WIDTH", 0)
            width_b = _param_int(parameters, "PORTB_WIDTH", 0)
            clock_mode = _param_int(parameters, "CLKMODE", 0)
            enables = {}
            for port in ("PORTA", "PORTB"):
                for signal in ("CLKIN", "CLKOUT", "RSTIN", "RSTOUT"):
                    name = "%s_%s_EN" % (port, signal)
                    enables[name] = _param_int(parameters, name, 0) or 0
            state.sets.extend(bram_emit.emit(
                x, y, width, clock_mode, init_value, enables, width_b=width_b
            ))
            state.clears.extend(bram_emit.owned_surface(x, y))
            state.cells.append((x, y, width, width_b, clock_mode))

        if state.cells:
            control = "bram_dual_ctrl.csv" if state.dual_rw else "bram_rom_ctrl.csv"
            count = 0
            for bit in self._read_bits(chipdb_root / control):
                if not state.dual_rw and state.portb_read and bit == (69006, 2):
                    continue
                state.sets.append(bit)
                count += 1
            print("BRAM %s control blob: +%d bits" %
                  ("dual-port R/W" if state.dual_rw else "ROM", count))
            if state.portb_read and not state.dual_rw:
                state.sets.extend(self._read_bits(chipdb_root / "bram_portb_read_ctrl.csv"))
                print("BRAM Port-B read control: KMUX71 -> KMUX62")
            if state.portb_read and state.portb_dynamic_address <= 2:
                bits = self._read_bits(chipdb_root / "bram_portb_const_ctrl.csv")
                state.sets.extend(bits)
                print("BRAM Port-B constant controls: +%d exact IMUX bits" % len(bits))
            elif state.portb_read:
                print("BRAM Port-B two-address constant blob skipped for %d dynamic address bits" %
                      state.portb_dynamic_address)
            print("BRAM cells:", state.cells, "; BRAM config bits:", len(state.sets))

        self._load_routing(state, chipdb_root, options)
        return state

    def _load_routing(self, state, chipdb_root, options):
        table = chipdb_root / "bram_pip_cfg.csv"
        if table.exists():
            with table.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    key = (row["dst_res"], row["src_res"], int(row["ddx"]), int(row["ddy"]))
                    state.exact_pips.setdefault(key, []).append((int(row["byte"]), int(row["mask"])))
            print("loaded %d exact BRAM routing pip(s) (bram_pip_cfg.csv)" % len(state.exact_pips))
        if options.enabled("AGAMEMNON_X9_Q5_ALT_EXPERIMENT"):
            alternate = chipdb_root / "bram_x9_data5_alt_candidate_pip_cfg.csv"
            if alternate.exists():
                with alternate.open(newline="", encoding="utf-8") as stream:
                    for row in csv.DictReader(stream):
                        key = (row["dst_res"], row["src_res"], int(row["ddx"]), int(row["ddy"]))
                        state.exact_pips.setdefault(key, []).append(
                            (int(row["byte"]), int(row["mask"]))
                        )
        resolver = chipdb_root / "bram_resolver.json"
        if resolver.exists():
            state.resolver = json.loads(resolver.read_text(encoding="utf-8"))
            print("loaded BramTile sel resolver (L0=%d L1=%d L2=%d)" % (
                len(state.resolver["L0"]), len(state.resolver["L1"]),
                len(state.resolver["L2"]),
            ))

    @staticmethod
    def _resolve(state, destination_family, destination_index, source_family,
                 source_index, delta_x, delta_y):
        resolver = state.resolver
        if resolver is None:
            return None
        if destination_family in BRAM_CONTROL_FAMILIES:
            return resolver.get("CTRL", {}).get(
                "%s|%d" % (destination_family, destination_index)
            )
        group = destination_index % resolver["NPI"][destination_family]
        block = group * resolver["BS"][destination_family]
        exact = "|".join(map(str, (
            destination_family, destination_index, source_family, source_index,
            delta_x, delta_y,
        )))
        local = "|".join(map(str, (
            destination_family, group, source_family, source_index, delta_x, delta_y,
        )))
        family = "|".join(map(str, (
            destination_family, source_family, delta_x, delta_y, source_index % 16,
        )))
        selectors = (
            resolver["L0"].get(exact) or resolver["L1"].get(local) or
            resolver["L2"].get(family)
        )
        return None if selectors is None else [block + selector for selector in selectors]

    def resolve_route(self, state, source, destination, cell_map, mux_groups, route_sets,
                      debug=False):
        sx, sy, sf, si = source
        dx, dy, df, di = destination
        key = ("%s%d" % (df, di), "%s%d" % (sf, si), dx - sx, dy - sy)
        if sf == "BufMUX" and (sx, sy) == (13, 4) and df == "RMUX":
            bits = state.exact_pips.get(key)
            if bits:
                route_sets.extend(bits)
                return True
            if debug:
                print("  BRAM-EXIT-UNMAPPED %s%d <- %s%d d=(%d,%d)" %
                      (df, di, sf, si, dx - sx, dy - sy))
            return False
        if (dx, dy) != (13, 4) or df not in BRAM_FAMILIES:
            return None
        if state.dual_rw and df in BRAM_CONTROL_FAMILIES:
            return True
        exact = state.exact_pips.get(key)
        if exact:
            route_sets.extend(exact)
            return True
        selectors = self._resolve(state, df, di, sf, si, dx - sx, dy - sy)
        config = "CFG_%s" % df if df in BRAM_FLAT_FAMILIES else "CFG_%s%d" % (
            df, di // mux_groups[df]
        )
        count = 0
        if selectors:
            for selector in selectors:
                bit = cell_map.get((dx, dy, config, selector))
                if bit:
                    route_sets.append(bit)
                    count += 1
        if count:
            return True
        if debug:
            print("  BRAM-UNMAPPED %s%d <- %s%d d=(%d,%d) sels=%s" %
                  (df, di, sf, si, dx - sx, dy - sy, selectors))
        return False

    def clear_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.clears:
            if byte < len(context.image):
                context.image[byte] &= (~mask) & 0xFF
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "BRAM")
                count += 1
        return count

    def writable_bits(self, state):
        return set(state.clears) | set(state.sets)

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "BRAM")
                count += 1
        return count


FEATURE = BramFeature()
