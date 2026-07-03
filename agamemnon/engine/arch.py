# nextpnr-generic --pre-pack adapter for the AGM AGRV2K eFPGA (Project AGaMEMnon).
# Builds the nextpnr arch from the validated open chip database:
#   wires.csv          -> every fabric wire (RMUX/IMUX/OMUX/ClkMUX/Seam/IO...)
#   rrg_edges_full.csv -> every routing pip (OMUX->RMUX, RMUX->RMUX, RMUX->IMUX, IO<->fabric)
# LE model (positional, from the recovered structure): each LogicTILE has 16 alta_slice LEs;
#   slice z inputs A,B,C,D = IMUX[4z..4z+3]; outputs LutOut=OMUX[3z], Q=OMUX[3z+1]; clk=ClkMUX[z].
# This is a FUNCTIONAL arch (routes on the real wire/pip graph). Exact pin<->wire indexing for a
# byte-exact bitstream is a refinement; documented as positional here.
import os, csv, json, re, sys

DATA = os.environ.get("AGAMEMNON_DATA",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chipdb"))

# ---- 0. PACKAGE / DEVICE selection (env AGAMEMNON_DEVICE, default = dev board L48) ----
# One AGRV2K die, 4 QFN packages differing ONLY in bonded perimeter IO pins (device.py). The core
# RMUX/LUT/FF mesh is identical. The package acts here purely as a PIN-NUMBER legality gate: the
# front-end rejects a design that DECLARES a PIN_n the package doesn't bond (device.check_pin). It
# does NOT cap the fabric IOB/pad bels -- precise per-package physical pad restriction needs the
# PIN_n->IOTILE bond map (in af.exe), a documented follow-up; until then all fabric pads are exposed.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import device as _device   # noqa: E402
DEV = _device.device_from_env()
print("AGRV2K arch: DEVICE=%s (%d-pin package, %d bonded user IO pins) [AGAMEMNON_DEVICE]"
      % (DEV.name, DEV.package_pin_count, DEV.user_pin_count))
if _device.MISSING_BOND_MAP:
    print("AGRV2K arch: note -- PIN_n->IOTILE bond map is not in front-end data; package gate is "
          "PIN-NUMBER legality only (device.check_pin); fabric pad bels are NOT package-capped")
K = 4
def W(x, y, res): return "X%sY%s_%s" % (x, y, res)
def fam(res):
    i = len(res)
    while i > 0 and res[i-1].isdigit(): i -= 1
    return res[:i]

# ---- 1. wires ----
wireset = set()
tile_res = {}                    # (x,y) -> {family: [indices...]} for LogicTILE bel binding
tile_type = {}                   # (x,y) -> tile type
n_wire = 0
with open(os.path.join(DATA, "wires.csv")) as f:
    for r in csv.DictReader(f):
        x, y, res, tt = r["x"], r["y"], r["resource"], r["tile"]
        name = W(x, y, res)
        if name in wireset: continue
        ctx.addWire(name=name, type=fam(res), x=int(x), y=int(y))
        wireset.add(name); n_wire += 1
        tile_type[(x, y)] = tt
        tile_res.setdefault((x, y), {}).setdefault(fam(res), []).append(res)
print("AGRV2K arch: added %d wires" % n_wire)

ctx.setLutK(K)

# ---- 2. bels: GENERIC_SLICE per LE on LogicTILEs ----
def has(x, y, res): return W(x, y, res) in wireset
n_slice = 0
clk_wires = []                   # every slice CLK wire, for the global-clock taps
for (x, y), tt in tile_type.items():
    if tt != "LogicTILE": continue
    for z in range(16):
        ia = ["IMUX%02d" % (4*z + i) for i in range(4)]
        # slice routed output = OMUX[3z+2] for BOTH comb (F) and registered (Q): the slice has one
        # mesh output, comb-or-registered selected by CFG_OMUX<z> sel=2 (proven byte-exact vs the
        # regd/combd/cnt vendor oracles -- findings_regsel.md; bitgen sets it for registered slices).
        # F and Q are mutually exclusive per slice (yosys packs one LUT + optionally one DFF), so they
        # share the wire. OMUX[3z+1] is LOCAL feedback only; OMUX[3z+0] is the slice's OTHER routable
        # mesh output (we route FF Q on [3z+2] only, so CFG_OMUX<z> sel=2 is the complete rule).
        f_o, q_o, clk = "OMUX%02d" % (3*z + 2), "OMUX%02d" % (3*z + 2), "ClkMUX%02d" % z
        if not all(has(x, y, w) for w in ia + [f_o, q_o, clk]): continue
        bel = "X%sY%s_SLICE%d" % (x, y, z)
        ctx.addBel(name=bel, type="GENERIC_SLICE", loc=Loc(int(x), int(y), z), gb=False, hidden=False)
        ctx.addBelInput(bel=bel, name="CLK", wire=W(x, y, clk))
        for i in range(K):
            ctx.addBelInput(bel=bel, name="I[%d]" % i, wire=W(x, y, ia[i]))
        ctx.addBelOutput(bel=bel, name="F", wire=W(x, y, f_o))
        ctx.addBelOutput(bel=bel, name="Q", wire=W(x, y, q_o))
        clk_wires.append(W(x, y, clk))
        n_slice += 1
print("AGRV2K arch: added %d GENERIC_SLICE bels" % n_slice)

# ---- 3. bels: GENERIC_IOB only where the IO wire is actually connected to the fabric ----
# Pre-scan the RRG: InputMUX wires that drive the fabric (src), IOMUX wires the fabric drives (dst).
in_conn = {}    # (x,y) -> [InputMUX res ...]  (pad -> fabric capable)
out_conn = {}   # (x,y) -> [IOMUX res ...]     (fabric -> pad capable)
with open(os.path.join(DATA, "rrg_edges_full.csv")) as f:
    for r in csv.DictReader(f):
        if r["src_res"].startswith("InputMUX"):
            in_conn.setdefault((r["src_x"], r["src_y"]), set()).add(r["src_res"])
        if r["dst_res"].startswith("IOMUX"):
            out_conn.setdefault((r["dst_x"], r["dst_y"]), set()).add(r["dst_res"])
n_io = 0
# Fully-capable IOBs: bind O to a fabric-driving InputMUX and I to a fabric-driven IOMUX. To reach
# enough IOBs for real designs, pair across all connected tiles (an IOB's two pins need not share a
# tile for a functional route — each is independently fabric-connected).
ins_all = sorted((xy, r) for xy, s in in_conn.items() for r in s)
outs_all = sorted((xy, r) for xy, s in out_conn.items() for r in s)
# PACKAGE LEGALITY is a PIN-NUMBER gate (check_design_pins vs CHIP_INFO), NOT a fabric-bel cap:
# the package selects which EXTERNAL pins are bonded, not how many internal IOB/pad bels the router
# may use. Capping fabric bels by user_pin_count starved routing (and is wrong anyway without the
# PIN_n->IOTILE pad bond map, which lives in af.exe -- a documented follow-up). So expose ALL fabric
# IOBs regardless of package; the package gate acts at the pin-DECLARATION level (device.check_pin).
for z in range(min(len(ins_all), len(outs_all))):
    (ix, iy), ires = ins_all[z]
    (ox, oy), ores = outs_all[z]
    bel = "X%sY%s_IO%d" % (ix, iy, z)
    ctx.addBel(name=bel, type="GENERIC_IOB", loc=Loc(int(ix), int(iy), z), gb=False, hidden=False)
    ctx.addBelOutput(bel=bel, name="O", wire=W(ix, iy, ires))   # pad -> fabric
    ctx.addBelInput(bel=bel, name="I", wire=W(ox, oy, ores))    # fabric -> pad
    n_io += 1
print("AGRV2K arch: added %d fully-capable GENERIC_IOB bels (%d in-conn, %d out-conn)"
      % (n_io, len(ins_all), len(outs_all)))

# ---- 3c. Ring-pad OUTPUT bels (GENERAL, from chipdb/io_pads.csv) + clock input (AGAMEMNON_LEDPADS) ----
# Every ring pad is driven by the fabric through the observed chain
#     fabric -> IOTILE.RMUX{R} -> IOMUX{z} -> pad
# where the fabric->RMUX{R} feeder carries a real CFG_RMUX source-select and the RMUX{R}->IOMUX{z} hop
# is a fixed (cfg-less) observed edge. We give each pad an OUTPUT IOB bel whose I pin sits on the real
# IOMUX{z} pad wire, so nextpnr routes the WHOLE conducting chain and bitgen emits the feeder's
# CFG_RMUX from the route (+ the IOMUX driver via io_emit). This is the general pad-output path for
# EVERY IOTILE/pad -- no hardcoded per-board pad list. (The old KITT bel pinned a LogicTile RMUX wire
# that has no RRG edge to the pad, so the signal never reached silicon.) Bels: X{x}Y{y}_OPAD{z}; a
# --pre-place hook (pin_leds.py) pins design LEDs onto the board's IOTILE(0,4) pads.
if os.environ.get("AGAMEMNON_LEDPADS"):
    n_pad = 0
    # Expose EVERY ring pad as an OUTPUT bel from the full corpus io_pads.csv. Package selection does
    # NOT prune fabric pads here: per-package physical pad restriction needs the PIN_n->IOTILE pad
    # bond map (in af.exe -- a documented follow-up), so io_pads_<DEVICE>.csv is kept only as an
    # informational artifact and is NOT used to cap the router's pad bels.
    with open(os.path.join(DATA, "io_pads.csv")) as _f:
        for r in csv.DictReader(_f):
            ix, iy, z = r["x"], r["y"], int(r["iomux"])
            w = W(ix, iy, "IOMUX%02d" % z)
            if w not in wireset:
                continue
            bel = "X%sY%s_OPAD%d" % (ix, iy, z)
            ctx.addBel(name=bel, type="GENERIC_IOB", loc=Loc(int(ix), int(iy), 100 + z), gb=False, hidden=False)
            ctx.addBelInput(bel=bel, name="I", wire=w)      # fabric -> pad (via IOMUX{z}, real pad wire)
            n_pad += 1
    if ins_all:                                             # clock input -> GCLK network
        (cx, cy), cres = ins_all[0]
        ctx.addBel(name="CLKIN", type="GENERIC_IOB", loc=Loc(1, 4, 220), gb=False, hidden=False)
        ctx.addBelOutput(bel="CLKIN", name="O", wire=W(cx, cy, cres))
    print("AGRV2K arch: added %d ring-pad OUTPUT bels (IOMUX pad wires) + CLKIN" % n_pad)

# ---- 3b. global clock network ----
# The AGRV2K clock is a dedicated tree (GCLK source -> spine -> per-tile TileClkMUX -> slice CLK),
# NOT general routing. Model it as 8 global-clock nets (LogicTILE TileClkMUX is 8-wide = 8 globals):
# any clock IOB can drive any global; any global can reach any slice CLK (the per-tile TileClkMUX[g]
# select). This lets nextpnr route clock nets so SEQUENTIAL designs place&route. The GCLK->sliceCLK
# pip maps in bitgen to CFG_TILECLKMUX[g] on that slice's tile.
NGCLK = 1   # constrain to global clock 0 (the spine we've characterized) for fully-open bitgen
for g in range(NGCLK):
    ctx.addWire(name="GCLK%d" % g, type="GLOBAL_CLK", x=0, y=0)
dclk = ctx.getDelayFromNS(0.05)
n_gpip = 0
for (ix, iy), ires in ins_all:                      # clock source: any IOB pad->fabric input
    src = W(ix, iy, ires)
    for g in range(NGCLK):
        ctx.addPip(name="%s.GCLK%d" % (src, g), type="GCLK_SRC",
                   srcWire=src, dstWire="GCLK%d" % g, delay=dclk, loc=Loc(0, 0, 0))
        n_gpip += 1
for cw in clk_wires:                                # distribution: global -> every slice CLK
    for g in range(NGCLK):
        ctx.addPip(name="GCLK%d.%s" % (g, cw), type="GCLK_TAP",
                   srcWire="GCLK%d" % g, dstWire=cw, delay=dclk, loc=Loc(0, 0, 0))
        n_gpip += 1
print("AGRV2K arch: added %d global-clock nets + %d clock pips" % (NGCLK, n_gpip))

# ---- 4. pips: every routing edge (RRG mesh + completed OMUX->IMUX crossbar) ----
# rrg_edges_full.csv     = enumerated RMUX mesh + observed intra-tile edges.
# rrg_omux_imux_full.csv = the intra-tile OMUX->IMUX LUT-feedback crossbar completed by cross-tile
#   union + replication (complete_omux_imux.py). This fills the dense-routing gap: the observed-only
#   crossbar had 6..110 of the 536 tile-invariant template edges per tile; now every LogicTILE gets
#   the full 536. Dedup by pip name (observed edges appear in both files).
# AGAMEMNON_OBSERVED_ONLY=1 restricts routing to OBSERVED edges (real vendor-router connections,
# gold-standard: physically real + sel-encoding in the training set). Enumerated edges are only
# ~94% byte-validated and include non-physical inferences — on silicon a route through them
# config-accepts but does not electrically connect. Observed-only trades coverage for correctness.
# AGAMEMNON_TRUE_TOPO=1 replaces the enumerated rrg_edges_full.csv with rrg_edges_true.csv, the
# TRUE physical topology harvested from the vendor router's own routed designs (decoded route.tx
# path blocks) unioned with the prior observed edges. Every edge is a real vendor-router hop, so a
# route composed from them physically propagates on silicon (fixes the din-never-reaches-LUT bug
# whose root cause was non-physical ENUMERATED edges). =2 also loads the tile-invariant replicated
# set (rrg_edges_true_repl.csv) for extra coverage if real-only is too sparse to route.
# AGAMEMNON_EDGE_BLACKLIST: exclude specific enumerated pips proven NON-CONDUCTING on silicon so
# nextpnr reroutes around them (e.g. RMUX26@(14,4)->RMUX19@(10,4), the +x/right feed into the MCU
# dout exit RMUX that config-accepts but is electrically dead, while RMUX74@(6,4)->RMUX19@(10,4)
# from the left conducts). Format: a list of "<src_res>@<sx>,<sy>-><dst_res>@<dx>,<dy>" edges,
# separated by comma and/or semicolon (edge coords contain commas, so the parse extracts each edge
# by pattern rather than splitting). OFF by default (empty set) -> the pip graph is unchanged.
# Matched on the raw CSV endpoint fields (res+x+y both ends) in every edge loop below.
EDGE_BLACKLIST = set(re.findall(
    r"(\w+)@(-?\d+),(-?\d+)\s*->\s*(\w+)@(-?\d+),(-?\d+)",
    os.environ.get("AGAMEMNON_EDGE_BLACKLIST", "")))
if EDGE_BLACKLIST:
    print("AGRV2K arch: EDGE BLACKLIST active (%d edge(s)): %s"
          % (len(EDGE_BLACKLIST), sorted(EDGE_BLACKLIST)))
def _blacklisted(r):
    return (r["src_res"], r["src_x"], r["src_y"],
            r["dst_res"], r["dst_x"], r["dst_y"]) in EDGE_BLACKLIST

# ---- EXIT-FEEDER WHITELIST (silicon-validated far-routing fix) --------------------------------
# The 4 forced MCU-dout exit RMUX nodes @ LogicTILE(10,4) (RMUX09/RMUX19/RMUX32/RMUX02 -> GPIO4
# bits 0/2/4/6) have MOST of their enumerated in-edges electrically DEAD on silicon even though the
# bitstream config-accepts; only a per-node set of feeders actually conducts (proven by per-feeder
# isolation bins read back on GPIO4). We restrict the IN-edges of ONLY these 4 dst nodes to the
# whitelisted live feeders, so nextpnr is forced to route a far-tile toggle out through a conducting
# feeder. The "top-1 rule" is REFUTED (RMUX32 conducts from a right/self feed, not a westward RMUX74
# tap), so this is an explicit per-node whitelist, not a global rule. Loaded from
# chipdb/exit_feeder_whitelist.csv; every OTHER node in the fabric is untouched. Set
# AGAMEMNON_NO_EXIT_WL=1 to disable (e.g. to reproduce the old dead-feeder behavior).
EXIT_WL = {}    # (dst_res,dst_x,dst_y) -> set of (src_res,src_x,src_y) live feeders
if not os.environ.get("AGAMEMNON_NO_EXIT_WL"):
    _wl = os.path.join(DATA, "exit_feeder_whitelist.csv")
    if os.path.exists(_wl):
        for r in csv.DictReader(open(_wl)):
            EXIT_WL.setdefault((r["dst_res"], r["dst_x"], r["dst_y"]), set()).add(
                (r["src_res"], r["src_x"], r["src_y"]))
        print("AGRV2K arch: EXIT-FEEDER WHITELIST active for %d exit node(s): %s"
              % (len(EXIT_WL), sorted(EXIT_WL)))
def _exit_pruned(r):
    """True if r is an in-edge to a whitelisted exit node that is NOT a listed live feeder."""
    dst = (r["dst_res"], r["dst_x"], r["dst_y"])
    if dst not in EXIT_WL:
        return False
    return (r["src_res"], r["src_x"], r["src_y"]) not in EXIT_WL[dst]

TRUE_TOPO = os.environ.get("AGAMEMNON_TRUE_TOPO")
OBSERVED_ONLY = os.environ.get("AGAMEMNON_OBSERVED_ONLY")
TRUSTED = os.environ.get("AGAMEMNON_TRUSTED")   # observed + closed-form-validated enumerated classes
def is_trusted(r, fn):
    if r.get("source") == "observed":
        return True                              # real vendor-router edge
    if fn == "rrg_omux_imux_full.csv":
        return True                              # OMUX->IMUX crossbar, tile-invariant validated
    if fam(r["src_res"]) == "OMUX" and fam(r["dst_res"]) == "RMUX":
        return True                              # RMUX<-OMUX is closed-form (100%)
    return False                                 # enumerated RMUX->RMUX / RMUX->IMUX guesses (~94-97%)
n_pip = 0; skipped = 0; dropped_enum = 0; exit_pruned = 0; seen_pip = set()
d = ctx.getDelayFromNS(0.1)
if TRUE_TOPO:
    _base = "rrg_edges_true_repl.csv" if TRUE_TOPO == "2" else "rrg_edges_true.csv"
    edge_files = (_base, "rrg_omux_imux_full.csv")
    print("AGRV2K arch: TRUE-TOPO mode -> loading %s" % _base)
else:
    edge_files = ("rrg_edges_full.csv", "rrg_omux_imux_full.csv")
for fn in edge_files:
    path = os.path.join(DATA, fn)
    if not os.path.exists(path):
        continue
    for r in csv.DictReader(open(path)):
        # BLACKLIST: drop specific non-conducting edges (AGAMEMNON_EDGE_BLACKLIST) so the router
        # reroutes around them. No-op when the env var is unset.
        if EDGE_BLACKLIST and _blacklisted(r):
            skipped += 1; continue
        # EXIT-FEEDER WHITELIST: for the 4 forced MCU-dout exit RMUX nodes, drop every in-edge that
        # is not a silicon-confirmed live feeder (guarded: only those dst nodes are affected).
        if EXIT_WL and _exit_pruned(r):
            exit_pruned += 1; continue
        # CORRECTNESS: a routing pip must not pass THROUGH a LUT. IMUX is a slice INPUT (sink only)
        # and OMUX is a slice OUTPUT (source only); an IMUX->x or x->OMUX edge is the LUT's internal
        # function (observed in real designs as logic), NOT a routing wire. Routing to/from a LUT is
        # via the bel's I[]/F/Q pins. Allowing these lets the router thread nets through unconfigured
        # slices -> the bitstream config-accepts but is electrically dead (silicon: dout stuck).
        if fam(r["src_res"]) == "IMUX" or fam(r["dst_res"]) == "OMUX":
            skipped += 1; continue
        # CONTROL/CLOCK/ASYNC NETWORK is not data routing: CtrlMUX/TileSyncMUX/TileAsyncMUX carry FF
        # set/reset/enable + clock-control, and AsyncMUX/ClkMUX/SeamMUX (incl. TileClkMUX) are the
        # async-set/reset + clock-tree muxes -- all encoded (if at all) by the clock/async path, NOT by
        # the data-pip encoder. If the router threads a DATA net through them the bitstream config-
        # accepts but the hop is electrically DEAD on silicon (a cause of dout-stuck). Keep them out of
        # the data mesh so data stays in the RMUX/IMUX/OMUX fabric. NOTE: the clock TREE is modeled
        # SEPARATELY (global-clock nets + GCLK_SRC/GCLK_TAP pips in section 3b; bitgen emits
        # CFG_SEAMMUX/CFG_TILECLKMUX independently), so dropping these here does NOT remove the clock
        # model -- the slice CLK wire (ClkMUX%02d) is still reached via the GCLK_TAP pips.
        if any(fam(r[k]).endswith(("CtrlMUX", "TileSyncMUX", "TileAsyncMUX",
                                   "AsyncMUX", "ClkMUX", "SeamMUX")) for k in ("src_res", "dst_res")):
            skipped += 1; continue
        # MCU-edge crossing muxes (BBMUXS/W/E) reachable ONLY via the encodable pips in
        # pips_mcuedge_routing.csv (RMUX19->BBMUXS02); drop harvested BBMUX fan-in so the router can't
        # pick an RMUX->BBMUXS whose sel-encoding we don't have (autonomous route must stay encodable).
        if fam(r["dst_res"]).startswith("BBMUX"):
            skipped += 1; continue
        # HARDEN pad-feed (LED builds): only an OBSERVED edge may drive an IOTILE pad-feed RMUX. The
        # enumerated fan-in sels into the pad tile (0,4) config-accept but do NOT conduct on silicon
        # (LEDs stay dark); the interior of the design still routes on the full mesh. This forces the
        # LED nets through the real vendor-router (4,4)->(0,4) feeder edges (whose harvested sels bitgen
        # reproduces via ABS_LUT), which is the whole point of "hardening the feeder sels".
        if os.environ.get("AGAMEMNON_HARDEN_PADFEED") and r["dst_tile"] == "IOTILE" \
           and fam(r["dst_res"]) == "RMUX" and r.get("source") != "observed":
            skipped += 1; continue
        # AGAMEMNON_MCU_ENTRY: force the din ENTRY through the encodable pips_mcuedge chain
        # (BufMUX10->InputMUX11->RMUX93) by dropping harvested BufMUX/InputMUX fan-out. Guarded so it
        # only applies to the MCU-edge loopback flow (general IO designs still need InputMUX edges).
        if os.environ.get("AGAMEMNON_MCU_ENTRY") and \
           (fam(r["src_res"]).startswith("BufMUX") or fam(r["src_res"]).startswith("InputMUX")):
            skipped += 1; continue
        # AGAMEMNON_NO_INTRA_RMUX: drop intra-tile RMUX->RMUX (a signal hopping RMUX->RMUX inside one
        # tile is the enumerated class most prone to wrong sel-bits); forces inter-tile physical wires.
        if os.environ.get("AGAMEMNON_NO_INTRA_RMUX") and r["src_x"] == r["dst_x"] and \
           r["src_y"] == r["dst_y"] and fam(r["src_res"]) == "RMUX" and fam(r["dst_res"]) == "RMUX":
            skipped += 1; continue
        # AGAMEMNON_OBS_IMUX: LUT-input crossbar (x->IMUX) only from OBSERVED edges — the RMUX->IMUX
        # sel-encoding is table-coverage-limited, so enumerated guesses drop the signal before the LUT.
        if os.environ.get("AGAMEMNON_OBS_IMUX") and fam(r["dst_res"]) == "IMUX" \
           and fn == "rrg_edges_full.csv" and r.get("source") != "observed":
            skipped += 1; continue
        if OBSERVED_ONLY and r.get("source") != "observed":
            dropped_enum += 1; continue
        if TRUSTED and not is_trusted(r, fn):
            dropped_enum += 1; continue
        s = W(r["src_x"], r["src_y"], r["src_res"])
        t = W(r["dst_x"], r["dst_y"], r["dst_res"])
        if s not in wireset or t not in wireset:
            skipped += 1; continue
        nm = "%s.%s" % (s, t)
        if nm in seen_pip:
            continue
        ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                   delay=d, loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
        seen_pip.add(nm); n_pip += 1
print("AGRV2K arch: added %d pips (%d skipped: endpoint absent; %d dropped: enumerated%s; "
      "%d exit in-edges pruned by whitelist)"
      % (n_pip, skipped, dropped_enum, " [OBSERVED-ONLY]" if OBSERVED_ONLY else "", exit_pruned))

# ---- 5. MCU-edge routing pips (UFMTILE boundary the RRG does not enumerate) ----
# rrg_edges_full.csv is LogicTile-only; it has NO UFMTILE MCU-edge routing. These pips come from
# the silicon-validated vendor loopback (loopback/logic_db/route.tx, net #13 gpio4_io_out_data[1]):
#   MCU(alta_rv3200@0,5) -> BufMUX10 -> InputMUX11 @UFMTILE(11,5)   (din enters the fabric)
#   -> RMUX93@LogicTILE(11,4) -> RMUX92@LogicTILE(10,4)             (already in the RRG mesh)
#   -> BBMUXS02@UFMTILE(10,5) -> SinkMUXPseudo143@UFMTILE(0,5) -> MCU  (dout returns to the MCU)
# We load them here as ROUTE pips so the router can cross the MCU edge. The two alta_rv3200
# self-edges are represented by the MCU bel pin binding (below), not as router pips.
bit_entry = {}                   # bit -> fabric-entry wire the MCU DRIVES (bel-out target)
bit_exit  = {}                   # bit -> fabric-exit wire that FEEDS the MCU (bel-in source)
n_mpip = 0; m_skip = 0
mcuedge_csv = os.path.join(DATA, "pips_mcuedge_routing.csv")
if os.path.exists(mcuedge_csv):
    with open(mcuedge_csv) as f:
        for r in csv.DictReader(f):
            if EDGE_BLACKLIST and _blacklisted(r):   # honor the blacklist on the MCU edge too
                m_skip += 1; continue
            bit = int(r.get("bit") or 0)          # per-GPIO-bit MCU edge (multi-signal); default 0
            s_is_mcu = r["src_res"].startswith("alta_rv")
            t_is_mcu = r["dst_res"].startswith("alta_rv")
            s = W(r["src_x"], r["src_y"], r["src_res"])
            t = W(r["dst_x"], r["dst_y"], r["dst_res"])
            if s_is_mcu:            # MCU -> fabric-entry wire: record entry wire, no pip
                if t in wireset: bit_entry[bit] = t
                continue
            if t_is_mcu:            # fabric-exit wire -> MCU: record exit wire, no pip
                if s in wireset: bit_exit[bit] = s
                continue
            if s not in wireset or t not in wireset:
                m_skip += 1; continue
            nm = "%s.%s" % (s, t)
            if nm in seen_pip:      # TRUE-TOPO union may already carry this MCU-edge hop
                continue
            ctx.addPip(name=nm, type="MCUEDGE", srcWire=s, dstWire=t,
                       delay=d, loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
            seen_pip.add(nm); n_mpip += 1
    print("AGRV2K arch: added %d MCU-edge pips (%d skipped); bits=%s"
          % (n_mpip, m_skip, sorted(set(bit_entry) & set(bit_exit))))

# ---- 6. alta_mcu bels: one MCU bel PER GPIO bit at the MCU location (UFMTILE 0,5) ----
# Each GPIO bit crosses the MCU<->fabric edge on its OWN wires (harvested from the vendor route.tx of
# the loopback + lutmcu oracles): DIN = the fabric-entry BufMUX wire the MCU drives; DOUT = the
# fabric-exit SinkMUXPseudo wire the MCU reads. The router threads MCU-out -> fabric LUT -> MCU-in
# for each bit independently. One MCU cell in the netlist per bit; nextpnr places each on its bel.
# Placed at UFMTILE(10,5) distinguished by z=bit (the fabric-crossing corner where entry/exit muxes
# live -> keeps the LUT local, route short, sel-encoding errors few). Bit 0 = the proven single-bit
# path (GPIO4_1/2, RMUX93/RMUX19/BBMUXS02); bit 1 = GPIO4_3/4, RMUX17/RMUX02/BBMUXS04.
MCUX, MCUY = 10, 5
n_mbel = 0
# A "bit" with BOTH entry+exit is a GPIO loopback pin (type MCU, DIN+DOUT). A bit with only an entry
# is an MCU->fabric bus INPUT (type MCU_DIN, e.g. an AHB signal hwdata/hwrite/htrans); with only an
# exit it's a fabric->MCU OUTPUT (type MCU_DOUT, e.g. GPIO observability or hrdata). This lets the AHB
# slave model many MCU-driven bus inputs + a readback, not just DIN/DOUT pairs.
for bit in sorted(set(bit_entry) | set(bit_exit)):
    has_e = bit in bit_entry; has_x = bit in bit_exit
    typ = "MCU" if (has_e and has_x) else ("MCU_DIN" if has_e else "MCU_DOUT")
    mcubel = "X%dY%d_%s%d" % (MCUX, MCUY, typ, bit)
    ctx.addBel(name=mcubel, type=typ, loc=Loc(MCUX, MCUY, bit), gb=False, hidden=False)
    if has_e: ctx.addBelOutput(bel=mcubel, name="DIN",  wire=bit_entry[bit])   # MCU -> fabric
    if has_x: ctx.addBelInput (bel=mcubel, name="DOUT", wire=bit_exit[bit])    # fabric -> MCU
    print("AGRV2K arch: %s bel %s  DIN->%s  DOUT<-%s"
          % (typ, mcubel, bit_entry.get(bit, "-"), bit_exit.get(bit, "-")))
    n_mbel += 1
if n_mbel == 0:
    print("AGRV2K arch: no MCU bels added (entry/exit wires absent)")

# ---- API probe (AGAMEMNON_PROBE=1) ----
if os.environ.get("AGAMEMNON_PROBE"):
    try:
        for c in ctx.cells:
            print("PROBE cell:", repr(c), type(c).__name__)
    except Exception as e:
        print("PROBE iterate cells ERR:", repr(e))
    print("PROBE bindBel doc:", getattr(ctx.bindBel, "__doc__", None))
    try:
        print("PROBE X10Y4_SLICE0 avail:", ctx.checkBelAvail("X10Y4_SLICE0"))
    except Exception as e:
        print("PROBE checkBelAvail ERR:", repr(e))
