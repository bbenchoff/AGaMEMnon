#!/usr/bin/env python3
"""Project Agamemnon — Step 4: the LUT-init physical map as a closed-form 3D formula, plus a
scale validation against a real design's bitstream.

Derived + validated (coord_map.csv x=20 column; coord_map_x.csv x=14..20):
  zblock(z) = z if z<8 else z+1
  init0_byte(x,y,z) = (779736 - y*63104 - x*36 + zblock(z)*3712) // 8
    - y-stride 63104 bits (7888 B), z-stride 3712 bits (464 B), x-stride 36 bits (cols share
      word-lines), gap of one z-block at z=8.
  init bit b of a LUT lands at byte init0_byte + (b//4)*116, bitmask PERM[b//4 % 2][b%4]:
      PERM_EVEN=[0x40,0x08,0x20,0x10], PERM_ODD=[0x20,0x10,0x40,0x08]
  value = bit b of the cell's (packing-transformed) routed mask.

This file (a) re-checks the formula on the swept CSVs, and (b) predicts every LUT-init bit of
cpld_native/blinky from blinky_routed.v and verifies it against the decoded .bin — a full-design
scale test of the map, and a coverage measurement (how much of the config is LUT-init vs the
still-unmapped routing/mux/IO)."""
import os, re, csv, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lzw_codec as L

HERE = os.path.dirname(os.path.abspath(__file__))
def zblock(z): return z if z < 8 else z + 1
def init0_byte(x, y, z):
    # x-stride formula fit on x>=14 (right of the BRAM column at x=13). Columns LEFT of the BRAM
    # column (x<=12) are shifted +18 bytes (verified byte-exact vs the oracle: slice0@(10,4) AND
    # LUT lands at 65888, not the formula's 65870). Without this, LUT-init edits for x<13 hit the
    # wrong bytes and the LUT is never configured (dout stuck).
    b = (779736 - y*63104 - x*36 + zblock(z)*3712) // 8
    return b + 18 if x < 13 else b
PERM = ([0x40, 0x08, 0x20, 0x10], [0x20, 0x10, 0x40, 0x08])
def init_bit_pos(x, y, z, b):
    g = b // 4
    return init0_byte(x, y, z) + g*116, PERM[g % 2][b % 4]

def check_csv(path, byte_col):
    ok = bad = 0
    for r in csv.DictReader(open(path)):
        if not r["x"].isdigit() or int(r[byte_col]) < 0: continue
        x,y,z,b = int(r["x"]),int(r["y"]),int(r["z"]),int(r[byte_col])
        pred = init0_byte(x,y,z)
        if pred == b: ok += 1
        else: bad += 1; print(f"   MISS ({x},{y},{z}) pred {pred} != {b}")
    print(f"  {os.path.basename(path)}: {ok}/{ok+bad} init0 bytes match formula")
    return bad == 0

def parse_slices(routed):
    txt = open(routed).read()
    cells = {}
    for c,v in re.findall(r"defparam (\S+?)\.coord_x = (\d+);", txt): cells.setdefault(c,{})["x"]=int(v)
    for c,v in re.findall(r"defparam (\S+?)\.coord_y = (\d+);", txt): cells.setdefault(c,{})["y"]=int(v)
    for c,v in re.findall(r"defparam (\S+?)\.coord_z = (\d+);", txt): cells.setdefault(c,{})["z"]=int(v)
    for c,v in re.findall(r"defparam (\S+?)\.mask = 16'h([0-9a-fA-F]+);", txt): cells.setdefault(c,{})["mask"]=int(v,16)
    return {c:d for c,d in cells.items() if {"x","y","z","mask"} <= set(d)}

def main():
    print("=== (a) formula re-check on swept data ===")
    check_csv(os.path.join(HERE,"coord_map.csv"), "init0_byte")
    check_csv(os.path.join(HERE,"coord_map_x.csv"), "init0_byte")

    print("\n=== (b) full-design scale test: predict blinky LUT-init from routed.v ===")
    routed = os.path.join(HERE,"cpld_native","blinky_routed.v")
    binf   = os.path.join(HERE,"cpld_native","blinky.bin")
    if not (os.path.exists(routed) and os.path.exists(binf)):
        print("  cpld_native/blinky_routed.v or blinky.bin missing"); return
    raw = L.decode(open(binf,"rb").read()[8:])
    slices = parse_slices(routed)
    nbits = m_direct = m_inv = 0
    for c,d in slices.items():
        x,y,z,m = d["x"],d["y"],d["z"],d["mask"]
        if not (0 <= init0_byte(x,y,z) < len(raw)-348): continue
        for b in range(16):
            byte,mask = init_bit_pos(x,y,z,b)
            if byte >= len(raw): continue
            bit = (m >> b) & 1
            got = 1 if (raw[byte] & mask) else 0
            nbits += 1
            if bit == got: m_direct += 1
            if (1-bit) == got: m_inv += 1
    print(f"  LEs: {len(slices)}; LUT-init bits predicted: {nbits}")
    print(f"  value match  DIRECT (config = mask bit):     {m_direct}/{nbits} ({100*m_direct//max(nbits,1)}%)")
    print(f"  value match  INVERTED (config = ~mask bit):  {m_inv}/{nbits} ({100*m_inv//max(nbits,1)}%)")

    # --- coverage: how much of the design's config footprint is LUT-init vs still-unmapped? ---
    from collections import Counter
    modal = Counter(raw).most_common(1)[0][0]            # the "blank" fill byte
    footprint = [i for i in range(len(raw)) if raw[i] != modal]
    lut_bytes = set()
    for c,d in slices.items():
        x,y,z = d["x"],d["y"],d["z"]
        if 0 <= init0_byte(x,y,z) < len(raw)-348:
            for g in range(4): lut_bytes.add(init0_byte(x,y,z)+g*116)
    lut_in_fp = sum(1 for i in footprint if i in lut_bytes)
    print(f"\n  config footprint: {len(footprint)} non-default bytes (modal byte 0x{modal:02x})")
    print(f"  bytes touched by LUT-init: {len(lut_bytes)}; of those in footprint: {lut_in_fp}")
    print(f"  => ~{len(footprint)-lut_in_fp} non-default bytes are NOT LUT-init "
          f"(routing/mux/IO/clock — the still-unmapped config)")

if __name__ == "__main__":
    main()
