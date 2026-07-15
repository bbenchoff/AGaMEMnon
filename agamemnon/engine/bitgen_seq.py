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

# BramTile (13,4) config cells (gen_bram_cell.py, from physical_map) -> merge into `cell` so the general
# resolvers (mesh RMUX closed-form + IMUX crossbar closed-form) can emit (byte,mask) for BramTile muxes.
# pips_full.csv is LogicTile-only; without these a BramTile-dst pip resolves a sel but finds no bit.
import csv as _csv
_bcell = os.path.join(SRC, "bram_cell.csv")
if os.path.exists(_bcell):
    _nbc = 0
    for r in _csv.DictReader(open(_bcell)):
        cell[(int(r["x"]), int(r["y"]), r["mux"], int(r["sel"]))] = (int(r["byte"]), int(r["mask"]))
        _nbc += 1
    print("loaded %d BramTile config cells (bram_cell.csv)" % _nbc)

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
GEOM_RMUX = ABS_LUT = GROUP_CTX = None
def _load_legacy_tables():
    """Load the large legacy/predictive tables only for a non-clean route.

    sel_edge_pairs.pkl is the release-quality exact table and is itself a large
    Python object.  Eagerly expanding it alongside _sel_tables2.pkl can exceed
    the address-space commit available to an otherwise tiny bitgen run.  Clean
    release routes never consult the older context/geometry fallbacks, so keep
    those compressed on disk unless a routed group actually lacks clean data.
    """
    global GEOM_RMUX, ABS_LUT, GROUP_CTX
    if GEOM_RMUX is not None:
        return
    if os.path.exists(_CACHE) and (not os.path.exists(_SDS) or os.path.getmtime(_CACHE) >= os.path.getmtime(_SDS)):
        with open(_CACHE, "rb") as _fh:
            GEOM_RMUX, ABS_LUT, GROUP_CTX = pickle.load(_fh)
        print("loaded fallback sel tables: %d geom, %d abs, %d group-ctx"
              % (len(GEOM_RMUX), len(ABS_LUT), len(GROUP_CTX)))
    else:
        GEOM_RMUX = _build_geom_rmux(); ABS_LUT = _build_abs_lut(); GROUP_CTX = _build_group_ctx()
        with open(_CACHE, "wb") as _fh:
            pickle.dump((GEOM_RMUX, ABS_LUT, GROUP_CTX), _fh)
        print("built + cached fallback sel tables: %d geom, %d abs, %d group-ctx"
              % (len(GEOM_RMUX), len(ABS_LUT), len(GROUP_CTX)))

# BLOCK-CLEAN absolute edge table.  The legacy ABS_LUT builder only attributed
# a pair when an entire CFG group (six RMUX nodes / four IMUX nodes) had one
# routed edge.  sel_dataset.csv already records the destination-node block, so
# a streaming corpus pass can isolate each node's 10/12-bit block even when
# sibling nodes in the group are also in use.  Promote only physical keys whose
# extracted pair is consistent across every observation; conflicting keys keep
# using the context-aware tables/fallbacks below.  This expands direct corpus
# coverage from 153,080 to the current shipped table without treating a majority as truth.
CLEAN_EDGE = {}
REL_EDGE = {}
ARCHIVAL_LEGACY = bool(os.environ.get("AGAMEMNON_ALLOW_UNMAPPED"))
_cef = SRCA + "/sel_edge_pairs.pkl"
if os.path.exists(_cef):
    _cep = pickle.load(open(_cef, "rb"))
    if _cep.get("version") != 1 or not isinstance(_cep.get("table"), dict):
        raise SystemExit("unsupported sel_edge_pairs.pkl format")
    CLEAN_EDGE = _cep["table"]
    print("loaded %d block-clean physical edge sel pairs" % len(CLEAN_EDGE))
    # Tile-relative replication is promoted only when every block-clean
    # physical occurrence agrees on the same local pair.  This captures the
    # repeated LogicTile mesh structure without majority voting: one conflict
    # removes the relative key entirely.  It closes unseen-at-this-coordinate
    # routes while retaining a fail-closed evidence rule.
    _rel_conflict = set()
    for (_dx, _dy, _df, _di, _sf, _sx, _sy, _si), _pair in CLEAN_EDGE.items():
        _rk = (_df, _di, _sf, _si, _dx - _sx, _dy - _sy)
        _pair = tuple(_pair)
        if _rk in REL_EDGE and REL_EDGE[_rk] != _pair:
            _rel_conflict.add(_rk)
        else:
            REL_EDGE[_rk] = _pair
    for _rk in _rel_conflict:
        REL_EDGE.pop(_rk, None)
    print("derived %d unanimous tile-relative sel pairs (%d conflicting keys rejected)"
          % (len(REL_EDGE), len(_rel_conflict)))

# MCU-edge BBMUXS input-select encoding: a BBMUXS field is a 2-hot {lo, hi} pair (lo in bank 0..3,
# hi in bank 4..7) that depends ONLY on the SOURCE RMUX index (validated INSTANCE-independent: the
# same source RMUX lights the same pair on different BBMUXS instances). Extracted byte-exact from four
# oracle designs: RMUX92->(2,6), RMUX19->(1,6), RMUX25->(0,4), RMUX02->(1,4). NOTE: hi is NOT fixed at
# 6 (that held only for RMUX92/19) nor lo+4 -- it's a genuine per-source pair (RMUX02->(1,4) and
# RMUX25->(0,4) both have hi=4). Cross-validated: RMUX02->BBMUXS04 gives {1,4} in BOTH loop4 (folded,
# +idle top-flag 8) and lutmcu4 (LUT-driven, no flag) -> the top-flag 8 is idle-only, not needed.
# BufMUX/InputMUX/SinkMUXPseudo are 0-config passthrough/pseudo nodes (no CFG cell).
mcue = {}   # (x,y,"BBMUXSn"|"BBMUXEn"|"BBMUXWn",sel_index) -> (byte,mask)
for r in csv.DictReader(open(SRCA + "/pips_mcuedge.csv")):
    if r["mux"].startswith(("BBMUXS", "BBMUXE", "BBMUXW")):
        mcue[(int(r["x"]), int(r["y"]), r["mux"], int(r["sel_index"]))] = (int(r["byte"]), int(r["mask"]))
    elif r["mux"].startswith("InputMUX"):
        mcue[(int(r["x"]), int(r["y"]), r["mux"], int(r["sel_index"]))] = (int(r["byte"]), int(r["mask"]))

# Exact node-local route fields from the protocol-valid, simultaneous 32-bit
# HADDR-to-HRDATA vendor oracle.  Several of these physical edges have other
# observations in the broad corpus with a different apparent pair because a
# sibling node in the same CFG group was active.  A majority pair is therefore
# not sufficient here: clear the one destination-node field and reproduce the
# exact oracle codeword.  The table also includes the one-bit InputMUX fields
# on BufMUX->InputMUX hard-boundary edges, which pips_full/sel_dataset do not
# represent at all.
EXACT_MCU_ADDR_PIP = {}
_wire_re = re.compile(r"X(\d+)Y(\d+)_([A-Za-z_]+?)0*(\d+)")
def _exact_wire(text):
    match = _wire_re.fullmatch(text)
    if not match:
        raise SystemExit("bad exact MCU corridor wire: %s" % text)
    x, y, family, index = match.groups()
    return int(x), int(y), family, int(index)
