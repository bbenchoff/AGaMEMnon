#!/usr/bin/env python3
"""Fail-closed audit for the exact public32 GPIO5 level-set derivative."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import compose_mcu_ahb_public16_exact_map as p16
import compose_mcu_ahb_public32_gpio5_w1c_exact_map as composer


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "mcu_ahb_public32_gpio5_w1c_exact_map_routed.json"
OR_CONTROL = HERE / "mcu_ahb_public32_gpio5_w1c_or_control_routed.json"
RAW_SHA256 = "bc338504e5b30fb9036d29f91c2cca6e384ef85ba2bde8ba8e79c62f05f4eb33"
COMP_SHA256 = "6f82f2a5aecd00347156d08af09d8a3755e3aebda3b81a459178dd0623b9b5db"
OR_RAW_SHA256 = "fe34d0b05e773b0fbd803f3a1809c4177afb3317d1049939e101a5cfc5e4d681"

HW_REMOVED = {
    ("X14Y10_RMUX31", "X14Y11_RMUX07.X14Y10_RMUX31", "1"),
    ("X18Y10_RMUX25", "X14Y10_RMUX31.X18Y10_RMUX25", "1"),
    ("X18Y11_RMUX00", "X18Y10_RMUX25.X18Y11_RMUX00", "1"),
    ("X17Y11_IMUX56", "X18Y11_RMUX00.X17Y11_IMUX56", "1"),
}
PENDING_REMOVED = {
    ("X17Y11_RMUX77", "X18Y11_RMUX93.X17Y11_RMUX77", "1"),
    ("X17Y11_IMUX57", "X17Y11_RMUX77.X17Y11_IMUX57", "1"),
}
RAW_ROUTE = [
    ("X9Y5_BufMUX01", "", "1"),
    ("X9Y5_InputMUX00", "X9Y5_BufMUX01.X9Y5_InputMUX00", "1"),
    ("X9Y4_RMUX23", "X9Y5_InputMUX00.X9Y4_RMUX23", "1"),
    ("X9Y4_IMUX15", "X9Y4_RMUX23.X9Y4_IMUX15", "1"),
]
RELAY_ROUTE = [
    ("X9Y4_OMUX11", "", "1"),
    ("X9Y4_RMUX20", "X9Y4_OMUX11.X9Y4_RMUX20", "1"),
    ("X8Y4_RMUX81", "X9Y4_RMUX20.X8Y4_RMUX81", "1"),
    ("X12Y4_RMUX38", "X8Y4_RMUX81.X12Y4_RMUX38", "1"),
    ("X16Y4_RMUX61", "X12Y4_RMUX38.X16Y4_RMUX61", "1"),
    ("X18Y4_RMUX55", "X16Y4_RMUX61.X18Y4_RMUX55", "1"),
    ("X18Y7_RMUX25", "X18Y4_RMUX55.X18Y7_RMUX25", "1"),
    ("X18Y11_RMUX00", "X18Y7_RMUX25.X18Y11_RMUX00", "1"),
    ("X17Y11_IMUX56", "X18Y11_RMUX00.X17Y11_IMUX56", "1"),
]


def _route(top, name):
    return p16.route_items(
        top["netnames"][name].get("attributes", {}).get("ROUTING", ""))


def _without_route(net):
    value = json.loads(json.dumps(net))
    value.setdefault("attributes", {}).pop("ROUTING", None)
    return value


def _unique_ownership(top):
    bels, wires = {}, {}
    routed = 0
    for name, cell in top["cells"].items():
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if not bel or bel in bels:
            raise SystemExit("unplaced or duplicate BEL: " + str(bel))
        bels[bel] = name
    for name, net in top["netnames"].items():
        items = _route(top, name)
        routed += bool(items)
        for dst, pip, strength in items:
            if strength not in {"1", "5"}:
                raise SystemExit("unexpected route strength")
            for wire in (dst, pip.split(".", 1)[0] if pip else None):
                if not wire:
                    continue
                prior = wires.get(wire)
                if prior is not None and prior != name:
                    raise SystemExit(f"wire conflict {wire}: {prior}/{name}")
                wires[wire] = name
    return len(bels), routed


def audit(raw_bin=None, compressed=None, or_raw_bin=None):
    encoded = composer.compose()
    or_encoded = composer.compose_or_control()
    if CANDIDATE.read_bytes() != encoded:
        raise SystemExit("tracked GPIO5 W1C checkpoint is not reproducible")
    if OR_CONTROL.read_bytes() != or_encoded:
        raise SystemExit("tracked GPIO5 OR control is not reproducible")
    base = json.loads(composer.BASE.read_bytes())["modules"]["top"]
    candidate = json.loads(encoded)["modules"]["top"]
    control = json.loads(or_encoded)["modules"]["top"]

    added = set(candidate["cells"]) - set(base["cells"])
    if added != {"mcu_gpio5_status_set", "public_status_gpio5_relay"} or \
            set(base["cells"]) - set(candidate["cells"]):
        raise SystemExit("cell inventory drifted")
    mutated = {name for name in base["cells"]
               if base["cells"][name] != candidate["cells"][name]}
    if mutated != {"public_set_event"}:
        raise SystemExit("base-cell mutation inventory drifted")
    before = base["cells"]["public_set_event"]
    after = candidate["cells"]["public_set_event"]
    normalized = json.loads(json.dumps(after))
    normalized["parameters"]["INIT"] = before["parameters"]["INIT"]
    normalized["connections"]["I"] = before["connections"]["I"]
    if normalized != before or after["parameters"]["INIT"] != \
            p16.lut_init(lambda gpio, _1, _2, _3: gpio):
        raise SystemExit("set-stage changed outside the reviewed identity cutover")

    hard = candidate["cells"]["mcu_gpio5_status_set"]
    relay = candidate["cells"]["public_status_gpio5_relay"]
    if hard["type"] != "MCU_GPIO5_OUT_DATA0" or hard["attributes"].get(
            "NEXTPNR_BEL") != "X10Y5_MCU_GPIO5_OUT_DATA0262":
        raise SystemExit("GPIO5 hard-source binding drifted")
    if relay["attributes"].get("NEXTPNR_BEL") != "X9Y4_SLICE3" or \
            relay["parameters"]["INIT"] != \
            p16.lut_init(lambda _0, _1, _2, gpio: gpio):
        raise SystemExit("GPIO5 relay binding/function drifted")
    raw_bit = candidate["netnames"]["public_status_gpio5_raw"]["bits"][0]
    relay_bit = candidate["netnames"]["public_status_gpio5_relay"]["bits"][0]
    if hard["connections"]["DIN"] != [raw_bit] or \
            relay["connections"]["I"] != ["0", "0", "0", raw_bit] or \
            after["connections"]["I"] != [relay_bit, "0", "0", "0"]:
        raise SystemExit("GPIO5 event connectivity drifted")
    if _route(candidate, "public_status_gpio5_raw") != RAW_ROUTE or \
            _route(candidate, "public_status_gpio5_relay") != RELAY_ROUTE:
        raise SystemExit("qualified GPIO5 event route drifted")

    changed = set()
    for name, old in base["netnames"].items():
        new = candidate["netnames"][name]
        if old == new:
            continue
        changed.add(name)
        if _without_route(old) != _without_route(new):
            raise SystemExit("base net changed outside routing: " + name)
        removed = set(_route(base, name)) - set(_route(candidate, name))
        added_items = set(_route(candidate, name)) - set(_route(base, name))
        expected = HW_REMOVED if name == "hwdata[1]" else PENDING_REMOVED
        if name not in {"hwdata[1]", "public_status_pending"} or \
                removed != expected or added_items:
            raise SystemExit("unreviewed base-route change: " + name)
    if changed != {"hwdata[1]", "public_status_pending"}:
        raise SystemExit("base route-change inventory drifted")
    if set(candidate["netnames"]) - set(base["netnames"]) != {
            "public_status_gpio5_raw", "public_status_gpio5_relay"}:
        raise SystemExit("added net inventory drifted")

    router = p16.Router(candidate)
    pending = {item[0] for item in _route(candidate, "public_status_pending")}
    for cell, port, index in (("public_clear_event", "I", 1),
                              ("write_wait_stage", "I", 3)):
        if router.pin(cell, port, index) not in pending:
            raise SystemExit(f"status_pending lost {cell}.{port}{index}")
    if router.pin("public_set_event", "I", 1) in pending:
        raise SystemExit("retired qualification pending branch survived")
    if _unique_ownership(candidate) != (138, 106):
        raise SystemExit("expected 138 unique BELs and 106 routed nets")

    # The OR image is a causal control: all base routes remain intact, the same
    # two cells/nets are added, and only the set LUT's I2/function changes.
    if set(control["cells"]) - set(base["cells"]) != added or \
            set(control["netnames"]) - set(base["netnames"]) != {
                "public_status_gpio5_raw", "public_status_gpio5_relay"}:
        raise SystemExit("OR-control inventory drifted")
    control_mutated = {name for name in base["cells"]
                       if base["cells"][name] != control["cells"][name]}
    if control_mutated != {"public_set_event"}:
        raise SystemExit("OR-control base mutation drifted")
    for name in base["netnames"]:
        if base["netnames"][name] != control["netnames"][name]:
            raise SystemExit("OR-control changed a base route: " + name)
    if _unique_ownership(control) != (138, 106):
        raise SystemExit("OR-control ownership/count drifted")

    for path, expected, label in ((raw_bin, RAW_SHA256, "raw"),
                                  (compressed, COMP_SHA256, "compressed"),
                                  (or_raw_bin, OR_RAW_SHA256, "OR raw")):
        if path is not None:
            data = Path(path).read_bytes()
            if (label != "compressed" and len(data) != 99_944) or \
                    hashlib.sha256(data).hexdigest() != expected:
                raise SystemExit("GPIO5 W1C " + label + " hash mismatch")

    print("PASS: public32 GPIO5 W1C production and OR-control checkpoints reproduce")
    print("PASS: exact lane-0 ingress + relay; old bit1 set branch removed only in production")
    print("PASS: clear, storage, wait and public32 map routes preserved; 138 BELs/106 nets")
    if raw_bin is not None:
        print("PASS: exact GPIO5 W1C raw/compressed image hashes pinned")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-bin", type=Path)
    parser.add_argument("--compressed", type=Path)
    parser.add_argument("--or-raw-bin", type=Path)
    args = parser.parse_args()
    audit(args.raw_bin, args.compressed, args.or_raw_bin)


if __name__ == "__main__":
    main()
