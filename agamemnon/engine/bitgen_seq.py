# Fully-open bitgen for a SEQUENTIAL design routed by nextpnr-agrv.
# Input: a nextpnr 'generic' --write JSON. Output: a flashable AGRV2K .bin.
#   LUT INITs  -> physmap.init_bit_pos (byte-exact open LUT editor)
#   data pips  -> sel_byteexact.predict_pair (RMUX/IMUX/OMUX sel encoding)
#   clock      -> clk-0 spine (clk0_spine.json) + CFG_TILECLKMUX[0] on each clocked tile
#   integrity  -> CRC-32/BZIP2 over hdr+raw[:99932], big-endian (validated on silicon)
# Baseline = cpld_native raw (already a clk-0 counter, so the spine is present); we clear its
# design routing and overlay ours. config-acceptance proven by FCB STAT on flash.
import json, struct, sys, re, csv, collections, os
_ENGINE = os.path.dirname(os.path.abspath(__file__)); SRC = SRCA = os.path.join(os.path.dirname(_ENGINE), "chipdb")
sys.path.insert(0, _ENGINE)
import sel_byteexact as SB, physmap, lzw_codec as L
NPG = {"RMUX": 6, "IMUX": 4, "OMUX": 3}; BS = {"RMUX": 10, "IMUX": 12}
if len(sys.argv) < 3:
    sys.exit("usage: bitgen_seq.py <routed.json> <out.bin>")
ROUTED, OUT = sys.argv[1], sys.argv[2]

cell, bymux = SB.load_pips()
lut = SB.train_lut("__none__")

# RMUX<-RMUX closed form (sel_findings.md): hi_n = dir_bank(dx,dy) [sel_map.json table];
# lo_n = geometric LUT keyed (src_idx, dx, dy) WITHOUT dst-node identity (96% predictive). This
# covers the inter/intra-tile mesh edges the dst-keyed held-out LUT misses (combos absent from the
# 25-design corpus) -> pushes general-routing pip coverage toward 100%.
import json as _json, collections as _c
_sm = _json.load(open(SRCA + "/sel_map.json"))
DIR_BANK = {tuple(int(v) for v in k.split(",")): b
            for k, b in _sm["RMUX_from_RMUX_hi_bank_by_dxdy"].items()}
def _build_geom_rmux():
    grp = _c.defaultdict(list)
    for r in csv.DictReader(open(SRCA + "/sel_dataset.csv")):
        grp[(r["build"], r["dst_x"], r["dst_y"], r["cfg_group"])].append(r)
    geom = _c.defaultdict(_c.Counter)
    for k, rs in grp.items():
        e = set((r["dst_idx"], r["src_idx"], r["src_fam"], r["dx"], r["dy"]) for r in rs)
        if len(e) != 1: continue
        r0 = rs[0]; sels = sorted(int(r["sel"]) for r in rs)
        if len(sels) != 2 or r0["dst_fam"] != "RMUX" or r0["src_fam"] != "RMUX": continue
        blk = 10 * int(r0["dst_group_offset"])
        geom[(int(r0["src_idx"]), int(r0["dx"]), int(r0["dy"]))][sels[0] - blk] += 1
    return {k: v.most_common(1)[0][0] for k, v in geom.items()}
# GEOM_RMUX + ABS_LUT are both built from sel_dataset.csv (now ~5M rows -> slow). Built together and
# pickle-cached below (keyed on sel_dataset.csv mtime), after both builder fns are defined.

# ABSOLUTE observed sel table (highest precedence): the EXACT vendor sel-pair for a specific PHYSICAL
# edge (dst tile+node <- src tile+node), harvested from the corpus. This "promotes enumerated->observed":
# where a real vendor design routed this exact edge, we use its byte-exact sel instead of the tile-
# invariant/geometric approximation. Consistency (post-harvest, 54 builds): RMUX 99.8%, IMUX 89.0% by
# absolute key vs 98.3%/83.1% tile-invariant. Sparse (only observed edges) so it AUGMENTS, never
# replaces, the dense tile-invariant LUT + closed-form fallbacks below.
def _build_abs_lut():
    grp = _c.defaultdict(list)
    for r in csv.DictReader(open(SRCA + "/sel_dataset.csv")):
        grp[(r["build"], r["dst_x"], r["dst_y"], r["cfg_group"])].append(r)
    acc = _c.defaultdict(_c.Counter)
    for k, rs in grp.items():
        e = set((r["dst_idx"], r["src_idx"], r["src_fam"], r["dx"], r["dy"]) for r in rs)
        if len(e) != 1: continue
        r0 = rs[0]; fam = r0["dst_fam"]
        if fam not in BS: continue
        sels = sorted(int(r["sel"]) for r in rs)
        if len(sels) != 2: continue
        blk = BS[fam] * int(r0["dst_group_offset"])
        key = (int(r0["dst_x"]), int(r0["dst_y"]), fam, int(r0["dst_idx"]),
               r0["src_fam"], int(r0["src_x"]), int(r0["src_y"]), int(r0["src_idx"]))
        acc[key][(sels[0] - blk, sels[1] - blk)] += 1
    return {k: v.most_common(1)[0][0] for k, v in acc.items()}
