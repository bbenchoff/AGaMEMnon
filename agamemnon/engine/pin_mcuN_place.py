# --pre-place (generalizes pin_mcu2_place) for the N-bit MCU loopback: bind each MCU cell to its bel
# (X10Y5_MCU<bit>) and each inverter slice to its assigned LogicTILE(10,4) slice, matched via the
# LUT-output -> MCU.DOUT net. Data-driven from BITCFG (bit -> slice_z). Uses ctx.bindBel (proven).
import re, json
# bit -> slice_z from the solver (mcu_place_solver.py -> mcu_bitcfg.json); nextpnr runs in the pnr dir
BITCFG = {int(k): v["slice"] for k, v in json.load(open("mcu_bitcfg.json")).items()}
strength = PlaceStrength.STRENGTH_FIXED

def ports(cell):
    out = {}
    for pk in cell.ports:
        pi = pk.second; out[str(pk.first)] = str(pi.net.name) if pi.net else None
    return out
def bit_of(m): return int(re.search(r"(\d+)$", m).group(1))

mcus = {}; slices = {}
for kv in ctx.cells:
    name = str(kv.first); cell = kv.second; t = str(cell.type)
    if t == "MCU": mcus[name] = cell
    elif t == "GENERIC_SLICE" and "PACKER_GND" not in name: slices[name] = cell

dout2bit = {}
for n, c in mcus.items():
    dn = ports(c).get("DOUT")
    if dn: dout2bit[dn] = bit_of(n)

for n, c in mcus.items():
    bit = bit_of(n)
    ctx.bindBel("X10Y5_MCU%d" % bit, c, strength)
    print("PIN mcu %s -> X10Y5_MCU%d" % (n, bit))
for n, c in slices.items():
    p = ports(c); outnet = p.get("F") or p.get("Q"); bit = dout2bit.get(outnet)
    if bit is None:
        print("WARN slice %s out-net %s matches no MCU.DOUT; skipping" % (n, outnet)); continue
    ctx.bindBel("X10Y4_SLICE%d" % BITCFG[bit], c, strength)
    print("PIN slice %s (bit%d) -> X10Y4_SLICE%d" % (n, bit, BITCFG[bit]))
