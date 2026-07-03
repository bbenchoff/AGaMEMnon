# --pre-place: pin the clk/led GENERIC_IOB cells to the board pads (CLKIN + the IOTILE(0,4) ring-pad
# OUTPUT bels X0Y4_OPAD{z}). The 4 board LEDs are the factory-driven pads IOMUX z in {0,2,3,4}; map
# design led index -> one of those pads. (Old code pinned X1Y4_LEDz, a LogicTile RMUX wire with no RRG
# edge to the pad -> dark on silicon. Now we pin the real IOMUX pad wire so the route conducts.)
# If AGAMEMNON_PIN is set, also pin the (single) GENERIC_SLICE there (debug). kv.first=name, kv.second=cell.
import re, os
LED_PADS = [4, 3, 2, 0]          # led0->OPAD4, led1->OPAD3, led2->OPAD2, led3->OPAD0 (board IOTILE(0,4))
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
        i = int(m.group(1)) if m else 0
        bel = "X0Y4_OPAD%d" % LED_PADS[i % len(LED_PADS)]
    if bel:
        ctx.bindBel(bel, cell, strength)
        print("PINNED %s -> %s" % (name, bel)); n += 1
print("PINPROBE pinned", n)
