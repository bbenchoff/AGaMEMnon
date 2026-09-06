"""BRAM configuration, control blobs, and BramTile routing resolution."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from agamemnon.engine import bram_emit
from agamemnon.engine import qualified_bram_tmux9

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
BRAM_CONTROL_FIELD_WIDTHS = {"KMUX": 9, "TMUX": 8}
# Fixed, zero-bit source presentation used by the individually qualified
# registered-source same-Port-A write checkpoints. This stays emitter-only:
# the ordinary architecture does not advertise the corridor or generalize
# TMUX09 routing from the bounded replay.
BRAM_FIXED_PRESENTATION = ((14, 8, "OMUX", 8), (14, 8, "OMUX", 6))
BRAM_TMUX9_QUALIFIED_PROFILES = frozenset({
    "bram-tmux9-i0-d1-we0", "bram-tmux9-i0-d1-we1",
    "bram-tmux9-i1-d0-we0", "bram-tmux9-i1-d0-we1",
})
BRAM_TMUX9_PROFILE_VALUES = {
    "bram-tmux9-i0-d1-we0": (0, 1, False),
    "bram-tmux9-i0-d1-we1": (0, 1, True),
    "bram-tmux9-i1-d0-we0": (1, 0, False),
    "bram-tmux9-i1-d0-we1": (1, 0, True),
}
BRAM_TMUX9_MODULE_SHA256 = {
    "bram-tmux9-i0-d1-we0": "a1163258cc1fff47b2023b52d7056e71264f48cff64960e58f4816ecd1d490c9",
    "bram-tmux9-i0-d1-we1": "434bb531de90eff0d1d27e19ae5e96be0399f72dea549335f357c5af970a0f11",
    "bram-tmux9-i1-d0-we0": "ecbbf0161fae43d640c27503a7233dcd77130d0c936f96ff9dd2556df20a7f2a",
    "bram-tmux9-i1-d0-we1": "4877ff0f609cb2332cae9fc696f1aeef6cf632e725c1ae09c874fee7d5035e22",
}


def _initialized_rom_supported(module, cell, options, portb_read):
    """Content-independent admission for the silicon-qualified single-port ROM mode.

    Routing/clock legality is still checked by the normal pipeline. This check
    selects the characterized ROM control semantics; it is not a routing proof.
    Empty write-control ports intentionally select the write-disabled ROM blob,
    not an assumed logic-zero value on an unselected hardware input.
    """
    memories = [c for c in module['cells'].values()
                if str(c.get('type', '')).upper() in BRAM_TYPES or
                re.match(r'X\d+Y\d+_BRAM', c.get('attributes', {}).get('NEXTPNR_BEL', ''))]
    if len(memories) != 1 or portb_read:
        return False
    if (options.enabled('AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG') or
            options.enabled('AGAMEMNON_BRAM_SITE_READ_PATHS')):
        return False
    if (options.raw('AGAMEMNON_DEVICE') != 'AGRV2KL48' or
            options.integer('AGAMEMNON_HSE') != 8 or
            options.integer('AGAMEMNON_SYSCLK') != 10):
        return False
    attrs = module.get('attributes', {})
    if (attrs.get('AGAMEMNON_CLOCK_SOURCE_PROFILE') != 'MCU_BUS_DEFAULT_V1' or
            attrs.get('AGAMEMNON_CLOCK_CLASS') != 'GCLK0' or
            cell.get('attributes', {}).get('NEXTPNR_BEL') != 'X13Y4_BRAM'):
        return False
    params = cell.get('parameters', {})
    if _param_int(params, 'PORTA_WIDTH', -1) not in (0, 15):
        return False
    required = {'PORTB_WIDTH': 0, 'CLKMODE': 0,
                'PORTB_CLKIN_EN': 1, 'PORTB_CLKOUT_EN': 1}
    if any(_param_int(params, name, 0) != value for name, value in required.items()):
        return False
    zero_fields = set(bram_emit.EXPERIMENTAL_FIELDS) | {
        'PORTA_CLKIN_EN', 'PORTA_CLKOUT_EN', 'PORTA_RSTIN_EN',
        'PORTA_RSTOUT_EN', 'PORTB_RSTIN_EN', 'PORTB_RSTOUT_EN'}
    if any(_param_int(params, name, 0) != 0 for name in zero_fields):
        return False
    ports = cell.get('connections', {})
    if any(ports.get(name, []) for name in ('WeA', 'WeB', 'ReA', 'ReB', 'Clk1', 'ClkEn1')):
        return False
    if len(ports.get('AddressA', [])) != 13:
        return False
    return all(len(ports.get(name, [])) == 1 and isinstance(ports[name][0], int)
               for name in ('Clk0', 'ClkEn0'))


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


def _tmux9_profile_signature(module, profile, require_module_hash=True):
    """Require the exact bounded registered-source x18 write composition."""
    if profile not in BRAM_TMUX9_QUALIFIED_PROFILES:
        return False
    canonical = json.dumps(module, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if (require_module_hash and
            hashlib.sha256(canonical).hexdigest() != BRAM_TMUX9_MODULE_SHA256[profile]):
        return False
    init, data, high = BRAM_TMUX9_PROFILE_VALUES[profile]
    cells = module.get("cells", {})
    required = {name: cells.get(name) for name in (
        "mem", "source_stage", "state_stage", "path_observer",
        "src_d1", "mcu_h0", "mcu_h1", "mcu_h2", "mcu_h3",
    )}
    if any(cell is None for cell in required.values()):
        return False
    brams = [cell for cell in cells.values() if cell.get("type") == "ALTA_BRAM9K"]
    if len(brams) != 1 or brams[0] is not required["mem"]:
        return False
    bram = required["mem"]
    params = bram.get("parameters", {})
    if (bram.get("attributes", {}).get("NEXTPNR_BEL") != "X13Y4_BRAM" or
            _param_int(params, "PORTA_WIDTH", -1) != 0 or
            _param_int(params, "PORTB_WIDTH", -1) != 0 or
            _param_int(params, "CLKMODE", -1) != 10 or
            _param_int(params, "INIT_VAL", -1) != (0 if init == 0 else (1 << 9216) - 1)):
        return False
    source, state, observer, data_cell = (
        required["source_stage"], required["state_stage"],
        required["path_observer"], required["src_d1"],
    )
    for cell, bel, mask, ff in (
        (source, "X14Y8_SLICE2", 0x00FF, 1),
        (state, "X10Y4_SLICE0", 0xFF00, 1),
        (observer, "X14Y12_SLICE0", 0xCCCC, 0),
    ):
        if (cell.get("type") != "GENERIC_SLICE" or
                cell.get("attributes", {}).get("NEXTPNR_BEL") != bel or
                _param_int(cell.get("parameters", {}), "INIT", -1) != mask or
                _param_int(cell.get("parameters", {}), "FF_USED", -1) != ff):
            return False
    h0 = required["mcu_h0"].get("connections", {}).get("DOUT", [])
    h1 = required["mcu_h1"].get("connections", {}).get("DOUT", [])
    h2 = required["mcu_h2"].get("connections", {}).get("DOUT", [])
    h3 = required["mcu_h3"].get("connections", {}).get("DOUT", [])
    if not all(len(bits) == 1 for bits in (h0, h1, h2, h3)):
        return False
    if (source.get("connections", {}).get("Q") != h1 or
            source.get("connections", {}).get("I", [None] * 4)[3] != h2[0] or
            state.get("connections", {}).get("Q") != h2 or
            state.get("connections", {}).get("I", [None] * 4)[3] != h1[0] or
            observer.get("connections", {}).get("I", [])[:2] != [h2[0], h1[0]] or
            observer.get("connections", {}).get("F") != h3 or
            bram.get("connections", {}).get("DataOutA", [None] * 2)[1] != h0[0] or
            bram.get("connections", {}).get("WeA", []) != (h1 if high else [])):
        return False
    if _param_int(data_cell.get("parameters", {}), "INIT", -1) != (0xFFFF if data else 0):
        return False
    if high and bram.get("connections", {}).get("DataInA", [None] * 2)[1] != \
            data_cell.get("connections", {}).get("F", [None])[0]:
        return False
    clock = source.get("connections", {}).get("CLK", [])
    if (len(clock) != 1 or state.get("connections", {}).get("CLK") != clock or
            bram.get("connections", {}).get("Clk0") != clock):
        return False
    routes = module.get("netnames", {})
    h1_route = routes.get("h1", {}).get("attributes", {}).get("ROUTING", "")
    required_h1 = (
        "X14Y8_OMUX08.X14Y8_OMUX06",
        "X15Y8_RMUX21.X15Y4_RMUX86",
    )
    if not all(edge in h1_route for edge in required_h1):
        return False
    write_edges = (
        "X15Y4_RMUX86.X13Y4_TMUX09",
        "X13Y4_TMUX09.X13Y4_KMUX03",
    )
    has_all_write_edges = all(edge in h1_route for edge in write_edges)
    has_any_write_edge = any(edge in h1_route for edge in write_edges)
    if (high and not has_all_write_edges) or (not high and has_any_write_edge):
        return False
    return True


def _tmux9_source_route_signature(module, profile):
    """Require the bounded structure plus every qualified source-tree edge."""
    return (
        _tmux9_profile_signature(module, profile, require_module_hash=False) and
        qualified_bram_tmux9.routes_match(module, profile)
    )


@dataclass
class BramState:
    sets: list = field(default_factory=list)
    clears: list = field(default_factory=list)
    cells: list = field(default_factory=list)
    portb_read: bool = False
    portb_dynamic_address: int = 0
    dual_rw: bool = False
    exact_pips: dict = field(default_factory=dict)
    exact_codewords: dict = field(default_factory=dict)
    control_owners: dict = field(default_factory=dict)
    resolver: Optional[dict] = None
    qualified_profile: Optional[str] = None


class BramFeature:
    descriptor = FeatureDescriptor(
        feature_id="bram",
        options=("AGAMEMNON_BRAM_HSE_INPUT", "AGAMEMNON_X9_Q5_ALT_EXPERIMENT",
                 "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG",
                 "AGAMEMNON_BRAM_SITE_READ_PATHS",
                 "AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE"),
        chipdb_files=(
            "bram_cell.csv",
            "bram_rom_ctrl.csv", "bram_site_rom_ctrl.csv", "bram_dual_ctrl.csv",
            "bram_portb_read_ctrl.csv", "bram_portb_const_ctrl.csv",
            "bram_pip_cfg.csv", "bram_route_codewords.csv",
            "bram_control_codewords.csv",
            "bram_x9_data5_alt_candidate_pip_cfg.csv",
            "bram_resolver.json", "bram_approach.csv", "bram_wl.csv",
            "bram_portb_corridors.csv", "bram_portb_exit_corridors.csv",
            "bram_portb_entry_corridors.csv",
            "bram_serv_write_paths.csv",
            "bram_tmux9_source_paths.csv",
            "bram_site_read_paths.csv",
            "bram_site_control_route_codewords.csv",
            "bram9k_edges.csv", "bram9k_bel.csv",
            "bram_site_route_corpus.csv",
            "bram9k_pinmap.csv", "bram_zero_pip_cfg.csv",
            "bram_config_admission.json",
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
        evidence=(
            "qualification/bram_evidence.jsonl",
            "qualification/bram_site_read_evidence.jsonl",
            "qualification/registered_bram_tmux9_evidence.jsonl",
        ),
        maturity="release",
        evidence_tier="individually_qualified",
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
        _blacklisted = shared["is_blacklisted"]
        _blacklisted_wires = shared["is_blacklisted_wires"]
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
                # The BramTILE boundary supplement is the last part-keyed pip
                # loader that never consulted the ban, so a blacklisted BramTile
                # edge stayed routable and the build looked like it had obeyed.
                # Removes nothing from the shipped chipdb (0 of 456 rows), so
                # this closes an operator-facing gap rather than narrowing the
                # graph.
                if _blacklisted(r):
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
                # N5.7A admits only the already-retained X13Y4 BRAM clock
                # branch.  Give both downstream hops a distinct type so
                # router2 and the independent validator can prove the entire
                # root/branch topology instead of fabricating a direct tap.
                pip_type = (
                    "GCLK0_BRAM_BRANCH"
                    if (s, t) in {
                        ("X13Y0_BufMUX05", "X13Y4_SeamMUX01"),
                        ("X13Y4_SeamMUX01", "X13Y4_TileClkMUX01"),
                    }
                    else "ROUTE"
                )
                ctx.addPip(name=nm, type=pip_type, srcWire=s, dstWire=t,
                           delay=_wire_delay(r["src_res"]), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                seen_pip.add(nm); n_bpip += 1
            print("AGRV2K arch: added %d BRAM routing pip(s) (%d skipped, %d pruned:no-config, "
                  "%d pruned:input-terminal-transit)" % (n_bpip, b_skip, b_prune, b_terminal_prune))

        # Every hop in this table belongs to the exact four-site x18 oracle
        # that exercised all 512 addresses and observed every HRDATA bit on
        # silicon.  Unlike bram_site_route_corpus.csv, these are sensitized
        # conduction witnesses rather than unsensitized vendor observations.
        # Re-admit only these complete measured address/data/clock trees after
        # the generic graph gates, preserving their exact coordinates.
        site_read_paths = os.path.join(DATA, "bram_site_read_paths.csv")
        site_read_added = 0; site_read_existing = 0; site_read_missing = 0
        if (context.options.enabled("AGAMEMNON_BRAM_SITE_READ_PATHS") and
                os.path.exists(site_read_paths)):
            with open(site_read_paths, newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    source, destination = row["src_wire"], row["dst_wire"]
                    if _blacklisted_wires(source, destination):
                        continue
                    name = "%s.%s" % (source, destination)
                    if name in seen_pip:
                        site_read_existing += 1
                        continue
                    if source not in wireset or destination not in wireset:
                        site_read_missing += 1
                        continue
                    match = _re.match(r"X(-?\d+)Y(-?\d+)_", destination)
                    if match is None:
                        raise RuntimeError(
                            "qualified four-site BRAM path destination is malformed: %s"
                            % destination
                        )
                    source_resource = source.split("_", 1)[1]
                    ctx.addPip(
                        name=name, type="ROUTE", srcWire=source, dstWire=destination,
                        delay=_wire_delay(source_resource),
                        loc=Loc(int(match.group(1)), int(match.group(2)), 0),
                    )
                    seen_pip.add(name)
                    site_read_added += 1
            print("AGRV2K arch: admitted %d exact four-site BRAM read-path pip(s) "
                  "(%d already present, %d missing endpoint)" %
                  (site_read_added, site_read_existing, site_read_missing))

        # The four qualified images carry a complete branched source/observer
        # solution. Several of its corpus-derived edges are intentionally not
        # in the ordinary strict graph, and Q presents from OMUX08 to OMUX06
        # through a zero-bit local bridge. Expose the entire measured tree only
        # for this exact source-build profile; ordinary architecture graphs
        # must not infer any of these additions as general routing.
        if context.options.enabled("AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE"):
            table = context.chipdb_root / "bram_tmux9_source_paths.csv"
            added = 0
            with table.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    source = row["src_wire"]
                    destination = row["dst_wire"]
                    if _blacklisted_wires(source, destination):
                        continue
                    if source not in wireset or destination not in wireset:
                        raise RuntimeError(
                            "qualified TMUX09 path wire is absent: %s -> %s" %
                            (source, destination)
                        )
                    name = "%s.%s" % (source, destination)
                    if name in seen_pip:
                        continue
                    match = re.match(r"X(-?\d+)Y(-?\d+)_", destination)
                    if match is None:
                        raise RuntimeError(
                            "qualified TMUX09 destination is malformed: %s" % destination
                        )
                    ctx.addPip(
                        name=name, type="ROUTE", srcWire=source,
                        dstWire=destination, delay=0.0,
                        loc=Loc(int(match.group(1)), int(match.group(2)), 0),
                    )
                    seen_pip.add(name)
                    n_bpip += 1
                    added += 1
            print("AGRV2K arch: added %d scoped qualified TMUX09 path pip(s)" % added)

        # ---- 5c. BRAM bel: an ALTA_BRAM9K on the BramTILE with each port pin bound to the harvested wire ----
        # chipdb/bram9k_bel.csv (port,bit,x,y,res) = the port->BramTILE-terminal map harvested from the vendor
        # oracle_bram_rw route.tx (harvest_bram_bel.py). Without this bel nextpnr cannot PLACE a BRAM cell; the
        # 5b pips give it something to route to/from. INPUT ports (Address/DataIn/We/Re/ByteEn/Clk/ClkEn) enter
        # via BramTILE IMUX/KMUX/TileClk wires; DataOut leaves via BufMUX. Guarded: file absent -> skip.
        _BRAM_SCALAR = {
            "WeA", "WeB", "ReA", "ReB", "Clk0", "Clk1", "ClkEn0", "ClkEn1",
            "AsyncReset0",
        }
        _BRAM_OUT = {"DataOutA", "DataOutB"}
        bram_bel_csv = os.path.join(DATA, "bram9k_bel.csv")
        if os.path.exists(bram_bel_csv):
            _btpins = {}
            for r in csv.DictReader(open(bram_bel_csv)):
                _btpins.setdefault((int(r["x"]), int(r["y"])), []).append(r)
            n_bram_bel = 0; bb_skip = 0
            for (bx, by), pins in _btpins.items():
                missing = [
                    W(r["x"], r["y"], r["res"])
                    for r in pins
                    if W(r["x"], r["y"], r["res"]) not in wireset
                ]
                # A partial hard-block BEL is unsafe: the placer can select it
                # even though a later port has no physical wire.  The four-site
                # terminal corpus is broader than the silicon-admitted routing
                # graph, so expose a site only after all of its pins are present.
                if missing:
                    bb_skip += len(pins)
                    continue
                bel = W(bx, by, "BRAM")
                ctx.addBel(name=bel, type="ALTA_BRAM9K", loc=Loc(bx, by, 0), gb=False, hidden=False)
                for r in pins:
                    w = W(r["x"], r["y"], r["res"])
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
            raise ValueError(
                "bram requires chipdb/bram_cell.csv; refusing to continue "
                "without release BramTile selector cells"
            )
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
            raise ValueError(
                "bram requires chipdb/%s for the selected BRAM mode" % path.name
            )
        with path.open(newline="", encoding="utf-8") as stream:
            return [(int(row["byte"]), int(row["mask"])) for row in csv.DictReader(stream)]

    @staticmethod
    def _read_site_control_bits(chipdb_root, sites):
        fields = []
        with (chipdb_root / "bram_site_rom_ctrl.csv").open(
                newline="", encoding="utf-8") as stream:
            fields = [(row["mux"], int(row["sel"])) for row in csv.DictReader(stream)]
        cells = {}
        with (chipdb_root / "bram_cell.csv").open(
                newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (int(row["x"]), int(row["y"]), row["mux"], int(row["sel"]))
                bit = (int(row["byte"]), int(row["mask"]))
                if key in cells and cells[key] != bit:
                    raise ValueError("duplicate BRAM site-control cell %r" % (key,))
                cells[key] = bit
        bits = []
        for x, y in sorted(set(sites)):
            for mux, selection in fields:
                key = (x, y, mux, selection)
                if key not in cells:
                    raise ValueError(
                        "BRAM site-control field %s[%d] has no cell at X%dY%d"
                        % (mux, selection, x, y)
                    )
                bits.append(cells[key])
        return bits

    def prepare(self, module, chipdb_root, options):
        state = BramState()
        requested_profile = options.environ.get("AGAMEMNON_QUALIFIED_ROUTE_PROFILE")
        source_profile = options.environ.get("AGAMEMNON_BRAM_TMUX9_SOURCE_PROFILE")
        if requested_profile and source_profile:
            raise ValueError("TMUX09 checkpoint and source profiles are mutually exclusive")
        if source_profile:
            source_structure_ok = _tmux9_profile_signature(
                module, source_profile, require_module_hash=False)
            source_routes_ok = qualified_bram_tmux9.routes_match(
                module, source_profile)
            source_context_ok = (
                options.raw("AGAMEMNON_DEVICE") == "AGRV2KL48" and
                options.integer("AGAMEMNON_HSE") == 8 and
                options.integer("AGAMEMNON_SYSCLK") == 10
            )
            if not (source_context_ok and source_structure_ok and source_routes_ok):
                raise ValueError(
                    "qualified TMUX09 BRAM source profile does not match its "
                    "bounded registered-source x18 structure and routes "
                    "(context=%s structure=%s routes=%s)" %
                    (source_context_ok, source_structure_ok, source_routes_ok)
                )
            state.qualified_profile = source_profile
        if requested_profile:
            if (options.raw("AGAMEMNON_DEVICE") != "AGRV2KL48" or
                    options.integer("AGAMEMNON_HSE") != 8 or
                    options.integer("AGAMEMNON_SYSCLK") != 10 or
                    not _tmux9_profile_signature(module, requested_profile)):
                raise ValueError(
                    "qualified TMUX09 BRAM profile does not match its exact "
                    "registered-source x18 signature"
                )
            state.qualified_profile = requested_profile
        net_refs = Counter()
        for cell in module["cells"].values():
            for bits in cell.get("connections", {}).values():
                net_refs.update(bit for bit in bits if isinstance(bit, int))
        # A BRAM port feeding a top-level output is live even without a cell
        # consumer. In particular, it must not be admitted as an unused Port B.
        for port in module.get('ports', {}).values():
            if port.get('direction') != 'input':
                net_refs.update(bit for bit in port.get('bits', []) if isinstance(bit, int))

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
            porta_read = any(
                net_refs[bit] > 1
                for bit in cell.get("connections", {}).get("DataOutA", [])
                if isinstance(bit, int)
            )
            # Full-depth address-plane/complement and fresh smaller-ROM silicon
            # qualify x1 and x18 read-only modes without binding source names,
            # INIT contents or routes. The separately witnessed TMUX09 source
            # matrix is admitted only after the structure/routes/context checks
            # above; CLI also binds source and final raw/compressed identities.
            # Retained checkpoint and general writable modes remain fenced.
            if (width in {0, 15} and init_value and porta_read and
                    not _initialized_rom_supported(module, cell, options, portb_read) and
                    not (source_profile and state.qualified_profile == source_profile
                         and not portb_read
                         and not options.enabled("AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG")
                         and not options.enabled("AGAMEMNON_BRAM_SITE_READ_PATHS"))):
                raise SystemExit(
                    "initialized BRAM Port-A width code %d is unqualified: "
                    "VP-AGM-006 requires broader initialized-read qualification after "
                    "clock-source and constant-input repairs" % width
                )
            experimental_enabled = options.enabled("AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG")
            if experimental_enabled:
                if options.raw("AGAMEMNON_DEVICE") != "AGRV2KL48":
                    raise ValueError(
                        "experimental BRAM config is scoped to AGRV2KL48/L48"
                    )
                if x != 13 or y not in {1, 2, 3, 4}:
                    raise ValueError(
                        "experimental BRAM config is scoped to BramTILE X13Y1..Y4"
                    )
            experimental = {
                name: _param_int(parameters, name, 0) or 0
                for name in bram_emit.EXPERIMENTAL_FIELDS
            }
            enables = {}
            for port in ("PORTA", "PORTB"):
                for signal in ("CLKIN", "CLKOUT", "RSTIN", "RSTOUT"):
                    name = "%s_%s_EN" % (port, signal)
                    enables[name] = _param_int(parameters, name, 0) or 0
            state.sets.extend(bram_emit.emit(
                x, y, width, clock_mode, init_value, enables, width_b=width_b,
                experimental=experimental,
                allow_experimental=experimental_enabled,
            ))
            state.clears.extend(bram_emit.owned_surface(
                x, y, experimental=experimental_enabled
            ))
            state.cells.append((x, y, width, width_b, clock_mode))

        if state.cells:
            control = "bram_dual_ctrl.csv" if state.dual_rw else "bram_rom_ctrl.csv"
            control_label = "dual-port R/W" if state.dual_rw else "ROM"
            count = 0
            if (not state.dual_rw and
                    options.enabled("AGAMEMNON_BRAM_SITE_READ_PATHS")):
                control_bits = self._read_site_control_bits(
                    chipdb_root, ((cell[0], cell[1]) for cell in state.cells)
                )
                control_label = "site-relative ROM"
            else:
                control_bits = self._read_bits(chipdb_root / control)
            for bit in control_bits:
                if not state.dual_rw and state.portb_read and bit == (69006, 2):
                    continue
                state.sets.append(bit)
                count += 1
            print("BRAM %s control blob: +%d bits" %
                  (control_label, count))
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
        # BramTILE routing remains part of the device graph even when the RTL
        # does not instantiate a BRAM.  Ordinary fabric nets can therefore use
        # X13Y4 as transit.  Load its exact selector tables unconditionally;
        # otherwise resolve_route() claims those physical edges but has no
        # codeword with which to emit them.
        table = chipdb_root / "bram_pip_cfg.csv"
        if not table.exists():
            raise ValueError("bram requires chipdb/bram_pip_cfg.csv when BRAM is used")
        with table.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (row["dst_res"], row["src_res"], int(row["ddx"]), int(row["ddy"]))
                state.exact_pips.setdefault(key, []).append((int(row["byte"]), int(row["mask"])))
        print("loaded %d exact BRAM routing pip(s) (bram_pip_cfg.csv)" % len(state.exact_pips))
        codewords = chipdb_root / "bram_route_codewords.csv"
        if not codewords.exists():
            raise ValueError("bram requires chipdb/bram_route_codewords.csv when BRAM is used")
        with codewords.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                qualified_profiles = {
                    name for name in row.get("qualified_profiles", "").split(";") if name
                }
                if qualified_profiles and state.qualified_profile not in qualified_profiles:
                    continue
                key = (
                    row["dst_family"], int(row["dst_index"]),
                    row["src_family"], int(row["src_index"]),
                    int(row["ddx"]), int(row["ddy"]),
                )
                if key in state.exact_codewords:
                    raise ValueError("duplicate exact BRAM route codeword %r" % (key,))
                parse = lambda value: [int(item) for item in value.split(";") if item]
                state.exact_codewords[key] = (
                    row["config"], parse(row["clear_selections"]),
                    parse(row["set_selections"]),
                )
        print("loaded %d exact BRAM route codeword(s)" % len(state.exact_codewords))
        self._load_control_codewords(state, chipdb_root)
        if options.enabled("AGAMEMNON_BRAM_SITE_READ_PATHS"):
            control_codewords = chipdb_root / "bram_site_control_route_codewords.csv"
            if not control_codewords.exists():
                raise ValueError(
                    "bram site-read mode requires chipdb/"
                    "bram_site_control_route_codewords.csv"
                )
            with control_codewords.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    key = (
                        row["dst_family"], int(row["dst_index"]),
                        row["src_family"], int(row["src_index"]),
                        int(row["ddx"]), int(row["ddy"]),
                    )
                    if key in state.exact_codewords:
                        raise ValueError(
                            "duplicate experimental BRAM control route codeword %r" %
                            (key,)
                        )
                    parse = lambda value: [
                        int(item) for item in value.split(";") if item
                    ]
                    state.exact_codewords[key] = (
                        row["config"], parse(row["clear_selections"]),
                        parse(row["set_selections"]),
                    )
            print("loaded experimental BRAM control route codewords")
        if options.enabled("AGAMEMNON_X9_Q5_ALT_EXPERIMENT"):
            alternate = chipdb_root / "bram_x9_data5_alt_candidate_pip_cfg.csv"
            if not alternate.exists():
                raise ValueError(
                    "BRAM x9 Q5 alternate mode requires chipdb/"
                    "bram_x9_data5_alt_candidate_pip_cfg.csv"
                )
            with alternate.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    key = (row["dst_res"], row["src_res"], int(row["ddx"]), int(row["ddy"]))
                    state.exact_pips.setdefault(key, []).append(
                        (int(row["byte"]), int(row["mask"]))
                    )
        resolver = chipdb_root / "bram_resolver.json"
        if not resolver.exists():
            raise ValueError("bram requires chipdb/bram_resolver.json when BRAM is used")
        state.resolver = json.loads(resolver.read_text(encoding="utf-8"))
        print("loaded BramTile sel resolver (L0=%d L1=%d L2=%d)" % (
            len(state.resolver["L0"]), len(state.resolver["L1"]),
            len(state.resolver["L2"]),
        ))

    @staticmethod
    def _load_control_codewords(state, chipdb_root):
        # Flat configuration storage does not mean one selector field per
        # family. Select only this destination's field, keyed by its source.
        # Scoped checkpoint replacements loaded above retain precedence.
        path = chipdb_root / "bram_control_codewords.csv"
        seen = set()
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                family, index = row["dst_family"], int(row["dst_index"])
                if family not in BRAM_CONTROL_FIELD_WIDTHS or not 0 <= index < (
                        10 if family == "KMUX" else 16):
                    raise ValueError("invalid BRAM control destination %s%d" % (family, index))
                key = (family, index, row["src_family"], int(row["src_index"]),
                       int(row["ddx"]), int(row["ddy"]))
                if key in seen:
                    raise ValueError("duplicate BRAM control codeword %r" % (key,))
                seen.add(key)
                width = BRAM_CONTROL_FIELD_WIDTHS[family]
                clear = list(range(index * width, (index + 1) * width))
                sels = [int(s) for s in row["set_selections"].split(";") if s]
                if not sels or len(set(sels)) != len(sels) or not set(sels).issubset(clear):
                    raise ValueError("BRAM control codeword writes outside its field: %r" % (key,))
                state.exact_codewords.setdefault(key, ("CFG_" + family, clear, sels))
        print("loaded %d field-local BRAM control codeword(s)" % len(seen))

    @staticmethod
    def _resolve(state, destination_family, destination_index, source_family,
                 source_index, delta_x, delta_y):
        resolver = state.resolver
        if resolver is None:
            return None
        if destination_family in BRAM_CONTROL_FAMILIES:
            return None  # aggregate CTRL rows conflate sources and adjacent fields
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
                      route_clears=None, debug=False):
        sx, sy, sf, si = source
        dx, dy, df, di = destination
        if (source, destination) == BRAM_FIXED_PRESENTATION:
            return state.qualified_profile in BRAM_TMUX9_QUALIFIED_PROFILES
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
        # X13Y4 was the original single-site model and remains resolvable for
        # direct resolver unit calls that do not construct a full BramState.
        # Additional physical sites are admitted only when a BRAM cell at that
        # exact coordinate is present in the prepared design.
        active_sites = {(13, 4)} | {(cell[0], cell[1]) for cell in state.cells}
        if (dx, dy) not in active_sites or df not in BRAM_FAMILIES:
            return None
        codeword = state.exact_codewords.get((df, di, sf, si, dx - sx, dy - sy))
        if codeword is not None:
            config, clear_selections, set_selections = codeword
            resolved_clears = [cell_map.get((dx, dy, config, sel)) for sel in clear_selections]
            resolved_sets = [cell_map.get((dx, dy, config, sel)) for sel in set_selections]
            missing = [
                (op, sel) for op, sels, bits in (
                    ("clear", clear_selections, resolved_clears),
                    ("set", set_selections, resolved_sets),
                ) for sel, bit in zip(sels, bits) if bit is None
            ]
            if missing:
                raise SystemExit(
                    "exact BRAM route codeword %s has no physical cell(s) %s"
                    % (config, missing)
                )
            if route_clears is None:
                raise SystemExit(
                    "exact BRAM route codeword %s requires clear-bit emission" % config
                )
            if df in BRAM_CONTROL_FAMILIES:
                field_key = (dx, dy, df, di)
                previous = state.control_owners.get(field_key)
                if previous is not None and previous != source:
                    raise SystemExit("conflicting BRAM control sources for %r: %r and %r" %
                                     (field_key, previous, source))
                state.control_owners[field_key] = source
            # Control blobs describe the unrouted baseline and can assert a
            # selector that this routed input must turn off (the Port-A ROM
            # baseline asserts TileAsync sel 3; MCU_RESETN needs sel 2,7).
            # A global clear phase followed by a global set phase would let the
            # stale blob bit win unless it is removed from the BRAM feature's
            # pending sets as part of this exact field replacement.
            cleared = set(resolved_clears)
            state.sets[:] = [bit for bit in state.sets if bit not in cleared]
            route_clears.extend(resolved_clears)
            route_sets.extend(resolved_sets)
            return True
        if df in BRAM_CONTROL_FAMILIES:
            if debug:
                print("  UNMAPPED[bram-control] %r <- %r" % (destination, source))
            return False  # unknown source: never emit a family-wide union or fixed blob
        # bram_pip_cfg.csv contains absolute X13Y4 bit locations.  Other
        # sites use the same recovered selector model but their independently
        # mapped bram_cell.csv coordinates; never transplant an absolute Y4
        # byte into another array.
        exact = state.exact_pips.get(key) if (dx, dy) == (13, 4) else None
        if exact:
            route_sets.extend(exact)
            return True
        selectors = self._resolve(state, df, di, sf, si, dx - sx, dy - sy)
        config = "CFG_%s" % df if df in BRAM_FLAT_FAMILIES else "CFG_%s%d" % (
            df, di // mux_groups[df]
        )
        count = 0
        if selectors:
            resolved = [
                (selector, cell_map.get((dx, dy, config, selector)))
                for selector in selectors
            ]
            missing = [selector for selector, bit in resolved if bit is None]
            if missing and len(missing) != len(resolved):
                # A partial BramTile codeword is not a weaker version of the
                # right selection, it is a different mux input: the image
                # config-accepts and the BRAM port reads the wrong place (or
                # nothing). A codeword with NO cells at all still reports
                # unmapped below, which the routing gate refuses.
                raise SystemExit(
                    "BRAM routing selector %s @X%dY%d has no config cell for "
                    "selector(s) %s in bram_cell.csv/pips_full.csv; refusing to "
                    "emit a partial BramTile codeword for %s%d <- %s%d"
                    % (config, dx, dy, missing, df, di, sf, si)
                )
            for _selector, bit in resolved:
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
