#!/usr/bin/env python3
"""Compose the exact L48 ID8/scratch16/counter3/W1C1 public map.

The composer preserves the qualified scratch16 routed spine, transplants the
isolated qualified counter island, and adds a bounded read/W1C overlay.  New
routes are selected only from the release-strict uarch graph and may not
consume a wire owned by another net.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = ROOT / "qualification/mcu_ahb_register_bank16_public_scratch4_routed.json"
PUBLIC = ROOT / "qualification/mcu_ahb_register_bank_complete_byte_waited_routed.json"
DEVDB = ROOT / "agamemnon/engine/uarch/agrv2k/devdb_strict"
OUT = HERE / "mcu_ahb_public16_exact_map_routed.json"
BASE_SHA256 = "97f164a72b22ea2f076f889ee771b577f482384469266dc489e0b2f243590610"
PUBLIC_SHA256 = "2eaaff39770df92f42da8e4498437ab415e90a904fb9d5381542452e5548894b"
OUTPUT_SHA256 = "aa7ff307b6d59035928bf79306a3e55a69434e9458672a36ed51a7abe162c5fe"

COUNTER_BELS = {
    "X15Y3_SLICE0", "X15Y3_SLICE2", "X19Y1_SLICE0",
    "X15Y1_SLICE0", "X15Y1_SLICE1", "X15Y1_SLICE2",
    "X15Y1_SLICE3", "X15Y1_SLICE4",
}


def canonical_lf(data):
    """Return platform-independent bytes for a hash-pinned text artifact."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def text_sha256(data):
    """Hash text with the repository's canonical-LF contract."""
    return hashlib.sha256(canonical_lf(data)).hexdigest()


def route_items(route):
    fields = route.split(";") if route else []
    if fields and len(fields) % 3:
        raise ValueError("malformed route")
    return [tuple(fields[i:i + 3]) for i in range(0, len(fields), 3)
            if fields[i]]


def encode_route(items):
    return ";".join(field for item in items for field in item)


def lut_init(fn):
    value = 0
    for index in range(16):
        inputs = tuple((index >> bit) & 1 for bit in range(4))
        value |= int(bool(fn(*inputs))) << index
    return f"{value:016b}"


