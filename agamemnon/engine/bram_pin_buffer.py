#!/usr/bin/env python3
"""Buffer a registered driver of a BRAM pin whose qualified source slot splits F and Q.

Run after pad_isolate and before nextpnr.  The uarch binds every dynamic BRAM
input to a fixed, silicon-qualified source slot (agrv2k.cc ``porta_addr_source``:
AddressA[4] of X13Y4_BRAM is driven from X14Y4_SLICE0).  That slot is one of
the three in the device whose LUT output and register output present on
*different* wires (F on X14Y4_OMUX00, Q on X14Y4_OMUX01, see dev_belpins.csv);
only the F wire reaches the pin in the admitted graph.  A design whose address
bit 4 comes straight from a flip-flop (``addr <= addr + 1``: bram_rom_kat,
bram_fifo_kat, 2026-09-19) therefore has no legal driver slot at all and the
pin packer reports "no gated-graph slice output reaches dynamic BRAM pin
AddressA[4]" on every attempt.  The shipped SERV register file happens to
drive that bit from a LUT.

Insert one identity LUT (INIT = I[0]) between such a register and the pin.  The
register keeps every other consumer; the BRAM sees a combinational driver the
packer can seat at the qualified slot.  Designs whose bit 4 is already a LUT
output are byte-identical.

Usage: python bram_pin_buffer.py <synth.json>
"""
import json
import sys

TOP_MARK = ("1", "00000000000000000000000000000001")
BRAM_TYPES = ("ALTA_BRAM9K",)
# (BRAM port, bit index): pins whose qualified source slot presents F and Q on
# different wires, so a registered driver cannot reach them.
SPLIT_PRESENTATION_PINS = (("AddressA", 4),)


def buffer_registered_drivers(design):
    """Insert the buffers in place; return (buffers_added, pins_examined)."""
    mods = design["modules"]
    topname = next((n for n, m in mods.items()
                    if str(m.get("attributes", {}).get("top", "0")) in TOP_MARK), None)
    if topname is None:
        topname = "top" if "top" in mods else max(mods, key=lambda n: len(mods[n].get("cells", {})))
    cells = mods[topname]["cells"]
    maxbit = max((b for c in cells.values() for bits in c.get("connections", {}).values()
                  for b in bits if isinstance(b, int)), default=0)
    nextbit = maxbit + 1
    drivers = {}
    for name, cell in cells.items():
        directions = cell.get("port_directions", {})
        for port, bits in cell.get("connections", {}).items():
            if directions.get(port) == "output":
                for bit in bits:
                    if isinstance(bit, int):
                        drivers[bit] = name
    added = 0
    examined = 0
    serial = 1
    for name in sorted(cells):
        cell = cells[name]
        if cell.get("type") not in BRAM_TYPES:
            continue
        for port, index in SPLIT_PRESENTATION_PINS:
            bits = cell.get("connections", {}).get(port, [])
            if index >= len(bits) or not isinstance(bits[index], int):
                continue
            examined += 1
            bit = bits[index]
            driver = cells.get(drivers.get(bit), {})
            if driver.get("type") == "LUT":
                continue
            output_bit = nextbit
            nextbit += 1
            buf = "$bram_pin_buf$%d" % serial
            while buf in cells:
                serial += 1
                buf = "$bram_pin_buf$%d" % serial
            serial += 1
            cells[buf] = {
                "hide_name": 1,
                "type": "LUT",
                # INIT bit i = I[0], with JSON binary strings written MSB first.
                "parameters": {"INIT": "1010101010101010",
                               "K": "00000000000000000000000000000100"},
                "attributes": {"agamemnon_bram_pin_buffer": "%s[%d]" % (port, index), "keep": "1"},
                "port_directions": {"I": "input", "Q": "output"},
                "connections": {"I": [bit, "0", "0", "0"], "Q": [output_bit]},
            }
            bits[index] = output_bit
            added += 1
    return added, examined


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        design = json.load(f)
    added, examined = buffer_registered_drivers(design)
    if added:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(design, f)
    print("bram_pin_buffer: %d split-presentation BRAM pin(s), inserted %d identity LUT driver(s)"
          % (examined, added))


if __name__ == "__main__":
    main()
