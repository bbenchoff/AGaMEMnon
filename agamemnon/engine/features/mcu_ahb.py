"""External MCU-AHB exact-corridor selector metadata and loading."""

from __future__ import annotations

import csv
import collections
import os
import re
from dataclasses import dataclass

from .protocol import EmissionPhase, FeatureDescriptor, WritableRegion


EXACT_PIP_CFG_FILES = (
    "mcu_ahb32_pip_cfg.csv",
    "mcu_ahb32_addr_pip_cfg.csv",
    "mcu_ahb_control_pip_cfg.csv",
    "mcu_haddr_missing_pip_cfg.csv",
    "mcu_haddr5_logic_pip_cfg.csv",
    "mcu_haddr3_logic_pip_cfg.csv",
    "mcu_hwrite_hwdata1_hburst2_pip_cfg.csv",
    "mcu_haddr_full_pip_cfg.csv",
)

# Qualified exact fields that share the hard MCU/fabric boundary resolver.
# They are kept separate from the original AHB32 tables so their evidence
# lineage remains visible while loading is centralized in this feature.
CORRIDOR_PIP_CFG_FILES = (
    "bram_x9_haddr_pip_cfg.csv",
    "bram_x9_data5_pip_cfg.csv",
    "bram_address_gnd_terminal_pip_cfg.csv",
    "mcu_resetn_fabric_pip_cfg.csv",
    "mcu_local_int0_pip_cfg.csv",
    "mcu_local_int1_pip_cfg.csv",
    "mcu_local_int2_pip_cfg.csv",
    "mcu_local_int3_pip_cfg.csv",
    "mcu_slave_ahb_response_pip_cfg.csv",
    "mcu_slave_ahb_hrdata1_4_pip_cfg.csv",
    "mcu_slave_ahb_hrdata5_8_pip_cfg.csv",
    "mcu_slave_ahb_hrdata9_12_pip_cfg.csv",
    "mcu_slave_ahb_hrdata13_16_pip_cfg.csv",
    "mcu_slave_ahb_hrdata17_20_pip_cfg.csv",
    "mcu_slave_ahb_hrdata21_24_pip_cfg.csv",
    "mcu_slave_ahb_hrdata25_28_pip_cfg.csv",
    "mcu_slave_ahb_hrdata29_31_pip_cfg.csv",
    "mcu_slave_ahb_hrdata_grouped_full_pip_cfg.csv",
    "mcu_slave_ahb_request_control_pip_cfg.csv",
    "mcu_slave_ahb_request_payload_pip_cfg.csv",
    "mcu_dma_response_all_pip_cfg.csv",
    "mcu_dma_request_all_pip_cfg.csv",
    "mcu_stop_pip_cfg.csv",
    "analog_adc0_db0_pip_cfg.csv",
    "analog_adc0_eoc_pip_cfg.csv",
    "analog_adc0_db1_pip_cfg.csv",
)

EXIT_PAIR_FILES = (
    "mcu_hrdata_lanes.csv",
    "mcu_hrdata_addr_lanes.csv",
    "mcu_ahb_response_controls.csv",
    "mcu_ahb_control_exit_pairs.csv",
    "mcu_haddr_missing_exit_pairs.csv",
    "mcu_haddr_full_exit_pairs.csv",
    "bram_x9_data3_mcu_exit.csv",
    "bram_x9_data4_mcu_exit.csv",
    "bram_x9_data5_mcu_exit.csv",
)

ARCHITECTURE_FILES = (
    "pips_mcuedge_routing.csv",
    "mcu_hrdata_lanes.csv",
    "mcu_ahb_response_controls.csv",
    "mcu_hwdata_lanes.csv",
    "mcu_ahb_request_controls.csv",
    "mcu_ahb_control_oracle_paths.csv",
    "mcu_hwrite_hwdata1_hburst2_paths.csv",
    "mcu_ahb_write_qualifier_paths.csv",
    "mcu_ahb_write_qualifier_slice1_paths.csv",
    "mcu_ahb_pipelined_token_paths.csv",
    "mcu_ahb_pipelined_internal_paths.csv",
    "mcu_ahb_pipelined_wait_paths.csv",
    "mcu_ahb_pipelined_apply_candidate_paths.csv",
    "mcu_hwdata0_logic_paths.csv",
    "mcu_hwdata0_storage_paths.csv",
    "mcu_hwdata1_logic_paths.csv",
    "mcu_hwdata2_logic_paths.csv",
    "mcu_hwdata3_logic_paths.csv",
    "mcu_hwdata4_logic_paths.csv",
    "mcu_hwdata5_logic_paths.csv",
    "mcu_hwdata7_logic_paths.csv",
    "mcu_scratch2_hrdata1_paths.csv",
    "mcu_scratch2_internal_paths.csv",
    "mcu_scratch3_final_paths.csv",
    "mcu_scratch3_internal_candidate_paths.csv",
    "mcu_scratch4_final_paths.csv",
    "mcu_scratch5_final_paths.csv",
    "mcu_hrdata2_x15y12_s2_paths.csv",
    "mcu_haddr_lanes.csv",
    "mcu_haddr_missing_lanes.csv",
    "mcu_haddr_missing_paths.csv",
    "mcu_haddr5_logic_paths.csv",
    "mcu_haddr3_logic_paths.csv",
    "mcu_haddr2_logic_paths.csv",
    "mcu_haddr_missing_exit_pairs.csv",
    "mcu_ahb_control_exit_pairs.csv",
    "mcu_haddr_full_exit_pairs.csv",
    "mcu_ahb32_corridors.csv",
    "mcu_haddr_full_corridors.csv",
    "mcu_hrdata_addr_lanes.csv",
    "bram_x9_haddr_paths.csv",
    "bram_x9_data5_paths.csv",
    "bram_x9_data5_alt_candidate_paths.csv",
    "bram_x9_data4_simultaneous_paths.csv",
    "mcu_resetn_fabric_path.csv",
    "mcu_slave_ahb_response_paths.csv",
    "mcu_slave_ahb_hrdata_grouped_full_paths.csv",
    "mcu_slave_ahb_request_control_paths.csv",
    "mcu_slave_ahb_request_payload_paths.csv",
    "mcu_dma_response_all_paths.csv",
    "mcu_dma_request_all_paths.csv",
    "mcu_stop_path.csv",
    "analog_adc0_db0_path.csv",
    "analog_adc0_eoc_path.csv",
    "analog_adc0_db1_path.csv",
)

# Retained discovery tables are non-emissive, but still have one semantic
# owner so the chipdb inventory cannot silently grow outside the registry.
ARCHIVAL_FILES = (
    "mcu_ahb32_addr_corridors.csv",
    "mcu_ahb_write_qualifier_pip_cfg.csv",
    "mcu_dma_request0_paths.csv",
    "mcu_dma_request0_pip_cfg.csv",
    "mcu_dma_response0_paths.csv",
    "mcu_dma_response0_pip_cfg.csv",
    "mcu_hwdata7_logic_pip_cfg.csv",
    "mcu_local_int0_path.csv",
    "mcu_local_int1_path.csv",
    "mcu_local_int2_path.csv",
    "mcu_local_int3_path.csv",
    "mcu_logic_consumer_footprints.csv",
    "mcu_scratch3_candidate_pip_cfg.csv",
    "mcu_slave_ahb_hrdata1_4_paths.csv",
    "mcu_slave_ahb_hrdata5_8_paths.csv",
    "mcu_slave_ahb_hrdata9_12_paths.csv",
    "mcu_slave_ahb_hrdata13_16_paths.csv",
    "mcu_slave_ahb_hrdata17_20_paths.csv",
    "mcu_slave_ahb_hrdata21_24_paths.csv",
    "mcu_slave_ahb_hrdata25_28_paths.csv",
    "mcu_slave_ahb_hrdata29_31_paths.csv",
)