for _map_name in ("mcu_ahb32_pip_cfg.csv", "mcu_ahb32_addr_pip_cfg.csv"):
    _mapf = os.path.join(SRCA, _map_name)
    if not os.path.exists(_mapf):
        continue
    for _r in csv.DictReader(open(_mapf)):
        _src = _exact_wire(_r["src_wire"]); _dst = _exact_wire(_r["dst_wire"])
        _key = _src + _dst
        _clear = tuple(int(v) for v in _r["clear_selectors"].split(";") if v != "")
        _set = tuple(int(v) for v in _r["set_selectors"].split(";") if v != "")
        _value = (_r["cell_table"], _r["cfg_group"], _clear, _set)
        if _key in EXACT_MCU_ADDR_PIP and EXACT_MCU_ADDR_PIP[_key] != _value:
            raise SystemExit("conflicting exact MCU corridor codeword for %s" % (_key,))
        EXACT_MCU_ADDR_PIP[_key] = _value
if EXACT_MCU_ADDR_PIP:
    print("loaded %d exact protocol-valid AHB32 corridor fields" % len(EXACT_MCU_ADDR_PIP))
# RMUX src idx -> 2-hot (lo,hi). Harvested byte-exact + instance-independent across the whole oracle
# corpus (harvest_bbmuxs_pairs.py: 10/10 consistent -- same RMUX -> same pair on different BBMUXS
# instances and different designs). This is the COMPLETE exit table for the BBMUXS@(10,5) fan-in.
BBMUXS_PAIR = {2: (1, 4), 9: (1, 5), 19: (1, 6), 25: (0, 4), 32: (0, 5),
               39: (0, 6), 55: (3, 4), 62: (3, 5), 69: (3, 6), 92: (2, 6)}
# MCU-edge EAST crossing (BBMUXE) exit = same 2-hot {lo,hi} scheme; source-RMUX -> pair, extracted
# byte-exact from the hrdata vendor recon (tools/oracle_ahbr/ahbr.bin, route.tx): the mem_ahb READ
# path (fabric -> MCU hrdata) at UFMTILE col-13. hrdata[0..3] <- BBMUXE02/03/04/05@(13,12) <-
# RMUX93/26/20/49@(14,12). idle BBMUXE sit at sel {8} (not emitted). See [[ag32-ahb-read-scoping]].
BBMUXE_PAIR = {93: (3, 6), 26: (1, 4), 20: (2, 6), 49: (0, 4),
               # widened AHB readout (2026-07-08, ahbrhi recon): hrdata[4..7] -> BBMUXE06..09.
               # source-RMUX-keyed, instance-independent (RMUX49/20 re-confirmed identical to the 4-bit recon).
               56: (0, 5), 33: (1, 5),
               # FULL BBMUXE fan-in from corpus harvest (harvest_bbmuxe.py -> chipdb/bbmuxe_fanin.csv):
               # the funnel is a clean 4x3=12-input mux, sel-pair=(lo in 0-3)+(hi in 4-6). 14 feeders, 12 at x=14.
               63: (0, 6), 79: (3, 4), 86: (3, 5), 13: (2, 5),
               # Internal-counter Port-B oracle (silicon-positive): these
               # two source codes supersede ambiguous corpus attribution.
               3: (1, 6), 43: (0, 6), 25: (0, 4), 92: (2, 6)}

# Exact, physical AHB hrdata edge encodings.  The vendor-routed 32-bit oracle
# proved that selector pairs are not globally source-index invariant: RMUX43,
# for example, uses a different pair at the y=11 east crossing than at y=12.
# Key the pair by the complete source->edge identity and use the older source
# tables only for the independently qualified alternate fan-ins above.
MCU_EXIT_PAIR = {}
for _hl_name in ("mcu_hrdata_lanes.csv", "mcu_hrdata_addr_lanes.csv"):
    _hl = os.path.join(SRCA, _hl_name)
    if not os.path.exists(_hl):
        continue
    for _r in csv.DictReader(open(_hl)):
        _em = re.fullmatch(r"(BBMUX[A-Z]+)0*([0-9]+)", _r["edge_res"])
        _sm = re.fullmatch(r"([A-Za-z]+)0*([0-9]+)", _r["src_res"])
        if not _em or not _sm:
            raise SystemExit("bad mcu_hrdata_lanes.csv resource: %s -> %s"
                             % (_r["src_res"], _r["edge_res"]))
        _key = (int(_r["edge_x"]), int(_r["edge_y"]), _em.group(1), int(_em.group(2)),
                int(_r["src_x"]), int(_r["src_y"]), _sm.group(1), int(_sm.group(2)))
        MCU_EXIT_PAIR[_key] = tuple(int(v) for v in _r["selectors"].split(";") if v)
print("loaded %d exact AHB hrdata edge selector codewords" % len(MCU_EXIT_PAIR))
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
PADFEED_EXACT = {}  # (dst x,R,src x,y,fam,index) -> exact codeword
LEFT_PAD_COMPANION = {}  # z -> [(cfg_group, sel)]; silicon-isolated pad-tile controls
for _pf_name in ("padfeed_L48_top.csv", "padfeed_L48_left.csv"):
    _pf = os.path.join(SRCA, _pf_name)
    if not os.path.exists(_pf):
        continue
    for r in csv.DictReader(open(_pf)):
        bs = [int(v) for v in r["codeword_bytes"].split(",") if v != ""]
        ms = [int(v) for v in r["codeword_masks"].split(",") if v != ""]
        PADFEED_EXACT[(int(r["padtile_x"]), int(r["padfeed_rmux"]), int(r["src_x"]),
                       int(r["src_y"]), r["src_res"].rstrip("0123456789"),
                       int(r["src_res"][len(r["src_res"].rstrip("0123456789")):]))] = list(zip(bs, ms))
        if _pf_name == "padfeed_L48_left.csv" and r.get("companion_cfg"):
            LEFT_PAD_COMPANION[int(r["iomux_z"])] = [
                (r["companion_cfg"], int(sel))
                for sel in r.get("companion_sels", "").split(",") if sel
            ]
print("loaded %d exact package pad-feed codewords" % len(PADFEED_EXACT))

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
carry_sets = []         # HW-Carry 3: ripple-carry slice config (CFG_LUTCMUX[2z+1]=pinC<-Cin)
carry_clears = []       # mutually-exclusive carry controls cleared before the design is overlaid
slices = []
clocked_tiles = set()   # tiles containing a registered FF -> need the clock distributed to them
_vout_all = bool(os.environ.get("AGAMEMNON_VENDOR_OUT_ALL"))
_vout = os.environ.get("AGAMEMNON_VENDOR_OUT_SLICE")
_vout = tuple(int(v) for v in _vout.split(",")) if _vout else None
_left_vout = ({(14, 11, 4), (14, 11, 5)}
              if os.environ.get("AGAMEMNON_LEFT_PAD_OUT") else set())
