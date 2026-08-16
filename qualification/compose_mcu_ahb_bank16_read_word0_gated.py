#!/usr/bin/env python3
"""Reproduce the exact silicon-qualified 16-lane read-word-zero checkpoint.

The five modes exist to reproduce the causal hardware controls.  ``real`` is
the qualified implementation: every HRDATA[15:0] exit is gated by
``!HADDR[2] && !HADDR[3]``.  The other modes change only that decoder LUT.
"""

from __future__ import annotations

from collections import defaultdict, deque
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
BASE = HERE / "mcu_ahb_register_bank16_word_byte_halfword_waited_routed.json"
TREE = HERE / "mcu_ahb_bank16_read_word0_gate_routes.json"
SWAP = HERE / "mcu_ahb_bank16_read_word0_local_exchange.json"
OUT = HERE / "mcu_ahb_register_bank16_read_word0_gated_routed.json"
EXPECTED_BASE_SHA256 = "2b70e625bf82f71c6fda3f50f1467a25adbfce81716d47a1809d7b483c62802a"
EXPECTED_REAL_SHA256 = "1daa7de2d8a5297182b35c21d745900e93bb540bd4ca3320449108dccd3fbef2"
MODES = {
    "one": 0xFFFF,
    "zero": 0x0000,
    "nota2": 0x5555,
    "nota3": 0x3333,
    "real": 0x1111,
}


def triples(route):
    fields = route.split(";")
    assert len(fields) % 3 == 0
    return [fields[i:i + 3] for i in range(0, len(fields), 3)]


def encode(items):
    return ";".join(value for item in items for value in item)


def path(items, target):
    root_items = [item for item in items if item[0] and not item[1]]
    assert len(root_items) == 1, root_items
    root = root_items[0][0]
    adjacency = defaultdict(list)
    for _destination, pip, _strength in items:
        if pip:
            source, destination = pip.split(".")
            adjacency[source].append(destination)
    queue = deque([root])
    previous = {root: None}
    while queue:
        wire = queue.popleft()
        if wire == target:
            break
        for nxt in adjacency.get(wire, ()):
            if nxt not in previous:
                previous[nxt] = wire
                queue.append(nxt)
    if target not in previous:
        raise SystemExit("route does not reach %s" % target)
    edges = []
    while previous[target] is not None:
        source = previous[target]
        edges.append((source, target))
        target = source
    return root_items[0], list(reversed(edges))


def routed(root, edges, strength="5"):
    return encode([[destination, source + "." + destination, strength]
                   for source, destination in edges] + [[root, "", strength]])


def append_edges(net, edges, strength="5"):
    items = triples(net["attributes"]["ROUTING"])
    present = {item[1] for item in items if item[1]}
    for source, destination in edges:
        pip = source + "." + destination
        if pip not in present:
            items.insert(0, [destination, pip, strength])
            present.add(pip)
    net["attributes"]["ROUTING"] = encode(items)


def original_items_for_edges(items, root_item, edges):
    by_pip = {item[1]: item for item in items if item[1]}
    result = [copy.deepcopy(root_item)]
    for source, destination in edges:
        result.append(copy.deepcopy(by_pip[source + "." + destination]))
    return result


def wire_owners(nets):
    owners = defaultdict(set)
    for name, net in nets.items():
        route = net.get("attributes", {}).get("ROUTING")
        if not route:
            continue
        for destination, pip, _strength in triples(route):
            if destination and destination != "GCLK0":
                owners[destination].add(name)
            if pip:
                for wire in pip.split("."):
                    if wire != "GCLK0":
                        owners[wire].add(name)
    return {wire: sorted(names) for wire, names in owners.items() if len(names) > 1}


