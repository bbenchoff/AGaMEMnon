#!/usr/bin/env python3
"""Compose public32 with a reset-rearmed fabric-autonomous W1C event.

The existing three-bit public counter is real application fabric running from
HCLK.  A count==7 detector and one ``armed`` flip-flop turn its first terminal
count after reset into a single synchronous event.  The source then stays low,
so firmware can distinguish latched hold from W1C clear without a software- or
package-pin-controlled stimulus.

This remains an exact L48 composition.  It proves a synchronous autonomous
fabric source can own the qualified W1C ingress; it is not a generic user-net
overlay, asynchronous CDC contract, interrupt controller, or event ABI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import compose_mcu_ahb_public16_exact_map as p16


HERE = Path(__file__).resolve().parent
BASE = HERE / "mcu_ahb_public32_exact_map_routed.json"
OUT = HERE / "mcu_ahb_public32_autoevent_w1c_exact_map_routed.json"
OR_OUT = HERE / "mcu_ahb_public32_autoevent_w1c_or_control_routed.json"
BASE_SHA256 = "ab76df409898241b0e631ac79926345ac4b4cd0783f0e02898d9f95e6525c574"
OUTPUT_SHA256 = "d2368d6209a8f113beb67cc2a2b4d2cdd0b6f3b922fd3005b467009281f849c5"
OR_OUTPUT_SHA256 = "3b840a7100110db781ce63caed10cec8f4af1328fe8c11be294b3cd9d7217198"


def _drop(net, destinations):
    items = [item for item in p16.route_items(net["attributes"]["ROUTING"])
             if item[0] not in destinations]
    net["attributes"]["ROUTING"] = p16.encode_route(items)


def compose(*, or_control: bool = False) -> bytes:
    raw = BASE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise SystemExit("public32 base hash drifted")
    design = json.loads(raw)
    top = design["modules"]["top"]
    max_bit = max(bit for net in top["netnames"].values()
                  for bit in net.get("bits", []) if isinstance(bit, int))
    count7, armed = max_bit + 1, max_bit + 2

    counter_bits = [
        top["netnames"][f"public_counter_net__core_i.counter[{index}]"]["bits"][0]
        for index in range(3)
    ]
    hclk = top["cells"]["mcu_bus_clock"]["connections"]["CLK"][0]
    reset = top["cells"]["mcu_reset_control"]["connections"]["DIN"][0]

    setter = top["cells"]["public_set_event"]
    if or_control:
        setter["connections"]["I"][2:] = [count7, armed]
        setter["parameters"]["INIT"] = p16.lut_init(
            lambda data, pending, terminal, is_armed:
            (data and pending) or (terminal and is_armed))
    else:
        # Remove exactly the qualification-only HWDATA1/pending set branches.
        # Both producers retain all of their other consumers.
        _drop(top["netnames"]["hwdata[1]"], {
            "X14Y10_RMUX31", "X18Y10_RMUX25", "X18Y11_RMUX00",
            "X17Y11_IMUX56",
        })
        _drop(top["netnames"]["public_status_pending"], {
            "X17Y11_RMUX77", "X17Y11_IMUX57",
        })
        setter["connections"]["I"] = [count7, armed, "0", "0"]
        setter["parameters"]["INIT"] = p16.lut_init(
            lambda terminal, is_armed, _2, _3: terminal and is_armed)

    p16.add_slice(
        top, "autonomous_count7", "X17Y11_SLICE0",
        p16.lut_init(lambda b0, b1, b2, _3: b0 and b1 and b2),
        [*counter_bits, "0"], count7,
    )
    p16.add_ff(
        top, "autonomous_armed", "X17Y11_SLICE1",
        p16.lut_init(lambda terminal, held, in_reset, _3:
                     in_reset or (held and not terminal)),
        [count7, armed, reset, "0"], hclk, armed,
    )

    router = p16.Router(top)
    # This order is part of the reviewed artifact: the armed feedback is the
    # scarcest route, then the terminal fanout, then the retained shared trees.
    router.route_new(
        "autonomous_armed",
        router.pin("autonomous_armed", "Q"),
        [router.pin("autonomous_armed", "I", 1),
         router.pin("public_set_event", "I", 3 if or_control else 1)],
    )
    router.route_new(
        "autonomous_count7",
        router.pin("autonomous_count7", "F"),
        [router.pin("autonomous_armed", "I", 0),
         router.pin("public_set_event", "I", 2 if or_control else 0)],
    )
    for index, bit in enumerate(counter_bits):
        router.extend(p16.find_net(top, bit),
                      [router.pin("autonomous_count7", "I", index)])
    router.extend(p16.find_net(top, reset),
                  [router.pin("autonomous_armed", "I", 2)])
    router.extend(p16.find_net(top, hclk),
                  [router.pin("autonomous_armed", "CLK")])

    encoded = (json.dumps(design, indent=2) + "\n").encode()
    expected = OR_OUTPUT_SHA256 if or_control else OUTPUT_SHA256
    actual = hashlib.sha256(encoded).hexdigest()
    if actual != expected:
        raise SystemExit(
            f"autonomous W1C artifact hash does not match review: {actual}")
    return encoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--or-control", action="store_true")
    args = parser.parse_args()
    encoded = compose(or_control=args.or_control)
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