for cn, c in mod["cells"].items():
    if c.get("type") != "GENERIC_SLICE": continue
    bel = c["attributes"]["NEXTPNR_BEL"]; mm = re.match(r"X(\d+)Y(\d+)_SLICE(\d+)", bel)
    x, y, z = int(mm.group(1)), int(mm.group(2)), int(mm.group(3))
    init = int(c["parameters"]["INIT"], 2)
    slices.append((x, y, z))
    # HW-Carry 3 (byte-exact vs vendor cnt8, decode_slice_cfg @ (20,12)): a slice in the dedicated ripple
    # carry chain (CIN or COUT driven) sets modeMux=1 => pinC=Cin, encoded CFG_LUTCMUX[2z+1]=1
    # (ag32-dense-carry-recipe M1; Qin uses [2z]=1). The seed (COUT only, injects the initial carry) and
    # every count bit both get this. Working registered carry bits keep CFG_BYPASSEN[z]=0 so LutOut feeds
    # the FF normally. CarryEnb=0 for the chain => CFG_CARRY_CRL[z] stays unset
    # (the all-zero default) so consecutive carry cells chain automatically. The ripple LUT mask (0x0055
    # seed / 0x96E8 bit0 / 0x69D4 bits1+) rides the normal INIT-complement path below (CFG_LUT = ~INIT).
    _conns = c.get("connections", {})
    _has_cin, _has_cout = bool(_conns.get("CIN")), bool(_conns.get("COUT"))
    if _has_cin or _has_cout:
        for _feat in ("CFG_LUTCMUX[%d]" % (2 * z), "CFG_LUTCMUX[%d]" % (2 * z + 1),
                      "CFG_BYPASSEN[%d]" % z, "CFG_CARRY_CRL[%d]" % z):
            bm = SLICE_CFG.get((x, y, _feat))
            if bm: carry_clears.append(bm)
        bm = SLICE_CFG.get((x, y, "CFG_LUTCMUX[%d]" % (2 * z + 1)))
        if bm: carry_sets.append(bm)
    if _has_cin:
        # Normal ripple registers capture LutOut.  The old default set
        # BYPASSEN=1, which makes Din depend on the tile SyncReset input and
        # froze every open carry counter on silicon.  The working vendor
        # oracle has BypassEn=0.  Retain a true bit only for an explicit
        # low-level primitive request.
        _bp = c["parameters"].get("BYPASSEN")
        if _bp is not None and int(str(_bp), 2):
            bm = SLICE_CFG.get((x, y, "CFG_BYPASSEN[%d]" % z))
            if bm: carry_sets.append(bm)
    _bram_sel = c.get("attributes", {}).get("AGRV2K_OMUX_SEL")
    _bram_sel = int(str(_bram_sel), 2) if _bram_sel is not None else None
    if int(c["parameters"].get("FF_USED", "0"), 2):        # registered slice -> present Q on OMUX[3z+2]
        # VENDOR-OUT slice (AGAMEMNON_VENDOR_OUT_SLICE="x,y,z"): the vendor-faithful output FF routes
        # F (LUT out) on OMUX[3z+0] and Q (feedback) on OMUX[3z+1] instead of the default OMUX[3z+2],
        # so it enters the silicon-conducting pad chain (OMUX42->RMUX74->RMUX09->pad) and feeds back
        # via the intra-tile crossbar (OMUX43->IMUX). CFG_OMUX<z> sel=b enables OMUX[3z+b] (proven by
        # the vendor pintest2 bits: slice14@(14,12) sets CFG_OMUX14 {0,1}). Emit sels {0,1} for it.
        _sels = ((0, 1) if _vout_all or _vout == (x, y, z) or (x, y, z) in _left_vout
                 else ((_bram_sel,) if _bram_sel is not None else (2,)))
        for _s in _sels:
            bm = cell.get((x, y, "CFG_OMUX%d" % z, _s))
            if bm: reg_sets.append(bm)
        clocked_tiles.add((x, y))
    elif _vout_all or (x, y, z) in _left_vout:
        # In vendor-output mode a combinational LUT is presented on
        # OMUX[3z+0]. This is used by exact carry-seam qualification where the
        # registered Q feedback wire must remain independent of the mesh tap.
        bm = cell.get((x, y, "CFG_OMUX%d" % z, 0))
        if bm: reg_sets.append(bm)
    elif _bram_sel is not None:
        # The vendor's conflict-free Port-B placement also uses alternate
        # combinational LUT presentation (not just alternate registered Q).
        # There is no cell-to-OMUX routing pip, so emit CFG_OMUX explicitly.
        bm = cell.get((x, y, "CFG_OMUX%d" % z, _bram_sel))
        if bm: reg_sets.append(bm)
    for b in range(16):
        byte, mask = physmap.init_bit_pos(x, y, z, b)
        if not ((init >> b) & 1): lut_sets.append((byte, mask))   # complement
print("slices placed:", slices, "; LUT-init bits:", len(lut_sets))

# 1b. BRAM (alta_bram9k) config emission. A placed BRAM9K cell -> its config bits via bram_emit
# (findings_bram_crack.md, byte-exact vs oracle_bram). The BRAM RE is DONE (config + routing); this is
# the bitgen plumbing that folds a placed+routed BRAM into the open bitstream. A BRAM cell is a nextpnr
# cell of type BRAM9K/alta_bram9k (or one whose bel is a X{x}Y{y}_BRAM* BramTILE bel at x=13). Params
# (nextpnr stores param values as binary strings): INIT_VAL (9216-bit), PORTA/B_WIDTH (5-bit thermometer),
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
    # yosys marks un-read memory bits as don't-care ('x'/'z') in INIT_VAL binary strings; treat as 0.
    if any(ch in "xzXZ" for ch in s) and all(ch in "01xzXZ" for ch in s):
        s = "".join("0" if ch in "xzXZ" else ch for ch in s)
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
# nextpnr leaves unconsumed BRAM output pins on private dangling nets.  A net
# referenced by another cell identifies a genuinely live read port after pack.
_net_refs = collections.Counter()
for _cell in mod["cells"].values():
    for _bits in _cell.get("connections", {}).values():
        _net_refs.update(_bit for _bit in _bits if isinstance(_bit, int))
bram_portb_read = False
bram_portb_dynamic_address = 0
bram_dual_rw = False
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
    portb_read = any(_net_refs[_bit] > 1 for _bit in c.get("connections", {}).get("DataOutB", [])
                     if isinstance(_bit, int))
    bram_portb_read |= portb_read
    bram_dual_rw |= portb_read and bool(c.get("connections", {}).get("WeA", []))
    bram_portb_dynamic_address = max(
        bram_portb_dynamic_address,
        sum(_net_refs[_bit] > 1 for _bit in c.get("connections", {}).get("AddressB", [])
            if isinstance(_bit, int)))
    init_val = _param_int(p, "INIT_VAL", 0)
    width = _param_int(p, "PORTA_WIDTH", 0)          # 5-bit thermometer (0=x18)
    width_b = _param_int(p, "PORTB_WIDTH", 0)
    clkmode = _param_int(p, "CLKMODE", 0)
    enables = {}
    for port in ("PORTA", "PORTB"):
        for sig in ("CLKIN", "CLKOUT", "RSTIN", "RSTOUT"):
            en = "%s_%s_EN" % (port, sig)
            enables[en] = _param_int(p, en, 0) or 0
    # Gate parameters are literal configuration values, not generic
    # "port enabled" flags.  The silicon-positive independent Port-B ROM
    # oracle leaves all four at zero.  Preserve explicit primitive parameters;
    # the techmap default of zero selects that hardware mode.
    for bmk in BRE.emit(x, y, width, clkmode, init_val, enables, width_b=width_b):
        bram_sets.append(bmk)
    brams.append((x, y, width, width_b, clkmode))
