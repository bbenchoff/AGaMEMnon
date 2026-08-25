#!/usr/bin/env python3
"""Fail-closed structural audit for the exact L48 public32 map."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import compose_mcu_ahb_public16_exact_map as p16
import compose_mcu_ahb_public32_exact_map as composer


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "mcu_ahb_public32_exact_map_routed.json"
RAW_SHA256 = "ac33ca6b4628258c62137e4c006ca25a222368e39c9a2e2d33a68e7b07dae6f5"
COMP_SHA256 = "ee5c464337ac389464f7d95ca522416752e6c62307ce3e2048a4e51aefdf6cba"
MUTATED_CELLS = {"read_gate8", "read_gate14"}
APPENDED_NETS = {"$PACKER_GND_NET", "read_word0", "public_high_active"}
REMOVED_STATUS = {
    ("X14Y9_RMUX19", "X14Y9_OMUX05.X14Y9_RMUX19", "1"),
    ("X14Y12_RMUX95", "X14Y9_RMUX19.X14Y12_RMUX95", "1"),
    ("X14Y12_IMUX57", "X14Y12_RMUX95.X14Y12_IMUX57", "1"),
}
ADDED_STATUS = set(composer.REVIEWED_STATUS_BRANCH)


def normalized_without_route(net):
    value = json.loads(json.dumps(net))
    value.setdefault("attributes", {}).pop("ROUTING", None)
    return value


def audit(raw_bin=None, compressed=None):
    encoded = composer.compose()
    if CANDIDATE.read_bytes() != encoded:
        raise SystemExit("tracked public32 checkpoint is not composer-reproducible")
    if p16.text_sha256(encoded) != composer.OUTPUT_SHA256:
        raise SystemExit("public32 routed hash mismatch")
    base = json.loads(composer.BASE.read_bytes())["modules"]["top"]
    candidate = json.loads(encoded)["modules"]["top"]

    added = set(candidate["cells"]) - set(base["cells"])
    expected_added = {"public_id_upper_select"} | {
        f"mcu_h{lane}" for lane in range(16, 32)}
    if added != expected_added or set(base["cells"]) - set(candidate["cells"]):
        raise SystemExit("public32 added/removed cell inventory drifted")
    mutated = {name for name in base["cells"]
               if base["cells"][name] != candidate["cells"][name]}
    if mutated != MUTATED_CELLS:
        raise SystemExit("public16 cell mutation inventory drifted")
    for name in MUTATED_CELLS:
        before, after = base["cells"][name], candidate["cells"][name]
        normalized = json.loads(json.dumps(after))
        normalized["parameters"]["INIT"] = before["parameters"]["INIT"]
        normalized["connections"]["I"] = before["connections"]["I"]
        if normalized != before:
            raise SystemExit(name + " changed outside INIT/I")

    for lane in range(16, 32):
        cell = candidate["cells"][f"mcu_h{lane}"]
        if cell["type"] != "MCU_DOUT" or \
                cell["attributes"]["NEXTPNR_BEL"] != \
                f"X10Y5_MCU_DOUT{lane + 13}":
            raise SystemExit(f"HRDATA{lane} exit binding drifted")
        bit = cell["connections"]["DOUT"][0]
        expected = (candidate["netnames"]["public_id_upper_select"]["bits"][0]
                    if lane in composer.ID_ONES else
                    candidate["netnames"]["$PACKER_GND_NET"]["bits"][0])
        if bit != expected:
            raise SystemExit(f"HRDATA{lane} source drifted")
    if candidate["cells"]["public_id_upper_select"]["attributes"][
            "NEXTPNR_BEL"] != "X16Y9_SLICE4":
        raise SystemExit("ID selector BEL drifted")

    changed_nets = set()
    for name, before in base["netnames"].items():
        after = candidate["netnames"][name]
        if before == after:
            continue
        changed_nets.add(name)
        if normalized_without_route(before) != normalized_without_route(after):
            raise SystemExit("base net changed outside ROUTING: " + name)
        old = p16.route_items(before.get("attributes", {}).get("ROUTING", ""))
        new = p16.route_items(after.get("attributes", {}).get("ROUTING", ""))
        if name in APPENDED_NETS:
            if new[:len(old)] != old or len(new) <= len(old):
                raise SystemExit("route was not append-only: " + name)
        elif name == "public_status_pending":
            if set(old) - set(new) != REMOVED_STATUS or \
                    set(new) - set(old) != ADDED_STATUS:
                raise SystemExit("status-pending route exchange drifted")
        else:
            raise SystemExit("unreviewed base route changed: " + name)
    if changed_nets != APPENDED_NETS | {"public_status_pending"}:
        raise SystemExit("changed base-net inventory drifted")

    bel_owners, wire_owners = {}, {}
    routed = 0
    for name, cell in candidate["cells"].items():
        bel = cell["attributes"].get("NEXTPNR_BEL")
        if not bel or bel in bel_owners:
            raise SystemExit("unplaced or duplicate BEL: " + str(bel))
        bel_owners[bel] = name
    for name, net in candidate["netnames"].items():
        route = p16.route_items(net.get("attributes", {}).get("ROUTING", ""))
        if route:
            routed += 1
        for dst, pip, strength in route:
            if strength not in {"1", "5"}:
                raise SystemExit("unexpected route strength")
            if pip == "X14Y11_RMUX42.X13Y11_BBMUXW03":
                raise SystemExit("unencoded HRDATA28 entrance selected")
            for wire in (dst, pip.split(".", 1)[0] if pip else None):
                if wire:
                    prior = wire_owners.get(wire)
                    if prior is not None and prior != name:
                        raise SystemExit(f"wire conflict {wire}: {prior}/{name}")
                    wire_owners[wire] = name
    if len(candidate["cells"]) != 136 or routed != 104:
        raise SystemExit("expected 136 cells and 104 routed nets")
    ground_pips = {item[1] for item in p16.route_items(
        candidate["netnames"]["$PACKER_GND_NET"]["attributes"]["ROUTING"])}
    if "X14Y11_RMUX90.X13Y11_BBMUXW03" not in ground_pips:
        raise SystemExit("exact HRDATA28 RMUX90 entrance missing")

    router = p16.Router(candidate)
    pending_route = {item[0] for item in p16.route_items(
        candidate["netnames"]["public_status_pending"]["attributes"]["ROUTING"])}
    for cell, port, index in (("public_clear_event", "I", 1),
                              ("public_set_event", "I", 1),
                              ("write_wait_stage", "I", 3)):
        if router.pin(cell, port, index) not in pending_route:
            raise SystemExit(f"status_pending no longer reaches {cell}.{port}{index}")

    if raw_bin is not None:
        data = Path(raw_bin).read_bytes()
        if len(data) != 99_944 or hashlib.sha256(data).hexdigest() != RAW_SHA256:
            raise SystemExit("public32 raw bitstream hash mismatch")
    if compressed is not None:
        data = Path(compressed).read_bytes()
        if hashlib.sha256(data).hexdigest() != COMP_SHA256:
            raise SystemExit("public32 compressed bitstream hash mismatch")

    print("PASS: composer-reproducible canonical public32 checkpoint")
    print("PASS: public16 base retained; 2 reviewed LUT edits, exact pending-branch relocation")
    print("PASS: 16 exact HRDATA exits + ID selector; 136 unique BELs, 104 routed nets")
    print("PASS: canonical ID 0x4147414d sources and all upper-zero sources pinned")
    if raw_bin is not None:
        print("PASS: exact public32 raw bitstream hash pinned")
    if compressed is not None:
        print("PASS: exact public32 compressed bitstream hash pinned")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-bin", type=Path)
    parser.add_argument("--compressed", type=Path)
    args = parser.parse_args()
    audit(args.raw_bin, args.compressed)


if __name__ == "__main__":
    main()
