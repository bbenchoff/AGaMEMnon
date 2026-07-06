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
import mesh_template as MT   # decoded vendor tile-template sel resolver (2026-07-04 breakthrough)
# AGAMEMNON_MESH_TEMPLATE=1 uses the decoded template's fan-in sel resolver (RMUX 92% / IMUX 84%
# byte-exact, sound legal-fan-in) between the observed ABS_LUT (top priority) and the old corpus
# heuristics (fallback). Default OFF = zero change to existing proven builds.
MESH_TMPL = bool(os.environ.get("AGAMEMNON_MESH_TEMPLATE"))
NPG = {"RMUX": 6, "IMUX": 4, "OMUX": 3}; BS = {"RMUX": 10, "IMUX": 12}
if len(sys.argv) < 3:
    sys.exit("usage: bitgen_seq.py <routed.json> <out.bin>")
ROUTED, OUT = sys.argv[1], sys.argv[2]

cell, bymux = SB.load_pips()
lut = SB.train_lut("__none__")

# LE-internal slice config (the C-input Qin/Cin mux + carry) -- these bits are NOT in pips_full.csv;
# they come from chipdb/slice_cfg.csv (gen_slice_cfg.py, from the vendor physical map). Needed for the
# Qin self-feedback model: CFG_LUTCMUX[2z]=1 selects pinC<-Qin (byte-exact, extracted from the vendor
# accumulator bin). See COUNTER_FREEZE_HANDOFF.md ⚠️ CORRECTION.
SLICE_CFG = {}   # (x,y,feature) -> (byte,mask)
_scf = os.path.join(SRC, "slice_cfg.csv")
if os.path.exists(_scf):
    for r in csv.DictReader(open(_scf)):
        SLICE_CFG[(int(r["x"]), int(r["y"]), r["feature"])] = (int(r["byte"]), int(r["mask"]))
    print("loaded %d LE-internal slice-config bits (slice_cfg.csv)" % len(SLICE_CFG))

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
mcue = {}   # (x,y,"BBMUXSn"|"BBMUXEn",sel_index) -> (byte,mask)
for r in csv.DictReader(open(SRCA + "/pips_mcuedge.csv")):
    if r["mux"].startswith(("BBMUXS", "BBMUXE")):
        mcue[(int(r["x"]), int(r["y"]), r["mux"], int(r["sel_index"]))] = (int(r["byte"]), int(r["mask"]))
# RMUX src idx -> 2-hot (lo,hi). Harvested byte-exact + instance-independent across the whole oracle
# corpus (harvest_bbmuxs_pairs.py: 10/10 consistent -- same RMUX -> same pair on different BBMUXS
# instances and different designs). This is the COMPLETE exit table for the BBMUXS@(10,5) fan-in.
BBMUXS_PAIR = {2: (1, 4), 9: (1, 5), 19: (1, 6), 25: (0, 4), 32: (0, 5),
               39: (0, 6), 55: (3, 4), 62: (3, 5), 69: (3, 6), 92: (2, 6)}
# MCU-edge EAST crossing (BBMUXE) exit = same 2-hot {lo,hi} scheme; source-RMUX -> pair, extracted
# byte-exact from the hrdata vendor recon (tools/oracle_ahbr/ahbr.bin, route.tx): the mem_ahb READ
# path (fabric -> MCU hrdata) at UFMTILE col-13. hrdata[0..3] <- BBMUXE02/03/04/05@(13,12) <-
# RMUX93/26/20/49@(14,12). idle BBMUXE sit at sel {8} (not emitted). See [[ag32-ahb-read-scoping]].
BBMUXE_PAIR = {93: (3, 6), 26: (1, 4), 20: (2, 6), 49: (0, 4)}
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