class Router:
    def __init__(self, top):
        self.top = top
        self.adj = defaultdict(list)
        with (DEVDB / "dev_pips.csv").open(newline="") as fh:
            for row in csv.DictReader(fh):
                self.adj[row["src"]].append((row["dst"], row["name"]))
        self.belpins = {}
        with (DEVDB / "dev_belpins.csv").open(newline="") as fh:
            for row in csv.DictReader(fh):
                self.belpins[(row["bel"], row["pin"])] = row["wire"]
        self.owners = {}
        for name, net in top["netnames"].items():
            for dst, pip, _strength in route_items(
                    net.get("attributes", {}).get("ROUTING", "")):
                self._claim(name, dst)
                if pip:
                    self._claim(name, pip.split(".", 1)[0])

    def _claim(self, name, wire):
        prior = self.owners.get(wire)
        if prior is not None and prior != name:
            raise ValueError(f"wire conflict {wire}: {prior} vs {name}")
        self.owners[wire] = name

    def pin(self, cell, port, index=None):
        bel = self.top["cells"][cell]["attributes"]["NEXTPNR_BEL"]
        suffix = f"[{index}]" if index is not None else ""
        return self.belpins[(bel, port + suffix)]

    def extend(self, name, sinks):
        net = self.top["netnames"][name]
        items = route_items(net.get("attributes", {}).get("ROUTING", ""))
        tree = set()
        for dst, pip, _strength in items:
            tree.add(dst)
            if pip:
                tree.add(pip.split(".", 1)[0])
        if not tree:
            raise ValueError(f"net {name} has no routed root")
        for sink in sinks:
            if sink in tree:
                continue
            parent = {}
            queue = deque(sorted(tree))
            seen = set(tree)
            found = False
            while queue and not found:
                src = queue.popleft()
                for dst, pip in self.adj.get(src, ()):
                    owner = self.owners.get(dst)
                    if owner is not None and owner != name:
                        continue
                    if dst in seen:
                        continue
                    seen.add(dst)
                    parent[dst] = (src, pip)
                    if dst == sink:
                        found = True
                        break
                    queue.append(dst)
            if not found:
                raise ValueError(f"no strict free route for {name} -> {sink}")
            path = []
            node = sink
            while node not in tree:
                src, pip = parent[node]
                path.append((node, pip, "1"))
                node = src
            path.reverse()
            for dst, pip, strength in path:
                items.append((dst, pip, strength))
                self._claim(name, pip.split(".", 1)[0])
                self._claim(name, dst)
                tree.add(pip.split(".", 1)[0])
                tree.add(dst)
        net.setdefault("attributes", {})["ROUTING"] = encode_route(items)

    def extend_exact(self, name, path):
        """Append one reviewed path while revalidating graph and ownership.

        Exact-map composers must not silently pick a different BFS path merely
        because the strict graph gained another legal edge.  The retained path
        remains fail-closed: every hop must still exist in the current graph,
        connect to the existing tree, and be free of cross-net ownership.
        """
        net = self.top["netnames"][name]
        items = route_items(net.get("attributes", {}).get("ROUTING", ""))
        tree = set()
        for dst, pip, _strength in items:
            tree.add(dst)
            if pip:
                tree.add(pip.split(".", 1)[0])
        if not tree:
            raise ValueError(f"net {name} has no routed root")
        for dst, pip, strength in path:
            if strength != "1" or not pip:
                raise ValueError(f"invalid reviewed route item: {(dst, pip, strength)}")
            src = pip.split(".", 1)[0]
            if src not in tree:
                raise ValueError(f"reviewed path for {name} is disconnected at {src}")
            if (dst, pip) not in self.adj.get(src, ()):
                raise ValueError(f"reviewed strict edge disappeared: {pip}")
            for wire in (src, dst):
                owner = self.owners.get(wire)
                if owner is not None and owner != name:
                    raise ValueError(f"wire conflict {wire}: {owner} vs {name}")
            items.append((dst, pip, strength))
            self._claim(name, src)
            self._claim(name, dst)
            tree.update((src, dst))
        net.setdefault("attributes", {})["ROUTING"] = encode_route(items)

    def route_new(self, name, source, sinks):
        self.top["netnames"][name].setdefault("attributes", {})["ROUTING"] = \
            encode_route([(source, "", "1")])
        self._claim(name, source)
        self.extend(name, sinks)


def find_net(top, bit):
    names = [name for name, net in top["netnames"].items()
             if net.get("bits") == [bit]]
    if len(names) != 1:
        raise ValueError(f"expected one named net for bit {bit}, got {names}")
    return names[0]


def add_slice(top, name, bel, init, inputs, output_bit):
    top["cells"][name] = {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": "00000000000000000000000000000000",
            "INIT": init,
            "K": "00000000000000000000000000000100",
        },
        "attributes": {"NEXTPNR_BEL": bel, "BEL_STRENGTH": "1"},
        "port_directions": {
            "CLK": "input", "I": "input", "F": "output", "Q": "output"
        },
        "connections": {"CLK": [], "I": inputs, "F": [output_bit], "Q": []},
    }
    top["netnames"][name] = {
        "hide_name": 0, "bits": [output_bit], "attributes": {}}


def add_ff(top, name, bel, init, inputs, clock_bit, output_bit):
    top["cells"][name] = {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": "00000000000000000000000000000001",
            "INIT": init,
            "K": "00000000000000000000000000000100",
        },
        "attributes": {"NEXTPNR_BEL": bel, "BEL_STRENGTH": "1"},
        "port_directions": {
            "CLK": "input", "I": "input", "F": "output", "Q": "output"
        },
        "connections": {"CLK": [clock_bit], "I": inputs, "F": [],
                        "Q": [output_bit]},
    }
    top["netnames"][name] = {
        "hide_name": 0, "bits": [output_bit], "attributes": {}}