if brams:
    # ROM read control blob: the BramTile control muxes (KMUX/TMUX/CtrlMUX/TileClk*) delivering the fixed
    # ReA=1/WeA=0/ByteEn=3/ClkEn=1 pattern (constants -> TMUX -> KMUX -> BRAM). Harvested from the vendor
    # ROM oracle (harvest_bram_rom_ctrl.py); without it the BRAM never reads (DataOut floats high on silicon).
    _rc = os.path.join(SRC, "bram_dual_ctrl.csv" if bram_dual_rw else "bram_rom_ctrl.csv")
    if os.path.exists(_rc):
        _n = 0
        for r in csv.DictReader(open(_rc)):
            bm = (int(r["byte"]), int(r["mask"]))
            # KMUX71 is the Port-A read select.  Port B uses the mutually
            # exclusive KMUX62 select below; setting both leaves DataOutB
            # stuck even though routing and initialization are correct.
            if not bram_dual_rw and bram_portb_read and bm == (69006, 2):
                continue
            bram_sets.append(bm); _n += 1
        print("BRAM %s control blob: +%d bits" %
              ("dual-port R/W" if bram_dual_rw else "ROM", _n))
    if bram_portb_read and not bram_dual_rw:
        _rbc = os.path.join(SRC, "bram_portb_read_ctrl.csv")
        if os.path.exists(_rbc):
            for r in csv.DictReader(open(_rbc)):
                bram_sets.append((int(r["byte"]), int(r["mask"])))
        print("BRAM Port-B read control: KMUX71 -> KMUX62")
    if bram_portb_read and bram_portb_dynamic_address <= 2:
        # The vendor drives every otherwise-constant Port-B BRAM input through
        # a deterministic IMUX selection.  An all-zero configuration is not a
        # logical zero at these muxes and leaves DataOutB stuck on silicon.
        # This blob is the exact vendor internal-counter/x2-ROM configuration,
        # excluding the two dynamic AddressB selectors applied by routing.
        _pbc = os.path.join(SRC, "bram_portb_const_ctrl.csv")
        _n = 0
        if os.path.exists(_pbc):
            for r in csv.DictReader(open(_pbc)):
                bram_sets.append((int(r["byte"]), int(r["mask"]))); _n += 1
        print("BRAM Port-B constant controls: +%d exact IMUX bits" % _n)
    elif bram_portb_read:
        # This blob was isolated with only AddressB[1:2] dynamic.  Applying
        # its fixed-address selectors to a wider live bus enables two sources
        # in the same IMUX blocks and produces a legal-but-static image.
        # Wider buses get their address selectors from their routed pips.
        print("BRAM Port-B two-address constant blob skipped for %d dynamic address bits" %
              bram_portb_dynamic_address)
    print("BRAM cells:", brams, "; BRAM config bits:", len(bram_sets))

# BramTile ROUTING-pip config (harvest_bram_pip_cfg.py): the LogicTile sel resolvers don't cover the
# BramTile IMUX/RMUX muxes, so a BramTile-dst routing pip carries a directly-harvested (byte,mask) set
# keyed on (dst_res, src_res, ddx, ddy). Closes the "unmapped BRAM pips" gap. Guarded: file absent -> {}.
# BramTile dst families routed via the learned sel resolver: IMUX/RMUX (block-decomposed) + the clean
# clock/control families (flat single-inst). KMUX/TMUX (R/W data-control) are per-wire-ambiguous -> deferred.
BRAM_FAMS = {"IMUX", "RMUX", "SeamMUX", "CtrlMUX", "TileClkMUX", "TileClkEnMUX", "TileAsyncMUX",
             "KMUX", "TMUX"}
BRAM_FLAT = {"SeamMUX", "CtrlMUX", "TileClkMUX", "TileClkEnMUX", "TileAsyncMUX", "KMUX", "TMUX"}
BRAM_CTRL = {"KMUX", "TMUX"}
# KMUX/TMUX control codewords are isolated per destination wire from the vendor's
# weonly/byteenonly/reonly/dinonly oracles.  The completed table covers every
# Port-A control wire used by SERV, so writable BRAM routing is no longer gated.
# BramTile sel resolver (build_bram_resolver.py): a routed edge lights local sels in the dst mux's
# block = (didx % NPI)*BS; local (lo,hi) learned from the vendor BRAM corpus, keyed hierarchically
# L0 exact -> L1 (fam,go,sfam,sidx,ddx,ddy) -> L2 (fam,sfam,ddx,ddy,sidx%16). RMUX<-RMUX depends on
# (ddx,ddy) only; IMUX<-RMUX on ddx + src geometry -> the L1/L2 keys GENERALIZE to unseen edges.
# abs sel -> (byte,mask) via the BramTile cell map (bram_cell.csv, merged into `cell` above).
# BRAM DataOut EXIT-boundary pips (harvest_bram_pip_cfg.py): BramTile BufMUX -> LogicTile(14,4)/(10,4)
# RMUX. The LogicTile resolver doesn't know BufMUX sources, so these emit no sel config -> the exit RMUX
# never selects the BRAM output -> DataOut floats (silicon: hrdata stuck high). Direct (byte,mask) lookup.
EXACT_BRAM_PIP = {}
_epc = os.path.join(SRC, "bram_pip_cfg.csv")
if os.path.exists(_epc):
    for r in csv.DictReader(open(_epc)):
        EXACT_BRAM_PIP.setdefault((r["dst_res"], r["src_res"], int(r["ddx"]), int(r["ddy"])), []) \
                .append((int(r["byte"]), int(r["mask"])))
    print("loaded %d exact BRAM routing pip(s) (bram_pip_cfg.csv)" % len(EXACT_BRAM_PIP))
BRAM_RES = None
_brj = os.path.join(SRC, "bram_resolver.json")
if os.path.exists(_brj):
    BRAM_RES = json.load(open(_brj))
    print("loaded BramTile sel resolver (L0=%d L1=%d L2=%d)"
          % (len(BRAM_RES["L0"]), len(BRAM_RES["L1"]), len(BRAM_RES["L2"])))