# TOP-ROW pad-feed (vertical LogicTile->IOTile hop into a top-row pad-feed RMUX): byte-exact vendor
# codeword per dst pad-feed RMUX (chipdb/padfeed_L48_top.csv, decoded from the vendor pintest2 build).
# The generic RMUX sel predictor assumes the LogicTile group layout (6 groups x 10-sel blocks), which
# is WRONG for an IOTILE pad-feed group (4 groups x 48 sels, two nodes/group) -> it emitted
# non-conducting bits and pads stayed dark. Here we emit the vendor's EXACT CFG_RMUX bits (usually a
# ZERO codeword = the default select for a directly-below dy=1 source) and SUPPRESS the generic
# predictor for these edges. Keyed by (dst_padtile_x, dst_pad-feed_RMUX_index). Guarded: only fires
# for a routed pip whose dst is a top IOTILE (y=13) RMUX -> zero effect on interior/normal routing.
PADFEED_TOP = {}   # (padtile_x, padfeed_rmux) -> [(byte,mask),...]  (empty list = zero codeword)
_pf = SRCA + "/padfeed_L48_top.csv"
if os.path.exists(_pf):
    for r in csv.DictReader(open(_pf)):
        bs = [int(v) for v in r["codeword_bytes"].split(",") if v != ""]
        ms = [int(v) for v in r["codeword_masks"].split(",") if v != ""]
        PADFEED_TOP[(int(r["padtile_x"]), int(r["padfeed_rmux"]))] = list(zip(bs, ms))
    print("loaded %d top-row pad-feed codewords (padfeed_L48_top.csv)" % len(PADFEED_TOP))

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
        # VENDOR-OUT slice (AGAMEMNON_VENDOR_OUT_SLICE="x,y,z"): the vendor-faithful output FF routes
        # F (LUT out) on OMUX[3z+0] and Q (feedback) on OMUX[3z+1] instead of the default OMUX[3z+2],
        # so it enters the silicon-conducting pad chain (OMUX42->RMUX74->RMUX09->pad) and feeds back
        # via the intra-tile crossbar (OMUX43->IMUX). CFG_OMUX<z> sel=b enables OMUX[3z+b] (proven by
        # the vendor pintest2 bits: slice14@(14,12) sets CFG_OMUX14 {0,1}). Emit sels {0,1} for it.
        _vout = os.environ.get("AGAMEMNON_VENDOR_OUT_SLICE")
        _vout = tuple(int(v) for v in _vout.split(",")) if _vout else None
        _sels = (0, 1) if _vout == (x, y, z) else (2,)
        for _s in _sels:
            bm = cell.get((x, y, "CFG_OMUX%d" % z, _s))
            if bm: reg_sets.append(bm)
        clocked_tiles.add((x, y))
    for b in range(16):
        byte, mask = physmap.init_bit_pos(x, y, z, b)
        if not ((init >> b) & 1): lut_sets.append((byte, mask))   # complement
print("slices placed:", slices, "; LUT-init bits:", len(lut_sets))

# 1b. BRAM (alta_bram9k) config emission. A placed BRAM9K cell -> its config bits via bram_emit
# (findings_bram_crack.md, byte-exact vs oracle_bram). The BRAM RE is DONE (config + routing); this is
# the bitgen plumbing that folds a placed+routed BRAM into the open bitstream. A BRAM cell is a nextpnr
# cell of type BRAM9K/alta_bram9k (or one whose bel is a X{x}Y{y}_BRAM* BramTILE bel at x=13). Params
# (nextpnr stores param values as binary strings): INIT_VAL (9216-bit), PORTA_WIDTH (5-bit thermometer),
# CLKMODE (2-bit), and PORT{A,B}_{CLKIN,CLKOUT,RSTIN,RSTOUT}_EN (1-bit). We emit ONLY the BRAM-family
# config cells (INIT_VAL / DWSEL / CLKMODE / port-enables); the BRAM<->fabric routing pips are handled
# by the router (arch bram9k_edges) and land in route_sets. Guarded: no BRAM cell -> zero change.
sys.path.insert(0, os.path.dirname(_ENGINE))   # tools/agamemnon (bram_emit lives here)
import bram_emit as BRE
def _param_int(params, key, default=None):
    v = params.get(key)
    if v is None: return default
    if isinstance(v, int): return v
    s = str(v)
    # nextpnr emits binary strings for bit params; hex ('h...) or decimal are also tolerated.
    try:
        if s.lower().startswith("0x"): return int(s, 16)
        if all(ch in "01" for ch in s) and len(s) > 2: return int(s, 2)
        return int(s, 0)
    except ValueError:
        return int(s, 2)
