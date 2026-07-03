#!/usr/bin/env python3
"""Automate the MCU-edge placement (retires the hand-authored BITCFG).

Given a set of loopback bits (din GPIO pin -> dout GPIO pin), solve a valid, non-colliding
assignment of {LUT slice, din LUT-input pin, exit RMUX} per bit from the routing data alone, then
emit the two artifacts the open flow consumes:
  * pips_mcuedge_routing.csv  (per-bit BufMUX->InputMUX->RMUX entry + RMUX->BBMUXS->SinkMUXPseudo exit)
  * mcu_bitcfg.json           (bit -> {slice, din_pin}) for mcuN_prep.py + pin_mcuN_place.py

Data sources (all validated this project): DIN_ENTRY/DOUT_EXIT harvested chains; BBMUXS_PAIR exit
table (instance-independent, harvest_bbmuxs_pairs.py); rrg_edges_full.csv for OMUX->RMUX (exit
reachability from a slice) and entry-RMUX-> (<=2 hop) ->IMUX (din reachability to a slice input).
Constraints: distinct slice per bit, distinct exit RMUX per bit (each carries a distinct signal);
entry RMUXes {93,17,47,28} are disjoint from the exit pool by construction.

Usage: python mcu_place_solver.py [din:dout,din:dout,...]   (default 1:6,3:4,5:2,7:0)
"""
import os, sys, csv, json, collections
DATA = os.environ.get("AGAMEMNON_DATA", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chipdb"))
HERE = os.path.dirname(os.path.abspath(__file__))

# --- harvested per-GPIO-pin MCU-edge chains (from vendor route.tx: loopback/lutmcu4/lut57/oracle_cnt) ---
# din pin -> (bufmux, bmx_x,bmx_y, inputmux, imx_x,imx_y, entry_rmux, rmx_x,rmx_y)
DIN_ENTRY = {
    1: ("BufMUX10", 11, 5, "InputMUX11", 11, 5, 93, 11, 4),
    3: ("BufMUX00", 10, 5, "InputMUX00", 10, 5, 17, 10, 4),
    5: ("BufMUX02", 10, 5, "InputMUX03", 10, 5, 47, 10, 4),
    7: ("BufMUX04", 10, 5, "InputMUX05", 10, 5, 28, 10, 4),
}
# dout pin N -> BBMUXS0N @(10,5) -> SinkMUXPseudo(141+N) @(0,5)   (fixed GPIO<->edge map, oracle_cnt)
def dout_exit(n): return ("BBMUXS%02d" % n, 141 + n)
BBMUXS_PAIR = {2, 9, 19, 25, 32, 39, 55, 62, 69, 92}   # RMUXes with a known exit pair (encodable)
MTX, MTY = 10, 4                                        # the MCU-edge LogicTile

def load_edges():
    """adjacency within/into (10,4): src_res -> [dst_res] for a couple of hop classes."""
    fwd = collections.defaultdict(set)      # (sx,sy,sres) -> {(dx,dy,dres)}
    for r in csv.DictReader(open(os.path.join(DATA, "rrg_edges_full.csv"))):
        s = (int(r["src_x"]), int(r["src_y"]), r["src_res"])
        d = (int(r["dst_x"]), int(r["dst_y"]), r["dst_res"])
        fwd[s].add(d)
    return fwd

def load_bbmuxs_fanin():
    fan = collections.defaultdict(set)      # bbmuxs_inst(int) -> {rmux_idx}
    for r in csv.DictReader(open(os.path.join(DATA, "routetx_observed_union.csv"))):
        if r["dst_res"].startswith("BBMUXS") and int(r["dst_x"]) == MTX and int(r["dst_y"]) == 5 \
           and r["src_res"].startswith("RMUX"):
            fan[int(r["dst_res"][6:])].add(int(r["src_res"][4:]))
    return fan

def imux_slice(idx): return idx // 4, idx % 4           # IMUX idx -> (slice_z, input_pin)

def entry_reach(fwd, entry_rmux, ex, ey):
    """(slice_z -> set(input_pin)) reachable from the entry RMUX into (10,4) IMUX in <=2 hops."""
    reach = collections.defaultdict(set)
    src = (ex, ey, "RMUX%d" % entry_rmux)
    frontier = {src}
    seen = set(frontier)
    for _hop in range(2):
        nxt = set()
        for node in frontier:
            for d in fwd.get(node, ()):
                dx, dy, dres = d
                if dx == MTX and dy == MTY and dres.startswith("IMUX"):
                    z, pin = imux_slice(int(dres[4:]))
                    reach[z].add(pin)
                if d not in seen and dres.startswith("RMUX") and dx == MTX and dy == MTY:
                    seen.add(d); nxt.add(d)
        frontier = nxt
    return reach

def exit_rmux_from_slice(fwd, z):
    """RMUXes @(10,4) reachable from this slice's routed output OMUX[3z+2] (1 hop), in the pair table."""
    src = (MTX, MTY, "OMUX%02d" % (3 * z + 2))
    return {int(dres[4:]) for (dx, dy, dres) in fwd.get(src, ())
            if dx == MTX and dy == MTY and dres.startswith("RMUX") and int(dres[4:]) in BBMUXS_PAIR}

def solve(bits):
    fwd = load_edges(); fan = load_bbmuxs_fanin()
    ereach = {p: entry_reach(fwd, DIN_ENTRY[p][6], DIN_ENTRY[p][7], DIN_ENTRY[p][8]) for (p, _) in bits}
    xreach = {z: exit_rmux_from_slice(fwd, z) for z in range(16)}
    # candidate (slice, din_pin, exit_rmux) per bit
    cands = []
    for (dpin, qpin) in bits:
        bbf = fan.get(qpin, set())              # RMUXes physically feeding this dout's BBMUXS
        c = []
        for z in range(16):
            din_pins = ereach[dpin].get(z, set())
            if not din_pins: continue
            for xr in sorted(xreach[z] & bbf):
                c.append((z, min(din_pins), xr))
        cands.append(c)
    # backtrack: distinct slice + distinct exit RMUX
    N = len(bits); assign = [None] * N
    used_z, used_x = set(), set()
    def bt(i):
        if i == N: return True
        for (z, dp, xr) in cands[i]:
            if z in used_z or xr in used_x: continue
            assign[i] = (z, dp, xr); used_z.add(z); used_x.add(xr)
            if bt(i + 1): return True
            used_z.discard(z); used_x.discard(xr); assign[i] = None
        return False
    if not bt(0):
        print("SOLVER: no valid assignment for", bits); return None
    return assign

def emit(bits, assign):
    # mcu_bitcfg.json (slice + din input pin) + INIT per pin
    INV = {0: "0101010101010101", 1: "0011001100110011", 2: "0000111100001111", 3: "0000000011111111"}
    cfg = {}
    for i, ((dpin, qpin), (z, dp, xr)) in enumerate(zip(bits, assign)):
        cfg[str(i)] = {"slice": z, "din_pin": dp, "init": INV[dp],
                       "din_gpio": dpin, "dout_gpio": qpin, "entry_rmux": DIN_ENTRY[dpin][6], "exit_rmux": xr}
    json.dump(cfg, open(os.path.join(HERE, "mcu_bitcfg.json"), "w"), indent=1)
    # pips_mcuedge_routing.csv
    rows = [["src_tile","src_x","src_y","src_res","dst_tile","dst_x","dst_y","dst_res","cfg","source","tier","bit"]]
    for i, ((dpin, qpin), (z, dp, xr)) in enumerate(zip(bits, assign)):
        bmx, bx, by, imx, ix, iy, er, erx, ery = DIN_ENTRY[dpin]
        bb, sink = dout_exit(qpin)
        rows += [
            ["UFMTILE",0,5,"alta_rv3200","UFMTILE",bx,by,bmx,"MCU_DIN_ENTRY","solver","mcuedge",i],
            ["UFMTILE",bx,by,bmx,"UFMTILE",ix,iy,imx,"MCU_DIN_BUF2IN","solver","mcuedge",i],
            ["UFMTILE",ix,iy,imx,"LogicTILE",erx,ery,"RMUX%02d"%er,"MCU_DIN_IN2RMUX","solver","mcuedge",i],
            ["LogicTILE",MTX,MTY,"RMUX%02d"%xr,"UFMTILE",MTX,5,bb,"MCU_DOUT_RMUX2BB","solver","mcuedge",i],
            ["UFMTILE",MTX,5,bb,"UFMTILE",0,5,"SinkMUXPseudo%d"%sink,"MCU_DOUT_BB2SINK","solver","mcuedge",i],
            ["UFMTILE",0,5,"SinkMUXPseudo%d"%sink,"UFMTILE",0,5,"alta_rv3200","MCU_DOUT_SINK2MCU","solver","mcuedge",i],
        ]
    with open(os.path.join(DATA, "pips_mcuedge_routing.csv"), "w", newline="") as f:
        csv.writer(f).writerows(rows)
    print("SOLVER: %d bits assigned:" % len(bits))
    for i, ((dpin, qpin), (z, dp, xr)) in enumerate(zip(bits, assign)):
        print("  bit%d  din GPIO4_%d (RMUX%d) -> slice%d I[%d] -> OMUX%d->RMUX%d->BBMUXS%02d -> dout GPIO4_%d"
              % (i, dpin, DIN_ENTRY[dpin][6], z, dp, 3*z+2, xr, qpin, qpin))
    print("wrote mcu_bitcfg.json + pips_mcuedge_routing.csv")

if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "1:6,3:4,5:2,7:0"
    bits = [tuple(int(x) for x in p.split(":")) for p in spec.split(",")]
    a = solve(bits)
    if a: emit(bits, a)
    else: sys.exit(1)