def bram_resolve(dfam, didx, sfam, sidx, ddx, ddy):
    """-> list of absolute sels for a BramTile routing edge, or None."""
    if BRAM_RES is None: return None
    if dfam in ("KMUX", "TMUX"):        # control: per-wire, src-independent (CTRL table)
        return BRAM_RES.get("CTRL", {}).get("%s|%d" % (dfam, didx))
    go = didx % BRAM_RES["NPI"][dfam]; block = go * BRAM_RES["BS"][dfam]
    k0 = "|".join(map(str, (dfam, didx, sfam, sidx, ddx, ddy)))
    k1 = "|".join(map(str, (dfam, go, sfam, sidx, ddx, ddy)))
    k2 = "|".join(map(str, (dfam, sfam, ddx, ddy, sidx % 16)))
    loc = BRAM_RES["L0"].get(k0) or BRAM_RES["L1"].get(k1) or BRAM_RES["L2"].get(k2)
    if loc is None: return None
    return [block + l for l in loc]

# IO output pads: GENERIC_IOB cells bound to X1Y4_LEDz -> pad-output config via io_emit
# (findings_io_crack.md). z->pad-feed-RMUX R is fixed by arch.py sec 3c; the RMUX->pad hop is
# implicit (io_emit encodes it at the N-1 config tile (0,4)), so it isn't a routed pip.
import io_emit as IOE
IOMUX_HOP = {}
_ihp = os.path.join(SRC, "iomux_hop_vendor.csv")
if os.path.exists(_ihp):
    for _r in csv.DictReader(_ln for _ln in open(_ihp) if not _ln.lstrip().startswith("#")):
        def _cells(_s):
            return [(int(_p.split(":")[0]), int(_p.split(":")[1]))
                    for _p in (_s or "").split(";") if _p]
        IOMUX_HOP[(int(_r["pad_x"]), int(_r["pad_y"]), int(_r["z"]), int(_r["feeder_R"]))] = \
            (_cells(_r.get("set_cells")), _cells(_r.get("clear_cells")))
# Ring-pad OUTPUT driver at IOTILE(0,4) LEFT EDGE -- now ROUTE-DRIVEN (2026-07-08 fix). The old code
# hardcoded a broken LED_DRV table that (a) mis-unpacked (block,R) as (z,R) and (b) used feeder R
# values NOT matching nextpnr's actual routed wire, so the IOMUX picked an UNDRIVEN wire -> LED stuck
# HIGH on silicon. The left-edge pad-feed RMUX is fixed per slot (from chipdb/rrg_edges_full.csv,
# confirmed against the byte-identical vendor pintest2/pintest4 oracle that TOGGLES (0,4) z0/z1
# on silicon):
#     z0<-RMUX30, z1<-RMUX6, z2<-RMUX18, z3<-RMUX0   -- NOT a top-row idx=R//4 rule
# source-select formula is WRONG here. The working absolute CFG_IOMUX0 source-select sels per (z,R)
# come straight from that oracle. Enable = CLEAR {7z+6} in CFG_IOMUX0..3 (baseline SET = pad disabled;
# matches the vendor (0,4) footprint). z0/z1 SILICON-PROVEN; z2/z3 from the same oracle (were stuck
# only because pintest2 fed them a constant, not a config error).
LEFT_IOMUX0_SEL = {   # (z, feeder_R) -> absolute CFG_IOMUX0 sels
    (0, 30): (1, 5), (1, 6): (8, 11), (2, 18): (17, 18), (3, 0): (21, 25),
}
led_outs = []          # (z, R) from the ACTUAL route at (0,4)
io_pad_hops = set()    # (x,y,iomux_z) of pads whose final RMUX->IOMUX hop is CONFIGURED HERE (not the
                       # data-pip loop) -> don't count it as unmapped.
_ledpips = set()
for nn, ni in mod.get("netnames", {}).items():
    for tok in ni.get("attributes", {}).get("ROUTING", "").split(";"):
        if "." in tok and "GCLK" not in tok: _ledpips.add(tok)
for tok in _ledpips:
    a, b = tok.split(".", 1); s = pw(a); t = pw(b)
    if s and t and t[2] == "IOMUX" and (t[0], t[1]) == (0, 4) and s[2] == "RMUX":
        led_outs.append((t[3], s[3])); io_pad_hops.add((0, 4, t[3]))
io_sets = []; io_clears = []
for (z, R) in led_outs:
    sels = LEFT_IOMUX0_SEL.get((z, R))
    if sels is None:
        if os.environ.get("AGAMEMNON_DEBUG"):
            print("  LED (0,4) z%d<-R%d: NO source-select in LEFT_IOMUX0_SEL table" % (z, R))
        continue
    for sel in sels:                                             # CFG_IOMUX0 source-select (2 bits/pad)
        bm = IOE.CELLS.get((0, 4, "CFG_IOMUX0"), {}).get(sel)
        if bm: io_sets.append(bm)
    for bank in range(4):                                        # enable pad z: CLEAR {7z+6} in IOMUX0..3
        bm = IOE.CELLS.get((0, 4, "CFG_IOMUX%d" % bank), {}).get(7 * z + 6)
        if bm: io_clears.append(bm)
    # AGAMEMNON_ALLOW_UNMAPPED is also the archival replay mode used by the
    # byte-exact legacy fixtures. Preserve their historical bytes; strict
    # release builds receive the newly isolated companion controls.
    if not ARCHIVAL_LEGACY:
        for cfg, sel in LEFT_PAD_COMPANION.get(z, ()):
            bm = cell.get((0, 4, cfg, sel))
            if bm: io_sets.append(bm)
if led_outs:
    print("IO LED pads (0,4) route-driven z<-R %s -> %d src-sel set + %d enable-clear"
          % (sorted(led_outs), len(io_sets), len(io_clears)))

# 2. data routing pips (exclude clock GCLK pips)
pips = set()
for nn, ni in mod.get("netnames", {}).items():
    rt = ni.get("attributes", {}).get("ROUTING", "")
    for tok in rt.split(";"):
        if "." in tok and "GCLK" not in tok: pips.add(tok)

# 2b. GENERAL top-row (y=13) ring-pad OUTPUT driver, ROUTE-DRIVEN via io_emit (byte-exact validated at
# (16,13)/(20,13)). Each routed RMUX{R}->IOMUX{z} hop AT a top-row pad tile gives (z=iomux slot, R=feeder)
# straight from the route; io_emit emits the CFG_IOMUX source-select+enable at the N-1 config tile
# (px-1,py). On the top row slot==iomux (validated). The feeder CFG_RMUX comes from route_sets below. This
# generalises pad output beyond the 4 hardcoded (0,4) LEDs (LED_DRV path above stays for the left edge).
_toprow = collections.defaultdict(list)
for _p in pips:
    _a, _b = _p.split(".", 1); _s = pw(_a); _t = pw(_b)
    if not _s or not _t:
        continue
    (_sx, _sy, _sf, _si) = _s; (_dx, _dy, _df, _di) = _t
    if _df == "IOMUX" and _dy == 13 and _sf == "RMUX":
        _toprow[(_dx, _dy)].append((_di, _si))          # (iomux slot z, feeder RMUX R)
