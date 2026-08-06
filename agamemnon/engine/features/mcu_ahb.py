"""External MCU-AHB exact-corridor selector metadata and loading."""

from __future__ import annotations

import csv
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
            tuple(filename for filename in EXIT_PAIR_FILES if filename not in ARCHITECTURE_FILES)
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
            "External AHB lane and corridor graph construction remains in arch.py "
            "during the strangler migration; its chipdb ownership is declared here."
        ),
        bitstream=(
            "Load the exact node-local selector fields for qualified External-AHB "
            "data, address, control, and register-bank corridors."
        ),
    )

    def add_architecture(self, context):
        return None

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
