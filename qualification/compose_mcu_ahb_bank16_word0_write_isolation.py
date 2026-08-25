#!/usr/bin/env python3
"""Compose +0/+4/+8/+c write isolation onto the qualified held bank.

The retained reset tree owns the shortest composable HADDR2 corridor.  Four
reset leaves are moved onto already-owned reset trunks, freeing R07/R25 for
HADDR2. HADDR3 has its direct qualified ingress. A single free LUT gates the
otherwise unchanged HWRITE leaf; storage, feedback, HREADYOUT, HWDATA and all
sixteen HRDATA routes are preserved.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "qualification" / "mcu_ahb_register_bank16_external_feedback_waited_routed.json"
OUT = ROOT / "qualification" / "mcu_ahb_register_bank16_address_write_isolated_waited_routed.json"
BASE_SHA256 = "b6dd1b592c790c9de07d1fe7d85b6f5295e9e05562a1f876c3c5ce80f179ebc8"
HADDR2_BIT, HADDR3_BIT, GATED_HWRITE_BIT = 302850, 302851, 302852

OLD_HWRITE_ROUTE = (
    "X14Y12_IMUX05;X14Y12_RMUX89.X14Y12_IMUX05;5;"
    "X14Y12_RMUX89;X13Y12_InputMUX09.X14Y12_RMUX89;5;"
    "X13Y12_InputMUX09;X13Y12_BufMUX09.X14Y12_RMUX89;5;"
    "X13Y12_BufMUX09;;5"
)
# The baseline spells the second edge with InputMUX09 as the destination.
OLD_HWRITE_ROUTE = OLD_HWRITE_ROUTE.replace(
    "X13Y12_InputMUX09.X14Y12_RMUX89",
    "X13Y12_InputMUX09.X14Y12_RMUX89",
)
NEW_HWRITE_ROUTE = (
    "X14Y12_IMUX01;X14Y12_RMUX89.X14Y12_IMUX01;5;"
    "X14Y12_RMUX89;X13Y12_InputMUX09.X14Y12_RMUX89;5;"
    "X13Y12_InputMUX09;X13Y12_BufMUX09.X13Y12_InputMUX09;5;"
    "X13Y12_BufMUX09;;5"
)
HADDR2_ROUTE = (
    "X14Y12_IMUX00;X14Y12_RMUX22.X14Y12_IMUX00;5;"
    "X14Y12_RMUX22;X14Y11_RMUX25.X14Y12_RMUX22;5;"
    "X14Y11_RMUX25;X14Y12_RMUX07.X14Y11_RMUX25;5;"
    "X14Y12_RMUX07;X13Y12_BufMUX12.X14Y12_RMUX07;5;"
    "X13Y12_BufMUX12;;5"
)
HADDR3_ROUTE = (
    "X14Y12_IMUX03;X14Y12_RMUX23.X14Y12_IMUX03;5;"
    "X14Y12_RMUX23;X13Y12_BufMUX13.X14Y12_RMUX23;5;"
    "X13Y12_BufMUX13;;5"
)
GATED_HWRITE_ROUTE = (
    "X14Y12_IMUX05;X14Y12_RMUX17.X14Y12_IMUX05;1;"
    "X14Y12_RMUX17;X14Y12_OMUX02.X14Y12_RMUX17;1;"
    "X14Y12_OMUX02;;1"
)
RESET_ADDITIONS = (
    "X14Y11_IMUX02;X14Y11_RMUX58.X14Y11_IMUX02;1;"
    "X14Y12_IMUX07;X14Y12_RMUX77.X14Y12_IMUX07;1;"
    "X14Y12_RMUX77;X14Y11_RMUX69.X14Y12_RMUX77;1;"
    "X14Y12_IMUX10;X14Y12_RMUX76.X14Y12_IMUX10;1;"
    "X14Y12_IMUX62;X14Y12_RMUX76.X14Y12_IMUX62;1"
)
RESET_REMOVE_PIPS = {
    "X14Y7_RMUX55.X14Y11_RMUX25",
    "X14Y11_RMUX25.X14Y12_RMUX17",
    "X14Y12_RMUX17.X14Y12_IMUX07",
    "X14Y11_RMUX25.X14Y12_RMUX07",
    "X14Y12_RMUX07.X14Y11_RMUX46",
    "X14Y11_RMUX46.X14Y11_IMUX02",
    "X14Y11_RMUX25.X14Y12_RMUX16",
    "X14Y12_RMUX16.X14Y12_IMUX10",
    "X14Y12_RMUX16.X14Y12_IMUX62",
}


def remove_route_pips(route: str, remove: set[str]) -> str:
    fields = route.split(";")
    triples = [fields[i:i + 3] for i in range(0, len(fields) - 1, 3)]
    seen = {triple[1] for triple in triples if triple[1] in remove}
    if seen != remove:
        raise SystemExit(f"reset route removal mismatch: missing {sorted(remove - seen)}")
    kept = [triple for triple in triples if triple[1] not in remove]
    return ";".join(item for triple in kept for item in triple)


def din(template, name: str, bel: str, bit: int) -> dict:
    return {
        "hide_name": 0, "type": "MCU_DIN", "parameters": {},
        "attributes": {**template["attributes"], "NEXTPNR_BEL": bel, "hdlname": name},
        "port_directions": {"DIN": "output"}, "connections": {"DIN": [bit]},
    }


def main() -> None:
    raw = BASE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != BASE_SHA256:
        raise SystemExit(f"base hash mismatch: {digest}")
    design = json.loads(raw)
    design["creator"] = (
        "Next Generation Place and Route (Version nextpnr-0.10-82-g2b560ad0); "
        "deterministic HADDR[3:2] write-isolation composition"
    )
    top = design["modules"]["top"]
    cells, nets = top["cells"], top["netnames"]
    actual_hwrite = nets["hwrite"]["attributes"]["ROUTING"]
    # Keep the literal baseline identity check readable despite the long route.
    if actual_hwrite != NEW_HWRITE_ROUTE.replace("IMUX01", "IMUX05", 1).replace(
            "RMUX89.X14Y12_IMUX01", "RMUX89.X14Y12_IMUX05", 1):
        raise SystemExit("qualified HWRITE route identity mismatch")
    if cells["write_stage"]["connections"]["I"][1] != nets["hwrite"]["bits"][0]:
        raise SystemExit("write-stage HWRITE input identity mismatch")
    if any(c.get("attributes", {}).get("NEXTPNR_BEL") == "X14Y12_SLICE0"
           for c in cells.values()):
        raise SystemExit("X14Y12_SLICE0 is occupied")

    reset = nets["reset_request"]
    reset["attributes"]["ROUTING"] = RESET_ADDITIONS + ";" + remove_route_pips(
        reset["attributes"]["ROUTING"], RESET_REMOVE_PIPS)

    template = cells["mcu_hwrite"]
    cells["mcu_haddr2"] = din(template, "mcu_haddr2", "X10Y5_MCU_DIN76", HADDR2_BIT)
    cells["mcu_haddr3"] = din(template, "mcu_haddr3", "X10Y5_MCU_DIN77", HADDR3_BIT)
    cells["hwrite_word0_gate"] = {
        "hide_name": 0, "type": "GENERIC_SLICE",
        "parameters": {
            "K": "00000000000000000000000000000100",
            # I0=HADDR2, I1=HWRITE, I2=0, I3=HADDR3.
            "INIT": "0000000001000100",
            "FF_USED": "00000000000000000000000000000000",
        },
        "attributes": {
            "BEL_STRENGTH": "00000000000000000000000000000101",
            "NEXTPNR_BEL": "X14Y12_SLICE0",
            "module_not_derived": "00000000000000000000000000000001",
            "keep": "00000000000000000000000000000001",
            "hdlname": "hwrite_word0_gate",
        },
        "port_directions": {"Q": "output", "F": "output", "I": "input", "CLK": "input"},
        "connections": {
            "Q": [], "F": [GATED_HWRITE_BIT],
            "I": [HADDR2_BIT, nets["hwrite"]["bits"][0], 302849, HADDR3_BIT],
            "CLK": [302609],
        },
    }
    nets["hwrite"]["attributes"]["ROUTING"] = NEW_HWRITE_ROUTE
    nets["haddr2"] = {"hide_name": 0, "bits": [HADDR2_BIT],
                      "attributes": {"ROUTING": HADDR2_ROUTE, "hdlname": "haddr2"}}
    nets["haddr3"] = {"hide_name": 0, "bits": [HADDR3_BIT],
                      "attributes": {"ROUTING": HADDR3_ROUTE, "hdlname": "haddr3"}}
    nets["hwrite_word0"] = {"hide_name": 0, "bits": [GATED_HWRITE_BIT],
                            "attributes": {"ROUTING": GATED_HWRITE_ROUTE,
                                           "hdlname": "hwrite_word0"}}
    cells["write_stage"]["connections"]["I"][1] = GATED_HWRITE_BIT

    OUT.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(OUT)
    print(hashlib.sha256(OUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
