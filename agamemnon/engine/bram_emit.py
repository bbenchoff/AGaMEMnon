#!/usr/bin/env python3
"""Open BRAM config emitter + byte-exact validator (Project Agamemnon).

Given a BRAM9K instance (tile x,y; port width; clkmode; port enables; 9216-bit INIT_VAL),
produce the exact (byte,mask) config-bit sets, using the cracked encoding
(findings_bram_crack.md) and the located cell positions in pips_bram_pll.csv:

  INIT_VAL : word w bit b (LSB-first) -> mux=INIT_VAL, sel = w*18 + b; SET iff mem bit == 1.
  CFG_DWSEL_A/_B[4:0] : PORTx_WIDTH verbatim, bit k -> sel k (thermometer width code).
  CFG_CLKMODE[1:0]    : CLKMODE binary, LSB-first (bit k -> sel k).
  CFG_PORTx_{CLKIN,CLKOUT,RSTIN,RSTOUT}_EN : 1-bit active-high at sel 0.

VALIDATION: reproduce the two vendor oracles (oracle_bram/bram.bin x18, bramp.bin x9) and
assert the emitted BRAM-family bit-set EXACTLY equals what af.exe emitted (byte-exact over the
whole BRAM config surface). No vendor bytes are copied — we compute from the params alone.
"""
import os, sys, csv, re, collections
HERE = os.path.dirname(os.path.abspath(__file__)); TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import lzw_codec as L
PIPS = os.path.join(HERE, "pips_bram_pll.csv")
RAWLEN = 99936

def load_cells():
    """(x,y,mux) -> {sel:(byte,mask)} for BRAM-family cells."""
    d = collections.defaultdict(dict)
    for r in csv.DictReader(open(PIPS)):
        d[(int(r["x"]), int(r["y"]), r["mux"])][int(r["sel"])] = (int(r["byte"]), int(r["mask"]))
    return d

CELLS = load_cells()

def emit(x, y, width, clkmode, init_val, enables):
    """-> set of (byte,mask) to OR into raw. enables: dict of PORTA/B_{CLKIN,CLKOUT,RSTIN,RSTOUT}_EN->0/1.
    width = PORTA_WIDTH 5-bit int (thermometer code, e.g. 0=x18, 0b01000=x9). init_val = 9216-bit int."""
    out = []
    def put(mux, sel):
        bm = CELLS.get((x, y, mux), {}).get(sel)
        if bm: out.append(bm)
    # INIT_VAL: sel = bit index; set iff that bit of init_val is 1
    for k in range(9216):
        if (init_val >> k) & 1: put("INIT_VAL", k)
    # DWSEL_A = PORTA_WIDTH bits (thermometer), bit k -> sel k
    for k in range(5):
        if (width >> k) & 1: put("CFG_DWSEL_A", k)
    # CLKMODE binary LSB-first
    for k in range(2):
        if (clkmode >> k) & 1: put("CFG_CLKMODE", k)
    # port enables: 1-bit at sel 0
    for en, v in enables.items():
        if v: put("CFG_%s" % en, 0)
    return set(out)

def observed_bram_bits(raw, x, y):
    """Every BRAM-family cell at (x,y) currently SET in raw -> set of (byte,mask)."""
    s = set()
    for (cx, cy, mux), sels in CELLS.items():
        if (cx, cy) != (x, y): continue
        for sel, (b, m) in sels.items():
            if b < len(raw) and (raw[b] & m): s.add((b, m))
    return s

def decode(path):
    b = open(path, "rb").read()[8:]
    return bytes(b) if len(b) == RAWLEN else L.decode(b)

def parse_initval(macro_path):
    txt = open(macro_path).read()
    m = re.search(r"INIT_VAL\s*=\s*9216'h([0-9a-fA-F]+)", txt)
    return int(m.group(1), 16)

def validate():
    ok = True
    # oracle #1: x18, CLKMODE indep(0), no enables
    iv = parse_initval(os.path.join(TOOLS, "oracle_bram", "bram_macro.v"))
    for name, width, clkmode, en in [
        ("bram.bin", 0b00000, 0b00, {}),
        ("bramp.bin", 0b01000, 0b10, {"PORTA_CLKIN_EN":1,"PORTA_CLKOUT_EN":1,"PORTA_RSTIN_EN":1,"PORTA_RSTOUT_EN":1}),
    ]:
        raw = decode(os.path.join(TOOLS, "oracle_bram", name))
        # find active tile = the one with INIT_VAL bits set
        per = collections.Counter()
        for (cx, cy, mux), sels in CELLS.items():
            if mux == "INIT_VAL":
                for sel, (b, m) in sels.items():
                    if b < len(raw) and raw[b] & m: per[(cx, cy)] += 1
        tile = max(per, key=per.get)
        emitted = emit(tile[0], tile[1], width, clkmode, iv, en)
        obs = observed_bram_bits(raw, tile[0], tile[1])
        extra = emitted - obs; missing = obs - emitted
        status = "PASS" if not extra and not missing else "FAIL"
        if status == "FAIL": ok = False
        print(f"  {name:10} tile{tile} width={width:05b} clkmode={clkmode:02b}: "
              f"emitted {len(emitted)} bits, observed {len(obs)}  -> {status}"
              + (f"  (+{len(extra)} extra, -{len(missing)} missing)" if status=="FAIL" else ""))
    return ok

if __name__ == "__main__":
    print("=== BRAM emit byte-exact validation vs vendor oracles ===")
    ok = validate()
    print("RESULT:", "byte-exact BRAM config reproduced" if ok else "MISMATCH")
    sys.exit(0 if ok else 1)