# GROUP-CONTEXT table: the EXACT bit pattern of a whole mux group keyed by (tile, cfg_group, the SET
# of edges routed into it). 98.9% deterministic and covers CO-USED groups (53% of all groups) that the
# per-edge ABS_LUT skips (it can't attribute mixed bits to individual edges). Emitted as the primary
# exact source; per-edge ABS_LUT/closed-form is the fallback for group edge-sets not in the corpus.
def _build_group_ctx():
    g = _c.defaultdict(list)
    for r in csv.DictReader(open(SRCA + "/sel_dataset.csv")):
        if r["dst_fam"] not in ("RMUX", "IMUX"): continue
        g[(r["build"], int(r["dst_x"]), int(r["dst_y"]), r["cfg_group"])].append(r)
    acc = _c.defaultdict(_c.Counter)
    for (b, dx, dy, cg), rs in g.items():
        es = frozenset((int(r["dst_idx"]), r["src_fam"], int(r["src_x"]), int(r["src_y"]), int(r["src_idx"])) for r in rs)
        sl = frozenset(int(r["sel"]) for r in rs)
        acc[(dx, dy, cg, es)][sl] += 1
    return {k: v.most_common(1)[0][0] for k, v in acc.items()}

import pickle
_SDS = SRCA + "/sel_dataset.csv"; _CACHE = SRCA + "/_sel_tables2.pkl"
if os.path.exists(_CACHE) and (not os.path.exists(_SDS) or os.path.getmtime(_CACHE) >= os.path.getmtime(_SDS)):
    GEOM_RMUX, ABS_LUT, GROUP_CTX = pickle.load(open(_CACHE, "rb"))
    print("loaded cached sel tables: %d geom, %d abs, %d group-ctx" % (len(GEOM_RMUX), len(ABS_LUT), len(GROUP_CTX)))
else:
    GEOM_RMUX = _build_geom_rmux(); ABS_LUT = _build_abs_lut(); GROUP_CTX = _build_group_ctx()
    pickle.dump((GEOM_RMUX, ABS_LUT, GROUP_CTX), open(_CACHE, "wb"))
    print("built + cached sel tables: %d geom, %d abs, %d group-ctx" % (len(GEOM_RMUX), len(ABS_LUT), len(GROUP_CTX)))

# MCU-edge BBMUXS input-select encoding: a BBMUXS field is a 2-hot {lo, hi} pair (lo in bank 0..3,
# hi in bank 4..7) that depends ONLY on the SOURCE RMUX index (validated INSTANCE-independent: the
# same source RMUX lights the same pair on different BBMUXS instances). Extracted byte-exact from four
# oracle designs: RMUX92->(2,6), RMUX19->(1,6), RMUX25->(0,4), RMUX02->(1,4). NOTE: hi is NOT fixed at
# 6 (that held only for RMUX92/19) nor lo+4 -- it's a genuine per-source pair (RMUX02->(1,4) and
# RMUX25->(0,4) both have hi=4). Cross-validated: RMUX02->BBMUXS04 gives {1,4} in BOTH loop4 (folded,
# +idle top-flag 8) and lutmcu4 (LUT-driven, no flag) -> the top-flag 8 is idle-only, not needed.
# BufMUX/InputMUX/SinkMUXPseudo are 0-config passthrough/pseudo nodes (no CFG cell).
mcue = {}   # (x,y,"BBMUXSn",sel_index) -> (byte,mask)
for r in csv.DictReader(open(SRCA + "/pips_mcuedge.csv")):
    if r["mux"].startswith("BBMUXS"):
        mcue[(int(r["x"]), int(r["y"]), r["mux"], int(r["sel_index"]))] = (int(r["byte"]), int(r["mask"]))
