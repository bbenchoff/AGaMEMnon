# JSON pre-pass (generalizes mcu2_prep) for the N-bit MCU loopback: put each inverter LUT's din on the
# input pin whose LogicTILE(10,4) IMUX its entry RMUX reaches, at that bit's assigned slice. Data-driven
# from BITCFG (bit -> (slice_z, din_input_pin)); see mcu_loop4b.v for the per-bit path rationale.
# Usage: python mcuN_prep.py <design.json>
import json, sys, re, os
# BITCFG now comes from the solver (mcu_place_solver.py -> mcu_bitcfg.json): bit -> {slice, din_pin, init}
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "mcu_bitcfg.json")))
jf = sys.argv[1]; d = json.load(open(jf)); c = d["modules"]["top"]["cells"]
mcu = {n: v for n, v in c.items() if v["type"] == "MCU"}
dout_net = {v["connections"]["DOUT"][0]: n for n, v in mcu.items()}
def bit_of(m): return int(re.search(r"(\d+)$", m).group(1))
for n, v in c.items():
    if v["type"] != "LUT": continue
    q = v["connections"]["Q"][0]; bit = bit_of(dout_net[q]); bc = CFG[str(bit)]
    din = v["connections"]["I"][0]; pin = bc["din_pin"]
    I = ["0", "0", "0", "0"]; I[pin] = din
    v["connections"]["I"] = I; v["parameters"]["INIT"] = bc["init"]
    print("bit%d LUT %s: din(net %s) -> I[%d] INIT=%s" % (bit, n, din, pin, bc["init"]))
json.dump(d, open(jf, "w"))
