#!/usr/bin/env python3
"""Render the AGRV2K die floorplan from the open project's own recovered device model.

Reads the two gzipped device tables shipped in the repo:
  agamemnon/engine/status_overlay_dev_belpins.csv.gz  (placeable bels: SLICE/BRAM/MCU/IO/OPAD/AGRV)
  agamemnon/engine/status_overlay_dev_pips.csv.gz      (routing graph -> full tile set)

and writes a self-contained HTML floorplan. No external dependencies; no vendor data.

    python3 docs/floorplan/render_die.py [engine_dir] [out.html]

Findings this visualizes (all cross-checked against the AGRV2K datasheet):
  * 132 logic tiles x 16 slices = 2112 LUT4 (the fabric's entire slice budget)
  * the logic array is L-shaped, not a rectangle (bottom band + tall right column)
  * the full routing grid is ~190 tiles; ~31 are routing-only switch tiles
    (the Y5 MCU boundary spine and the X21 spacer column, which carries routing
     but holds no ordinary slices)
  * the large blank top-left is the hard MCU/SoC block (RISC-V core, flash, SRAM,
    hard peripherals): real silicon, but NOT FPGA fabric, so it holds no tiles.
    It meets the fabric only along the Y5 boundary spine (the MCU/AHB port at X10Y5).
"""
import sys, csv, re, gzip, collections

def load(engine="agamemnon/engine"):
    tb = collections.defaultdict(set)
    with gzip.open(f"{engine}/status_overlay_dev_belpins.csv.gz", "rt") as f:
        r = csv.reader(f); next(r)
        for row in r:
            m = re.match(r'X(\d+)Y(\d+)_([A-Za-z]+)', row[0])
            if m: tb[(int(m.group(1)), int(m.group(2)))].add(m.group(3))
    pip = set()
    with gzip.open(f"{engine}/status_overlay_dev_pips.csv.gz", "rt") as f:
        for line in f:
            for m in re.finditer(r'X(\d+)Y(\d+)', line):
                pip.add((int(m.group(1)), int(m.group(2))))
    return tb, pip

def kind(ts):
    for t, k in (("AGRV","analog"),("MCU","mcu"),("BRAM","bram"),("SLICE","logic"),("IO","io"),("OPAD","opad")):
        if t in ts: return k
    return "other"

def render(tb, pip):
    tile = {xy: (kind(ts), sum(1 for t in ts if t == "SLICE")) for xy, ts in tb.items()}
    XMAX = max(x for x, y in pip | set(tile)); YMAX = max(y for x, y in pip | set(tile))
    routing = pip - set(tile)
    void = {(x, y) for x in range(XMAX+1) for y in range(YMAX+1) if (x,y) not in tile and (x,y) not in pip}
    soc = {(x, y) for (x, y) in void if x <= 12 and y >= 6}
    maxsl, TS, GAP, PAD = 16, 26, 3, 58
    W = PAD*2 + (XMAX+1)*(TS+GAP); H = PAD*2 + (YMAX+1)*(TS+GAP)
    cx = lambda x: PAD + x*(TS+GAP) + TS/2; cy = lambda y: H - PAD - y*(TS+GAP) - TS/2
    COL = {"bram":"#f2b134","mcu":"#7c5cff","io":"#4f7cc4","opad":"#2f4a6e","analog":"#ff6ec7","other":"#ff5a5f"}
    LAB = {"mcu":"M","bram":"B","io":"IO","opad":"O","analog":"A","other":"?"}
    lh = lambda s: tuple(round((18,58,74)[k] + ((72,224,208)[k]-(18,58,74)[k])*(0.22+0.78*s/maxsl)) for k in range(3))
    S = [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" font-family="ui-monospace,Menlo,monospace">',
         f'<rect width="{W}" height="{H}" fill="#0b0e14"/>']
    sx = [x for x, y in soc]; sy = [y for x, y in soc]
    x0, x1 = cx(min(sx))-TS/2-2, cx(max(sx))+TS/2+2; y0, y1 = cy(max(sy))-TS/2-2, cy(min(sy))+TS/2+2
    S.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1-x0:.1f}" height="{y1-y0:.1f}" rx="8" fill="#241a4d" fill-opacity=".55" stroke="#7c5cff" stroke-opacity=".5" stroke-dasharray="5 4"/>')
    mxc = (x0+x1)/2
    S.append(f'<text x="{mxc:.1f}" y="{(y0+y1)/2-14:.1f}" fill="#c9bbff" font-size="17" font-weight="800" text-anchor="middle">MCU + HARD SoC</text>')
    for i, t in enumerate(["RISC-V core · 256KB flash · 128KB SRAM","hard peripherals — not FPGA fabric","surfaces only as its AHB boundary ↓"]):
        S.append(f'<text x="{mxc:.1f}" y="{(y0+y1)/2+8+i*17:.1f}" fill="#8f83c0" font-size="12" text-anchor="middle">{t}</text>')
    for x in range(0, XMAX+1, 2):
        S.append(f'<text x="{cx(x):.1f}" y="{H-PAD+20:.1f}" fill="#4a5766" font-size="10" text-anchor="middle">X{x}</text>')
    for y in range(0, YMAX+1, 2):
        S.append(f'<text x="{PAD-14:.1f}" y="{cy(y)+4:.1f}" fill="#4a5766" font-size="10" text-anchor="end">Y{y}</text>')
    for (x, y) in routing:
        S.append(f'<rect x="{cx(x)-7:.1f}" y="{cy(y)-7:.1f}" width="14" height="14" rx="2" fill="#2b3543" stroke="#3a4757"/>')
    for (x, y), (k, sl) in tile.items():
        fill = f"rgb{lh(sl)}" if k == "logic" else COL[k]
        S.append(f'<rect x="{cx(x)-TS/2:.1f}" y="{cy(y)-TS/2:.1f}" width="{TS}" height="{TS}" rx="3" fill="{fill}" fill-opacity=".92" stroke="{fill}" stroke-opacity=".45"/>')
        if k != "logic":
            S.append(f'<text x="{cx(x):.1f}" y="{cy(y)+3.5:.1f}" fill="#0b0e14" font-size="{9 if len(LAB[k])>1 else 10}" font-weight="800" text-anchor="middle">{LAB[k]}</text>')
    S.append('</svg>')
    cnt = collections.Counter(k for k, _ in tile.values())
    return "\n".join(S), cnt, len(pip | set(tile)), len(routing)

if __name__ == "__main__":
    engine = sys.argv[1] if len(sys.argv) > 1 else "agamemnon/engine"
    out = sys.argv[2] if len(sys.argv) > 2 else "docs/floorplan/agrv2k_die.html"
    tb, pip = load(engine)
    svg, cnt, total, nrout = render(tb, pip)
    open(out, "w", encoding="utf-8").write(
        f"<!doctype html><meta charset=utf-8><title>AGRV2K die</title>"
        f"<body style='background:#0b0e14;margin:0'>{svg}</body>")
    print(f"wrote {out}: {total} routing-grid tiles, {cnt['logic']} logic (=2112 LUT4), "
          f"{cnt.get('bram',0)} BRAM, {nrout} routing-only, kinds={dict(cnt)}")
