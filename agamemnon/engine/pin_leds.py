# --pre-place: pin the clk/led GENERIC_IOB cells to the KITT-demo bels (CLKIN, X1Y4_LEDz).
# Also, if AGAMEMNON_PIN is set, pin the (single) GENERIC_SLICE there (debug: put a FF right at the
# MCU-edge exit to isolate route vs clock). Cell iter: kv.first=name, kv.second=CellInfo.
import re, os
strength = PlaceStrength.STRENGTH_FIXED
_slice_pin = os.environ.get("AGAMEMNON_PIN")
n = 0
for kv in ctx.cells:
    name = str(kv.first); cell = kv.second
    if str(cell.type) == "GENERIC_SLICE" and _slice_pin and "PACKER_GND" not in name:
        ctx.bindBel(_slice_pin, cell, strength); print("PINNED %s -> %s" % (name, _slice_pin)); n += 1
        continue
    if str(cell.type) != "GENERIC_IOB":
        continue
    bel = None
    if "clk" in name:
        bel = "CLKIN"
    elif "led" in name:
        m = re.search(r"led_(\d+)", name) or re.search(r"led\[(\d+)\]", name)
        bel = "X1Y4_LED%d" % (int(m.group(1)) if m else 0)
    if bel:
        ctx.bindBel(bel, cell, strength)
        print("PINNED %s -> %s" % (name, bel)); n += 1
print("PINPROBE pinned", n)
