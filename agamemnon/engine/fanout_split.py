#!/usr/bin/env python3
"""Bound data-net fanout with balanced identity-LUT trees.

Run after qin_pack and before nextpnr.  Duplicating a LUT/DFF driver also
duplicates all of its input loads; iterating that scheme through a CPU's
feedback graph grows exponentially.  A K-ary identity-buffer tree adds only
O(fanout) LUTs and preserves both combinational and registered semantics.
"""
import collections
import json
import sys


def main():
    path = sys.argv[1]
    maxfo = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    if maxfo < 2:
        raise SystemExit("fanout_split: MAXFO must be at least 2")
    with open(path) as f:
        design = json.load(f)

    mods = design["modules"]
    topname = next((n for n, m in mods.items()
                    if str(m.get("attributes", {}).get("top", "0"))
                    in ("1", "00000000000000000000000000000001")), None)
    if topname is None:
        topname = "top" if "top" in mods else max(mods, key=lambda n: len(mods[n].get("cells", {})))
    cells = mods[topname]["cells"]

    maxbit = max((b for c in cells.values() for bits in c["connections"].values()
                  for b in bits if isinstance(b, int)), default=0)
    nextbit = maxbit + 1

    drivers = {}
    users = collections.defaultdict(list)
    for name, cell in cells.items():
        directions = cell.get("port_directions", {})
        for port, bits in cell["connections"].items():
            for index, bit in enumerate(bits):
                if not isinstance(bit, int):
                    continue
                if directions.get(port) == "output":
                    drivers[bit] = (name, port)
                else:
                    users[bit].append((name, port, index))

    targets = []
    for bit, sinks in users.items():
        if len(sinks) <= maxfo or bit not in drivers:
            continue
        driver_type = cells[drivers[bit][0]]["type"]
        if driver_type not in ("LUT", "DFF", "GENERIC_IOB"):
            continue
        # A clock IOB already uses the dedicated global network.  Buffering it
        # through LUTs would turn a clock into ordinary data routing; reset and
        # other high-fanout IOB controls are safe and need the tree.
        if driver_type == "GENERIC_IOB" and any(port in ("CLK", "Clk0", "Clk1")
                                                for _, port, _ in sinks):
            continue
        targets.append(bit)
    # Identify both internal connections before any tree changes the graph.
    # These are local feedback/fusion resources, not ordinary routed fanout.
    protected = set()
    for name, lut in cells.items():
        attrs = lut.get("attributes", {})
        axis = (2 if attrs.get("agamemnon_local_qin_feedback") == "1" else
                3 if attrs.get("agamemnon_direct_d_feedback") == "1" else None)
        inputs = lut.get("connections", {}).get("I", [])
        output = lut.get("connections", {}).get("Q", [])
        if lut["type"] != "LUT" or axis is None or len(inputs) != 4 or len(output) != 1:
            continue
        paired = [(ff_name, ff) for ff_name, ff in cells.items() if ff["type"] == "DFF"
                  and ff.get("connections", {}).get("D") == output]
        if len(paired) != 1 or paired[0][1].get("connections", {}).get("Q") != [inputs[axis]]:
            continue
        protected.add((output[0], paired[0][0], "D", 0))
        protected.add((inputs[axis], name, "I", axis))
    made = 0
    next_name = 1

    def new_buffer(input_bit=None):
        nonlocal made, nextbit, next_name
        made += 1
        output_bit = nextbit
        nextbit += 1
        name = "$fanout_buf$%d" % next_name
        while name in cells:
            next_name += 1
            name = "$fanout_buf$%d" % next_name
        next_name += 1
        cells[name] = {
            "hide_name": 1,
            "type": "LUT",
            # INIT bit i = I[0], with JSON binary strings written MSB first.
            "parameters": {"INIT": "1010101010101010",
                           "K": "00000000000000000000000000000100"},
            "attributes": {"agamemnon_fanout_buffer": "1"},
            "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": [input_bit if input_bit is not None else "0", "0", "0", "0"],
                            "Q": [output_bit]},
        }
        return name, output_bit

    for bit in targets:
        # Keep hard-block terminals on the original driver.  Replacing a BRAM
        # address/control source with a leaf LUT changes its physical source
        # class and invalidates the simultaneously qualified Port-B pin pack.
        # Buffer only the ordinary fabric consumers; the few protected hard
        # terminals do not materially affect the fanout bound.
        sinks = [sink for sink in users[bit]
                 if cells[sink[0]]["type"] not in ("ALTA_BRAM9K", "MCU", "MCU_DIN", "MCU_DOUT")
                 and (bit, *sink) not in protected]
        if len(sinks) <= maxfo:
            continue
        level = []
        # Leaves drive the original consumers.
        for offset in range(0, len(sinks), maxfo):
            name, output_bit = new_buffer()
            for cell_name, port, index in sinks[offset:offset + maxfo]:
                cells[cell_name]["connections"][port][index] = output_bit
            level.append(name)

        # Parents drive groups of child-buffer inputs until the original net
        # has no more than maxfo root loads.
        while len(level) > maxfo:
            parents = []
            for offset in range(0, len(level), maxfo):
                parent, parent_bit = new_buffer()
                for child in level[offset:offset + maxfo]:
                    cells[child]["connections"]["I"][0] = parent_bit
                parents.append(parent)
            level = parents
        for root in level:
            cells[root]["connections"]["I"][0] = bit

    # Refuse to write a structurally corrupt netlist.
    check = collections.defaultdict(list)
    for name, cell in cells.items():
        directions = cell.get("port_directions", {})
        for port, bits in cell["connections"].items():
            if directions.get(port) != "output":
                continue
            for bit in bits:
                if isinstance(bit, int):
                    check[bit].append((name, port))
    multi = {bit: ports for bit, ports in check.items() if len(ports) > 1}
    if multi:
        bit, ports = next(iter(multi.items()))
        raise SystemExit("fanout_split: internal error: bit %d has multiple drivers %r" % (bit, ports))

    if made:
        with open(path, "w") as f:
            json.dump(design, f)
    print("fanout_split: MAXFO=%d, inserted %d identity LUT buffers across %d nets"
          % (maxfo, made, len(targets)))


if __name__ == "__main__":
    main()
