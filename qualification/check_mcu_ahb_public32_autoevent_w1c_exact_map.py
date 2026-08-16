#!/usr/bin/env python3
"""Fail-closed audit for the exact public32 autonomous-event derivative."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import compose_mcu_ahb_public16_exact_map as p16
import compose_mcu_ahb_public32_autoevent_w1c_exact_map as composer


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "mcu_ahb_public32_autoevent_w1c_exact_map_routed.json"
OR_CONTROL = HERE / "mcu_ahb_public32_autoevent_w1c_or_control_routed.json"
RAW_SHA256 = "cb8372e669833ef103638d4f64ad86cf0e841cb448a9350dbafb79ad33ba1a9b"
COMP_SHA256 = "03da390c45630702c8c73ea47addc9ac201cece8e1b7065ef77908522fab9197"
OR_RAW_SHA256 = "297a5116cd71c8987f1850a459a940fc16c85d8e3492183b2b6d5bbaddcc1aca"
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
    for name in top["netnames"]:
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


def _require_endpoint(top, router, net, cell, port, index=None):
    wire = router.pin(cell, port, index)
    if wire not in {item[0] for item in _route(top, net)}:
        suffix = "" if index is None else str(index)
        raise SystemExit(f"{net} lost {cell}.{port}{suffix}")


def _audit_shared_extensions(base, candidate, *, production):
    shared = {
        "hclk", "reset_request",
        "public_counter_net__core_i.counter[0]",
        "public_counter_net__core_i.counter[1]",
        "public_counter_net__core_i.counter[2]",
    }
    expected_changed = set(shared)
    if production:
        expected_changed |= {"hwdata[1]", "public_status_pending"}
    changed = {name for name in base["netnames"]
               if base["netnames"][name] != candidate["netnames"][name]}
    if changed != expected_changed:
        raise SystemExit(f"base route-change inventory drifted: {changed}")
    for name in shared:
        if _without_route(base["netnames"][name]) != \
                _without_route(candidate["netnames"][name]):
            raise SystemExit("shared net changed outside routing: " + name)
        if not set(_route(base, name)) < set(_route(candidate, name)):
            raise SystemExit("shared net was not append-only: " + name)
    if production:
        for name, removed in (("hwdata[1]", HW_REMOVED),
                              ("public_status_pending", PENDING_REMOVED)):
            if _without_route(base["netnames"][name]) != \
                    _without_route(candidate["netnames"][name]):
                raise SystemExit("retired hook net changed outside routing")
            before, after = set(_route(base, name)), set(_route(candidate, name))
            if before - after != removed or after - before:
                raise SystemExit("retired hook cut drifted: " + name)


def audit(raw_bin=None, compressed=None, or_raw_bin=None):
    encoded = composer.compose()
    or_encoded = composer.compose(or_control=True)
    if CANDIDATE.read_bytes() != encoded or OR_CONTROL.read_bytes() != or_encoded:
        raise SystemExit("tracked autonomous-event checkpoint is not reproducible")
    base = json.loads(composer.BASE.read_bytes())["modules"]["top"]
    candidate = json.loads(encoded)["modules"]["top"]
    control = json.loads(or_encoded)["modules"]["top"]

    for top, label in ((candidate, "production"), (control, "OR control")):
        if set(top["cells"]) - set(base["cells"]) != {
                "autonomous_count7", "autonomous_armed"} or \
                set(base["cells"]) - set(top["cells"]):
            raise SystemExit(label + " cell inventory drifted")
        if {name for name in base["cells"]
                if base["cells"][name] != top["cells"][name]} != {
                    "public_set_event"}:
            raise SystemExit(label + " base-cell mutation drifted")
        if set(top["netnames"]) - set(base["netnames"]) != {
                "autonomous_count7", "autonomous_armed"}:
            raise SystemExit(label + " net inventory drifted")
        count7 = top["cells"]["autonomous_count7"]
        armed = top["cells"]["autonomous_armed"]
        if count7["attributes"]["NEXTPNR_BEL"] != "X17Y11_SLICE0" or \
                count7["parameters"]["INIT"] != p16.lut_init(
                    lambda b0, b1, b2, _3: b0 and b1 and b2):
            raise SystemExit(label + " count==7 detector drifted")
        if armed["attributes"]["NEXTPNR_BEL"] != "X17Y11_SLICE1" or \
                armed["parameters"]["INIT"] != p16.lut_init(
                    lambda terminal, held, reset, _3:
                    reset or (held and not terminal)):
            raise SystemExit(label + " one-shot arm stage drifted")
        if _unique_ownership(top) != (138, 106):
            raise SystemExit(label + " expected 138 BELs / 106 routed nets")

        router = p16.Router(top)
        for index in range(3):
            name = f"public_counter_net__core_i.counter[{index}]"
            _require_endpoint(top, router, name, "autonomous_count7", "I", index)
        _require_endpoint(top, router, "autonomous_count7",
                          "autonomous_armed", "I", 0)
        _require_endpoint(top, router, "autonomous_armed",
                          "autonomous_armed", "I", 1)
        _require_endpoint(top, router, "reset_request",
                          "autonomous_armed", "I", 2)
        _require_endpoint(top, router, "hclk", "autonomous_armed", "CLK")

    _audit_shared_extensions(base, candidate, production=True)
    _audit_shared_extensions(base, control, production=False)
    prod_set = candidate["cells"]["public_set_event"]
    or_set = control["cells"]["public_set_event"]
    if prod_set["parameters"]["INIT"] != p16.lut_init(
            lambda terminal, armed, _2, _3: terminal and armed) or \
            prod_set["connections"]["I"][2:] != ["0", "0"]:
        raise SystemExit("production set stage is not autonomous-only")
    if or_set["parameters"]["INIT"] != p16.lut_init(
            lambda data, pending, terminal, armed:
            (data and pending) or (terminal and armed)):
        raise SystemExit("OR control no longer retains both sources")
    for top, count_pin, arm_pin in ((candidate, 0, 1), (control, 2, 3)):
        router = p16.Router(top)
        _require_endpoint(top, router, "autonomous_count7",
                          "public_set_event", "I", count_pin)
        _require_endpoint(top, router, "autonomous_armed",
                          "public_set_event", "I", arm_pin)

    for path, expected, label in ((raw_bin, RAW_SHA256, "raw"),
                                  (compressed, COMP_SHA256, "compressed"),
                                  (or_raw_bin, OR_RAW_SHA256, "OR raw")):
        if path is None:
            continue
        data = Path(path).read_bytes()
        if (label != "compressed" and len(data) != 99_944) or \
                hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit("autonomous W1C " + label + " hash mismatch")

    print("PASS: autonomous W1C production and OR checkpoints reproduce")
    print("PASS: reset-rearmed count==7 one-shot owns production set ingress")
    print("PASS: old bit1 hook survives only in OR control; public32 map preserved")
    print("PASS: 138 unique BELs / 106 routed nets; append-only shared trees")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-bin", type=Path)
    parser.add_argument("--compressed", type=Path)
    parser.add_argument("--or-raw-bin", type=Path)
    args = parser.parse_args()
    audit(args.raw_bin, args.compressed, args.or_raw_bin)


if __name__ == "__main__":
    main()