_WIRE_RE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z_]+?)0*(\d+)")


@dataclass(frozen=True)
class McuRoutingMetadata:
    exact_pips: dict
    exit_pairs: dict


def exact_wire(text):
    match = _WIRE_RE.fullmatch(text)
    if not match:
        raise SystemExit("bad exact MCU corridor wire: %s" % text)
    x, y, family, index = match.groups()
    return int(x), int(y), family, int(index)


class McuAhbFeature:
    descriptor = FeatureDescriptor(
        feature_id="mcu_ahb",
        options=(
            "AGAMEMNON_SCRATCH3_EXPERIMENT",
            "AGAMEMNON_PIPELINED_APPLY_EXPERIMENT",
            "AGAMEMNON_X9_FULL_ADDRESS",
        ),
        chipdb_files=(
            EXACT_PIP_CFG_FILES + CORRIDOR_PIP_CFG_FILES + ARCHITECTURE_FILES +
            tuple(filename for filename in EXIT_PAIR_FILES if filename not in ARCHITECTURE_FILES) +
            ARCHIVAL_FILES
        ),
        writable_regions=tuple(
            WritableRegion(kind="selector_table", source=filename)
            for filename in EXACT_PIP_CFG_FILES + CORRIDOR_PIP_CFG_FILES
        ),
        phase=EmissionPhase.MCU_EDGES,
        evidence=(
            "qualification/mcu_ahb32_read_evidence.jsonl",
            "qualification/mcu_ahb32_write_evidence.jsonl",
            "qualification/mcu_ahb_register_bank_evidence.jsonl",
        ),
        maturity="release",
        architecture=(
            "Construct typed MCU/hard-block corridors, endpoints, and boundary BELs."
        ),
        bitstream=(
            "Load the exact node-local selector fields for qualified External-AHB "
            "data, address, control, and register-bank corridors."
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
        n_wire = shared["wire_count"]
        seen_pip = shared["seen_pips"]
        _wire_delay = shared["wire_delay"]
        EDGE_BLACKLIST = shared["edge_blacklist"]
        _blacklisted = shared["is_blacklisted"]
        _outside_bram_corridor = shared["outside_bram_corridor"]

        # ---- 5. MCU-edge routing pips (UFMTILE boundary the RRG does not enumerate) ----
        # rrg_edges_full.csv is LogicTile-only; it has NO UFMTILE MCU-edge routing. These pips come from
        # the silicon-validated vendor loopback (loopback/logic_db/route.tx, net #13 gpio4_io_out_data[1]):
        #   MCU(alta_rv3200@0,5) -> BufMUX10 -> InputMUX11 @UFMTILE(11,5)   (din enters the fabric)
        #   -> RMUX93@LogicTILE(11,4) -> RMUX92@LogicTILE(10,4)             (already in the RRG mesh)
        #   -> BBMUXS02@UFMTILE(10,5) -> SinkMUXPseudo143@UFMTILE(0,5) -> MCU  (dout returns to the MCU)
        # We load them here as ROUTE pips so the router can cross the MCU edge. The two alta_rv3200
        # self-edges are represented by the MCU bel pin binding (below), not as router pips.
        bit_entry = {}                   # bit -> fabric-entry wire the MCU DRIVES (bel-out target)
        bit_exit  = {}                   # bit -> fabric-exit wire that FEEDS the MCU (bel-in source)
        n_mpip = 0; m_skip = 0
        mcuedge_csv = os.path.join(DATA, "pips_mcuedge_routing.csv")
        if os.path.exists(mcuedge_csv):
            with open(mcuedge_csv) as f:
                for r in csv.DictReader(f):
                    if _outside_bram_corridor(r):
                        m_skip += 1; continue
                    if EDGE_BLACKLIST and _blacklisted(r):   # honor the blacklist on the MCU edge too
                        m_skip += 1; continue
                    bit = int(r.get("bit") or 0)          # per-GPIO-bit MCU edge (multi-signal); default 0
                    s_is_mcu = r["src_res"].startswith("alta_rv")
                    t_is_mcu = r["dst_res"].startswith("alta_rv")
                    s = W(r["src_x"], r["src_y"], r["src_res"])
                    t = W(r["dst_x"], r["dst_y"], r["dst_res"])
                    if s_is_mcu:            # MCU -> fabric-entry wire: record entry wire, no pip
                        if t in wireset: bit_entry[bit] = t
                        continue
                    if t_is_mcu:            # fabric-exit wire -> MCU: record exit wire, no pip
                        if s in wireset: bit_exit[bit] = s
                        continue
                    if s not in wireset or t not in wireset:
                        m_skip += 1; continue
                    nm = "%s.%s" % (s, t)
                    if nm in seen_pip:      # TRUE-TOPO union may already carry this MCU-edge hop
                        continue
                    ctx.addPip(name=nm, type="MCUEDGE", srcWire=s, dstWire=t,
                               delay=_wire_delay(r["src_res"]), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                    seen_pip.add(nm); n_mpip += 1
            print("AGRV2K arch: added %d MCU-edge pips (%d skipped); bits=%s"
                  % (n_mpip, m_skip, sorted(set(bit_entry) & set(bit_exit))))

        # The AHB read-data bus is physically wider than the original GPIO-loopback
        # harvest.  mcu_hrdata_lanes.csv records all 32 vendor-routed hrdata endpoints,
        # including the BBMUXW family and the second east-edge row.  ``bel_bit`` is an
        # internal, collision-free BEL id (20..22 are already the three qualified AHB
        # input BELs); ``logical_bit`` is the actual hrdata bit and is consumed by the
        # packer/verification mapping.
        _hrlane_csv = os.path.join(DATA, "mcu_hrdata_lanes.csv")
        _n_hrlane = 0; _hrlane_skip = 0
        if os.path.exists(_hrlane_csv):
            for _r in csv.DictReader(open(_hrlane_csv)):
                _bit = int(_r["bel_bit"])
                _src = W(_r["src_x"], _r["src_y"], _r["src_res"])
                _edge = W(_r["edge_x"], _r["edge_y"], _r["edge_res"])
                _sink = W(0, 5, _r["sink_res"])
                if _src not in wireset or _edge not in wireset or _sink not in wireset:
                    _hrlane_skip += 1
                    continue
                for _a, _b in ((_src, _edge), (_edge, _sink)):
                    _nm = "%s.%s" % (_a, _b)
                    if _nm not in seen_pip:
                        ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_a, dstWire=_b,
                                   delay=_wire_delay(_a.rsplit("_", 1)[-1]),
                                   loc=Loc(int(_r["edge_x"]), int(_r["edge_y"]), 0))
                        seen_pip.add(_nm); n_mpip += 1
                bit_exit[_bit] = _sink
                _n_hrlane += 1
            print("AGRV2K arch: loaded %d/32 exact AHB hrdata lane(s) (%d skipped)"
                  % (_n_hrlane, _hrlane_skip))

        # External AHB response controls occupy the two flattened sink slots just
        # before HRDATA. Their exact RMUX->BBMUX->SinkPseudo routes and selector
        # pairs come from the control-plane oracle.
        _response_csv = os.path.join(DATA, "mcu_ahb_response_controls.csv")
        _n_response = 0; _response_skip = 0
        if os.path.exists(_response_csv):
            for _r in csv.DictReader(open(_response_csv)):
                _bit = int(_r["bel_bit"])
                _src = W(_r["src_x"], _r["src_y"], _r["src_res"])
                _edge = W(_r["edge_x"], _r["edge_y"], _r["edge_res"])
                _sink = W(0, 5, _r["sink_res"])
                if _src not in wireset or _edge not in wireset or _sink not in wireset:
                    _response_skip += 1
                    continue
                for _a, _b in ((_src, _edge), (_edge, _sink)):
                    _nm = "%s.%s" % (_a, _b)
                    if _nm not in seen_pip:
                        ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_a, dstWire=_b,
                                   delay=_wire_delay(_a.rsplit("_", 1)[-1]),
                                   loc=Loc(int(_r["edge_x"]), int(_r["edge_y"]), 0))
                        seen_pip.add(_nm); n_mpip += 1
                bit_exit[_bit] = _sink
                _n_response += 1
            print("AGRV2K arch: loaded %d/2 exact AHB response control lane(s) (%d skipped)"
                  % (_n_response, _response_skip))

        # Full-width MCU-to-fabric AHB write-data sources recovered from the same
        # simultaneous vendor loopback.  The BEL output is the per-lane UFMTILE
        # BufMUX root; for lanes with an explicit InputMUX, add that zero-config hard
        # hop here.  The remaining path into the LogicTile mesh is already present in
        # corpus_conduction.csv from the vendor route.
        _hwlane_csv = os.path.join(DATA, "mcu_hwdata_lanes.csv")
        _n_hwlane = 0; _hwlane_skip = 0
        if os.path.exists(_hwlane_csv):
            for _r in csv.DictReader(open(_hwlane_csv)):
                _bit = int(_r["bel_bit"])
                _entry = W(_r["entry_x"], _r["entry_y"], _r["entry_res"])
                if _entry not in wireset:
                    _hwlane_skip += 1
                    continue
                _next_res = _r.get("next_res", "")
                if _next_res:
                    _next = W(_r["entry_x"], _r["entry_y"], _next_res)
                    if _next not in wireset:
                        _hwlane_skip += 1
                        continue
                    _nm = "%s.%s" % (_entry, _next)
                    if _nm not in seen_pip:
                        ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_entry, dstWire=_next,
                                   delay=_wire_delay(_r["entry_res"]),
                                   loc=Loc(int(_r["entry_x"]), int(_r["entry_y"]), 0))
                        seen_pip.add(_nm); n_mpip += 1
                bit_entry[_bit] = _entry
                _n_hwlane += 1
            print("AGRV2K arch: loaded %d/32 exact AHB hwdata lane(s) (%d skipped)"
                  % (_n_hwlane, _hwlane_skip))

        # Remaining External AHB request controls. HWRITE and HTRANS[1] retain
        # their historical BEL ids; the other controls use collision-free ids.
        _request_csv = os.path.join(DATA, "mcu_ahb_request_controls.csv")
        _n_request = 0; _request_skip = 0
        if os.path.exists(_request_csv):
            for _r in csv.DictReader(open(_request_csv)):
                _bit = int(_r["bel_bit"])
                _entry = W(_r["entry_x"], _r["entry_y"], _r["entry_res"])
                if _entry not in wireset:
                    _request_skip += 1
                    continue
                _next_res = _r.get("next_res", "")
                if _next_res:
                    _next = W(_r["entry_x"], _r["entry_y"], _next_res)
                    if _next not in wireset:
                        _request_skip += 1
                        continue
                    _nm = "%s.%s" % (_entry, _next)
                    if _nm not in seen_pip:
                        ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_entry, dstWire=_next,
                                   delay=_wire_delay(_r["entry_res"]),
                                   loc=Loc(int(_r["entry_x"]), int(_r["entry_y"]), 0))
                        seen_pip.add(_nm); n_mpip += 1
                bit_entry[_bit] = _entry
                _n_request += 1
            print("AGRV2K arch: loaded %d/10 exact AHB request control lane(s) (%d skipped)"
                  % (_n_request, _request_skip))

        # Preserve every non-BEL routing hop observed in the simultaneous control
        # oracle. Rows touching alta_slice are logical cell arcs and remain the
        # placer/packer responsibility; all other rows are physical pips.
        _n_control_path = 0; _control_path_skip = 0
        _control_names = ["mcu_ahb_control_oracle_paths.csv",
                              "mcu_hwrite_hwdata1_hburst2_paths.csv",
                              "mcu_ahb_write_qualifier_paths.csv",
                              "mcu_ahb_write_qualifier_slice1_paths.csv",
                              "mcu_ahb_pipelined_token_paths.csv",
                              "mcu_ahb_pipelined_internal_paths.csv",
                              "mcu_ahb_pipelined_wait_paths.csv",
                              "mcu_hwdata0_logic_paths.csv",
                              "mcu_hwdata0_storage_paths.csv",
                              "mcu_hwdata1_logic_paths.csv",
                              "mcu_hwdata2_logic_paths.csv",
                              "mcu_hwdata3_logic_paths.csv",
                              "mcu_hwdata4_logic_paths.csv",
                              "mcu_hwdata5_logic_paths.csv",
                              "mcu_scratch3_final_paths.csv",
                              "mcu_scratch4_final_paths.csv",
                              "mcu_scratch5_final_paths.csv",
                              "mcu_scratch2_hrdata1_paths.csv",
                              "mcu_scratch2_internal_paths.csv",
                              "mcu_hrdata2_x15y12_s2_paths.csv",
                              "mcu_hwdata7_logic_paths.csv"]
        if os.environ.get("AGAMEMNON_SCRATCH3_EXPERIMENT"):
            _control_names.append("mcu_scratch3_internal_candidate_paths.csv")
        if os.environ.get("AGAMEMNON_PIPELINED_APPLY_EXPERIMENT"):
            _control_names.append("mcu_ahb_pipelined_apply_candidate_paths.csv")
        for _control_name in _control_names:
            _control_paths_csv = os.path.join(DATA, _control_name)
            if not os.path.exists(_control_paths_csv):
                continue
            for _r in csv.DictReader(open(_control_paths_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                if "_alta_slice" in _src or "_alta_slice" in _dst:
                    continue
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _control_path_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_control_path += 1
        print("AGRV2K arch: loaded %d AHB control oracle hop(s) (%d skipped)"
              % (_n_control_path, _control_path_skip))

        # Protocol-valid address-to-read-data oracles: expose all 32 HADDR bits as
        # fixed MCU_DIN roots.  The original table covers [27:2]; the full identity
        # oracle contributes the six formerly missing lanes without renumbering the
        # already released BELs.
        _n_halane = 0; _halane_skip = 0
        for _halane_name in ("mcu_haddr_lanes.csv", "mcu_haddr_missing_lanes.csv"):
            _halane_csv = os.path.join(DATA, _halane_name)
            if not os.path.exists(_halane_csv):
                continue
            for _r in csv.DictReader(open(_halane_csv)):
                _entry = W(_r["entry_x"], _r["entry_y"], _r["entry_res"])
                if _entry not in wireset:
                    _halane_skip += 1
                    continue
                _next_res = _r.get("next_res", "")
                if _next_res:
                    _next = W(_r["entry_x"], _r["entry_y"], _next_res)
                    if _next not in wireset:
                        _halane_skip += 1
                        continue
                    _nm = "%s.%s" % (_entry, _next)
                    if _nm not in seen_pip:
                        ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_entry, dstWire=_next,
                                   delay=_wire_delay(_r["entry_res"]),
                                   loc=Loc(int(_r["entry_x"]), int(_r["entry_y"]), 0))
                        seen_pip.add(_nm); n_mpip += 1
                bit_entry[int(_r["bel_bit"])] = _entry
                _n_halane += 1
        print("AGRV2K arch: loaded %d/32 exact AHB haddr source lane(s) (%d skipped)"
              % (_n_halane, _halane_skip))

        # Preserve the six new HADDR-to-HRDATA oracle corridors.  This both supplies
        # boundary pips absent from the older corpus and gives the strict smoke a
        # completely vendor-observed path for the newly recovered lanes.
        _n_hamissing_path = 0; _hamissing_path_skip = 0
        for _hapath_name in ("mcu_haddr_missing_paths.csv", "mcu_haddr5_logic_paths.csv",
                             "mcu_haddr3_logic_paths.csv", "mcu_haddr2_logic_paths.csv"):
            _hamissing_paths = os.path.join(DATA, _hapath_name)
            if not os.path.exists(_hamissing_paths):
                continue
            for _r in csv.DictReader(open(_hamissing_paths)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                # alta_slice rows describe a LUT cell arc in the vendor route,
                # not a programmable routing pip.  Exposing them as graph edges
                # lets nextpnr route through an uninstantiated LUT whose INIT is
                # never emitted (observed as stuck-high HRDATA lanes on silicon).
                if "_alta_slice" in _src or "_alta_slice" in _dst:
                    continue
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _hamissing_path_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_hamissing_path += 1
        print("AGRV2K arch: loaded %d qualified HADDR oracle hop(s) (%d skipped)"
              % (_n_hamissing_path, _hamissing_path_skip))

        # Promote the complete simultaneous vendor corridors as ordinary graph
        # pips.  Without these, 18 of the 66 MCU_DIN entry roots (HWDATA[10:17],
        # HWDATA[31:30], HADDR[9:6], HADDR[23:22], HADDR[27:26]) have zero
        # downhill edges in the release graph: their roots were promoted but their
        # first mesh hops exist only in the exact-replay corridor tables.  Every
        # hop is vendor-observed and its selector is in the matching pip_cfg table
        # consumed by bitgen; strict bitgen still fails closed on any pip without
        # an encoding.
        # A corridor hop into a BBMUX family is a boundary-exit selector; the
        # graph must not expose one that strict bitgen cannot encode.  Gather the
        # encodable exit pairs from every table bitgen ingests and gate on them.
        _encodable_exits = set()
        for _enc_name in ("mcu_haddr_missing_exit_pairs.csv", "mcu_ahb_control_exit_pairs.csv",
                          "mcu_haddr_full_exit_pairs.csv"):
            _enc_csv = os.path.join(DATA, _enc_name)
            if not os.path.exists(_enc_csv):
                continue
            for _r in csv.DictReader(open(_enc_csv)):
                _encodable_exits.add("X%sY%s_%s%s" % (_r["src_x"], _r["src_y"], _r["src_res"],
                                                      ".X%sY%s_%s" % (_r["edge_x"], _r["edge_y"],
                                                                      _r["edge_res"])))
        for _enc_name in ("mcu_ahb32_pip_cfg.csv", "mcu_haddr_full_pip_cfg.csv",
                          "mcu_ahb_control_pip_cfg.csv", "mcu_haddr_missing_pip_cfg.csv",
                          "mcu_haddr5_logic_pip_cfg.csv",
                          "mcu_haddr3_logic_pip_cfg.csv"):
            _enc_csv = os.path.join(DATA, _enc_name)
            if not os.path.exists(_enc_csv):
                continue
            for _r in csv.DictReader(open(_enc_csv)):
                _encodable_exits.add("%s.%s" % (_r["src_wire"], _r["dst_wire"]))
        for _corr_name, _corr_evidence in (("mcu_ahb32_corridors.csv", "ahbrwide32"),
                                           ("mcu_haddr_full_corridors.csv", "haddr-full")):
            _corr_csv = os.path.join(DATA, _corr_name)
            if not os.path.exists(_corr_csv):
                continue
            _n_corr = 0; _corr_skip = 0
            for _r in csv.DictReader(open(_corr_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                # A vendor corridor may include a real LUT buffer.  Its
                # IMUX->alta_slice->OMUX segment is a logical cell arc and must be
                # implemented by placement/packing, never admitted as a free pip.
                if "_alta_slice" in _src or "_alta_slice" in _dst:
                    continue
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _corr_skip += 1
                    continue
                # A corridor hop into a BBMUX exit family must be encodable by
                # bitgen or the router will land a net on a pip with no selector.
                # BBMUXW exits are keyed src->edge in mcu_haddr_full_exit_pairs;
                # keep the gate only for exit families with NO recovered pair for
                # this exact edge, so a missing selector fails at graph build (a
                # clear diagnostic) rather than deep in bitgen.
                if "_BBMUX" in _dst and _dst.split("_", 1)[1][:6] in ("BBMUXW",) \
                        and "%s.%s" % (_src, _dst) not in _encodable_exits:
                    _corr_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_corr += 1
            print("AGRV2K arch: loaded %d %s corridor hop(s) (%d skipped)"
                  % (_n_corr, _corr_evidence, _corr_skip))

        # Native L48 x9 positive control: preserve the qualified HADDR[2:5] to BRAM
        # AddressA[3:6] ingress.  The general MCU-entry gate intentionally drops
        # unrestricted BufMUX fanout, and the BramTile coverage gate intentionally
        # drops unqualified terminal choices; this one silicon-positive vendor
        # path supplies exact selector fields for every hop in both gates.
        _x9_haddr_paths = os.path.join(DATA, "bram_x9_haddr_paths.csv")
        _n_x9_haddr = 0; _x9_haddr_skip = 0
        if os.path.exists(_x9_haddr_paths):
            for _r in csv.DictReader(open(_x9_haddr_paths)):
                # HADDR[6:11] is a vendor-control extraction for the bounded
                # complete-address experiment.  Keep it out of the normal strict
                # graph until the coupled silicon discriminator qualifies it.
                if int(_r["logical_bit"]) > 5 and not OPTIONS.enabled("AGAMEMNON_X9_FULL_ADDRESS"):
                    continue
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _x9_haddr_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="BRAMX9", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_x9_haddr += 1
            print("AGRV2K arch: loaded %d x9 HADDR-to-BRAM hop(s) (%d skipped)"
                  % (_n_x9_haddr, _x9_haddr_skip))

        # The first open q5 graph used a q4-shaped path that config-accepted but
        # returned a constant.  A coherent corridor transplant and an open-bitgen
        # replay both conduct on silicon.  Admit this complete source-to-sink path
        # atomically: the middle selector fields and BBMUX exit codeword live in
        # the companion tables consumed by strict bitgen.
        _x9_data5_paths = os.path.join(DATA, "bram_x9_data5_paths.csv")
        _n_x9_data5 = 0; _x9_data5_skip = 0
        if os.path.exists(_x9_data5_paths):
            for _r in csv.DictReader(open(_x9_data5_paths)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _x9_data5_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="BRAMX9", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_x9_data5 += 1
            print("AGRV2K arch: loaded %d x9 data5 egress hop(s) (%d skipped)"
                  % (_n_x9_data5, _x9_data5_skip))

        # q4 and q5 cannot share their individually qualified RMUX92 source.  The
        # paired silicon oracle qualifies this disjoint q4 route as one atomic
        # corridor, including its source-dependent BBMUXE06 selector.  The uarch
        # reserves it only when both physical DataOutA13/A14 nets are live; load
        # every hop here so that pre-routing fails closed if the footprint is ever
        # incomplete.
        _x9_data4_pair = os.path.join(DATA, "bram_x9_data4_simultaneous_paths.csv")
        _n_x9_data4_pair = 0; _x9_data4_pair_skip = 0
        if os.path.exists(_x9_data4_pair):
            for _r in csv.DictReader(open(_x9_data4_pair)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _x9_data4_pair_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="BRAMX9", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_x9_data4_pair += 1
            print("AGRV2K arch: loaded %d simultaneous x9 data4 egress hop(s) (%d skipped)"
                  % (_n_x9_data4_pair, _x9_data4_pair_skip))

        # Vendor-routed x18 artifacts show the complementary DataOutA14 source
        # edge through RMUX75, which is required to use data4 and data5 together.
        # The earlier x9 negative combined that source with a different downstream
        # route, so keep this complete alternate corridor experiment-gated until a
        # same-image q4/q5 silicon trial observes both lanes.
        if os.environ.get("AGAMEMNON_X9_Q5_ALT_EXPERIMENT"):
            _x9_q5_alt = os.path.join(DATA, "bram_x9_data5_alt_candidate_paths.csv")
            if os.path.exists(_x9_q5_alt):
                for _r in csv.DictReader(open(_x9_q5_alt)):
                    _src = _r["src_wire"]; _dst = _r["dst_wire"]
                    _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                    if _src not in wireset or _dst not in wireset or not _dm:
                        continue
                    _nm = "%s.%s" % (_src, _dst)
                    if _nm not in seen_pip:
                        ctx.addPip(name=_nm, type="BRAMX9", srcWire=_src,
                                   dstWire=_dst,
                                   delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                   loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                        seen_pip.add(_nm); n_mpip += 1

        # Active-low MCU reset source routed into an ordinary LUT input by the
        # resetn^HADDR[2] vendor oracle.  This is intentionally a data-path source;
        # dedicated tile asynchronous-reset controls remain a separate model.
        _reset_path_csv = os.path.join(DATA, "mcu_resetn_fabric_path.csv")
        _n_reset_path = 0; _reset_path_skip = 0
        if os.path.exists(_reset_path_csv):
            _reset_root = None
            for _r in csv.DictReader(open(_reset_path_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                if _reset_root is None:
                    _reset_root = _src
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _reset_path_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_reset_path += 1
            if _reset_root in wireset:
                bit_entry[120] = _reset_root
            else:
                _reset_path_skip += 1
            print("AGRV2K arch: loaded %d reset-to-fabric hop(s) (%d skipped)"
                  % (_n_reset_path, _reset_path_skip))

        # MCU system-control stop observation. This is exposed strictly as a data
        # source on the isolated vendor corridor; no clock-gating semantics are
        # inferred from the signal name.
        _stop_path_csv = os.path.join(DATA, "mcu_stop_path.csv")
        _n_stop_path = 0; _stop_path_skip = 0
        if os.path.exists(_stop_path_csv):
            _stop_root = None
            for _r in csv.DictReader(open(_stop_path_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                if _stop_root is None:
                    _stop_root = _src
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _stop_path_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_stop_path += 1
            if _stop_root in wireset:
                bit_entry[258] = _stop_root
            else:
                _stop_path_skip += 1
            print("AGRV2K arch: loaded %d stop-observation hop(s) (%d skipped)"
                  % (_n_stop_path, _stop_path_skip))

        shared.update({
            "bit_entry": bit_entry,
            "bit_exit": bit_exit,
            "mcu_pip_count": n_mpip,
            "wire_count": n_wire,
        })
        shared["mcu_gpio_feature"].add_architecture(context)
        n_mpip = shared["mcu_pip_count"]

        # Read-only analog hard-block routes. Vendor route.tx names the ADC cell,
        # not the individual output pin, so DB0 and EOC both appear as
        # `X22Y7_alta_adc00`. Distinct synthetic source wires preserve the two
        # isolated oracle-net identities and bind each to its recovered first hop.
        # This prevents the open router from swapping those exact corridors; it is
        # not a general output-pin encoding claim (DB1 also uses InputMUX01).
        for (_analog_csv, _analog_root, _analog_exit, _analog_type, _analog_port,
             _analog_label, _analog_z) in (
                ("analog_adc0_db0_path.csv", "X22Y7_ADCDBSOURCE00", "X22Y7_InputMUX100",
                 "AGRV2K_ADC0_DB0", "DB", "ADC0 DB0", 0),
                ("analog_adc0_eoc_path.csv", "X22Y7_ADCEOCSOURCE00", "X22Y7_BufMUX100",
                 "AGRV2K_ADC0_EOC", "EOC", "ADC0 EOC", 1),
                ("analog_adc0_db1_path.csv", "X22Y7_ADCDBSOURCE01", "X22Y7_InputMUX101",
                 "AGRV2K_ADC0_DB1", "DB", "ADC0 DB1", 2)):
            _analog_path_csv = os.path.join(DATA, _analog_csv)
            if not os.path.exists(_analog_path_csv):
                continue
            if _analog_root not in wireset:
                ctx.addWire(name=_analog_root, type=fam(_analog_root.rsplit("_", 1)[-1]),
                            x=22, y=7)
                wireset.add(_analog_root); n_wire += 1
            if _analog_exit not in wireset:
                ctx.addWire(name=_analog_exit, type=fam(_analog_exit.rsplit("_", 1)[-1]),
                            x=22, y=7)
                wireset.add(_analog_exit); n_wire += 1
            _n_analog = 0; _analog_skip = 0; _path_root = None
            for _r in csv.DictReader(open(_analog_path_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                if _path_root is None:
                    _path_root = _src
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _analog_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="ANALOG", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_analog += 1
            if _path_root == _analog_root and _path_root in wireset:
                _analog_bel = "X22Y7_%s00" % _analog_type
                ctx.addBel(name=_analog_bel, type=_analog_type,
                           loc=Loc(22, 7, _analog_z), gb=False, hidden=False)
                ctx.addBelOutput(bel=_analog_bel, name=_analog_port, wire=_path_root)
            else:
                _analog_skip += 1
            print("AGRV2K arch: loaded %d %s hop(s) (%d skipped)"
                  % (_n_analog, _analog_label, _analog_skip))

        # Fabric-to-core local interrupts. Each isolated vendor oracle drives one
        # lane from a retained LUT and observes the same net on a GPIO probe,
        # proving the complete LUT-output-to-hard-sink corridor.
        for _local_int_bit in range(4):
            _local_int_csv = os.path.join(
                DATA, "mcu_local_int%d_path.csv" % _local_int_bit)
            _n_local_int = 0; _local_int_skip = 0
            if not os.path.exists(_local_int_csv):
                continue
            _local_int_sink = None
            for _r in csv.DictReader(open(_local_int_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _local_int_sink = _dst
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _local_int_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_local_int += 1
            if _local_int_sink in wireset:
                bit_exit[121 + _local_int_bit] = _local_int_sink
            else:
                _local_int_skip += 1
            print("AGRV2K arch: loaded %d local_int[%d] hop(s) (%d skipped)"
                  % (_n_local_int, _local_int_bit, _local_int_skip))

        # Safety-ordered first slice of the fabric AHB master: MCU/system response
        # inputs into ordinary fabric logic.
        _slave_response_bits = {
            "slave_ahb_hreadyout": 125,
            "slave_ahb_hresp": 126,
            "slave_ahb_hrdata[0]": 127,
        }
        _slave_response_csv = os.path.join(DATA, "mcu_slave_ahb_response_paths.csv")
        _n_slave_response = 0; _slave_response_skip = 0
        _slave_response_roots = {}
        if os.path.exists(_slave_response_csv):
            for _r in csv.DictReader(open(_slave_response_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                if int(_r["step"]) == 0:
                    _slave_response_roots[_r["signal"]] = _src
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _slave_response_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_slave_response += 1
            for _signal, _bit in _slave_response_bits.items():
                _root = _slave_response_roots.get(_signal)
                if _root in wireset:
                    bit_entry[_bit] = _root
                else:
                    _slave_response_skip += 1
            print("AGRV2K arch: loaded %d fabric-master response hop(s) (%d skipped)"
                  % (_n_slave_response, _slave_response_skip))

        # Time-boxed four-lane HRDATA groups. Each vendor oracle consumes four
        # response bits in one LUT, avoiding the failed full-width oracle's 32-LUT
        # placement collapse. Load every promoted bounded group by filename.
        _slave_hrdata_grouped = os.path.join(
            DATA, "mcu_slave_ahb_hrdata_grouped_full_paths.csv")
        _slave_hrdata_csvs = ([ _slave_hrdata_grouped ]
            if os.path.exists(_slave_hrdata_grouped) else sorted(
                os.path.join(DATA, _name) for _name in os.listdir(DATA)
                if re.fullmatch(r"mcu_slave_ahb_hrdata\d+_\d+_paths\.csv", _name)))
        _n_slave_hrdata = 0; _slave_hrdata_skip = 0
        _slave_hrdata_roots = {}
        for _slave_hrdata_csv in _slave_hrdata_csvs:
            for _r in csv.DictReader(open(_slave_hrdata_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                if int(_r["step"]) == 0:
                    _slave_hrdata_roots[_r["signal"]] = _src
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _slave_hrdata_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_slave_hrdata += 1
        for _signal, _root in _slave_hrdata_roots.items():
            _lane_match = re.fullmatch(r"slave_ahb_hrdata\[(\d+)\]", _signal)
            if _lane_match and _root in wireset:
                bit_entry[133 + int(_lane_match.group(1))] = _root
            else:
                _slave_hrdata_skip += 1
        if _slave_hrdata_csvs:
            print("AGRV2K arch: loaded %d bounded fabric-master HRDATA hop(s) (%d skipped)"
                  % (_n_slave_hrdata, _slave_hrdata_skip))

        # Fabric-master request qualifiers. The oracle uses one retained LUT as a
        # shared source for all 11 sinks, proving a conflict-free simultaneous
        # route tree without yet claiming independent sources or bus semantics.
        _slave_request_bits = {
            "slave_ahb_hsel": 165,
            "slave_ahb_hready": 166,
            "slave_ahb_htrans[0]": 167,
            "slave_ahb_htrans[1]": 168,
            "slave_ahb_hsize[0]": 169,
            "slave_ahb_hsize[1]": 170,
            "slave_ahb_hsize[2]": 171,
            "slave_ahb_hburst[0]": 172,
            "slave_ahb_hburst[1]": 173,
            "slave_ahb_hburst[2]": 174,
            "slave_ahb_hwrite": 175,
        }
        _slave_request_csv = os.path.join(
            DATA, "mcu_slave_ahb_request_control_paths.csv")
        _n_slave_request = 0; _slave_request_skip = 0
        _slave_request_sinks = {}
        if os.path.exists(_slave_request_csv):
            for _r in csv.DictReader(open(_slave_request_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _slave_request_sinks[_r["signal"]] = _dst
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _slave_request_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_slave_request += 1
            for _signal, _bit in _slave_request_bits.items():
                _sink = _slave_request_sinks.get(_signal)
                if _sink in wireset:
                    bit_exit[_bit] = _sink
                else:
                    _slave_request_skip += 1
            print("AGRV2K arch: loaded %d fabric-master request-control hop(s) (%d skipped)"
                  % (_n_slave_request, _slave_request_skip))

        # Full fabric-master request payload route tree. The vendor oracle fans a
        # single safe-idle value onto every HADDR/HWDATA sink through OMUX00/02.
        _slave_payload_csv = os.path.join(
            DATA, "mcu_slave_ahb_request_payload_paths.csv")
        _n_slave_payload = 0; _slave_payload_skip = 0
        _slave_payload_sinks = {}
        if os.path.exists(_slave_payload_csv):
            for _r in csv.DictReader(open(_slave_payload_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _slave_payload_sinks[_r["signal"]] = _dst
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _slave_payload_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_slave_payload += 1
            for _lane in range(32):
                for _name, _bit in (("slave_ahb_haddr[%d]" % _lane, 176 + _lane),
                                    ("slave_ahb_hwdata[%d]" % _lane, 208 + _lane)):
                    _sink = _slave_payload_sinks.get(_name)
                    if _sink in wireset:
                        bit_exit[_bit] = _sink
                    else:
                        _slave_payload_skip += 1
            print("AGRV2K arch: loaded %d fabric-master request-payload hop(s) (%d skipped)"
                  % (_n_slave_payload, _slave_payload_skip))

        # All MCU-to-fabric DMA response channels. These inputs are observational
        # and cannot initiate a DMA transfer by themselves.
        _dma_response_bits = {
            "ext_dma_DMACCLR[0]": 128,
            "ext_dma_DMACTC[0]": 129,
            "ext_dma_DMACCLR[1]": 252,
            "ext_dma_DMACCLR[2]": 253,
            "ext_dma_DMACCLR[3]": 254,
            "ext_dma_DMACTC[1]": 255,
            "ext_dma_DMACTC[2]": 256,
            "ext_dma_DMACTC[3]": 257,
        }
        _dma_response_csv = os.path.join(DATA, "mcu_dma_response_all_paths.csv")
        _n_dma_response = 0; _dma_response_skip = 0
        _dma_response_roots = {}
        if os.path.exists(_dma_response_csv):
            for _r in csv.DictReader(open(_dma_response_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                if int(_r["step"]) == 0:
                    _dma_response_roots[_r["signal"]] = _src
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _dma_response_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_dma_response += 1
            for _signal, _bit in _dma_response_bits.items():
                _root = _dma_response_roots.get(_signal)
                if _root in wireset:
                    bit_entry[_bit] = _root
                else:
                    _dma_response_skip += 1
            print("AGRV2K arch: loaded %d DMA-response hop(s) (%d skipped)"
                  % (_n_dma_response, _dma_response_skip))

        # All fabric-to-MCU DMA request endpoints.  The bounded vendor oracle drove
        # all sixteen request bits from one retained LUT, so this graph proves a
        # shared branch tree only; separate-source routability is deliberately not
        # inferred from it.
        _dma_request_bits = {
            "ext_dma_DMACBREQ[0]": 130,
            "ext_dma_DMACLBREQ[0]": 131,
            "ext_dma_DMACSREQ[0]": 132,
            "ext_dma_DMACLSREQ[0]": 133,
            "ext_dma_DMACBREQ[1]": 240,
            "ext_dma_DMACBREQ[2]": 241,
            "ext_dma_DMACBREQ[3]": 242,
            "ext_dma_DMACLBREQ[1]": 243,
            "ext_dma_DMACLBREQ[2]": 244,
            "ext_dma_DMACLBREQ[3]": 245,
            "ext_dma_DMACSREQ[1]": 246,
            "ext_dma_DMACSREQ[2]": 247,
            "ext_dma_DMACSREQ[3]": 248,
            "ext_dma_DMACLSREQ[1]": 249,
            "ext_dma_DMACLSREQ[2]": 250,
            "ext_dma_DMACLSREQ[3]": 251,
        }
        _dma_request_csv = os.path.join(DATA, "mcu_dma_request_all_paths.csv")
        _n_dma_request = 0; _dma_request_skip = 0
        _dma_request_sinks = {}
        if os.path.exists(_dma_request_csv):
            for _r in csv.DictReader(open(_dma_request_csv)):
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dma_request_sinks[_r["signal"]] = _dst
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _dma_request_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_dma_request += 1
            for _signal, _bit in _dma_request_bits.items():
                _sink = _dma_request_sinks.get(_signal)
                if _sink in wireset:
                    bit_exit[_bit] = _sink
                else:
                    _dma_request_skip += 1
            print("AGRV2K arch: loaded %d DMA-request hop(s) (%d skipped)"
                  % (_n_dma_request, _dma_request_skip))

        # Alternate endpoint fan-ins selected by the simultaneous HADDR->HRDATA
        # vendor route.  They feed the same fixed SinkMUXPseudo wires/BELs as the
        # HWDATA oracle but use a different conflict-free RMUX assignment.
        _haexit_csv = os.path.join(DATA, "mcu_hrdata_addr_lanes.csv")
        _n_haexit = 0; _haexit_skip = 0
        if os.path.exists(_haexit_csv):
            for _r in csv.DictReader(open(_haexit_csv)):
                _src = W(_r["src_x"], _r["src_y"], _r["src_res"])
                _edge = W(_r["edge_x"], _r["edge_y"], _r["edge_res"])
                _sink = W(0, 5, _r["sink_res"])
                if _src not in wireset or _edge not in wireset or _sink not in wireset:
                    _haexit_skip += 1
                    continue
                for _a, _b in ((_src, _edge), (_edge, _sink)):
                    _nm = "%s.%s" % (_a, _b)
                    if _nm not in seen_pip:
                        ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_a, dstWire=_b,
                                   delay=_wire_delay(_a.rsplit("_", 1)[-1]),
                                   loc=Loc(int(_r["edge_x"]), int(_r["edge_y"]), 0))
                        seen_pip.add(_nm); n_mpip += 1
                _n_haexit += 1
            print("AGRV2K arch: loaded %d/32 alternate HADDR->HRDATA endpoint(s) (%d skipped)"
                  % (_n_haexit, _haexit_skip))

        # Two lanes in the simultaneous vendor corridor use the LUT's alternate
        # OMUX[3z+0] output (the other three inserted buffers use the default +2
        # output).  Represent the selectable output as a short internal pip so a
        # per-cell route can choose it without globally changing every slice BEL.
        for _x, _y, _z in ((14, 10, 3), (14, 9, 7)):
            _src = W(_x, _y, "OMUX%02d" % (3 * _z + 2))
            _dst = W(_x, _y, "OMUX%02d" % (3 * _z + 0))
            if _src in wireset and _dst in wireset:
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay("OMUX"), loc=Loc(_x, _y, _z))
                    seen_pip.add(_nm); n_mpip += 1

        # PIN_25/PIN_26 in the silicon-positive pintest2 route use F on OMUX[3z+0]
        # and Q on OMUX[3z+1], not the ordinary registered +2 presentation.  The
        # bridge represents the shared physical presentation selected by the
        # vendor's exact {0,1} CFG_OMUX pattern.
        if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
            for _x, _y, _si, _di in ((14, 11, 13, 12), (14, 11, 16, 15)):
                _src = W(_x, _y, "OMUX%02d" % _si); _dst = W(_x, _y, "OMUX%02d" % _di)
                _nm = "%s.%s" % (_src, _dst)
                if _src in wireset and _dst in wireset and _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="PADOUT", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay("OMUX"), loc=Loc(_x, _y, 0))
                    seen_pip.add(_nm); n_mpip += 1

        shared.update({
            "bit_entry": bit_entry,
            "bit_exit": bit_exit,
            "mcu_pip_count": n_mpip,
            "wire_count": n_wire,
        })
        return n_mpip

    def add_bels(self, context):
        """Construct one typed hard-boundary BEL for each surfaced MCU signal."""
        ctx, Loc = context.ctx, context.loc
        OPTIONS = context.options
        bit_entry = context.shared["bit_entry"]
        bit_exit = context.shared["bit_exit"]

        # ---- 6. alta_mcu bels: one MCU bel PER GPIO bit at the MCU location (UFMTILE 0,5) ----
        # Each GPIO bit crosses the MCU<->fabric edge on its OWN wires (harvested from the vendor route.tx of
        # the loopback + lutmcu oracles): DIN = the fabric-entry BufMUX wire the MCU drives; DOUT = the
        # fabric-exit SinkMUXPseudo wire the MCU reads. The router threads MCU-out -> fabric LUT -> MCU-in
        # for each bit independently. One MCU cell in the netlist per bit; nextpnr places each on its bel.
        # Placed at UFMTILE(10,5) distinguished by z=bit (the fabric-crossing corner where entry/exit muxes
        # live -> keeps the LUT local, route short, sel-encoding errors few). Bit 0 = the proven single-bit
        # path (GPIO4_1/2, RMUX93/RMUX19/BBMUXS02); bit 1 = GPIO4_3/4, RMUX17/RMUX02/BBMUXS04.
        # MCU-edge tile: a PHYSICAL silicon constant (the MCU<->fabric crossing corner), not a free choice --
        # but named + env-overridable (AGAMEMNON_MCU_XY="x,y") rather than a scattered magic number, so a
        # different package/part revision can point it elsewhere without hunting literals.
        MCUX, MCUY = OPTIONS.coordinates("AGAMEMNON_MCU_XY")
        n_mbel = 0
        _typed_mcu = {
            102: "MCU_AHB_HREADY",
            103: "MCU_AHB_HTRANS0",
            104: "MCU_AHB_HSIZE0",
            105: "MCU_AHB_HSIZE1",
            106: "MCU_AHB_HSIZE2",
            107: "MCU_AHB_HBURST0",
            108: "MCU_AHB_HBURST1",
            109: "MCU_AHB_HBURST2",
            110: "MCU_AHB_HREADYOUT",
            111: "MCU_AHB_HRESP",
            120: "MCU_RESETN",
            121: "MCU_LOCAL_INT0",
            122: "MCU_LOCAL_INT1",
            123: "MCU_LOCAL_INT2",
            124: "MCU_LOCAL_INT3",
            125: "MCU_SLAVE_AHB_HREADYOUT",
            126: "MCU_SLAVE_AHB_HRESP",
            127: "MCU_SLAVE_AHB_HRDATA0",
            128: "MCU_DMA_CLR0",
            129: "MCU_DMA_TC0",
            130: "MCU_DMA_BREQ0",
            131: "MCU_DMA_LBREQ0",
            132: "MCU_DMA_SREQ0",
            133: "MCU_DMA_LSREQ0",
            240: "MCU_DMA_BREQ1",
            241: "MCU_DMA_BREQ2",
            242: "MCU_DMA_BREQ3",
            243: "MCU_DMA_LBREQ1",
            244: "MCU_DMA_LBREQ2",
            245: "MCU_DMA_LBREQ3",
            246: "MCU_DMA_SREQ1",
            247: "MCU_DMA_SREQ2",
            248: "MCU_DMA_SREQ3",
            249: "MCU_DMA_LSREQ1",
            250: "MCU_DMA_LSREQ2",
            251: "MCU_DMA_LSREQ3",
            252: "MCU_DMA_CLR1",
            253: "MCU_DMA_CLR2",
            254: "MCU_DMA_CLR3",
            255: "MCU_DMA_TC1",
            256: "MCU_DMA_TC2",
            257: "MCU_DMA_TC3",
            258: "MCU_STOP",
            259: "MCU_GPIO5_OUT_DATA1",
            260: "MCU_GPIO5_OUT_EN1",
            261: "MCU_GPIO5_IN2",
            262: "MCU_GPIO5_OUT_DATA0",
            263: "MCU_GPIO5_OUT_EN0",
            134: "MCU_SLAVE_AHB_HRDATA1",
            135: "MCU_SLAVE_AHB_HRDATA2",
            136: "MCU_SLAVE_AHB_HRDATA3",
            137: "MCU_SLAVE_AHB_HRDATA4",
            138: "MCU_SLAVE_AHB_HRDATA5",
            139: "MCU_SLAVE_AHB_HRDATA6",
            140: "MCU_SLAVE_AHB_HRDATA7",
            141: "MCU_SLAVE_AHB_HRDATA8",
            142: "MCU_SLAVE_AHB_HRDATA9",
            143: "MCU_SLAVE_AHB_HRDATA10",
            144: "MCU_SLAVE_AHB_HRDATA11",
            145: "MCU_SLAVE_AHB_HRDATA12",
            146: "MCU_SLAVE_AHB_HRDATA13",
            147: "MCU_SLAVE_AHB_HRDATA14",
            148: "MCU_SLAVE_AHB_HRDATA15",
            149: "MCU_SLAVE_AHB_HRDATA16",
            150: "MCU_SLAVE_AHB_HRDATA17",
            151: "MCU_SLAVE_AHB_HRDATA18",
            152: "MCU_SLAVE_AHB_HRDATA19",
            153: "MCU_SLAVE_AHB_HRDATA20",
            154: "MCU_SLAVE_AHB_HRDATA21",
            155: "MCU_SLAVE_AHB_HRDATA22",
            156: "MCU_SLAVE_AHB_HRDATA23",
            157: "MCU_SLAVE_AHB_HRDATA24",
            158: "MCU_SLAVE_AHB_HRDATA25",
            159: "MCU_SLAVE_AHB_HRDATA26",
            160: "MCU_SLAVE_AHB_HRDATA27",
            161: "MCU_SLAVE_AHB_HRDATA28",
            162: "MCU_SLAVE_AHB_HRDATA29",
            163: "MCU_SLAVE_AHB_HRDATA30",
            164: "MCU_SLAVE_AHB_HRDATA31",
            165: "MCU_SLAVE_AHB_HSEL",
            166: "MCU_SLAVE_AHB_HREADY",
            167: "MCU_SLAVE_AHB_HTRANS0",
            168: "MCU_SLAVE_AHB_HTRANS1",
            169: "MCU_SLAVE_AHB_HSIZE0",
            170: "MCU_SLAVE_AHB_HSIZE1",
            171: "MCU_SLAVE_AHB_HSIZE2",
            172: "MCU_SLAVE_AHB_HBURST0",
            173: "MCU_SLAVE_AHB_HBURST1",
            174: "MCU_SLAVE_AHB_HBURST2",
            175: "MCU_SLAVE_AHB_HWRITE",
        }
        # A "bit" with BOTH entry+exit is a GPIO loopback pin (type MCU, DIN+DOUT). A bit with only an entry
        # is an MCU->fabric bus INPUT (type MCU_DIN, e.g. an AHB signal hwdata/hwrite/htrans); with only an
        # exit it's a fabric->MCU OUTPUT (type MCU_DOUT, e.g. GPIO observability or hrdata). This lets the AHB
        # slave model many MCU-driven bus inputs + a readback, not just DIN/DOUT pairs.
        for bit in sorted(set(bit_entry) | set(bit_exit)):
            has_e = bit in bit_entry; has_x = bit in bit_exit
            typ = _typed_mcu.get(
                bit, "MCU" if (has_e and has_x) else ("MCU_DIN" if has_e else "MCU_DOUT")
            )
            mcubel = "X%dY%d_%s%d" % (MCUX, MCUY, typ, bit)
            ctx.addBel(name=mcubel, type=typ, loc=Loc(MCUX, MCUY, bit), gb=False, hidden=False)
            if has_e:
                _entry_pin = "RESETN" if typ == "MCU_RESETN" else "DIN"
                ctx.addBelOutput(bel=mcubel, name=_entry_pin, wire=bit_entry[bit])   # MCU -> fabric
            if has_x: ctx.addBelInput (bel=mcubel, name="DOUT", wire=bit_exit[bit])    # fabric -> MCU
            print("AGRV2K arch: %s bel %s  DIN->%s  DOUT<-%s"
                  % (typ, mcubel, bit_entry.get(bit, "-"), bit_exit.get(bit, "-")))
            n_mbel += 1
        if n_mbel == 0:
            print("AGRV2K arch: no MCU bels added (entry/exit wires absent)")

        return n_mbel

    def clear_bitstream(self, context):
        return 0

    def emit_bitstream(self, context):
        return 0

    def load_exact_pip_fields(self, chipdb_root):
        fields = {}
        for filename in EXACT_PIP_CFG_FILES:
            path = chipdb_root / filename
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    source = exact_wire(row["src_wire"])
                    destination = exact_wire(row["dst_wire"])
                    key = source + destination
                    clear = tuple(
                        int(value) for value in row["clear_selectors"].split(";")
                        if value != ""
                    )
                    set_bits = tuple(
                        int(value) for value in row["set_selectors"].split(";")
                        if value != ""
                    )
                    value = (row["cell_table"], row["cfg_group"], clear, set_bits)
                    if key in fields and fields[key] != value:
                        raise SystemExit(
                            "conflicting exact MCU corridor codeword for %s" % (key,)
                        )
                    fields[key] = value
        return fields

    @staticmethod
    def _merge_field(fields, key, value, label):
        if key in fields and fields[key] != value:
            raise SystemExit("conflicting exact %s codeword for %s" % (label, key))
        fields[key] = value

    def load_routing_metadata(self, chipdb_root, options, supplemental_fields=()):
        """Load every qualified exact MCU/hard-boundary routing codeword."""
        fields = self.load_exact_pip_fields(chipdb_root)
        for filename in CORRIDOR_PIP_CFG_FILES:
            path = chipdb_root / filename
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as stream:
                for row_index, row in enumerate(csv.DictReader(stream)):
                    if (
                        filename == "bram_x9_haddr_pip_cfg.csv"
                        and row_index >= 21
                        and not options.enabled("AGAMEMNON_X9_FULL_ADDRESS")
                    ):
                        continue
                    key = exact_wire(row["src_wire"]) + exact_wire(row["dst_wire"])
                    value = (
                        row["cell_table"],
                        row["cfg_group"],
                        tuple(
                            int(item) for item in row["clear_selectors"].split(";")
                            if item
                        ),
                        tuple(
                            int(item) for item in row["set_selectors"].split(";")
                            if item
                        ),
                    )
                    self._merge_field(fields, key, value, "MCU corridor")
        for supplemental in supplemental_fields:
            for key, value in supplemental.items():
                self._merge_field(fields, key, value, "MCU GPIO corridor")
        if fields:
            print("loaded %d exact protocol-valid AHB32 corridor fields" % len(fields))

        exit_pairs = {}
        for filename in EXIT_PAIR_FILES:
            path = chipdb_root / filename
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    edge = re.fullmatch(r"(BBMUX[A-Z]+)0*([0-9]+)", row["edge_res"])
                    source = re.fullmatch(r"([A-Za-z]+)0*([0-9]+)", row["src_res"])
                    if not edge or not source:
                        raise SystemExit(
                            "bad %s resource: %s -> %s" %
                            (filename, row["src_res"], row["edge_res"])
                        )
                    key = (
                        int(row["edge_x"]), int(row["edge_y"]),
                        edge.group(1), int(edge.group(2)),
                        int(row["src_x"]), int(row["src_y"]),
                        source.group(1), int(source.group(2)),
                    )
                    exit_pairs[key] = tuple(
                        int(item) for item in row["selectors"].split(";") if item
                    )
        print("loaded %d exact AHB hrdata edge selector codewords" % len(exit_pairs))
        return McuRoutingMetadata(fields, exit_pairs)


FEATURE = McuAhbFeature()