for (_px, _py), _outs in _toprow.items():
    # The top-row driver lives at the N-1 config tile. Clear the whole mutually-exclusive IOMUX
    # selection there before emitting this design's source, then add any silicon-derived implicit hop.
    for (_x, _y, _mux), _sels in IOE.CELLS.items():
        if (_x, _y) == (_px - 1, _py) and _mux.startswith("CFG_IOMUX"):
            io_clears += list(_sels.values())
    _bits = IOE.emit_bits(_px - 1, _py, _outs)          # CFG_IOMUX driver at N-1 tile
    io_sets += list(_bits)
    for (_z, _R) in _outs:
        _hs, _hc = IOMUX_HOP.get((_px, _py, _z, _R), ([], []))
        io_sets += _hs; io_clears += _hc
        io_pad_hops.add((_px, _py, _z))                 # truthful unmapped counter (final hop cfg'd here)
    if os.environ.get("AGAMEMNON_DEBUG"):
        print("  IO top-row pad tile (%d,%d): outs=%s -> %d CFG_IOMUX bit(s) @N-1(%d,%d)"
              % (_px, _py, sorted(_outs), len(_bits), _px - 1, _py))
if _toprow:
    print("IO top-row pads: %s (CFG_IOMUX driver via io_emit; feeder CFG_RMUX from route)"
          % {"%d,%d" % k: sorted(z for z, _ in v) for k, v in _toprow.items()})

route_sets = []; route_clears = []; n_map = n_unmap = 0
pad_input_used = set()                           # exact characterized perimeter-input route keys
PAD_INPUT_EDGE = {}
_pie = os.path.join(SRC, "pad_input_L48.csv")
if os.path.exists(_pie):
    for _r in csv.DictReader(open(_pie)):
        _m = re.fullmatch(r"(CFG_[A-Z0-9]+)\[([0-9, ]+)\]", _r["cfg"])
        if not _m:
            raise SystemExit("bad pad_input_L48.csv cfg: %r" % _r["cfg"])
        _key = (int(_r["pad_x"]), int(_r["pad_y"]), int(_r["inputmux"]),
                int(_r["dst_x"]), int(_r["dst_y"]), int(_r["dst_rmux"]))
        def _input_cells(_text):
            return [(int(_p.split(":")[0]), int(_p.split(":")[1]))
                    for _p in (_text or "").split(";") if _p]
        _sets = _input_cells(_r.get("set_cells")) or \
            [(int(_r["enable_byte"]), int(_r["enable_mask"]))]
        _clears = _input_cells(_r.get("clear_cells"))
        PAD_INPUT_EDGE[_key] = (_m.group(1), [int(_s) for _s in _m.group(2).split(",")],
                                _sets, _clears)
