# --pre-place for the AHB-slave -> PIN_18 blink: MCU_DIN bus inputs at their col-13/14 entry bels,
# datareg (drives the OPAD) at the proven pad-route source (AGAMEMNON_PIN=X14Y9), wr_ph LOCAL to its
# hwrite/htrans1 entries at (14,12), output IOB at the pad, clk->CLKIN.
import os
strength = PlaceStrength.STRENGTH_FIXED
FF_BEL = os.environ["AGAMEMNON_PIN"]          # datareg -> pad source
OPAD   = os.environ["AGAMEMNON_OPAD"]
MCU_BEL = {"mcu_hwdata0": "X10Y5_MCU_DIN20", "mcu_hwrite": "X10Y5_MCU_DIN21",
           "mcu_htrans1": "X10Y5_MCU_DIN22"}

def ports(cell):
    out = {}
    for pk in cell.ports:
        pi = pk.second; out[str(pk.first)] = str(pi.net.name) if pi.net else None
    return out

out_iob = None; slices = {}
for kv in ctx.cells:
    name = str(kv.first); cell = kv.second; t = str(cell.type)
    if name in MCU_BEL:
        ctx.bindBel(MCU_BEL[name], cell, strength); print("PIN %s -> %s" % (name, MCU_BEL[name]))
    elif t == "GENERIC_SLICE" and "PACKER_GND" not in name:
        slices[name] = cell
    elif t == "GENERIC_IOB":
        if "clk" in name.lower():
            ctx.bindBel("CLKIN", cell, strength); print("PIN clk -> CLKIN")
        else:
            out_iob = cell; ctx.bindBel(OPAD, cell, strength); print("PIN out -> %s" % OPAD)

onet = ports(out_iob).get("I") if out_iob else None
for name, cell in slices.items():
    p = ports(cell); drv = p.get("Q") or p.get("F")
    bel = FF_BEL if (drv is not None and drv == onet) else "X14Y12_SLICE0"
    ctx.bindBel(bel, cell, strength)
    print("PIN slice %s (%s) -> %s" % (name, "datareg" if bel == FF_BEL else "wr_ph", bel))