def compose(mode):
    raw = BASE.read_bytes()
    actual_base = hashlib.sha256(raw).hexdigest()
    if actual_base != EXPECTED_BASE_SHA256:
        raise SystemExit("base checkpoint hash drift: %s" % actual_base)
    design = json.loads(raw)
    top = design["modules"]["top"]
    cells, nets = top["cells"], top["netnames"]
    bit_name = {bit: name for name, net in nets.items() for bit in net.get("bits", [])}
    tree = json.loads(TREE.read_text(encoding="utf-8"))
    swap = json.loads(SWAP.read_text(encoding="utf-8"))["exchange"]
    seeds = tree["independent_gate_routes"]

    baseline_collisions = wire_owners(nets)
    print("base sha256", hashlib.sha256(raw).hexdigest())
    print("baseline cross-net wires", len(baseline_collisions))

    integer_bits = [bit for net in nets.values() for bit in net.get("bits", [])
                    if isinstance(bit, int)]
    next_bit = max(integer_bits) + 1
    read_bit = next_bit
    next_bit += 1

    # Exact predecoder.  Branch from the already-qualified HADDR trunks.
    template = cells["high_request"]
    decoder = copy.deepcopy(template)
    decoder["parameters"]["INIT"] = format(MODES[mode], "016b")
    decoder["parameters"]["FF_USED"] = "0"
    decoder["attributes"]["NEXTPNR_BEL"] = tree["logic"]["bel"]
    decoder["attributes"]["hdlname"] = "read_word0"
    decoder["connections"] = {
        "Q": [], "F": [read_bit],
        "I": [nets["haddr2"]["bits"][0], nets["haddr3"]["bits"][0], "0", "0"],
        "CLK": template["connections"]["CLK"],
    }
    cells["read_word0"] = decoder
    append_edges(nets["haddr2"], [("X14Y12_RMUX22", "X14Y12_IMUX20")])
    append_edges(nets["haddr3"], [("X14Y12_RMUX23", "X14Y12_IMUX21")])
    nets["read_word0"] = {
        "hide_name": 0,
        "bits": [read_bit],
        "attributes": {"ROUTING": routed("X14Y12_OMUX17",
                                            [tuple(edge) for edge in tree["edges"]])},
    }

    lane_records = {}
    for lane in range(16):
        capture = cells[f"capture{lane}"]
        state_bit = capture["connections"]["Q"][0]
        state_name = bit_name[state_bit]
        state_net = nets[state_name]
        original = triples(state_net["attributes"]["ROUTING"])
        feedback = cells[f"feedback_buffer{lane}"]
        match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", feedback["attributes"]["NEXTPNR_BEL"])
        fx, fy, fz = map(int, match.groups())
        feedback_target = f"X{fx}Y{fy}_IMUX{4*fz:02d}"
        sink = next(item[0] for item in original if item[0].startswith("X0Y5_SinkMUXPseudo"))
        root_item, feedback_path = path(original, feedback_target)
        _root_item, sink_path = path(original, sink)
        # Keep the true graph path, irrespective of ROUTING strength tags.
        state_net["attributes"]["ROUTING"] = encode(
            original_items_for_edges(original, root_item, feedback_path))

        seed = seeds[str(lane)]
        input_edges = [tuple(edge) for edge in seed["state"]]
        input_source = input_edges[0][0]
        feedback_bit = feedback["connections"]["F"][0]
        feedback_name = bit_name[feedback_bit]
        state_wires = {wire for edge in feedback_path for wire in edge} | {root_item[0]}
        feedback_items = triples(nets[feedback_name]["attributes"]["ROUTING"])
        feedback_wires = {wire for item in feedback_items for wire in
                          ([item[0]] if item[0] else []) + (item[1].split(".") if item[1] else [])}
        if input_source in state_wires:
            gate_input_bit = state_bit
            append_edges(state_net, input_edges)
            source_kind = "state"
        elif input_source in feedback_wires:
            gate_input_bit = feedback_bit
            append_edges(nets[feedback_name], input_edges)
            source_kind = "feedback"
        else:
            raise SystemExit("lane %d input source is not state/feedback owned" % lane)

        output_prefix = ([tuple(edge) for edge in swap["read_gate_lane0_output_prefix"]]
                         if lane == 0 else [tuple(edge) for edge in seed["output"]])
        join = output_prefix[-1][1]
        join_index = next(index for index, edge in enumerate(sink_path) if edge[1] == join)
        suffix = sink_path[join_index + 1:]

        output_bit = next_bit
        next_bit += 1
        gate = copy.deepcopy(template)
        gate["parameters"]["INIT"] = format(0x8888, "016b")
        gate["parameters"]["FF_USED"] = "0"
        gate["attributes"]["NEXTPNR_BEL"] = tree["gate_bels"][str(lane)]
        gate["attributes"]["hdlname"] = f"read_gate{lane}"
        gate["connections"] = {
            "Q": [], "F": [output_bit],
            "I": [gate_input_bit, read_bit, "0", "0"],
            "CLK": template["connections"]["CLK"],
        }
        cells[f"read_gate{lane}"] = gate
        match = re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", gate["attributes"]["NEXTPNR_BEL"])
        gx, gy, gz = map(int, match.groups())
        omux = f"X{gx}Y{gy}_OMUX{3*gz+2:02d}"
        nets[f"read_gate{lane}"] = {
            "hide_name": 0,
            "bits": [output_bit],
            "attributes": {"ROUTING": routed(omux, output_prefix + suffix)},
        }
        dout_cells = [cell for cell in cells.values()
                      if cell["type"] == "MCU_DOUT" and cell["connections"]["DOUT"] == [state_bit]]
        assert len(dout_cells) == 1
        dout_cells[0]["connections"]["DOUT"] = [output_bit]
        lane_records[lane] = {
            "bel": gate["attributes"]["NEXTPNR_BEL"],
            "input_source": source_kind,
            "input_edges": input_edges,
            "output_edges": output_prefix + suffix,
            "feedback_edges_preserved": feedback_path,
            "sink": sink,
        }

    # Three-route local exchange needed by the lane-0 downstream cut.
    hwdata9_edges = [tuple(edge) for edge in swap["hwdata[9]"]]
    nets["hwdata[9]"]["attributes"]["ROUTING"] = routed(hwdata9_edges[0][0], hwdata9_edges)

    gnd_name = "$PACKER_GND_NET"
    gnd_original = triples(nets[gnd_name]["attributes"]["ROUTING"])
    gnd_sink = next(item[0] for item in gnd_original if item[0].startswith("X0Y5_SinkMUXPseudo"))
    _gnd_root, gnd_path = path(gnd_original, gnd_sink)
    gnd_prefix = [tuple(edge) for edge in swap["$PACKER_GND_NET_prefix"]]
    gnd_join = gnd_prefix[-1][1]
    gnd_join_index = next(index for index, edge in enumerate(gnd_path) if edge[1] == gnd_join)
    gnd_suffix = gnd_path[gnd_join_index + 1:]
    nets[gnd_name]["attributes"]["ROUTING"] = routed(gnd_prefix[0][0], gnd_prefix + gnd_suffix)

    # Structural ownership and endpoint audits before bitgen.
    collisions = wire_owners(nets)
    new_collisions = {wire: names for wire, names in collisions.items()
                      if baseline_collisions.get(wire) != names}
    if new_collisions:
        raise SystemExit("new cross-net wire ownership: %r" % new_collisions)
    for lane, record in lane_records.items():
        if not record["output_edges"] or record["output_edges"][-1][1] != record["sink"]:
            raise SystemExit("lane %d does not reach its original sink" % lane)
    print("new cross-net wires 0; all 16 original MCU_DOUT sinks reached")
    print("HWDATA9 edges", len(hwdata9_edges), "GND edges", len(gnd_prefix + gnd_suffix))

    encoded = (json.dumps(design, indent=2) + "\n").encode("utf-8")
    return encoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=sorted(MODES), default="real")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    encoded = compose(args.mode)
    digest = hashlib.sha256(encoded).hexdigest()
    if args.mode == "real" and digest != EXPECTED_REAL_SHA256:
        raise SystemExit("qualified real-route hash drift: %s" % digest)
    args.out.write_bytes(encoded)
    print("candidate sha256", digest)
    print("mode", args.mode, "wrote", args.out)


if __name__ == "__main__":
    main()