general = collections.defaultdict(list)         # (dx,dy,cfg,df) -> [(di,sf,sx,sy,si)] for group-ctx
for p in pips:
    a, b = p.split(".", 1); s = pw(a); t = pw(b)
    if not s or not t: continue
    sx, sy, sf, si = s; dx, dy, df, di = t
    if sf.startswith("CARRY") or df.startswith("CARRY"):
        continue   # synthetic dedicated-carry pip (COUT<z>->CIN<z+1>): the carry is internal HW, configured
                   # via CFG_LUTCMUX[2z+1] (carry_sets, modeMux=1), NOT a routed-pip config -> not unmapped
    _mcu_exact = EXACT_MCU_ADDR_PIP.get((sx, sy, sf, si, dx, dy, df, di))
    if _mcu_exact is not None:
        _table, _cfg, _clear_sels, _set_sels = _mcu_exact
        _lookup = mcue if _table == "mcu" else cell
        _missing = []
        for _sel in _clear_sels:
            _bm = _lookup.get((dx, dy, _cfg, _sel))
            if _bm is None:
                _missing.append(("clear", _sel))
            else:
                route_clears.append(_bm)
        for _sel in _set_sels:
            _bm = _lookup.get((dx, dy, _cfg, _sel))
            if _bm is None:
                _missing.append(("set", _sel))
            else:
                route_sets.append(_bm)
        if _missing:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  UNMAPPED[exact-ahb32] %s%d <- %s%d @(%d,%d): %s" %
                      (df, di, sf, si, dx, dy, _missing))
        else:
            n_map += 1
        continue
    if sf == "OMUX" and si % 3 != 2:
        # The default combinational mesh output is OMUX[3z+2] and requires NO CFG_OMUX bit (vendor
        # LUT oracles are all-zero here). Alternate wires OMUX[3z+0/1] do require their selector;
        # registered Q on OMUX[3z+2] is emitted separately by reg_sets above.
        _bm = cell.get((sx, sy, "CFG_OMUX%d" % (si // 3), si % 3))
        if _bm:
            route_sets.append(_bm)
    if sf == "BufMUX" and sx == 13 and sy == 4 and df == "RMUX":   # BRAM DataOut EXIT boundary
        bms = EXACT_BRAM_PIP.get(("%s%d" % (df, di), "%s%d" % (sf, si), dx - sx, dy - sy))
        if bms:
            for bm in bms: route_sets.append(bm)
            n_map += 1
        else:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  BRAM-EXIT-UNMAPPED %s%d <- %s%d d=(%d,%d)" % (df, di, sf, si, dx - sx, dy - sy))
        continue
    if dx == 13 and dy == 4 and df in BRAM_FAMS:   # BramTile routing pip: learned sel resolver
        if bram_dual_rw and df in BRAM_CTRL:
            # The simultaneous vendor dual-port blob already contains the
            # complete mutually-exclusive KMUX/TMUX codeword for routed WeA,
            # ReB, byte enables and clock controls.  The old CTRL resolver was
            # a union of observations per destination wire; composing it here
            # enabled six additional selectors and stalled SERV after its
            # first store.  Count the pre-routed vendor corridor as mapped,
            # but do not OR another ambiguous control codeword over it.
            n_map += 1
            continue
        exact = EXACT_BRAM_PIP.get(("%s%d" % (df, di), "%s%d" % (sf, si), dx - sx, dy - sy))
        if exact:
            route_sets.extend(exact)
            n_map += 1
            continue
        sels = bram_resolve(df, di, sf, si, dx - sx, dy - sy)
        cfg = "CFG_%s" % df if df in BRAM_FLAT else "CFG_%s%d" % (df, di // NPG[df])
        ok = 0
        if sels:
            for s_ in sels:
                k = (dx, dy, cfg, s_)
                if k in cell: route_sets.append(cell[k]); ok += 1
        if ok:
            n_map += 1
        else:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  BRAM-UNMAPPED %s%d <- %s%d d=(%d,%d) sels=%s" % (df, di, sf, si, dx - sx, dy - sy, sels))
        continue
    if df in ("BBMUXS", "BBMUXE", "BBMUXW"):   # MCU-edge crossing mux: set 2-hot input pair (lo,hi)
        _ek = (dx, dy, df, di, sx, sy, sf, si)
        pair = MCU_EXIT_PAIR.get(_ek)
        if pair is None and sf == "RMUX":
            if df == "BBMUXS":
                pair = BBMUXS_PAIR.get(si)
            elif df == "BBMUXE":
                pair = BBMUXE_PAIR.get(si)
            # BBMUXW has no source-only fallback: its recovered pairs are
            # physical-edge-specific, so an unseen edge must fail closed.
        if pair is None:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  UNMAPPED[bbmux] %s%d <- %s%d @(%d,%d)" % (df, di, sf, si, dx, dy))
            continue
        ok = 0
        # BBMUXE route resource N is configured by CFG_BBMUXEN.  A proposed
        # one-slot offset regressed the silicon-qualified counter readout:
        # BBMUXE02/RMUX93 must set CFG_BBMUXE2 {3,6}, and BBMUXE03/RMUX26 must
        # set CFG_BBMUXE3 {1,4}.  Preserve the direct physical index.
        mux_i = di
        _mux_name = "%s%d" % (df, mux_i)
        route_clears.extend(_bm for (_x, _y, _mx, _sel), _bm in mcue.items()
                            if (_x, _y, _mx) == (dx, dy, _mux_name))
        for sel in pair:
            k = (dx, dy, _mux_name, sel)
            if k in mcue: route_sets.append(mcue[k]); ok += 1
        # An empty exact tuple is a real zero codeword, observed on 28/32
        # lanes in the simultaneous vendor AHB loopback.  Clearing the field
        # is the complete encoding for those inputs; do not misclassify it as
        # an unmapped edge merely because no selector bit is set.
        if ok == len(pair):
            n_map += 1
        else:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  UNMAPPED[bbmux-nosel] %s%d <- %s%d @(%d,%d)" % (df, di, sf, si, dx, dy))
        continue
    if sf == "InputMUX" and df == "RMUX" and (sy in (0, 13) or sx == 0):
        # PERIMETER-IOTILE pad INPUT in use: beyond the ordinary RMUX source-select (general resolver
        # below), the pad-input domain needs the GLOBAL input enable in the preamble (see the emission
        # at the end of this file). Silicon-proven 2026-07-12: pad(17,13)z3 -> InputMUX07 -> RMUX61
        # conducts ONLY with raw[97]|=0x40 (byte-bisected on silicon against a known-good reference
        # image; the single differing byte). Without it every ring-pad input reads stuck.
        _pik = (sx, sy, si, dx, dy, di)
        _pi = PAD_INPUT_EDGE.get(_pik)
        if _pi is None:
            if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
                raise SystemExit("perimeter pad-input route has no silicon-verified encoding: %s" % (_pik,))
            # Legacy routed JSON may contain generic perimeter InputMUX resources that were never
            # package-constrained. Preserve historical `pack` behavior (the legacy global top-input
            # enable at raw[97].6) and let the generic resolver encode the route; only a physical-PCF
            # build promises and enforces a per-pin silicon characterization.
            pad_input_used.add((_pik, ((97, 64),), ()))
        else:
            _cfg, _sels, _sets, _clears = _pi
            _ok = 0
            for _sel in _sels:
                _bm = cell.get((dx, dy, _cfg, _sel))
                if _bm:
                    route_sets.append(_bm); _ok += 1
            if _ok != len(_sels):
                raise SystemExit("pad-input config cells missing for %s: %s%s" % (_pik, _cfg, _sels))
            pad_input_used.add((_pik, tuple(_sets), tuple(_clears)))
            n_map += 1
            continue
    if sf == "InputMUX" and df == "RMUX" and not (sy in (0, 13) or sx == 0):
        # MCU-edge din ENTRY (INTERIOR InputMUX only, e.g. UFMTILE (11,5)): RMUX selects its InputMUX
        # input via a special MCU-entry pair. A PERIMETER-IOTILE InputMUX (top y=13 / bottom y=0 / left
        # x=0) is a REAL IO-PAD input, NOT the MCU -- its InputMUX->RMUX is an ordinary RMUX source-select
        # (cfg=CFG_RMUX{g}[lo,hi] in rrg_edges_full, source=observed), so it falls through to the general
        # RMUX resolver below. (Right edge x=22 mixes IO pads (22,1-3) with interior muxes -> left as MCU
        # path for now, pending characterization.)
        # Prefer the physical edge's block-clean corpus pair.  The hard-boundary
        # fan-in position is not globally constant: at the AHB rows it is often
        # (2,8), and at x=15 it can be (3,8), while the older GPIO-only fallback
        # is (3,9).  Intercepting these edges before the general resolver and
        # blindly applying the GPIO formula made otherwise exact HWDATA lanes
        # read stuck-high on silicon.
        _entry_key = (dx, dy, "RMUX", di, "InputMUX", sx, sy, si)
        _entry_rel = ("RMUX", di, "InputMUX", si, dx - sx, dy - sy)
        _entry_pair = None if ARCHIVAL_LEGACY else CLEAN_EDGE.get(_entry_key)
        if _entry_pair is None and not ARCHIVAL_LEGACY:
            _entry_pair = REL_EDGE.get(_entry_rel)
        if _entry_pair is not None:
            _block = BS_RMUX * (di % 6)
            _cfg = "CFG_RMUX%d" % (di // 6)
            ent = [(_cfg, _block + _sel) for _sel in _entry_pair]
        else:
            ent = MCU_ENTRY.get((dx, dy, di))   # explicit override, else GPIO-region fallback
            if ent is None:
                cfg, sels = mcu_entry_pair(di); ent = [(cfg, s) for s in sels]
        ok = 0
        for (cfg, sel) in ent:
            k = (dx, dy, cfg, sel)
            if k in cell: route_sets.append(cell[k]); ok += 1
        n_map += 1 if ok else 0
        if not ok:
            n_unmap += 1
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  UNMAPPED[inputmux-entry] %s%d <- %s%d @(%d,%d)" % (df, di, sf, si, dx, dy))
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
    if sf == "OMUX" and df == "OMUX" and (sx, sy) == (dx, dy) and \
            si % 3 == 2 and di == si - 2:
        # Vendor AHB32 buffer route: select the same LUT F on its alternate
        # OMUX[3z+0] mesh output.  The internal pip models the selectable
        # presentation; CFG_OMUX<z>[0] is the complete physical encoding.
        z = di // 3
        bm = cell.get((dx, dy, "CFG_OMUX%d" % z, 0))
        if bm: route_sets.append(bm); n_map += 1
        else: n_unmap += 1
        continue
    if sf == "OMUX" and df == "IMUX" and (sx, sy) == (dx, dy) and di % 4 == 2 and (
            si == 3*(di // 4) + 2 or
            ((sx, sy, di // 4) in _left_vout and si == 3*(di // 4) + 1)):
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
    _pfk = (dx, di, sx, sy, sf, si)
    if df == "RMUX" and _pfk in PADFEED_EXACT:  # package IOTILE pad-feed: exact codeword
        cw = PADFEED_EXACT[_pfk]
        for bm in cw: route_sets.append(tuple(bm))
        n_map += 1                              # counts as mapped even for a zero codeword (default sel)
        if os.environ.get("AGAMEMNON_DEBUG"):
            print("  PADFEED %s%d@(%d,%d) <- %s%d : %d codeword bit(s)" % (df, di, dx, dy, sf, si, len(cw)))
        continue
    if df == "IOMUX" and (dx, dy, di) in io_pad_hops:
        # Final pad hop RMUX{si}->IOMUX{di}: its source-select config is emitted by io_emit above
        # (CFG_IOMUX src-sel), NOT here. Count as mapped so the unmapped tally is truthful.
        n_map += 1
        continue
    if df not in BS:
        n_unmap += 1
        if os.environ.get("AGAMEMNON_DEBUG"):
            print("  UNMAPPED[df-not-in-BS] %s%d <- %s%d @(%d,%d)" % (df, di, sf, si, dx, dy))
        continue
    general[(dx, dy, "CFG_%s%d" % (df, di // NPG[df]), df)].append((di, sf, sx, sy, si))

# each RMUX/IMUX mux GROUP: GROUP_CTX exact bit-pattern (whole group) -> else per-edge fallback
n_gc = n_clean = n_rel = n_abs = n_pred = 0
for (dx, dy, cfg, df), es in general.items():
    # A CFG group is six independent 10-bit RMUX node blocks or four independent
    # 12-bit IMUX node blocks.  When every routed destination node has a
    # block-clean physical pair, composing those disjoint blocks is stronger
    # evidence than GROUP_CTX's 98.9%-deterministic majority for the whole
    # group.  Keep the context table only for mixed/unobserved groups, where it
    # may encode interactions that cannot yet be attributed per edge.
    all_block_clean = not ARCHIVAL_LEGACY and all(
        ((dx, dy, df, di, sf, sx, sy, si) in CLEAN_EDGE
         or (df, di, sf, si, dx - sx, dy - sy) in REL_EDGE)
        for (di, sf, sx, sy, si) in es
    )
    if not all_block_clean:
        _load_legacy_tables()
    gc = None if all_block_clean else GROUP_CTX.get((dx, dy, cfg, frozenset(es)))
    if gc is not None:                          # exact observed pattern for THIS group's edge-set
        for sidx in gc:
            k = (dx, dy, cfg, sidx)
            if k in cell: route_sets.append(cell[k])
        n_map += len(es); n_gc += 1
        continue
    for (di, sf, sx, sy, si) in es:             # fallback: per-edge (observed > closed-form > geom)
        blk = BS[df] * (di % NPG[df])
        edge_key = (dx, dy, df, di, sf, sx, sy, si)
        rel_key = (df, di, sf, si, dx - sx, dy - sy)
        pr = None if ARCHIVAL_LEGACY else CLEAN_EDGE.get(edge_key)
        if pr is not None:
            n_clean += 1
        else:
            pr = None if ARCHIVAL_LEGACY else REL_EDGE.get(rel_key)
            if pr is not None:
                n_rel += 1
            else:
                pr = ABS_LUT.get(edge_key)
                if pr is not None:
                    n_abs += 1
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
        if edge_key not in CLEAN_EDGE and rel_key not in REL_EDGE and edge_key not in ABS_LUT:
            n_pred += 1
        ok = 0
        for ln in pr:
            k = (dx, dy, cfg, blk + ln)
            if k in cell: route_sets.append(cell[k]); ok += 1
        n_map += 1 if ok else 0
print("data pips: %d total, %d mapped (%d groups exact, %d block-clean, %d relative-clean, "
      "%d legacy-abs, %d predicted), "
      "%d unmapped -> %d bits"
      % (len(pips), n_map, n_gc, n_clean, n_rel, n_abs, n_pred, n_unmap, len(route_sets)))
if n_unmap and not os.environ.get("AGAMEMNON_ALLOW_UNMAPPED"):
    raise SystemExit(
        "refusing to emit a partial bitstream: %d routed data PIP(s) have no exact encoding; "
        "set AGAMEMNON_DEBUG=1 to identify them" % n_unmap
    )
if n_pred and os.environ.get("AGAMEMNON_CLEAN_SEL_GATE"):
    raise SystemExit(
        "refusing to emit a selector-uncertain bitstream: %d routed data PIP(s) "
        "needed a legacy or predicted selector encoding" % n_pred
    )

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
for (by, ms) in carry_clears:
    if by < len(raw): raw[by] &= (~ms) & 0xFF
for (by, ms) in io_clears:                    # clear mutually-exclusive baseline I/O selections first
    if by < len(raw): raw[by] &= (~ms) & 0xFF
for (by, ms) in route_clears:                 # clear active BBMUX fields (including idle selectors)
    if by < len(raw): raw[by] &= (~ms) & 0xFF
for (by, ms) in route_sets + lut_sets + clk_sets + io_sets + reg_sets + bram_sets + carry_sets:
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
    # PARAMETRIC PLL clock: overlay the divider bits for a non-default SYSCLK/HSE onto the 100/8
    # baseline blob (pll_emit; byte-exact vs 4 vendor oracles, findings_pll_crack.md). Default
    # (100,8) leaves the proven blob untouched -> zero regression; env override enables other clocks.
    _sys = int(os.environ.get("AGAMEMNON_SYSCLK", "100")); _hse = int(os.environ.get("AGAMEMNON_HSE", "8"))
    if (_sys, _hse) != (100, 8):
        import pll_emit as _PE
        _PE.apply_ratio(raw, _sys, _hse)
        print("parametric CLKGEN SYSCLK=%d HSE=%d [byte-exact ratio]" % (_sys, _hse))
    # HSE clock INPUT enable: CFG_IOMUX11[9] @ IOTILE(22,4) routes the HSE pin into the fabric clock
    # network. Set by every HSE-clock vendor design (regd/cnt/combd), absent from a non-HSE baseline.
    # Isolated by bisection as THE remaining missing clock bit (byte 71737 bit2). Fixed for this
    # board's HSE spec. With this + CLKGEN + per-tile config + the LUT/OMUX residue clear, a clocked
    # design runs on ANY baseline -> fully-open SYSCLK-100 clock, no vendor clocked baseline needed.
    if 71737 < len(raw): raw[71737] |= 0x04
    print("emitted OPEN %dMHz clock (gen preamble + HSE input CFG_IOMUX11[9]@(22,4))" %
          int(os.environ.get("AGAMEMNON_SYSCLK", "100")))
print("registered slices (CFG_OMUX<z> sel=2 set): %d" % len(reg_sets))
def crc32_bzip2(dd):
    c = 0xFFFFFFFF
    for b in dd:
        c ^= b << 24
        for _ in range(8): c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (c & 0x80000000) else (c << 1) & 0xFFFFFFFF
    return c ^ 0xFFFFFFFF
if pad_input_used:
    _set = {_bm for _key, _sets, _clears in pad_input_used for _bm in _sets}
    _clear = {_bm for _key, _sets, _clears in pad_input_used for _bm in _clears}
    for _by, _ms in _clear:
        raw[_by] &= ~_ms
    for _by, _ms in _set:
        raw[_by] |= _ms
    print("pad-input codeword set=%s clear=%s for route(s): %s"
          % (sorted(_set), sorted(_clear), sorted(_key for _key, _sets, _clears in pad_input_used)))
raw[99932:99936] = struct.pack(">I", crc32_bzip2(bytes(hdr) + bytes(raw[:99932])))
out = hdr + L.encode(bytes(raw))
open(OUT, "wb").write(out)
print("wrote %s (%d B); re-decodes to %d B raw" % (OUT, len(out), len(L.decode(out[8:]))))