# RMUX src idx -> 2-hot (lo,hi). Harvested byte-exact + instance-independent across the whole oracle
# corpus (harvest_bbmuxs_pairs.py: 10/10 consistent -- same RMUX -> same pair on different BBMUXS
# instances and different designs). This is the COMPLETE exit table for the BBMUXS@(10,5) fan-in.
BBMUXS_PAIR = {2: (1, 4), 9: (1, 5), 19: (1, 6), 25: (0, 4), 32: (0, 5),
               39: (0, 6), 55: (3, 4), 62: (3, 5), 69: (3, 6), 92: (2, 6)}
NOCFG = ("BufMUX", "InputMUX", "SinkMUXPseudo")  # MCU-edge passthrough: no CFG cell, correctly no bits
# MCU-edge din ENTRY: an RMUX_N selecting its UFMTILE InputMUX input lights a 2-hot pair within its
# CFG_RMUX(N//6) block. In the GPIO4 region (10-11,4) that pair is (3,9) -- verified byte-exact for
# RMUX93/19/25/39 (verify_entry_formula.py, 4/4) and silicon-proven. *** BUT this pair is
# REGION-DEPENDENT, not universal *** (findings_ahb.md): the AHB entry region (col 14) uses (2,8), and
# a BufMUX-direct entry uses (0,7). The pair is really a per-edge fan-in POSITION code (like BBMUXS).
# So the (3,9) default below is correct ONLY for the GPIO region; for AHB / other regions, populate the
# MCU_ENTRY override dict with the harvested per-edge pair (do NOT trust the formula there).
BS_RMUX = 10
def mcu_entry_pair(di):                         # RMUX di <- InputMUX -> (cfg_group, [sel_lo, sel_hi])
    block = BS_RMUX * (di % 6)
    return ("CFG_RMUX%d" % (di // 6), [block + 3, block + 9])   # GPIO-region default (3,9)
MCU_ENTRY = {                                   # (dx,dy,rmux_idx) -> [(cfg,sel),...] per-edge overrides
    # AHB bus entry region (col 14): pair (2,8), NOT the GPIO-region (3,9). Extracted byte-exact from
    # oracle_ahb.bin (findings_ahb.md). Block = 10*(N%6); pair (2,8) -> [block+2, block+8].
    (14, 10, 14): [("CFG_RMUX2", 22),  ("CFG_RMUX2", 28)],    # hwdata0 <- InputMUX02
    (14, 12, 73): [("CFG_RMUX12", 12), ("CFG_RMUX12", 18)],   # hwrite  <- InputMUX09
    (14, 12, 21): [("CFG_RMUX3", 32),  ("CFG_RMUX3", 38)],    # htrans1 <- InputMUX02
}

def pw(w):
    m = re.match(r"X(\d+)Y(\d+)_([A-Za-z]+)(\d+)", w);
    return (int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))) if m else None

d = json.load(open(ROUTED)); mod = d["modules"]["top"]

# 1. LUT INITs (SRAM stores complement)
# REGISTER-OUTPUT-SELECT = CFG_OMUX<z> sel=2 : presents the FF-Q (instead of the default LUT-F) on the
# slice's mesh output OMUX[3z+2]. Proven byte-exact vs vendor oracles (AG32-Docs findings_regsel.md):
# the isolated registered LE (regd) sets CFG_OMUX0[2]; the 8-bit counter sets CFG_OMUX<z>[2] for
# EXACTLY the FFs whose Q routes via OMUX[3z+2]. Our arch models FF Q only on OMUX[3z+2], so every
# used registered slice sets its CFG_OMUX<z> sel=2 bit. (The previous CFG_LUTCMUX[2z+1] was WRONG: it
# is the carry/cascade-chain bit -- 0 in the isolated registered regd, but 1 for the counter's z=0
# COMB glue LUT -- not the register-select. The oracle triple regd/combd/cnt disambiguates them.)
# CFG_OMUX pips are already in `cell` (load_pips -> pips_full.csv), keyed (x,y,"CFG_OMUX<z>",sel).
lut_sets = []
reg_sets = []
slices = []
clocked_tiles = set()   # tiles containing a registered FF -> need the clock distributed to them
for cn, c in mod["cells"].items():
    if c.get("type") != "GENERIC_SLICE": continue
    bel = c["attributes"]["NEXTPNR_BEL"]; mm = re.match(r"X(\d+)Y(\d+)_SLICE(\d+)", bel)
    x, y, z = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
    init = int(c["parameters"]["INIT"], 2)
    slices.append((x, y, z))
    if int(c["parameters"].get("FF_USED", "0"), 2):        # registered slice -> present Q on OMUX[3z+2]
        bm = cell.get((x, y, "CFG_OMUX%d" % z, 2))
        if bm: reg_sets.append(bm)
        clocked_tiles.add((x, y))
    for b in range(16):
        byte, mask = physmap.init_bit_pos(x, y, z, b)
        if not ((init >> b) & 1): lut_sets.append((byte, mask))   # complement
