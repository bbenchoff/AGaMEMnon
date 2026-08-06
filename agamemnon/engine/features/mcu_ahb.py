"""External MCU-AHB exact-corridor selector metadata and loading."""

from __future__ import annotations

import csv
import re

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
        ),
        chipdb_files=EXACT_PIP_CFG_FILES + ARCHITECTURE_FILES,
        writable_regions=tuple(
            WritableRegion(kind="selector_table", source=filename)
            for filename in EXACT_PIP_CFG_FILES
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


FEATURE = McuAhbFeature()
