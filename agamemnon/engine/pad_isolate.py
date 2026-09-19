#!/usr/bin/env python3
"""Give every output pad a dedicated identity-LUT driver when its net fans out.

Run after qin_pack and before nextpnr.  The qualified physical-output
compositions on this device are a dedicated copy whose one consumer is the pad:
the typed L48 left-output lanes refuse a driver "with unsupported internal
fanout; only one pad sink is qualified", and the board-proven top-edge outputs
were all presented through an identity LUT.  A hobbyist writes

    assign led = count[11];

where `count[11]` also feeds the counter's own logic, and used to be refused at
packing on every placement attempt.  This step inserts, for each GENERIC_IOB
output that is not already driven by a LUT whose only consumer is that pad,
one identity LUT (INIT = I[0]) that drives only the pad: nets with internal
fanout and registers presented straight to a pad (``output reg led``) both get
one.  The register case matters on its own: bitgen's native-endpoint check
counts every input of the pad's driver as an endpoint claim, so an FF clocked
by the hard CLKIN driving a pad directly fails with "GENERIC_IOB ... has
malformed or unqualified fixed input NEXTPNR_BEL 'CLKIN'".  Combinational
semantics are preserved (one LUT delay on the pad path); registered drivers
keep their register.  A pad already driven by a dedicated LUT is left exactly
as it was, so already-qualified designs are byte-identical.

Usage: python pad_isolate.py <synth.json>
"""
import collections
import json
import sys

TOP_MARK = ("1", "00000000000000000000000000000001")


def isolate(design):
    """Insert the buffers in place; return (buffers_added, pads_examined)."""
    mods = design["modules"]
    topname = next((n for n, m in mods.items()
                    if str(m.get("attributes", {}).get("top", "0")) in TOP_MARK), None)
    if topname is None:
        topname = "top" if "top" in mods else max(mods, key=lambda n: len(mods[n].get("cells", {})))
    cells = mods[topname]["cells"]

    maxbit = max((b for c in cells.values() for bits in c.get("connections", {}).values()
                  for b in bits if isinstance(b, int)), default=0)
    nextbit = maxbit + 1
    users = collections.defaultdict(list)
    drivers = {}
    for name, cell in cells.items():
        directions = cell.get("port_directions", {})
        for port, bits in cell.get("connections", {}).items():
            if directions.get(port) == "output":
                for bit in bits:
                    if isinstance(bit, int):
                        drivers[bit] = name
                continue
            for index, bit in enumerate(bits):
                if isinstance(bit, int):
                    users[bit].append((name, port, index))

    added = 0
    examined = 0
    serial = 1
    for name in sorted(cells):
        cell = cells[name]
        if cell.get("type") != "GENERIC_IOB":
            continue
        data = cell.get("connections", {}).get("I", [])
        if len(data) != 1 or not isinstance(data[0], int):
            continue
        examined += 1
        bit = data[0]
        driver = cells.get(drivers.get(bit), {})
        if len(users[bit]) <= 1 and driver.get("type") == "LUT":
            continue
        output_bit = nextbit
        nextbit += 1
        buf = "$pad_buf$%d" % serial
        while buf in cells:
            serial += 1
            buf = "$pad_buf$%d" % serial
        serial += 1
        cells[buf] = {
            "hide_name": 1,
            "type": "LUT",
            # INIT bit i = I[0], with JSON binary strings written MSB first.
            "parameters": {"INIT": "1010101010101010",
                           "K": "00000000000000000000000000000100"},
            "attributes": {"agamemnon_pad_buffer": "1", "keep": "1"},
            "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": [bit, "0", "0", "0"], "Q": [output_bit]},
        }
        cell["connections"]["I"] = [output_bit]
        users[bit] = [u for u in users[bit] if u[0] != name]
        users[output_bit] = [(name, "I", 0)]
        added += 1
    return added, examined


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        design = json.load(f)
    added, examined = isolate(design)
    if added:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(design, f)
    print("pad_isolate: %d output pad(s), inserted %d dedicated identity LUT driver(s)"
          % (examined, added))


if __name__ == "__main__":
    main()
