#!/usr/bin/env python3
"""Open BRAM (alta_bram9k) config emitter (Project AGaMEMnon).

Given a BRAM9K instance (tile x,y; port width; clkmode; port enables; 9216-bit INIT_VAL), produce the
exact (byte,mask) config-bit sets using the cracked encoding + the located cell positions in
pips_bram_pll.csv:

  INIT_VAL : word w bit b (LSB-first) -> mux=INIT_VAL, sel = w*18 + b; SET iff mem bit == 1.
  CFG_DWSEL_A/_B[4:0] : PORTx_WIDTH verbatim, bit k -> sel k (thermometer width code).
  CFG_CLKMODE[1:0]    : CLKMODE binary, LSB-first (bit k -> sel k).
  CFG_PORTx_{CLKIN,CLKOUT,RSTIN,RSTOUT}_EN : 1-bit active-high at sel 0.

The encoding is byte-exact vs the vendor (validated in the RE workbench). This module contains only the
emitter used by bitgen; the vendor-oracle validation harness stays in the RE workbench.
"""
import os, csv, collections
HERE = os.path.dirname(os.path.abspath(__file__))
PIPS = os.path.join(HERE, "pips_bram_pll.csv")


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
        if bm:
            out.append(bm)
    for k in range(9216):                       # INIT_VAL: sel = bit index; set iff that bit is 1
        if (init_val >> k) & 1:
            put("INIT_VAL", k)
    for k in range(5):                          # DWSEL_A = PORTA_WIDTH bits (thermometer), bit k -> sel k
        if (width >> k) & 1:
            put("CFG_DWSEL_A", k)
    for k in range(2):                          # CLKMODE binary LSB-first
        if (clkmode >> k) & 1:
            put("CFG_CLKMODE", k)
    for en, v in enables.items():               # port enables: 1-bit at sel 0
        if v:
            put("CFG_%s" % en, 0)
    return set(out)