print("slices placed:", slices, "; LUT-init bits:", len(lut_sets))

# IO output pads: GENERIC_IOB cells bound to X1Y4_LEDz -> pad-output config via io_emit
# (findings_io_crack.md). z->pad-feed-RMUX R is fixed by arch.py sec 3c; the RMUX->pad hop is
# implicit (io_emit encodes it at the N-1 config tile (0,4)), so it isn't a routed pip.
import io_emit as IOE
PAD_RMUX = {0: 24, 1: 20, 2: 0, 3: 12}
led_outs = []
for cn, c in mod["cells"].items():
    if c.get("type") != "GENERIC_IOB": continue
    m = re.match(r"X1Y4_LED(\d)", c.get("attributes", {}).get("NEXTPNR_BEL", ""))
    if m: led_outs.append((int(m.group(1)), PAD_RMUX[int(m.group(1))]))
io_sets = list(IOE.emit_bits(0, 4, led_outs)) if led_outs else []
if led_outs: print("IO LED pads %s -> %d io-config bits" % (sorted(led_outs), len(io_sets)))

# 2. data routing pips (exclude clock GCLK pips)
pips = set()
for nn, ni in mod.get("netnames", {}).items():
    rt = ni.get("attributes", {}).get("ROUTING", "")
    for tok in rt.split(";"):
        if "." in tok and "GCLK" not in tok: pips.add(tok)
