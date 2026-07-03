# --pre-place: pin the inverter LUT (GENERIC_SLICE, not the GND packer cell) to AGAMEMNON_PIN, so it
# lands where the real MCU-edge routing exists. Cell iter: kv.first=name, kv.second=CellInfo.
import os
BEL = os.environ.get("AGAMEMNON_PIN", "X10Y4_SLICE0")
strength = PlaceStrength.STRENGTH_FIXED
n = 0
for kv in ctx.cells:
    name = str(kv.first); cell = kv.second
    if str(cell.type) == "GENERIC_SLICE" and "PACKER_GND" not in name:
        ctx.bindBel(BEL, cell, strength)
        print("PINNED %s -> %s" % (name, BEL)); n += 1
print("PINPROBE pinned", n)
