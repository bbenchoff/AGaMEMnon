#!/usr/bin/env python3
"""Compose the exact L48 32-bit public map from the qualified public16 map.

The public16 state machine and all 101 cells inherited from its scratch base are
preserved.  This adds the sixteen hard HRDATA exits, qualifies the upper ID
constant at +0, and forces every upper bit low at +4/+8/+c.  Routing uses only
the same strict graph as the public16 composer and rejects cross-net ownership.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import compose_mcu_ahb_public16_exact_map as p16


HERE = Path(__file__).resolve().parent
BASE = HERE / "mcu_ahb_public16_exact_map_routed.json"
OUT = HERE / "mcu_ahb_public32_exact_map_routed.json"
BASE_SHA256 = "aa7ff307b6d59035928bf79306a3e55a69434e9458672a36ed51a7abe162c5fe"
OUTPUT_SHA256 = "ab76df409898241b0e631ac79926345ac4b4cd0783f0e02898d9f95e6525c574"
ID_ONES = {16, 17, 18, 22, 24, 30}
REVIEWED_STATUS_BRANCH = [
    ("X15Y9_RMUX69", "X14Y9_RMUX15.X15Y9_RMUX69", "1"),
    ("X15Y10_RMUX92", "X15Y9_RMUX69.X15Y10_RMUX92", "1"),
    ("X15Y11_RMUX85", "X15Y10_RMUX92.X15Y11_RMUX85", "1"),
    ("X15Y12_RMUX54", "X15Y11_RMUX85.X15Y12_RMUX54", "1"),
    ("X14Y12_IMUX57", "X15Y12_RMUX54.X14Y12_IMUX57", "1"),
]


def compose() -> bytes:
    raw = BASE.read_bytes()
    if p16.text_sha256(raw) != BASE_SHA256:
        raise SystemExit("public16 base hash drifted")
    design = json.loads(raw)
    top = design["modules"]["top"]
    base_max_bit = max(
        bit for net in top["netnames"].values()
        for bit in net.get("bits", []) if isinstance(bit, int)
    )
    id_select = base_max_bit + 1
    high_active = top["netnames"]["public_high_active"]["bits"][0]
    read_word4 = top["cells"]["read_word0"]["connections"]["F"][0]
    ground = top["netnames"]["$PACKER_GND_NET"]["bits"][0]

    # ID selector: +0 is the only class that is neither +4 nor the +8/+c high
    # class.  One shared net supplies exactly the six asserted upper ID bits.
    p16.add_slice(
        top, "public_id_upper_select", "X16Y9_SLICE4",
        p16.lut_init(lambda high, read4, _2, _3: not high and not read4),
        [high_active, read_word4, "0", "0"], id_select,
    )

    # Complete the lower half of 0x4147414d.  At +4 these retain scratch bits;
    # at +8/+c they remain zero.
    id_low_init = p16.lut_init(
        lambda held, read4, high, _3:
        (not high) and (held if read4 else True)
    )
    for index in (8, 14):
        state = top["cells"][f"capture{index}"]["connections"]["Q"][0]
        gate = top["cells"][f"read_gate{index}"]
        gate["connections"]["I"] = [state, read_word4, high_active, "0"]
        gate["parameters"]["INIT"] = id_low_init

    for lane in range(16, 32):
        name = f"mcu_h{lane}"
        top["cells"][name] = {
            "hide_name": 0,
            "type": "MCU_DOUT",
            "parameters": {},
            "attributes": {
                "BEL_STRENGTH": "00000000000000000000000000000101",
                "NEXTPNR_BEL": f"X10Y5_MCU_DOUT{lane + 13}",
                "module_not_derived":
                    "00000000000000000000000000000001",
                "keep": "00000000000000000000000000000001",
                "hdlname": name,
            },
            "port_directions": {"DOUT": "input"},
            "connections": {"DOUT": [id_select if lane in ID_ONES else ground]},
        }

    # Lane30's exact RMUX19 entrance was the status_pending branch to
    # public_clear_event.I1.  Remove only that branch; the producer and its
    # other consumers remain routed.
    status_net = top["netnames"]["public_status_pending"]
    removed = {"X14Y9_RMUX19", "X14Y12_RMUX95", "X14Y12_IMUX57"}
    status_items = [item for item in p16.route_items(
        status_net["attributes"]["ROUTING"]) if item[0] not in removed]
    status_net["attributes"]["ROUTING"] = p16.encode_route(status_items)

    router = p16.Router(top)
    router.route_new(
        "public_id_upper_select",
        router.pin("public_id_upper_select", "F"),
        [router.pin("mcu_h30", "DOUT")],
    )

    # The strict RRG still exposes one generic ROUTE into HRDATA28 that has no
    # bitgen encoding.  Refuse it explicitly so BFS chooses an exact MCUEDGE.
    router.owners["X14Y11_RMUX42"] = "__reject_unencoded_hrdata28__"
    router.extend(
        "$PACKER_GND_NET",
        [router.pin(f"mcu_h{lane}", "DOUT")
         for lane in range(16, 32) if lane not in ID_ONES],
    )
    del router.owners["X14Y11_RMUX42"]
    router.extend(
        "public_id_upper_select",
        [router.pin(f"mcu_h{lane}", "DOUT")
         for lane in sorted(ID_ONES - {30})],
    )

    # Restore the displaced status consumer after the new exits own their
    # paths, then append only the three required selector branches.
    router.extend_exact("public_status_pending", REVIEWED_STATUS_BRANCH)
    if REVIEWED_STATUS_BRANCH[-1][0] != router.pin("public_clear_event", "I", 1):
        raise SystemExit("reviewed status branch no longer reaches clear-event input")
    router.extend("public_high_active", [
        router.pin("public_id_upper_select", "I", 0),
        router.pin("read_gate8", "I", 2),
        router.pin("read_gate14", "I", 2),
    ])
    router.extend(p16.find_net(top, read_word4),
                  [router.pin("public_id_upper_select", "I", 1)])

    bels = defaultdict(list)
    for name, cell in top["cells"].items():
        bels[cell["attributes"].get("NEXTPNR_BEL")].append(name)
    duplicates = {bel: names for bel, names in bels.items()
                  if bel and len(names) > 1}
    if duplicates:
        raise SystemExit(f"duplicate BELs: {duplicates}")

    encoded = (json.dumps(design, indent=2) + "\n").encode()
    if p16.text_sha256(encoded) != OUTPUT_SHA256:
        raise SystemExit("public32 candidate hash does not match reviewed artifact")
    return encoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    encoded = compose()
    args.out.write_bytes(encoded)
    top = json.loads(encoded)["modules"]["top"]
    print(f"wrote {args.out}")
    print(f"sha256={p16.text_sha256(encoded)}")
    print(f"cells={len(top['cells'])} routed_nets="
          f"{sum(bool(n.get('attributes', {}).get('ROUTING')) for n in top['netnames'].values())}")


if __name__ == "__main__":
    main()