def compose() -> bytes:
    base_raw = BASE.read_bytes()
    if text_sha256(base_raw) != BASE_SHA256:
        raise SystemExit("qualified +4 scratch base hash drifted")
    public_raw = PUBLIC.read_bytes()
    if text_sha256(public_raw) != PUBLIC_SHA256:
        raise SystemExit("qualified public8 donor hash drifted")
    design = json.loads(base_raw)
    top = design["modules"]["top"]
    public = json.loads(public_raw)["modules"]["top"]

    used_bels = {cell["attributes"].get("NEXTPNR_BEL")
                 for cell in top["cells"].values()}
    if used_bels & COUNTER_BELS:
        raise SystemExit("counter BEL collision: %s" % sorted(used_bels & COUNTER_BELS))

    counter_cells = {name for name, cell in public["cells"].items()
                     if cell["attributes"].get("NEXTPNR_BEL") in COUNTER_BELS}
    if len(counter_cells) != 8:
        raise SystemExit("expected eight counter island cells")

    base_hclk = top["cells"]["mcu_bus_clock"]["connections"]["CLK"][0]
    base_reset = top["cells"]["mcu_reset_control"]["connections"]["DIN"][0]
    pub_hclk = public["cells"]["mcu_bus_clock"]["connections"]["CLK"][0]
    pub_reset = public["cells"]["mcu_reset_control"]["connections"]["DIN"][0]
    bit_map = {pub_hclk: base_hclk, pub_reset: base_reset}
    base_max_bit = max(bit for net in top["netnames"].values()
                       for bit in net.get("bits", []) if isinstance(bit, int))
    next_bit = base_max_bit + 1

    endpoint_count = defaultdict(int)
    produced = set()
    for cell_name in counter_cells:
        cell = public["cells"][cell_name]
        for port, bits in cell["connections"].items():
            for bit in bits:
                if isinstance(bit, int):
                    endpoint_count[bit] += 1
                    if cell["port_directions"].get(port) == "output":
                        produced.add(bit)
    for bit in sorted(endpoint_count):
        if bit in bit_map:
            continue
        if bit not in produced and endpoint_count[bit] == 1:
            bit_map[bit] = "0"
        else:
            bit_map[bit] = next_bit
            next_bit += 1

    public_name_for_bit = {}
    for name, net in public["netnames"].items():
        if len(net.get("bits", [])) == 1 and isinstance(net["bits"][0], int):
            public_name_for_bit[net["bits"][0]] = name

    for old_name in sorted(counter_cells):
        cell = json.loads(json.dumps(public["cells"][old_name]))
        new_name = "public_counter__" + old_name.replace("$", "_")
        cell["connections"] = {
            port: [bit_map.get(bit, bit) if isinstance(bit, int) else bit
                   for bit in bits]
            for port, bits in cell["connections"].items()
        }
        top["cells"][new_name] = cell

    for old_bit, new_bit in bit_map.items():
        if old_bit in (pub_hclk, pub_reset) or not isinstance(new_bit, int):
            continue
        old_name = public_name_for_bit.get(old_bit, f"counter_bit_{old_bit}")
        new_name = "public_counter_net__" + old_name.replace("$", "_")
        top["netnames"][new_name] = {
            "hide_name": 0, "bits": [new_bit], "attributes": {}}

    # Add the five read-overlay LUTs.  ``high_active`` distinguishes +8/+c
    # from the low address half, which lets the retained read gates supply the
    # immutable 0x4d ID as their low-class default without a separate ID net.
    haddr2 = top["cells"]["mcu_haddr2"]["connections"]["DIN"][0]
    haddr3 = top["cells"]["mcu_haddr3"]["connections"]["DIN"][0]
    counter_bits = {}
    for bit, old_name in public_name_for_bit.items():
        if old_name.startswith("core_i.counter["):
            counter_bits[int(old_name.split("[")[1].split("]")[0])] = bit_map[bit]
    if set(counter_bits) != {0, 1, 2}:
        raise SystemExit(f"counter bit mapping incomplete: {counter_bits}")

    select_counter, select_status, high_active, high_data0, high_data2 = \
        range(next_bit, next_bit + 5)
    next_bit += 5
    add_slice(top, "public_select_counter", "X14Y12_SLICE6",
              lut_init(lambda a2, a3, _2, _3: a3 and not a2),
              [haddr2, haddr3, "0", "0"], select_counter)
    add_slice(top, "public_select_status", "X14Y12_SLICE4",
              lut_init(lambda a2, a3, _2, _3: a3 and a2),
              [haddr2, haddr3, "0", "0"], select_status)
    add_slice(top, "public_high_active", "X14Y12_SLICE10",
              lut_init(lambda counter, _1, status, _3: counter or status),
              [select_counter, "0", select_status, "0"], high_active)
    add_slice(top, "public_high_data0", "X15Y11_SLICE6",
              lut_init(lambda csel, count, _2, _3: csel and count),
              [select_counter, counter_bits[0], "0", "0"], high_data0)
    add_slice(top, "public_high_data2", "X15Y11_SLICE10",
              lut_init(lambda csel, count, _2, _3: csel and count),
              [select_counter, counter_bits[2], "0", "0"], high_data2)

    # One independent W1C write pipeline.  The scratch address gate remains
    # untouched; +c receives its own accepted-write token and shares only the
    # already-qualified HREADY output LUT.
    hwrite = top["cells"]["mcu_hwrite"]["connections"]["DIN"][0]
    htrans1 = top["cells"]["mcu_htrans1"]["connections"]["DIN"][0]
    hready = top["cells"]["mcu_hreadyout"]["connections"]["DOUT"][0]
    hwdata0 = top["cells"]["mcu_hwdata0"]["connections"]["DIN"][0]
    hwdata1 = top["cells"]["mcu_hwdata1"]["connections"]["DIN"][0]
    low_request = top["cells"]["low_request"]["connections"]["F"][0]
    status_gate, status_pending, clear_event, set_event, status = \
        range(next_bit, next_bit + 5)
    next_bit += 5
    add_slice(top, "public_status_hwrite_gate", "X14Y12_SLICE11",
              lut_init(lambda low, write, a2, a3:
                       low and write and a2 and a3),
              [low_request, hwrite, haddr2, haddr3], status_gate)
    add_ff(top, "public_status_pending", "X14Y9_SLICE1",
           lut_init(lambda trans, gate, ready, reset:
                    (not reset) and trans and gate and ready),
           [htrans1, status_gate, hready, base_reset], base_hclk,
           status_pending)
    add_ff(top, "public_clear_event", "X14Y12_SLICE14",
           lut_init(lambda data, pending, _2, _3: data and pending),
           [hwdata0, status_pending, "0", "0"], base_hclk, clear_event)
    add_ff(top, "public_set_event", "X17Y11_SLICE14",
           lut_init(lambda data, pending, _2, _3: data and pending),
           [hwdata1, status_pending, "0", "0"], base_hclk, set_event)
    add_ff(top, "public_status_storage", "X14Y12_SLICE9",
           lut_init(lambda clear, set_, held, reset:
                    False if reset else (True if set_ else
                                         (False if clear else held))),
           [clear_event, set_event, status, base_reset], base_hclk, status)

    high0 = top["cells"]["public_high_data0"]
    high0["connections"]["I"] = [select_counter, counter_bits[0], "0", status]
    high0["parameters"]["INIT"] = lut_init(
        lambda csel, count, _2, state: count if csel else state)
    wait = top["cells"]["write_wait_stage"]
    wait["connections"]["I"][3] = status_pending
    wait["parameters"]["INIT"] = "1100110011001101"  # 0xCCCD

    read_word4 = top["cells"]["read_word0"]["connections"]["F"][0]
    state_bits = {}
    for index in range(16):
        state_bits[index] = top["cells"][f"capture{index}"]["connections"]["Q"][0]
    data_init = lut_init(lambda state, read4, high, data:
                         data if high else (state if read4 else True))
    counter1_init = lut_init(lambda state, read4, sel, count:
                             (state and read4) or (sel and count))
    id_only_init = lut_init(lambda state, read4, high, _3:
                            (not high) and (state if read4 else True))
    for index, third, init, fourth in (
            (0, high_active, data_init, high_data0),
            (1, select_counter, counter1_init, counter_bits[1]),
            (2, high_active, data_init, high_data2),
            (3, high_active, id_only_init, "0"),
            (6, high_active, id_only_init, "0")):
        cell = top["cells"][f"read_gate{index}"]
        cell["connections"]["I"] = [state_bits[index], read_word4, third, fourth]
        cell["parameters"]["INIT"] = init

    router = Router(top)

    # Route every newly introduced counter net from its unique producer to all
    # consumers.  Shared reset and clock are extended from their existing trees.
    all_cells = top["cells"]
    bit_endpoints = defaultdict(list)
    for cell_name, cell in all_cells.items():
        for port, bits in cell["connections"].items():
            for index, bit in enumerate(bits):
                if isinstance(bit, int):
                    bit_endpoints[bit].append((cell_name, port, index,
                                               cell["port_directions"].get(port)))

    def pin_for(endpoint):
        cell, port, index, _direction = endpoint
        return router.pin(cell, port, index if port == "I" else None)

    hclk_name = find_net(top, base_hclk)
    reset_name = find_net(top, base_reset)
    existing_shared = (base_hclk, base_reset, haddr2, haddr3, hwrite,
                       htrans1, hready, hwdata0, hwdata1, read_word4,
                       low_request, *state_bits.values())
    new_bits = {bit for bit in bit_endpoints if bit > base_max_bit}
    # Include allocated counter bits and support outputs, but not shared base nets.
    new_bits = {bit for bit in new_bits if bit not in (base_hclk, base_reset)}
    # The retained status state has the scarcest readback/self-feedback tail;
    # claim it before the event/pending fanouts and let those adapt around it.
    ordered_new_bits = [status] + sorted(new_bits - {status})
    for bit in ordered_new_bits:
        endpoints = bit_endpoints[bit]
        outputs = [ep for ep in endpoints if ep[3] == "output"]
        inputs = [ep for ep in endpoints if ep[3] == "input"]
        if not outputs or not inputs:
            continue
        if len(outputs) != 1:
            raise SystemExit(f"bit {bit} has {len(outputs)} producers")
        net_name = find_net(top, bit)
        router.route_new(net_name, pin_for(outputs[0]),
                         [pin_for(ep) for ep in inputs])

    # Extend retained hard/shared trees only after the new functional nets have
    # claimed their scarce local tails.  The original tree is immutable; BFS
    # adds branches without rip-up and still rejects every cross-net conflict.
    for shared_bit in dict.fromkeys(existing_shared):
        shared_name = find_net(top, shared_bit)
        sinks = [pin_for(ep) for ep in bit_endpoints[shared_bit]
                 if ep[3] == "input"]
        router.extend(shared_name, sinks)

    # Final ownership and placement audit.
    bels = defaultdict(list)
    for name, cell in top["cells"].items():
        bels[cell["attributes"].get("NEXTPNR_BEL")].append(name)
    duplicates = {bel: names for bel, names in bels.items()
                  if bel and len(names) > 1}
    if duplicates:
        raise SystemExit(f"duplicate BELs: {duplicates}")
    encoded = (json.dumps(design, indent=2) + "\n").encode()
    if text_sha256(encoded) != OUTPUT_SHA256:
        raise SystemExit("public16 candidate hash does not match reviewed artifact")
    return encoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    encoded = compose()
    args.out.write_bytes(encoded)
    top = json.loads(encoded)["modules"]["top"]
    print(f"wrote {args.out}")
    print(f"sha256={text_sha256(encoded)}")
    print(f"cells={len(top['cells'])} routed_nets="
          f"{sum(bool(n.get('attributes', {}).get('ROUTING')) for n in top['netnames'].values())}")


if __name__ == "__main__":
    main()