BRAM_TYPES = {"BRAM9K", "ALTA_BRAM9K", "ALTA_BRAM", "$mem", "BRAM"}
bram_sets = []
brams = []
for cn, c in mod["cells"].items():
    typ = str(c.get("type", "")).upper()
    bel = c.get("attributes", {}).get("NEXTPNR_BEL", "")
    bm = re.match(r"X(\d+)Y(\d+)_BRAM", bel or "")
    if typ not in BRAM_TYPES and not bm: continue
    if bm:
        x, y = int(bm.group(1)), int(bm.group(2))
    else:
        # no BRAM bel yet (config-only probe) -> default to the first BramTILE (13,4)
        x, y = 13, 4
    p = c.get("parameters", {})
    init_val = _param_int(p, "INIT_VAL", 0)
    width = _param_int(p, "PORTA_WIDTH", 0)          # 5-bit thermometer (0=x18)
    clkmode = _param_int(p, "CLKMODE", 0)
    enables = {}
    for port in ("PORTA", "PORTB"):
        for sig in ("CLKIN", "CLKOUT", "RSTIN", "RSTOUT"):
            en = "%s_%s_EN" % (port, sig)
            enables[en] = _param_int(p, en, 0) or 0
    for bmk in BRE.emit(x, y, width, clkmode, init_val, enables):
        bram_sets.append(bmk)
    brams.append((x, y, width, clkmode))
if brams:
    print("BRAM cells:", brams, "; BRAM config bits:", len(bram_sets))

# IO output pads: GENERIC_IOB cells bound to X1Y4_LEDz -> pad-output config via io_emit
# (findings_io_crack.md). z->pad-feed-RMUX R is fixed by arch.py sec 3c; the RMUX->pad hop is
# implicit (io_emit encodes it at the N-1 config tile (0,4)), so it isn't a routed pip.
import io_emit as IOE
# Ring-pad OUTPUT driver at IOTILE(0,4). The pad-output bels (arch.py sec 3c) sit on the real IOMUX{z}
# pad wire, so nextpnr routes the full chain fabric -> feeder -> RMUX{R} -> IOMUX{z}; the feeder's
# CFG_RMUX source-select is emitted from the route (route_sets below) -- that was the missing piece that
# left every from-scratch pad dark. Here we emit only the pad DRIVER (CFG_IOMUX): source-select + the
# left-edge output-ENABLE, which is done by CLEARING the per-block flag {7z+6} in CFG_IOMUX0..3 (the
# baseline defaults them SET = pad disabled). Byte-exact vs the FACTORY (0,4) footprint. LED_DRV maps
# each board LED's IOMUX pad index -> (CFG_IOMUX0 block, io_emit source-select R).
LED_DRV = {2: (0, 24), 0: (1, 20), 4: (2, 0), 3: (3, 12)}   # IOTILE(0,4) IOMUX z -> (block, R select)
# R is the IOMUX source-SELECT value (multiple of 4), byte-exact vs factory. The observed
# (0,4) RMUX->IOMUX pips it selects: IOMUX2/R24->wire RMUX24, IOMUX0/R20->wire RMUX18,
# IOMUX4/R0->RMUX00, IOMUX3/R12->RMUX12. The feeder must drive THAT wire (see LED_FEEDER below).
led_outs = []
for cn, c in mod["cells"].items():
    if c.get("type") != "GENERIC_IOB": continue
    m = re.match(r"X0Y4_OPAD(\d+)", c.get("attributes", {}).get("NEXTPNR_BEL", ""))
    if m and int(m.group(1)) in LED_DRV:
        led_outs.append(LED_DRV[int(m.group(1))])
io_sets = []; io_clears = []
for (z, R) in led_outs:
    idx = R // 4
    for sel in (7 * z + (idx & 3), 7 * z + 4 + (idx >> 2)):     # CFG_IOMUX0 source-select (2 bits/pad)
        bm = IOE.CELLS.get((0, 4, "CFG_IOMUX0"), {}).get(sel)
        if bm: io_sets.append(bm)
    for bank in range(4):                                        # enable pad z: CLEAR {7z+6} in IOMUX0..3
        bm = IOE.CELLS.get((0, 4, "CFG_IOMUX%d" % bank), {}).get(7 * z + 6)
        if bm: io_clears.append(bm)
