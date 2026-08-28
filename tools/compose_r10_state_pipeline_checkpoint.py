"""Seed the R10 two-stage observer from the exact accepted R8 checkpoint.

The R10 source deliberately changes only four observer-net endpoint sets.  All
other cells, placements, and routed nets must replay exactly from R8.  The two
old pending/start observer leaves are removed, while the two first-stage Q
routes remain imported so router2 may add only the new second-stage sinks.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


class CompositionError(RuntimeError):
    pass


OBSERVER_CELL_MAP = {
    "first_master_state0_ff": "trace_master_state0_ff",
    "first_master_state1_ff": "trace_master_state1_ff",
    "second_master_state0_ff": "trace_start_pulse_ff",
    "second_master_state1_ff": "trace_command_pending_ff",
}

OBSERVER_NET_MAP = {
    "first_master_state[0]": "trace_master_state0",
    "first_master_state[1]": "trace_master_state1",
    "second_master_state[0]": "trace_start_pulse",
    "second_master_state[1]": "trace_command_pending",
    "dut.start_pulse": "raw_start_pulse",
    "dut.command_pending": "raw_command_pending",
}

EXPECTED_ENDPOINT_DRIFT = {
    "first_master_state[0]",
    "first_master_state[1]",
    "dut.start_pulse",
    "dut.command_pending",
}

REMOVED_R8_LEAVES = {
    "dut.start_pulse": ("X14Y11_RMUX94", "X14Y11_IMUX24"),
    "dut.command_pending": ("X14Y11_RMUX22", "X14Y11_IMUX28"),
}


def _module(document: dict) -> dict:
    modules = document.get("modules", {})
    if set(modules) != {"top"}:
        raise CompositionError("both checkpoints must contain only module top")
    return modules["top"]


def _abc_names(module: dict) -> list[str]:
    return sorted(name for name in module["cells"] if name.startswith("$abc$"))


def _cell_map(r8: dict, r10: dict) -> dict[str, str]:
    mapping = {
        name: name for name in r10["cells"] if name in r8["cells"]
    }
    mapping.update(OBSERVER_CELL_MAP)
    r8_abc = _abc_names(r8)
    r10_abc = _abc_names(r10)
    if len(r8_abc) != len(r10_abc):
        raise CompositionError("R8/R10 generated-cell counts differ")
    mapping.update(zip(r10_abc, r8_abc))
    if set(mapping) != set(r10["cells"]):
        missing = sorted(set(r10["cells"]) - set(mapping))
        raise CompositionError(f"unmapped R10 cells: {missing}")
    if len(set(mapping.values())) != len(mapping):
        raise CompositionError("R10-to-R8 cell mapping is not bijective")
    if set(mapping.values()) != set(r8["cells"]):
        raise CompositionError("R10-to-R8 cell mapping does not cover R8")
    for r10_name, r8_name in mapping.items():
        candidate = r10["cells"][r10_name]
        reference = r8["cells"][r8_name]
        candidate_signature = (
            candidate.get("type"), candidate.get("parameters", {})
        )
        reference_signature = (
            reference.get("type"), reference.get("parameters", {})
        )
        if candidate_signature != reference_signature:
            raise CompositionError(
                f"cell signature drift: {r10_name} -> {r8_name}"
            )
    return mapping


def _net_map(name: str, r8: dict) -> str:
    if name in OBSERVER_NET_MAP:
        return OBSERVER_NET_MAP[name]
    if "$logic_and$" in name:
        matches = [item for item in r8["netnames"] if "$logic_and$" in item]
        if len(matches) != 1:
            raise CompositionError("R8 logic-and net is not unique")
        return matches[0]
    if "$logic_or$" in name:
        matches = [item for item in r8["netnames"] if "$logic_or$" in item]
        if len(matches) != 1:
            raise CompositionError("R8 logic-or net is not unique")
        return matches[0]
    return name.replace("$abc$435$", "$abc$450$")


def _endpoints(module: dict, bit: int, cell_map: dict[str, str] | None = None):
    result = []
    for cell_name, cell in module["cells"].items():
        mapped_name = cell_map.get(cell_name, cell_name) if cell_map else cell_name
        for port, bits in cell.get("connections", {}).items():
            for index, item in enumerate(bits):
                if item == bit:
                    result.append(("cell", mapped_name, port, index))
    for port_name, port in module.get("ports", {}).items():
        for index, item in enumerate(port.get("bits", [])):
            if item == bit:
                result.append(("port", port_name, port.get("direction"), index))
    return tuple(sorted(result))


def _remove_leaf(route: str, expected_src: str, expected_dst: str) -> str:
    parts = route.split(";")
    if len(parts) % 3:
        raise CompositionError("R8 route is not encoded as triples")
    retained = []
    removed = 0
    for index in range(0, len(parts), 3):
        wire, pip, strength = parts[index:index + 3]
        if pip == f"{expected_src}.{expected_dst}" and wire == expected_dst:
            removed += 1
            continue
        retained.extend((wire, pip, strength))
    if removed != 1:
        raise CompositionError(
            f"expected exactly one R8 leaf {expected_src}->{expected_dst}; "
            f"removed {removed}"
        )
    return ";".join(retained)


def compose(r8_document: dict, r10_document: dict) -> tuple[dict, dict]:
    r8 = _module(r8_document)
    r10 = _module(r10_document)
    if len(r8["cells"]) != 145 or len(r10["cells"]) != 145:
        raise CompositionError("expected exact 145-cell R8/R10 structures")
    if len(r8["netnames"]) != 61 or len(r10["netnames"]) != 61:
        raise CompositionError("expected exact 61-net R8/R10 structures")

    mapping = _cell_map(r8, r10)
    for r10_name, r8_name in mapping.items():
        reference_bel = r8["cells"][r8_name].get("attributes", {}).get(
            "NEXTPNR_BEL"
        )
        if not reference_bel:
            raise CompositionError(f"R8 cell has no BEL: {r8_name}")
        r10["cells"][r10_name].setdefault("attributes", {})[
            "NEXTPNR_BEL"
        ] = reference_bel

    endpoint_drift = set()
    copied_routes = 0
    pruned_routes = 0
    for r10_name, r10_net in r10["netnames"].items():
        r8_name = _net_map(r10_name, r8)
        if r8_name not in r8["netnames"]:
            raise CompositionError(f"R8 net mapping missing: {r10_name} -> {r8_name}")
        r8_net = r8["netnames"][r8_name]
        r10_signature = _endpoints(r10, r10_net["bits"][0], mapping)
        r8_signature = _endpoints(r8, r8_net["bits"][0])
        if r10_signature != r8_signature:
            endpoint_drift.add(r10_name)
        route = r8_net.get("attributes", {}).get("ROUTING")
        if route is None:
            raise CompositionError(f"R8 net has no route: {r8_name}")
        if r10_name in REMOVED_R8_LEAVES:
            route = _remove_leaf(route, *REMOVED_R8_LEAVES[r10_name])
            pruned_routes += 1
        r10_net.setdefault("attributes", {})["ROUTING"] = route
        copied_routes += 1

    if endpoint_drift != EXPECTED_ENDPOINT_DRIFT:
        raise CompositionError(
            "endpoint drift is not the exact four-net R10 contract: "
            f"{sorted(endpoint_drift)}"
        )
    return r10_document, {
        "cells": len(mapping),
        "nets": copied_routes,
        "pruned_obsolete_leaves": pruned_routes,
        "endpoint_drift": sorted(endpoint_drift),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("r8")
    parser.add_argument("r10")
    parser.add_argument("output")
    args = parser.parse_args()
    r8_path = Path(args.r8)
    r10_path = Path(args.r10)
    output_path = Path(args.output)
    result, summary = compose(
        json.loads(r8_path.read_text(encoding="utf-8")),
        json.loads(r10_path.read_text(encoding="utf-8")),
    )
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
