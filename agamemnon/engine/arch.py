# nextpnr-generic --pre-pack adapter for the AGM AGRV2K eFPGA (Project AGaMEMnon).
# Builds the nextpnr arch from the validated open chip database:
#   wires.csv          -> every fabric wire (RMUX/IMUX/OMUX/ClkMUX/Seam/IO...)
#   rrg_edges_full.csv -> every routing pip (OMUX->RMUX, RMUX->RMUX, RMUX->IMUX, IO<->fabric)
# LE model (positional, from the recovered structure): each LogicTILE has 16 alta_slice LEs;
#   slice z inputs A,B,C,D = IMUX[4z..4z+3]; outputs LutOut=OMUX[3z], Q=OMUX[3z+1]; clk=ClkMUX[z].
# This is a FUNCTIONAL arch (routes on the real wire/pip graph). Exact pin<->wire indexing for a
# byte-exact bitstream is a refinement; documented as positional here.
import os, csv, json

DATA = os.environ.get("AGAMEMNON_DATA",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chipdb"))
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

# ---- 3c. Grounded LED output pads + clock input for the KITT demo (AGAMEMNON_LEDPADS=1) ----
# The board's 4 LEDs are fabric pads IOTILE(1,4) z0-3, fed by pad-tile RMUX 24/20/0/12 (RE'd from the
# stock blinky). Give each an output IOB bel whose I pin sits on that pad-feed RMUX; bitgen adds the
# final RMUX->pad hop via io_emit. Plus a clock-input bel feeding the GCLK network (bitgen maps the
# clock to the real clk-0 spine from the baseline). Named bels so a --pre-place hook can pin them.
if os.environ.get("AGAMEMNON_LEDPADS"):
    PAD_RMUX = {0: "RMUX24", 1: "RMUX20", 2: "RMUX00", 3: "RMUX12"}   # (1,4) pad-feed RMUX per z
    n_led = 0
    for z, rm in PAD_RMUX.items():
        w = W(1, 4, rm)
        if w in wireset:
            bel = "X1Y4_LED%d" % z
            ctx.addBel(name=bel, type="GENERIC_IOB", loc=Loc(1, 4, 200 + z), gb=False, hidden=False)
            ctx.addBelInput(bel=bel, name="I", wire=w)      # fabric -> pad (via this RMUX)
            n_led += 1
    if ins_all:                                             # clock input -> GCLK network
        (cx, cy), cres = ins_all[0]
        ctx.addBel(name="CLKIN", type="GENERIC_IOB", loc=Loc(1, 4, 220), gb=False, hidden=False)
        ctx.addBelOutput(bel="CLKIN", name="O", wire=W(cx, cy, cres))
    print("AGRV2K arch: added %d LED output pads at (1,4) + CLKIN (KITT demo)" % n_led)

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
n_pip = 0; skipped = 0; dropped_enum = 0; seen_pip = set()
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
        # CORRECTNESS: a routing pip must not pass THROUGH a LUT. IMUX is a slice INPUT (sink only)
        # and OMUX is a slice OUTPUT (source only); an IMUX->x or x->OMUX edge is the LUT's internal
        # function (observed in real designs as logic), NOT a routing wire. Routing to/from a LUT is
        # via the bel's I[]/F/Q pins. Allowing these lets the router thread nets through unconfigured
        # slices -> the bitstream config-accepts but is electrically dead (silicon: dout stuck).
        if fam(r["src_res"]) == "IMUX" or fam(r["dst_res"]) == "OMUX":
            skipped += 1; continue
        # CONTROL NETWORK is not data routing: CtrlMUX/TileSyncMUX/TileAsyncMUX carry FF set/reset/
        # enable + clock-control, encoded (if at all) by the clock/async path -- NOT by the data-pip
        # encoder. If the router threads a DATA net through them, bitgen can't encode it (unmapped ->
        # dead on silicon). Keep them out of the data mesh so data stays in the RMUX/IMUX/OMUX fabric.
        if any(fam(r[k]).endswith(("CtrlMUX", "TileSyncMUX", "TileAsyncMUX")) for k in ("src_res", "dst_res")):
            skipped += 1; continue
        # MCU-edge crossing muxes (BBMUXS/W/E) reachable ONLY via the encodable pips in
        # pips_mcuedge_routing.csv (RMUX19->BBMUXS02); drop harvested BBMUX fan-in so the router can't
        # pick an RMUX->BBMUXS whose sel-encoding we don't have (autonomous route must stay encodable).
        if fam(r["dst_res"]).startswith("BBMUX"):
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
print("AGRV2K arch: added %d pips (%d skipped: endpoint absent; %d dropped: enumerated%s)"
      % (n_pip, skipped, dropped_enum, " [OBSERVED-ONLY]" if OBSERVED_ONLY else ""))

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