if led_outs:
    print("IO LED pads (0,4) blocks %s -> %d src-sel set + %d enable-clear (feeder CFG_RMUX from route)"
          % (sorted(b for b, _ in led_outs), len(io_sets), len(io_clears)))

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
    if df in ("BBMUXS", "BBMUXE"):              # MCU-edge crossing mux: set 2-hot input pair (lo,hi)
        pairtab = BBMUXS_PAIR if df == "BBMUXS" else BBMUXE_PAIR
        pair = pairtab.get(si) if sf == "RMUX" else None
        if pair is None: n_unmap += 1; continue
        ok = 0
        for sel in pair:
            k = (dx, dy, "%s%d" % (df, di), sel)
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
    if sf == "OMUX" and df == "OMUX" and (sx, sy) == (dx, dy) and di == si - 1:
        # FF-FEEDBACK BRIDGE (arch 4c): OMUX[3z+2]->OMUX[3z+1] presents Q ALSO on the feedback wire so
        # the slice's Q reaches its own LUT (the OMUX[3z+1]->IMUX self-loop, resolved normally below).
        # Emit CFG_OMUX<z> sel=1 (Q on OMUX[3z+1]); sel=2 (external) is already set for registered slices.
        z = di // 3
        bm = cell.get((dx, dy, "CFG_OMUX%d" % z, 1))
        if bm: route_sets.append(bm); n_map += 1
        else: n_unmap += 1
        continue
    if sf == "OMUX" and df == "IMUX" and (sx, sy) == (dx, dy) and di % 4 == 2 and si == 3*(di // 4) + 2:
        # INTERNAL Qin FEEDBACK (arch 4d): the slice's Q (OMUX[3z+2]) feeds its OWN LUT C-input
        # (IMUX[4z+2] = pinC) via the internal FeedbackMux -- NOT a routed crossbar edge. Select Qin
        # with CFG_LUTCMUX[2z]=1 (byte-exact, slice_cfg.csv); emit NO CFG_IMUX sel (Qin bypasses the
        # IMUX crossbar). The LUT INIT already has I[2]=the fed-back Q, so the function is correct.
        z = di // 4
        bm = SLICE_CFG.get((dx, dy, "CFG_LUTCMUX[%d]" % (2 * z)))
        if bm: route_sets.append(bm); n_map += 1
        else:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  QINFB no LUTCMUX bit for slice z=%d @(%d,%d)" % (z, dx, dy))
        continue
    if df in NOCFG: continue                    # 0-config passthrough (BufMUX/InputMUX/SinkMUXPseudo)
    if df == "RMUX" and dy == 13 and (dx, di) in PADFEED_TOP:   # TOP-ROW IOTILE pad-feed: exact codeword
        cw = PADFEED_TOP[(dx, di)]
        for bm in cw: route_sets.append(tuple(bm))
        n_map += 1                              # counts as mapped even for a zero codeword (default sel)
        if os.environ.get("AGAMEMNON_DEBUG"):
            print("  PADFEED %s%d@(%d,%d) <- %s%d : %d codeword bit(s)" % (df, di, dx, dy, sf, si, len(cw)))
        continue
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
        if pr is None and MESH_TMPL:
            mt = MT.resolve(df, di, sf, si, dx - sx, dy - sy)   # absolute sels (block+local); guarded legal-fanin
            if mt is not None:
                pr = (mt[0] - blk, mt[1] - blk)                 # -> within-block offsets for the blk+ln lookup below
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
CLK_SEAM_SEL = int(os.environ.get("AGAMEMNON_CLK_SEAM", "5"))   # clock seam = sel 5 (SILICON-PROVEN at
# (10,4): the working mcu_toggle sets CFG_SEAMMUX[5]=0x80 @byte69603; a seam-0 build reads dout STUCK).
# The corpus "seam 0 uniform" harvest was a FALSE LEAD (wrong sel decode) -- do not trust it over silicon.
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
for (by, ms) in route_sets + lut_sets + clk_sets + io_sets + reg_sets + bram_sets:
    if by < len(raw): raw[by] |= ms
for (by, ms) in io_clears:                    # left-edge LED output-enable = clear baseline disable flags
    if by < len(raw): raw[by] &= (~ms) & 0xFF

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
    # PARAMETRIC PLL clock: overlay the divider bits for a non-default SYSCLK/HSE onto the 100/8
    # baseline blob (pll_emit; byte-exact vs 4 vendor oracles, findings_pll_crack.md). Default
    # (100,8) leaves the proven blob untouched -> zero regression; env override enables other clocks.
    _sys = int(os.environ.get("AGAMEMNON_SYSCLK", "100")); _hse = int(os.environ.get("AGAMEMNON_HSE", "8"))
    if (_sys, _hse) != (100, 8):
        import pll_emit as _PE
        _um = _PE.apply_fields(raw, _PE.emit_fields(_sys, _hse)[0])
        print("parametric CLKGEN SYSCLK=%d HSE=%d %s" % (_sys, _hse, ("UNMAPPABLE %s" % _um) if _um else "ok"))
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