route_sets = []; n_map = n_unmap = 0
general = collections.defaultdict(list)         # (dx,dy,cfg,df) -> [(di,sf,sx,sy,si)] for group-ctx
for p in pips:
    a, b = p.split(".", 1); s = pw(a); t = pw(b)
    if not s or not t: continue
    sx, sy, sf, si = s; dx, dy, df, di = t
    if df == "BBMUXS":                          # MCU-edge crossing mux: set 2-hot input pair (lo,hi)
        pair = BBMUXS_PAIR.get(si) if sf == "RMUX" else None
        if pair is None: n_unmap += 1; continue
        ok = 0
        for sel in pair:
            k = (dx, dy, "BBMUXS%d" % di, sel)
            if k in mcue: route_sets.append(mcue[k]); ok += 1
        n_map += 1 if ok else 0
        if not ok: n_unmap += 1
        continue
    if sf == "InputMUX" and df == "RMUX":       # MCU-edge din ENTRY: RMUX selects its InputMUX input
        ent = MCU_ENTRY.get((dx, dy, di))       # explicit override, else the (3,9)-in-block formula
        if ent is None:
            cfg, sels = mcu_entry_pair(di); ent = [(cfg, s) for s in sels]
        ok = 0
        for (cfg, sel) in ent:
            k = (dx, dy, cfg, sel)
            if k in cell: route_sets.append(cell[k]); ok += 1
        n_map += 1 if ok else 0
        if not ok: n_unmap += 1
        continue
    if df in NOCFG: continue                    # 0-config passthrough (BufMUX/InputMUX/SinkMUXPseudo)
    if df not in BS: n_unmap += 1; continue
    general[(dx, dy, "CFG_%s%d" % (df, di // NPG[df]), df)].append((di, sf, sx, sy, si))

# each RMUX/IMUX mux GROUP: GROUP_CTX exact bit-pattern (whole group) -> else per-edge fallback
n_gc = 0
for (dx, dy, cfg, df), es in general.items():
    gc = GROUP_CTX.get((dx, dy, cfg, frozenset(es)))
    if gc is not None:                          # exact observed pattern for THIS group's edge-set
        for sidx in gc:
            k = (dx, dy, cfg, sidx)
            if k in cell: route_sets.append(cell[k])
        n_map += len(es); n_gc += 1
        continue
    for (di, sf, sx, sy, si) in es:             # fallback: per-edge (observed > closed-form > geom)
        blk = BS[df] * (di % NPG[df])
        pr = ABS_LUT.get((dx, dy, df, di, sf, sx, sy, si))
        if pr is None:
            pr = SB.predict_pair(df, sf, di, si, dx - sx, dy - sy, lut)
        if pr is None and df == "IMUX" and sf == "RMUX" and dx == sx and dy == sy:
            idx27 = (si // 6 + 11) % 27          # IMUX-input crossbar closed form (mixed-radix 2-hot)
            pr = (idx27 % 9, 9 + idx27 // 9)
        if pr is None and df == "RMUX" and sf == "RMUX":     # mesh closed form (hi=dir-bank, lo=src-geom)
            hi = DIR_BANK.get((dx - sx, dy - sy)); lo = GEOM_RMUX.get((si, dx - sx, dy - sy))
            if hi is not None and lo is not None: pr = (lo, hi)
        if pr is None:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  UNMAPPED %s%d <- %s%d  d=(%d,%d)" % (df, di, sf, si, dx - sx, dy - sy))
            continue
        ok = 0
        for ln in pr:
            k = (dx, dy, cfg, blk + ln)
            if k in cell: route_sets.append(cell[k]); ok += 1
        n_map += 1 if ok else 0
print("data pips: %d total, %d mapped (%d groups exact), %d unmapped -> %d bits"
      % (len(pips), n_map, n_gc, n_unmap, len(route_sets)))

# 3. clock: spine (global ring + GCLKDMUX) + CFG_TILECLKMUX[0] on each clocked tile
spine = [tuple(bm) for bm in json.load(open(SRCA + "/clk0_spine.json"))]
clksel0 = json.load(open(SRCA + "/logictile_clksel0.json"))
asyncmux3 = json.load(open(SRCA + "/logictile_asyncmux3.json"))   # CFG_TILEASYNCMUX[3] per tile
# AGAMEMNON_NOSPINE: when the BASELINE already sources+distributes a running fabric clock (e.g. the
# regd/cnt vendor clocked baselines whose preamble configures the PLL->global-clock), the derived
# clk0_spine (harvested from a DIFFERENT design) can mis-set GCLKDMUX/ring bits and kill it. In that
# case keep only the per-tile clock SELECT (clksel0) and inherit source+ring from the baseline.
clk_sets = [] if os.environ.get("AGAMEMNON_NOSPINE") else list(spine)
# Per-clocked-tile distribution (proven uniform vs regd/cnt/cnt24, tiles (10,3)/(10,4)):
#   CFG_TILECLKMUX[0]  (tile clock select, from clksel0)  +  CFG_SEAMMUX[5]  (the SeamMUX00 clock
#   seam that carries the global clock from the ClkdisTILE spine INTO the LogicTile). CFG_SEAMMUX is
#   NOT in pips_clock.csv (it's the routing family) -- that omission is exactly why the clock never
#   reached an open-flow tile before. The shared source+spine (PLL->gclkgen05->ClkdisTILE BufMUX05)
#   is in the preamble (emitted by CLKGEN above). sel 5 = clock seam, uniform across tiles.
CLK_SEAM_SEL = 5
for (x, y) in sorted(clocked_tiles):
    key = "%d,%d" % (x, y)
    if key in clksel0:   clk_sets.append(tuple(clksel0[key]))     # CFG_TILECLKMUX[0] (tile clock select)
    sm = cell.get((x, y, "CFG_SEAMMUX", CLK_SEAM_SEL))            # CFG_SEAMMUX[5] (clock seam from spine)
    if sm and not os.environ.get("AGAMEMNON_NO_SEAM"): clk_sets.append(sm)
    if key in asyncmux3: clk_sets.append(tuple(asyncmux3[key]))   # CFG_TILEASYNCMUX[3] (FF async-reset inactive)
print("clock bits: %d (spine + %d clocked-tile seam/select/async)" % (len(clk_sets), len(clocked_tiles)))

# 4. assemble on a baseline. Default cpld_native (clk-0 spine). AGAMEMNON_BASELINE overrides with an
# MCU-USING baseline (e.g. the vendor loopback loop.bin) so the MCU<->fabric edge is ENABLED —
# cpld_native is fabric-only and never sets up the MCU edge, so MCU-edge routing overlaid on it does
# not electrically propagate (root cause of the din-stuck bug).
_bl = os.environ.get("AGAMEMNON_BASELINE", SRC + "/fabric_default.bin")
base = open(_bl, "rb").read()
hdr = base[:8]
raw = bytearray(base[8:] if len(base) - 8 == 99936 else L.decode(base[8:]))   # uncompressed .bin or LZW
oracle = set(k for k, (by, ms) in cell.items() if by < len(raw) and raw[by] & ms)
abg = collections.defaultdict(set)
for (x, y, mx, se) in oracle: abg[(x, y, mx)].add(se)
sat = set(k for k, s in abg.items() if set(bymux.get(k, {})) and s == set(bymux.get(k, {})))
for (x, y, mx, se), (by, ms) in cell.items():
    if mx.rstrip("0123456789") in ("CFG_RMUX", "CFG_IMUX") and (x, y, mx) not in sat and by < len(raw):
        raw[by] &= (~ms) & 0xFF
# CLEAR each PLACED slice's LUT (16 bits) + OMUX (sel 0/1/2) so the baseline's residual slice config
# can't corrupt the overlaid design. bitgen only OR's the design on; without this, a baseline LUT bit
# the design leaves 0 stays set -> wrong LUT function. This was the real "stuck on a foreign baseline"
# bug (mis-diagnosed as a clock failure): mcu_loop's LUT residue at the target tile corrupted the FF.
for (x, y, z) in slices:
    for b in range(16):
        by, ms = physmap.init_bit_pos(x, y, z, b)
        if by < len(raw): raw[by] &= (~ms) & 0xFF
    for s in range(3):
        bm = cell.get((x, y, "CFG_OMUX%d" % z, s))
        if bm and bm[0] < len(raw): raw[bm[0]] &= (~bm[1]) & 0xFF
for (by, ms) in route_sets + lut_sets + clk_sets + io_sets + reg_sets:
    if by < len(raw): raw[by] |= ms

# OPEN fabric-clock SOURCE: the MCU HSE(8MHz)->PLL(100MHz, /2*25) clock-generation preamble chain
# (PREAMBLE_MAP bytes 83-85 + 124-153). FIXED for this clock spec (byte-identical in the regd/cnt/
# combd vendor oracles), so emit it directly (ASSIGN, not OR -- 83-85 differ from the comb baseline).
# This lets a CLOCKED open design run on ANY baseline (incl. the combinational mcu_loop MCU-edge
# baseline) without borrowing a vendor clocked bitstream. Guarded to clocked designs (reg_sets).
CLKGEN_100MHZ = bytes([0x29,0x40,0x00,0x00,0x20,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0xfe,0xff,0x7f,
    0xbf,0xdf,0xef,0xf7,0xfb,0xfd,0x01,0x00,0x52,0x49,0x00,0x00,0x01,0x06,0xa4])   # bytes 124..153
if reg_sets and not os.environ.get("AGAMEMNON_NO_CLKGEN"):
    raw[83], raw[84], raw[85] = 0x84, 0x20, 0x42
    raw[124:154] = CLKGEN_100MHZ
    # HSE clock INPUT enable: CFG_IOMUX11[9] @ IOTILE(22,4) routes the HSE pin into the fabric clock
    # network. Set by every HSE-clock vendor design (regd/cnt/combd), absent from a non-HSE baseline.
    # Isolated by bisection as THE remaining missing clock bit (byte 71737 bit2). Fixed for this
    # board's HSE spec. With this + CLKGEN + per-tile config + the LUT/OMUX residue clear, a clocked
    # design runs on ANY baseline -> fully-open SYSCLK-100 clock, no vendor clocked baseline needed.
    if 71737 < len(raw): raw[71737] |= 0x04
    print("emitted OPEN 100MHz clock (gen preamble + HSE input CFG_IOMUX11[9]@(22,4))")
print("registered slices (CFG_OMUX<z> sel=2 set): %d" % len(reg_sets))
def crc32_bzip2(dd):
    c = 0xFFFFFFFF
    for b in dd:
        c ^= b << 24
        for _ in range(8): c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (c & 0x80000000) else (c << 1) & 0xFFFFFFFF
    return c ^ 0xFFFFFFFF
raw[99932:99936] = struct.pack(">I", crc32_bzip2(bytes(hdr) + bytes(raw[:99932])))
out = hdr + L.encode(bytes(raw))
open(OUT, "wb").write(out)
print("wrote %s (%d B); re-decodes to %d B raw" % (OUT, len(out), len(L.decode(out[8:]))))
