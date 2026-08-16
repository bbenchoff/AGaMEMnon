#!/usr/bin/env python3
"""Independent structural audit of the exact bank16 read-gated checkpoint."""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import re

import compose_mcu_ahb_bank16_read_word0_gated as composer


HERE = Path(__file__).resolve().parent
BASE = HERE / "mcu_ahb_register_bank16_word_byte_halfword_waited_routed.json"
ROUTED = HERE / "mcu_ahb_register_bank16_read_word0_gated_routed.json"
EXPECTED_ROUTED_SHA256 = "1daa7de2d8a5297182b35c21d745900e93bb540bd4ca3320449108dccd3fbef2"
MODE_INITS = {
    "zero": "0000000000000000",
    "one": "1111111111111111",
    "nota2": "0101010101010101",
    "nota3": "0011001100110011",
    "real": "0001000100010001",
}


def triples(route):
    fields = route.split(";")
    assert len(fields) % 3 == 0
    return [fields[index:index + 3] for index in range(0, len(fields), 3)]


def path_items(items, target):
    roots = [item[0] for item in items if item[0] and not item[1]]
    assert len(roots) == 1, roots
    adjacency = defaultdict(list)
    by_edge = {}
    for item in items:
        if item[1]:
            source, destination = item[1].split(".")
            adjacency[source].append(destination)
            by_edge[(source, destination)] = item
    queue = deque([roots[0]])
    previous = {roots[0]: None}
    while queue:
        wire = queue.popleft()
        if wire == target:
            break
        for nxt in adjacency.get(wire, ()):
            if nxt not in previous:
                previous[nxt] = wire
                queue.append(nxt)
    assert target in previous, target
    result = []
    while previous[target] is not None:
        source = previous[target]
        result.append(by_edge[(source, target)])
        target = source
    return list(reversed(result))


def recursive_diffs(left, right, path=""):
    if type(left) is not type(right):
        return [(path, left, right)]
    if isinstance(left, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                result.append((path + "/" + key, left.get(key), right.get(key)))
            else:
                result.extend(recursive_diffs(left[key], right[key], path + "/" + key))
        return result
    if isinstance(left, list):
        if len(left) != len(right):
            return [(path, left, right)]
        result = []
        for index, (lvalue, rvalue) in enumerate(zip(left, right)):
            result.extend(recursive_diffs(lvalue, rvalue, path + "/%d" % index))
        return result
    return [] if left == right else [(path, left, right)]


def endpoints(route):
    items = triples(route)
    roots = sorted(item[0] for item in items if item[0] and not item[1])
    destinations = {item[0] for item in items if item[0]}
    sources = {item[1].split(".")[0] for item in items if item[1]}
    return roots, sorted(destinations - sources)


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))["modules"]["top"]
    encoded = {mode: composer.compose(mode) for mode in MODE_INITS}
    variants = {mode: json.loads(payload) for mode, payload in encoded.items()}
    assert encoded["real"] == ROUTED.read_bytes()
    assert hashlib.sha256(encoded["real"]).hexdigest() == EXPECTED_ROUTED_SHA256

    reference = variants["zero"]
    expected_path = "/modules/top/cells/read_word0/parameters/INIT"
    for mode, expected_init in MODE_INITS.items():
        actual = variants[mode]["modules"]["top"]["cells"]["read_word0"]["parameters"]["INIT"]
        assert actual == expected_init, (mode, actual)
        if mode != "zero":
            diffs = recursive_diffs(reference, variants[mode])
            assert len(diffs) == 1 and diffs[0][0] == expected_path, (mode, diffs[:5])

    candidate = variants["real"]["modules"]["top"]
    base_bits = {bit: name for name, net in base["netnames"].items()
                 for bit in net.get("bits", []) if isinstance(bit, int)}
    candidate_bits = {bit: name for name, net in candidate["netnames"].items()
                      for bit in net.get("bits", []) if isinstance(bit, int)}

    decoder = candidate["cells"]["read_word0"]
    assert decoder["attributes"]["NEXTPNR_BEL"] == "X14Y12_SLICE5"
    assert decoder["connections"]["I"][:2] == [
        candidate["netnames"]["haddr2"]["bits"][0],
        candidate["netnames"]["haddr3"]["bits"][0],
    ]
    assert int(decoder["parameters"]["INIT"], 2) == 0x1111

    for lane in range(16):
        base_feedback = base["cells"][f"feedback_buffer{lane}"]
        assert candidate["cells"][f"feedback_buffer{lane}"] == base_feedback
        state_bit = base["cells"][f"capture{lane}"]["connections"]["Q"][0]
        state_name = base_bits[state_bit]
        match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)",
                             base_feedback["attributes"]["NEXTPNR_BEL"])
        x, y, z = map(int, match.groups())
        feedback_target = f"X{x}Y{y}_IMUX{4*z:02d}"
        original_feedback = path_items(
            triples(base["netnames"][state_name]["attributes"]["ROUTING"]),
            feedback_target)
        retained_items = triples(
            candidate["netnames"][state_name]["attributes"]["ROUTING"])
        retained_by_pip = {item[1]: item for item in retained_items if item[1]}
        for item in original_feedback:
            assert retained_by_pip.get(item[1]) == item, (lane, item)

        gate = candidate["cells"][f"read_gate{lane}"]
        assert int(gate["parameters"]["INIT"], 2) == 0x8888
        assert gate["connections"]["I"][1] == decoder["connections"]["F"][0]
        output_bit = gate["connections"]["F"][0]
        output_name = candidate_bits[output_bit]
        assert output_name == f"read_gate{lane}"
        original_sinks = [item[0] for item in
                          triples(base["netnames"][state_name]["attributes"]["ROUTING"])
                          if item[0].startswith("X0Y5_SinkMUXPseudo")]
        assert len(original_sinks) == 1
        output_items = triples(candidate["netnames"][output_name]["attributes"]["ROUTING"])
        path_items(output_items, original_sinks[0])
        consumers = [cell for cell in candidate["cells"].values()
                     if cell["type"] == "MCU_DOUT" and cell["connections"]["DOUT"] == [output_bit]]
        assert len(consumers) == 1

    for net_name in ("hwdata[9]", "$PACKER_GND_NET"):
        assert endpoints(base["netnames"][net_name]["attributes"]["ROUTING"]) == \
            endpoints(candidate["netnames"][net_name]["attributes"]["ROUTING"])

    baseline_owners = composer.wire_owners(base["netnames"])
    candidate_owners = composer.wire_owners(candidate["netnames"])
    changed_collisions = {wire: owners for wire, owners in candidate_owners.items()
                          if baseline_owners.get(wire) != owners}
    assert not changed_collisions, changed_collisions
    print("PASS: exact routed hash, five-mode isolation, 16 feedback paths, "
          "16 MCU sinks, local-exchange endpoints, and wire ownership")


if __name__ == "__main__":
    main()
