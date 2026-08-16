#!/usr/bin/env python3
"""Compose the exact public32 map with GPIO5 DATA0 as W1C level-set input.

This is a deliberately bounded derivative of the silicon-qualified public32
checkpoint.  It removes the qualification-only HWDATA1 set hook, preserves the
entire read/scratch/counter/clear/storage path, and adds the already-qualified
GPIO5 lane-0 hard ingress through one combinational relay into the existing
HCLK-registered set stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import compose_mcu_ahb_public16_exact_map as p16


HERE = Path(__file__).resolve().parent
BASE = HERE / "mcu_ahb_public32_exact_map_routed.json"
OUT = HERE / "mcu_ahb_public32_gpio5_w1c_exact_map_routed.json"
OR_OUT = HERE / "mcu_ahb_public32_gpio5_w1c_or_control_routed.json"
BASE_SHA256 = "ab76df409898241b0e631ac79926345ac4b4cd0783f0e02898d9f95e6525c574"
OUTPUT_SHA256 = "a067a7328b06c20bc6c050bcd7e968cafdda9471ed57477c771652c48bb2d3ea"
OR_OUTPUT_SHA256 = "fd788250f6ff9b0fa9373e477472bc8d59ece2a0c914e3704c545f63ed5751a6"


def _drop(net, destinations):
    items = [item for item in p16.route_items(net["attributes"]["ROUTING"])
             if item[0] not in destinations]
    net["attributes"]["ROUTING"] = p16.encode_route(items)


def compose() -> bytes:
    raw = BASE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise SystemExit("public32 base hash drifted")
    design = json.loads(raw)
    top = design["modules"]["top"]

    max_bit = max(bit for net in top["netnames"].values()
                  for bit in net.get("bits", []) if isinstance(bit, int))
    event, relayed_event = max_bit + 1, max_bit + 2

    # Delete only the two branches that implemented the qualification set hook.
    # HWDATA1 and status_pending retain every other routed consumer.
    _drop(top["netnames"]["hwdata[1]"], {
        "X14Y10_RMUX31", "X18Y10_RMUX25", "X18Y11_RMUX00",
        "X17Y11_IMUX56",
    })
    _drop(top["netnames"]["public_status_pending"], {
        "X17Y11_RMUX77", "X17Y11_IMUX57",
    })

    setter = top["cells"]["public_set_event"]
    setter["connections"]["I"] = [relayed_event, "0", "0", "0"]
    setter["parameters"]["INIT"] = p16.lut_init(
        lambda gpio, _1, _2, _3: gpio)

    # The GPIO5 lane-0 source is characterized at SLICE3.I3.  The relay is
    # combinational; public_set_event remains the clocked level synchronizer.
    p16.add_slice(
        top, "public_status_gpio5_relay", "X9Y4_SLICE3",
        p16.lut_init(lambda _0, _1, _2, gpio: gpio),
        ["0", "0", "0", event], relayed_event,
    )
    top["cells"]["mcu_gpio5_status_set"] = {
        "hide_name": 0,
        "type": "MCU_GPIO5_OUT_DATA0",
        "parameters": {},
        "attributes": {
            "BEL_STRENGTH": "00000000000000000000000000000001",
            "NEXTPNR_BEL": "X10Y5_MCU_GPIO5_OUT_DATA0262",
            "module_not_derived": "00000000000000000000000000000001",
            "keep": "00000000000000000000000000000001",
            "hdlname": "mcu_gpio5_status_set",
        },
        "port_directions": {"DIN": "output"},
        "connections": {"DIN": [event]},
    }
    top["netnames"]["public_status_gpio5_raw"] = {
        "hide_name": 0, "bits": [event], "attributes": {},
    }

    router = p16.Router(top)
    router.route_new(
        "public_status_gpio5_raw",
        router.pin("mcu_gpio5_status_set", "DIN"),
        [router.pin("public_status_gpio5_relay", "I", 3)],
    )
    router.route_new(
        "public_status_gpio5_relay",
        router.pin("public_status_gpio5_relay", "F"),
        [router.pin("public_set_event", "I", 0)],
    )

    encoded = (json.dumps(design, indent=2) + "\n").encode()
    if hashlib.sha256(encoded).hexdigest() != OUTPUT_SHA256:
        raise SystemExit("GPIO5 W1C candidate hash does not match reviewed artifact")
    return encoded


def compose_or_control() -> bytes:
    """Retain the old bit1 hook and OR in GPIO5 for a causal control image."""
    raw = BASE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise SystemExit("public32 base hash drifted")
    design = json.loads(raw)
    top = design["modules"]["top"]
    max_bit = max(bit for net in top["netnames"].values()
                  for bit in net.get("bits", []) if isinstance(bit, int))
    event, relayed_event = max_bit + 1, max_bit + 2

    setter = top["cells"]["public_set_event"]
    setter["connections"]["I"][2] = relayed_event
    setter["parameters"]["INIT"] = p16.lut_init(
        lambda hwdata1, pending, gpio, _3: (hwdata1 and pending) or gpio)
    p16.add_slice(
        top, "public_status_gpio5_relay", "X9Y4_SLICE3",
        p16.lut_init(lambda _0, _1, _2, gpio: gpio),
        ["0", "0", "0", event], relayed_event,
    )
    top["cells"]["mcu_gpio5_status_set"] = {
        "hide_name": 0,
        "type": "MCU_GPIO5_OUT_DATA0",
        "parameters": {},
        "attributes": {
            "BEL_STRENGTH": "00000000000000000000000000000001",
            "NEXTPNR_BEL": "X10Y5_MCU_GPIO5_OUT_DATA0262",
            "module_not_derived": "00000000000000000000000000000001",
            "keep": "00000000000000000000000000000001",
            "hdlname": "mcu_gpio5_status_set",
        },
        "port_directions": {"DIN": "output"},
        "connections": {"DIN": [event]},
    }
    top["netnames"]["public_status_gpio5_raw"] = {
        "hide_name": 0, "bits": [event], "attributes": {},
    }
    router = p16.Router(top)
    router.route_new(
        "public_status_gpio5_raw",
        router.pin("mcu_gpio5_status_set", "DIN"),
        [router.pin("public_status_gpio5_relay", "I", 3)],
    )
    router.route_new(
        "public_status_gpio5_relay",
        router.pin("public_status_gpio5_relay", "F"),
        [router.pin("public_set_event", "I", 2)],
    )
    encoded = (json.dumps(design, indent=2) + "\n").encode()
    if hashlib.sha256(encoded).hexdigest() != OR_OUTPUT_SHA256:
        raise SystemExit("GPIO5 W1C OR-control hash does not match reviewed artifact")
    return encoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--or-control", action="store_true")
    args = parser.parse_args()
    encoded = compose_or_control() if args.or_control else compose()
    output = args.out or (OR_OUT if args.or_control else OUT)
    output.write_bytes(encoded)
    top = json.loads(encoded)["modules"]["top"]
    routed = sum(bool(net.get("attributes", {}).get("ROUTING"))
                 for net in top["netnames"].values())
    print(f"wrote {output}")
    print(f"sha256={hashlib.sha256(encoded).hexdigest()}")
    print(f"cells={len(top['cells'])} routed_nets={routed}")


if __name__ == "__main__":
    main()
