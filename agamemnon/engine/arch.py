# nextpnr-generic --pre-pack adapter for the AGM AGRV2K eFPGA (Project AGaMEMnon).
# Builds the nextpnr arch from the validated open chip database:
#   wires.csv          -> every fabric wire (RMUX/IMUX/OMUX/ClkMUX/Seam/IO...)
#   rrg_edges_full.csv -> every routing pip (OMUX->RMUX, RMUX->RMUX, RMUX->IMUX, IO<->fabric)
# LE model (positional, from the recovered structure): each LogicTILE has 16 alta_slice LEs;
#   slice z inputs A,B,C,D = IMUX[4z..4z+3]; outputs LutOut=OMUX[3z], Q=OMUX[3z+1]; clk=ClkMUX[z].
# This is a FUNCTIONAL arch (routes on the real wire/pip graph). Exact pin<->wire indexing for a
# byte-exact bitstream is a refinement; documented as positional here.
import os, csv, json, re, sys, collections

def build_arch(ctx, Loc, environ=None):

    _ENGINE = os.path.dirname(os.path.abspath(__file__))
    from agamemnon.engine.registry import CONSTANTS, options_from

    OPTIONS = options_from(environ)
    DATA = OPTIONS.raw("AGAMEMNON_DATA",
        os.path.join(_ENGINE, "..", "chipdb"))

    # ---- 0. PACKAGE / DEVICE selection (env AGAMEMNON_DEVICE, default = dev board L48) ----
    # One AGRV2K fabric is offered in four packages. The core RMUX/LUT/FF mesh is
    # shared; legal package pins and PIN_n->IOTILE coordinates come from the
    # selected package's recovered bond map. L48 is silicon-qualified, while
    # L100/L64/Q32 builds retain an explicit unqualified-map warning.
    from agamemnon.engine import device as _device
    DEV = _device.get_device(OPTIONS.raw("AGAMEMNON_DEVICE"))
    print("AGRV2K arch: DEVICE=%s (%d-pin package, %d bonded user IO pins) [AGAMEMNON_DEVICE]"
          % (DEV.name, DEV.package_pin_count, DEV.user_pin_count))
    if not DEV.bond_map:
        print("AGRV2K arch: note -- selected package has no PIN_n->IOTILE bond map; "
              "physical package IO cannot be exposed")
    K = CONSTANTS["lut_inputs"].value
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
    # AGAMEMNON_VENDOR_OUT_SLICE="x,y,z": a VENDOR-FAITHFUL output slice. Our default model routes the
    # slice output on OMUX[3z+2] (CFG_OMUX sel=2). But the vendor's silicon-conducting routes to the
    # top-row IO pads ALL originate from the LUT-output wire OMUX[3z+0] (e.g. OMUX42 @slice14) with the
    # FF feedback on OMUX[3z+1] (e.g. OMUX43->IMUX57, a direct intra-tile crossbar self-loop). For this
    # ONE slice we therefore bind F (LUT comb out) -> OMUX[3z+0] (drives the vendor pad chain) and
    # Q (DFF) -> OMUX[3z+1] (the clean intra-tile feedback wire), matching the vendor bit-for-bit
    # (bitgen emits CFG_OMUX<z> sels {0,1}). Design must use `assign o=~q` so F drives the pad and Q the
    # feedback. Every OTHER slice is unchanged (zero regression when the env var is unset).
    _VOUT = OPTIONS.raw("AGAMEMNON_VENDOR_OUT_SLICE")
    _VOUT = OPTIONS.coordinates("AGAMEMNON_VENDOR_OUT_SLICE") if _VOUT else None
    _VOUT_ALL = OPTIONS.enabled("AGAMEMNON_VENDOR_OUT_ALL")
    _LEFT_VOUT = (set(CONSTANTS["left_vendor_slices"].value)
                  if OPTIONS.enabled("AGAMEMNON_LEFT_PAD_OUT") else set())
    # The simultaneous dynamic-ClkEn1 Port-B oracle uses alternate presentation
    # sel=0 for four reserved address-source slots.  The BRAM pin packer locks only
    # the matching drivers here and tags their selected OMUX for bitgen.  Expose
    # those physical wires so routing follows the conflict-free vendor path.
    _BRAM_QSEL = (dict(CONSTANTS["bram_portb_qsel"].value)
                  if OPTIONS.enabled("AGAMEMNON_BRAM_PORTB_EXIT") else {})
    # The vendor can present one LUT value on both OMUX[3z+0] and the default
    # OMUX[3z+2]. Model the proven constant safe-idle case behind an explicit
    # coordinate option; this does not claim a general dual-output LUT.
    _DUAL_CONST = OPTIONS.raw("AGAMEMNON_DUAL_LUT_CONST")
    _DUAL_CONST = (OPTIONS.coordinates("AGAMEMNON_DUAL_LUT_CONST")
                   if _DUAL_CONST else None)
    if _VOUT_ALL:
        print("AGRV2K arch: VENDOR-OUT enabled for every slice (F=OMUX[3z], Q=OMUX[3z+1])")
    elif _VOUT:
        print("AGRV2K arch: VENDOR-OUT slice %s -> F on OMUX[3z+0], Q on OMUX[3z+1]" % (_VOUT,))
    n_slice = 0
    clk_wires = []                   # every slice CLK wire, for the global-clock taps
    slice_bels = {}                  # (x,y) -> {z: bel}  (for the HW-carry chain, below)
    for (x, y), tt in tile_type.items():
        if tt != "LogicTILE": continue
        for z in range(16):
            ia = ["IMUX%02d" % (4*z + i) for i in range(4)]
            if _DUAL_CONST == (int(x), int(y), z):
                _o0, _o2 = "OMUX%02d" % (3*z), "OMUX%02d" % (3*z + 2)
                if not all(has(x, y, w) for w in (_o0, _o2)):
                    continue
                bel = "X%sY%s_DUAL_SLICE%d" % (x, y, z)
                ctx.addBel(name=bel, type="AGRV2K_DUAL_LUT_CONST",
                           loc=Loc(int(x), int(y), z), gb=False, hidden=False)
                ctx.addBelOutput(bel=bel, name="F0", wire=W(x, y, _o0))
                ctx.addBelOutput(bel=bel, name="F2", wire=W(x, y, _o2))
                n_slice += 1
                continue
            # slice routed output = OMUX[3z+2] for BOTH comb (F) and registered (Q): the slice has one
            # mesh output, comb-or-registered selected by CFG_OMUX<z> sel=2 (proven byte-exact vs the
            # regd/combd/cnt vendor oracles -- findings_regsel.md; bitgen sets it for registered slices).
            # F and Q are mutually exclusive per slice (yosys packs one LUT + optionally one DFF), so they
            # share the wire. OMUX[3z+1] is LOCAL feedback only; OMUX[3z+0] is the slice's OTHER routable
            # mesh output (we route FF Q on [3z+2] only, so CFG_OMUX<z> sel=2 is the complete rule).
            f_o, q_o, clk = "OMUX%02d" % (3*z + 2), "OMUX%02d" % (3*z + 2), "ClkMUX%02d" % z
            if (int(x), int(y), z) in _BRAM_QSEL:
                f_o = q_o = "OMUX%02d" % (3*z + _BRAM_QSEL[(int(x), int(y), z)])
            if _VOUT_ALL or _VOUT == (int(x), int(y), z) or (int(x), int(y), z) in _LEFT_VOUT:
                # vendor-faithful: F->OMUX[3z+0], Q->OMUX[3z+1]
                f_o, q_o = "OMUX%02d" % (3*z + 0), "OMUX%02d" % (3*z + 1)
            if not all(has(x, y, w) for w in ia + [f_o, q_o, clk]): continue
            bel = "X%sY%s_SLICE%d" % (x, y, z)
            ctx.addBel(name=bel, type="GENERIC_SLICE", loc=Loc(int(x), int(y), z), gb=False, hidden=False)
            ctx.addBelInput(bel=bel, name="CLK", wire=W(x, y, clk))
            for i in range(K):
                ctx.addBelInput(bel=bel, name="I[%d]" % i, wire=W(x, y, ia[i]))
            ctx.addBelOutput(bel=bel, name="F", wire=W(x, y, f_o))
            ctx.addBelOutput(bel=bel, name="Q", wire=W(x, y, q_o))
            clk_wires.append(W(x, y, clk))
            slice_bels.setdefault((int(x), int(y)), {})[z] = bel
            n_slice += 1
    print("AGRV2K arch: added %d GENERIC_SLICE bels" % n_slice)

    # ---- 2b. HW-CARRY (AGAMEMNON_HW_CARRY=1): the dedicated intra-tile Cin/Cout carry chain -----------
    # 2026-07-06: dense LUT-carry (routed through the OMUX->IMUX crossbar) depth-limits at ~4 bits on silicon
    # (structural, NOT coverage -- proven at 543/544 coverage). The vendor packs deep counters via the slice's
    # DEDICATED hardware carry (alta_slice mode="ripple", modeMux=1 -> pinC=Cin, Cin/Cout chained slice-to-
    # slice; cnt8 = 9-slice chain in one tile). There are NO fabric carry WIRES (carry is internal hardware),
    # so we model SYNTHETIC per-slice Cin/Cout wires + fixed intra-tile carry pips COUT<z>->CIN<z+1>. The
    # synthetic-wire trick forces nextpnr to place a carry chain on the vendor-observed site order, matching
    # the hardware. bitgen emits the ripple config for cells that use CIN/COUT (HW-Carry 3).  The only exposed
    # inter-tile continuations are the three transitions present in independent vendor 16/24/32-bit oracles.
    # Vendor LCCELL_X1001_Y1001 is physical route tile X20Y12 (the vendor grid is rotated relative to the
    # route/bitstream grid), so those transitions are X20Y12->X20Y11, X20Y11->X20Y12, and
    # X20Y12->X20Y10.  Treating the LCCELL coordinates as route coordinates produced a cleanly accepted but
    # static X1Y1->X2Y1 experiment and is retained only as negative evidence.
    # OFF by default -> zero change to the working flow (extra bel pins on unused = harmless).
    if os.environ.get("AGAMEMNON_HW_CARRY"):
        dcarry = ctx.getDelayFromNS(0.05)
        n_cw = n_cp = 0
        for (tx, ty), zbels in slice_bels.items():
            for z in sorted(zbels):
                cin = "X%dY%d_CARRYIN%02d" % (tx, ty, z); cout = "X%dY%d_CARRYOUT%02d" % (tx, ty, z)
                ctx.addWire(name=cin, type="CARRY", x=tx, y=ty); ctx.addWire(name=cout, type="CARRY", x=tx, y=ty)
                ctx.addBelInput(bel=zbels[z], name="CIN", wire=cin)
                ctx.addBelOutput(bel=zbels[z], name="COUT", wire=cout)
                n_cw += 2
            for z in sorted(zbels):                     # dedicated carry: COUT<z> -> CIN<z+1> (adjacent only)
                if z + 1 in zbels:
                    s = "X%dY%d_CARRYOUT%02d" % (tx, ty, z); t = "X%dY%d_CARRYIN%02d" % (tx, ty, z + 1)
                    ctx.addPip(name="%s.%s" % (s, t), type="CARRY", srcWire=s, dstWire=t, delay=dcarry,
                               loc=Loc(tx, ty, 0)); n_cp += 1
        # Exact fixed-function seam order recovered from the vendor's packed carry
        # graph.  These pips carry no configurable selector bits.
        for sx, sy, dx, dy in ((20, 12, 20, 11), (20, 11, 20, 12), (20, 12, 20, 10)):
            s = "X%dY%d_CARRYOUT15" % (sx, sy)
            t = "X%dY%d_CARRYIN00" % (dx, dy)
            if (sx, sy) in slice_bels and 15 in slice_bels[(sx, sy)] \
                    and (dx, dy) in slice_bels and 0 in slice_bels[(dx, dy)]:
                ctx.addPip(name="%s.%s" % (s, t), type="CARRY_SEAM", srcWire=s, dstWire=t,
                           delay=ctx.getDelayFromNS(0.10), loc=Loc(sx, sy, 0))
                n_cp += 1
        print("AGRV2K arch: HW-CARRY on: %d synthetic carry wires + %d qualified COUT->CIN pips"
              % (n_cw, n_cp))

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

    # Physical package inputs. Unlike the legacy generic IOBs above, these bind a package pin to the
    # InputMUX on that SAME pad. The L48 top-edge mapping is hardware-recovered; other edges stay disabled
    # until their input-bank enable bits and InputMUX numbering are silicon-validated.
    if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
        _imux_for_top_z = {0: 1, 1: 2, 2: 4, 3: 7}
        _verified_imux = {}
        _pi_bels = os.path.join(DATA, "pad_input_L48.csv")
        if os.path.exists(_pi_bels):
            for _r in csv.DictReader(open(_pi_bels)):
                _pad = DEV.bond_map.get(_r.get("verified_pin"))
                if _pad is not None:
                    _verified_imux[tuple(_pad[:3])] = int(_r["inputmux"])
        n_ipad = 0
        for _pin, _pad in sorted(DEV.bond_map.items()):
            _x, _y, _z, _edge = _pad
            if _edge != "TOP" or _z not in _imux_for_top_z:
                continue
            _imux = _verified_imux.get((_x, _y, _z), _imux_for_top_z[_z])
            _w = W(_x, _y, "InputMUX%02d" % _imux)
            if _w not in wireset:
                continue
            _bel = "X%dY%d_IPAD%d" % (_x, _y, _z)
            ctx.addBel(name=_bel, type="GENERIC_IOB", loc=Loc(_x, _y, 200 + _z), gb=False, hidden=False)
            ctx.addBelOutput(bel=_bel, name="O", wire=_w)
            n_ipad += 1
        print("AGRV2K arch: added %d physical L48 top-row INPUT pad bels" % n_ipad)

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
    NGCLK = OPTIONS.integer("AGAMEMNON_NGCLK")   # #global-clock spines to model. Default 1: only
    # spine 0 is silicon-characterized for fully-open bitgen; raise (up to 5) to experiment with more once the
    # other spines' CFG_TILECLKMUX selects are validated. Env-overridable so it's not a baked-in ceiling.
    for g in range(NGCLK):
        ctx.addWire(name="GCLK%d" % g, type="GLOBAL_CLK", x=0, y=0)
    # gen_vlog explicitly emits `assign bus_clk = sys_gck`; a clocked vendor
    # oracle routes that net from ClkdisTILE(13,0):BufMUX05 into the ordinary
    # per-tile SeamMUX/TileClkMUX tree. Expose both wrapper names as alternative
    # typed sources on the already characterized GCLK0 abstraction.
    if NGCLK:
        for _clock_type, _clock_z in (("MCU_SYS_CLOCK", 118), ("MCU_BUS_CLOCK", 119)):
            _clock_bel = "X10Y5_%s" % _clock_type
            ctx.addBel(name=_clock_bel, type=_clock_type, loc=Loc(10, 5, _clock_z),
                       gb=True, hidden=False)
            ctx.addBelOutput(bel=_clock_bel, name="CLK", wire="GCLK0")
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
    # BRAM clock feed: the BRAM's Clk0 enters the BramTILE at ClkdisTILE(13,0) BufMUX05 (harvested from
    # the vendor sys_gck path: BufMUX05 -> SeamMUX01 -> TileClkMUX01=Clk0; the last two hops are in
    # bram9k_edges). Slice CLKs tap GCLK via GCLK_TAP; give the BRAM clock the same tap into BufMUX05 so a
    # clock net can reach a placed BRAM. Guarded on wire existence.
    _bramclk_feed = W(13, 0, "BufMUX05")
    if _bramclk_feed in wireset:
        for g in range(NGCLK):
            ctx.addPip(name="GCLK%d.%s" % (g, _bramclk_feed), type="GCLK_TAP",
                       srcWire="GCLK%d" % g, dstWire=_bramclk_feed, delay=dclk, loc=Loc(13, 0, 0))
            n_gpip += 1
        print("AGRV2K arch: added BRAM clock feed (GCLK -> ClkdisTILE(13,0) BufMUX05)")
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
    # dead_edges_silicon.csv and AGAMEMNON_EDGE_BLACKLIST exclude specific pips proven
    # NON-CONDUCTING on silicon so
    # nextpnr reroutes around them (e.g. RMUX26@(14,4)->RMUX19@(10,4), the +x/right feed into the MCU
    # dout exit RMUX that config-accepts but is electrically dead, while RMUX74@(6,4)->RMUX19@(10,4)
    # from the left conducts). Format: a list of "<src_res>@<sx>,<sy>-><dst_res>@<dx>,<dy>" edges,
    # separated by comma and/or semicolon (edge coords contain commas, so the parse extracts each edge
    # by pattern rather than splitting).  The checked-in negative evidence is always active and has
    # precedence over observed, vendor-mined, and positive-campaign evidence.  The environment variable
    # adds temporary experiment edges; it cannot remove checked-in negatives.
    # Matched on the raw CSV endpoint fields (res+x+y both ends) in every edge loop below.
    _dead_edge_re = r"(\w+)@(-?\d+),(-?\d+)\s*->\s*(\w+)@(-?\d+),(-?\d+)"
    EDGE_BLACKLIST = set(re.findall(_dead_edge_re, os.environ.get("AGAMEMNON_EDGE_BLACKLIST", "")))
    _dead_csv = os.path.join(DATA, "dead_edges_silicon.csv")
    if os.path.exists(_dead_csv):
        for _dead_row in csv.DictReader(open(_dead_csv)):
            _match = re.fullmatch(_dead_edge_re, _dead_row.get("edge", "").strip())
            if not _match:
                raise ValueError("malformed silicon-dead edge: %r" % _dead_row)
            EDGE_BLACKLIST.add(_match.groups())
    if EDGE_BLACKLIST:
        print("AGRV2K arch: SILICON-DEAD EDGE BLACKLIST active (%d edge(s)): %s"
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

    # CONDUCTION GATE (silicon truth, from the full-fabric sweep_all campaign): chipdb/master_conduction.csv
    # holds every routing edge PROVEN to electrically conduct on silicon (the open flow routed a toggling FF
    # through it and the readout toggled). Loading it here lets is_trusted() promote a silicon-conducting edge
    # to trusted even if it was an ENUMERATED guess (byte-validated by the toggle, not just the sel-encoder).
    # AGAMEMNON_CONDUCTION_GATE=1 turns on trusted-only routing = observed U conducting U validated-closed-form
    # -> the arch offers ONLY edges that work on silicon, so the router auto-avoids the offered-but-dead edges
    # (e.g. the dead intra-tile carry that packs a counter into one tile -> [[counter-freeze]] auto-fixes:
    # nextpnr can't pack it, so it spreads across tiles onto conducting inter-tile carry). This is Phase B of
    # the plan: make the model TRUTHFUL so arbitrary auto-placed RTL routes+runs on silicon-verified edges.
    CONDUCT = set()
    for _cf in ("master_conduction.csv",      # silicon-swept (sweep_all) FF->dout reach edges
                "ff2_conduction.csv",          # silicon-swept (ff2_sweep) FF->FF INTER-tile directed corridors
                "harvest_conduction.csv",      # silicon-swept (harvest_sweep) all pips of CONDUCTING designs
                "corpus_conduction.csv"):      # vendor-route-mined per-position conducting edges (mine_corpus.py A2)
        _cp = os.path.join(DATA, _cf)
        if os.path.exists(_cp):
            _n0 = len(CONDUCT)
            for r in csv.DictReader(open(_cp)):
                CONDUCT.add((r["src_res"], r["src_x"], r["src_y"], r["dst_res"], r["dst_x"], r["dst_y"]))
            print("AGRV2K arch: loaded %d conducting edges from %s (+%d, total %d)"
                  % (len(CONDUCT) - _n0, _cf, len(CONDUCT) - _n0, len(CONDUCT)))
    _dead_positive_conflicts = CONDUCT.intersection(EDGE_BLACKLIST)
    if _dead_positive_conflicts:
        print("AGRV2K arch: negative evidence overrides %d conflicting positive edge(s)"
              % len(_dead_positive_conflicts))
        CONDUCT.difference_update(EDGE_BLACKLIST)
    def _cond_key(r):
        return (r["src_res"], r["src_x"], r["src_y"], r["dst_res"], r["dst_x"], r["dst_y"])

    TRUE_TOPO = os.environ.get("AGAMEMNON_TRUE_TOPO")
    OBSERVED_ONLY = os.environ.get("AGAMEMNON_OBSERVED_ONLY")
    # AGAMEMNON_CONDUCTION_GATE implies TRUSTED (trusted-only routing) but with the conducting set folded in.
    TRUSTED = os.environ.get("AGAMEMNON_TRUSTED") or os.environ.get("AGAMEMNON_CONDUCTION_GATE")
    # AGAMEMNON_STRICT_GATE: trust ONLY per-position silicon/vendor-proven edges (observed U CONDUCT) and DROP
    # the position-agnostic closed-form trust (OMUX->IMUX tile-invariance + OMUX->RMUX closed-form). Those two
    # are trusted at EVERY position without per-position proof, and per-position electrical death (proven) makes
    # a spread design route on paper but FREEZE on silicon. Now that the conducting set covers ~89% of the pip
    # model (silicon sweep U corpus-route mining), we can afford to gate strictly and route only proven edges.
    STRICT_GATE = bool(os.environ.get("AGAMEMNON_STRICT_GATE"))
    def is_trusted(r, fn):
        if _blacklisted(r):
            return False                             # negative silicon evidence has absolute precedence
        if r.get("source") == "observed":
            return True                              # real vendor-router edge (per-position)
        if CONDUCT and _cond_key(r) in CONDUCT:
            return True                              # silicon/vendor-PROVEN conducting edge (per-position)
        if STRICT_GATE:
            return False                             # strict: nothing else is trusted (drop closed-form guesses)
        if fn == "rrg_omux_imux_full.csv":
            return True                              # OMUX->IMUX crossbar, tile-invariant validated
        if fam(r["src_res"]) == "OMUX" and fam(r["dst_res"]) == "RMUX":
            return True                              # RMUX<-OMUX is closed-form (100%)
        return False                                 # enumerated RMUX->RMUX / RMUX->IMUX guesses (~94-97%)
    n_pip = 0; skipped = 0; dropped_enum = 0; exit_pruned = 0; seen_pip = set()
    d = ctx.getDelayFromNS(0.1)
    # Conservative vendor routing timing.  The derived table is the maximum of
    # every WORST transition/fanout row across all decoded alta_wire PVT inputs.
    # Until every physical wire index has a proven native T0/T1/T4/TG class, use
    # the maximum for its driving mux family across classes.  Unknown families use
    # the global maximum rather than an optimistic synthetic default.
    _wt_path = os.path.join(DATA, "wire_timing_worst.json")
    _wt_source = {}; _wt_fallback = 0.1
    if os.path.exists(_wt_path):
        with open(_wt_path, encoding="utf-8") as _wt_handle:
            _wt = json.load(_wt_handle)
        _wt_source = {str(k): float(v) for k, v in _wt.get("source_max_ns", {}).items()}
        _wt_fallback = float(_wt.get("fallback_max_ns", max(_wt_source.values()) if _wt_source else 0.1))
    _wt_margin = max(1.0, OPTIONS.number("AGAMEMNON_WIRE_TIMING_MARGIN"))
    def _wire_delay_ns(resource):
        family = fam(resource)
        if family in _wt_source:
            return _wt_source[family] * _wt_margin
        folded = family.lower()
        aliases = [value for name, value in _wt_source.items()
                   if name.lower().startswith(folded) or folded.startswith(name.lower())]
        return (max(aliases) if aliases else _wt_fallback) * _wt_margin
    def _wire_delay(resource):
        return ctx.getDelayFromNS(_wire_delay_ns(resource))
    if _wt_source:
        print("AGRV2K arch: conservative vendor wire timing for %d source families "
              "(unknown fallback %.3f ns, margin %.3fx)" %
              (len(_wt_source), _wt_fallback, _wt_margin))
    # SOFT conducting-PREFERENCE (AGAMEMNON_SOFT_PREFER=1): instead of the hard conduction GATE (which
    # route-fails when the proven set lacks a resource-level path), keep the full mesh routable but make
    # TRUSTED edges (observed U conducting U closed-form) CHEAP and enumerated guesses EXPENSIVE. The router
    # then prefers silicon-conducting edges and falls back to an enumerated edge only when no proven path
    # exists -> most hops land on conducting edges (silicon-correct) without a hard failure. The remaining
    # enumerated fallbacks are exactly the edges to prove/blacklist next (reactive convergence). Penalty is
    # tunable (AGAMEMNON_SOFT_PENALTY ns, default 30) and is ADDED to the edge's base wire delay. Replacing
    # the base delay with the penalty would invert the preference whenever a characterized trusted wire is
    # slower than the penalty. No-op unless SOFT is set.
    SOFT = bool(os.environ.get("AGAMEMNON_SOFT_PREFER"))
    _soft_penalty_ns = OPTIONS.number("AGAMEMNON_SOFT_PENALTY")
    # SPAN-DELAY (AGAMEMNON_SPAN_DELAY=1): give trusted edges a geometric cost = base + step*(|dx|+|dy|), so
    # intra-tile hops are ~free and inter-tile hops cost with distance. This hands nextpnr-generic's placer a
    # real WIRELENGTH GRADIENT (cluster connected cells, pull them toward their exits) instead of the flat
    # 0.1ns that made native placement scatter. Delays don't affect emitted bytes, but they change routing
    # choices -> gated OFF by default so the byte-exact regression + working flows are untouched.
    SPAN_DELAY = bool(os.environ.get("AGAMEMNON_SPAN_DELAY"))
    _span_step = OPTIONS.number("AGAMEMNON_SPAN_STEP")
    def pip_delay(r, fn):
        if SPAN_DELAY:
            try:
                span = abs(int(r["dst_x"]) - int(r["src_x"])) + abs(int(r["dst_y"]) - int(r["src_y"]))
            except Exception:
                span = 0
            base_ns = 0.05 + _span_step * span
        else:
            base_ns = _wire_delay_ns(r["src_res"]) if _wt_source else 0.1
        if SOFT and not is_trusted(r, fn):
            base_ns += _soft_penalty_ns
        if CLEAN_SEL_PREFER and not _clean_sel_encodable(r):
            base_ns += CLEAN_SEL_PENALTY_NS
        return ctx.getDelayFromNS(base_ns)
    if TRUE_TOPO:
        _base = "rrg_edges_true_repl.csv" if TRUE_TOPO == "2" else "rrg_edges_true.csv"
        edge_files = (_base, "rrg_omux_imux_full.csv")
        print("AGRV2K arch: TRUE-TOPO mode -> loading %s" % _base)
    else:
        # The enumerated RRG is incomplete: vendor routes have exposed additional
        # physical inter-tile edges.  corpus_conduction.csv is therefore both
        # positive conduction evidence and a topology supplement.  `seen_pip`
        # below makes the large overlap with rrg_edges_full.csv free of duplicate
        # pips while retaining vendor-only links.
        edge_files = ("rrg_edges_full.csv", "rrg_omux_imux_full.csv",
                      "corpus_conduction.csv")
    # XBAR-FULL (AGAMEMNON_XBAR_FULL=1): add the COMPLETED intra-tile RMUX->IMUX input crossbar (union+
    # replicate the tile-invariant template -> every RMUX source reaches its full ~32 IMUX targets per tile).
    # Widens high-fanout control/select routing (mux sel, freeze) that the observed-only crossbar (566..625
    # of 1013 pairs/tile) starves. Same tile-invariance justification + silicon caveat as rrg_omux_imux_full
    # (some completed pairs may be electrically dead -> gate with CONDUCTION_GATE/SOFT_PREFER). See
    # complete_rmux_imux.py / OBSERVABILITY_FINDINGS.md. Opt-in until silicon-validated.
    if os.environ.get("AGAMEMNON_XBAR_FULL"):
        edge_files = tuple(edge_files) + ("rrg_rmux_imux_full.csv",)
        print("AGRV2K arch: XBAR-FULL -> adding completed RMUX->IMUX input crossbar")
    # RES-NAME NORMALIZER: rrg_omux_imux_full.csv uses UNPADDED res names (OMUX1/IMUX0) while wires.csv +
    # rrg_edges_full.csv use 2-digit PADDED (OMUX01/IMUX00). Without normalizing, W() builds "X..Y.._OMUX1"
    # which is NOT in wireset -> the ENTIRE OMUX->IMUX feedback crossbar (70752 edges) was silently dropped
    # as "endpoint absent" -> registered cells had NO intra-slice feedback path (THE counter-freeze root
    # cause). Pad the numeric suffix so both formats match. Harmless for already-padded names.
    def _padres(res):
        m = re.match(r"([A-Za-z]+)(\d+)$", res)
        return "%s%02d" % (m.group(1), int(m.group(2))) if m else res

    # CONFIG-ENCODING GATE (AGAMEMNON_CLEAN_SEL_GATE=1): electrical adjacency and selector encoding are
    # separate qualifications.  A route can use only conducting edges yet still program the wrong mux input
    # if bitgen has to guess a selector pair.  The block-clean corpus table attributes active bits within each
    # destination node's independent 10-bit RMUX / 12-bit IMUX block and includes only physical edge keys
    # consistent across every observation.  In strict mode, prune uncertain mesh edges before nextpnr sees
    # them, so the router finds another route instead of bitgen silently using an 84--98% predictor.
    CLEAN_SEL_GATE = bool(os.environ.get("AGAMEMNON_CLEAN_SEL_GATE"))
    CLEAN_SEL_PREFER = bool(os.environ.get("AGAMEMNON_CLEAN_SEL_PREFER"))
    CLEAN_SEL_PENALTY_NS = OPTIONS.number("AGAMEMNON_CLEAN_SEL_PENALTY")
    CLEAN_SEL_EDGE = {}
    CLEAN_SEL_REL = {}
    _cse = os.path.join(DATA, "sel_edge_pairs.agdb")
    if CLEAN_SEL_GATE or CLEAN_SEL_PREFER:
        if not os.path.exists(_cse):
            raise ValueError("AGAMEMNON_CLEAN_SEL_GATE requires chipdb/sel_edge_pairs.agdb")
        from agamemnon.engine import routing_selectors
        CLEAN_SEL_EDGE = routing_selectors.load_clean_edges(DATA)
        CLEAN_SEL_REL, _csr_conflict = routing_selectors.relative_edges(CLEAN_SEL_EDGE)
        _csm = "gate" if CLEAN_SEL_GATE else "prefer +%.1f ns" % CLEAN_SEL_PENALTY_NS
        print("AGRV2K arch: CLEAN-SEL encoding %s ON (%d physical + %d unanimous relative keys; "
              "%d conflicting relative keys rejected)"
              % (_csm, len(CLEAN_SEL_EDGE), len(CLEAN_SEL_REL), len(_csr_conflict)))
    def _clean_sel_encodable(r):
        df, sf = fam(r["dst_res"]), fam(r["src_res"])
        if df not in ("RMUX", "IMUX") or sf not in ("RMUX", "OMUX"):
            return True
        di = int(r["dst_res"][len(df):]); si = int(r["src_res"][len(sf):])
        key = (int(r["dst_x"]), int(r["dst_y"]), df, di, sf,
               int(r["src_x"]), int(r["src_y"]), si)
        if key in CLEAN_SEL_EDGE:
            return True
        if (df, di, sf, si, int(r["dst_x"]) - int(r["src_x"]),
                int(r["dst_y"]) - int(r["src_y"])) in CLEAN_SEL_REL:
            return True
        # Two byte-exact closed forms remain safe outside the corpus table.
        if df == "RMUX" and sf == "OMUX":
            return True
        if df == "IMUX" and sf == "OMUX" and r["src_x"] == r["dst_x"] \
           and r["src_y"] == r["dst_y"] and (si - 1) % 3 == 0:
            return True
        return False
    # FEEDBACK-TARGET RESTRICTION: the OMUX[3z+1]->IMUX crossbar (enum_xbar) offers MANY legal targets but
    # only VENDOR-USED (source,target) pairs actually CONDUCT (silicon: OMUX01->IMUX00 is legal, sel resolves,
    # but is DEAD; OMUX01->IMUX07 conducts). Restrict OMUX->IMUX feedback pips to the vendor-observed pairs
    # harvested in chipdb/ff_feedback_map.csv (tile-invariant (src_res,dst_res)); bitgen resolves their sels
    # byte-exact via the mesh template. This forces the router onto conducting feedback targets = the
    # counter-freeze fix. AGAMEMNON_NO_FBRESTRICT disables. Empty map -> no restriction (safe).
    FB_ALLOWED = set()
    _fbm = os.path.join(DATA, "ff_feedback_map.csv")
    # OPT-IN (AGAMEMNON_FBRESTRICT=1): the map is a partial 30-edge sample, so restricting the whole OMUX->IMUX
    # crossbar to it would route-fail designs whose feedback target isn't sampled. Keep OFF by default until
    # the bel LUT-input fix lands + the map is complete (see COUNTER_FREEZE_HANDOFF.md). Enable only for the
    # counter-freeze fix experiments.
    if os.path.exists(_fbm) and os.environ.get("AGAMEMNON_FBRESTRICT"):
        for r in csv.DictReader(open(_fbm)):
            FB_ALLOWED.add((_padres(r["omux_src"]), _padres(r["imux_fb"])))
        print("AGRV2K arch: FEEDBACK-TARGET restriction ON (%d vendor OMUX->IMUX pairs)" % len(FB_ALLOWED))
    # SILICON intra-tile crossbar conduction prune (AGAMEMNON_XBAR_CONDUCT): drop the PHYSICAL OMUX->IMUX pips
    # PROVEN DEAD on silicon (chipdb/xbar_dead_pips.csv, from xbar_pip_sweep.py -- the TRUE src->dst pip per
    # placement, not the placement label). A tile-invariant BLACKLIST (res-level): with the dead pips removed,
    # nextpnr's OWN placer+router pack cells densely and use only conducting intra-tile links -- no hand-packer.
    XBAR_DEAD = set()
    _xd = os.path.join(DATA, "xbar_dead_pips.csv")
    if os.path.exists(_xd) and os.environ.get("AGAMEMNON_XBAR_CONDUCT"):
        for r in csv.DictReader(open(_xd)):
            if r.get("omux") and r.get("imux"): XBAR_DEAD.add((_padres(r["omux"]), _padres(r["imux"])))
        print("AGRV2K arch: XBAR conduction prune ON (%d dead intra-tile OMUX->IMUX pips blacklisted)" % len(XBAR_DEAD))
    # BRAM coverage prune (default ON): a BramTile IMUX/RMUX-dst mesh edge is kept only if bitgen can emit
    # its config (chipdb/bram_pip_cfg.csv). Forces nextpnr to route BRAM data/addr through configurable
    # edges -> silicon-correct. Non-BRAM designs are unaffected (no BramTile-dst edges). Disable with
    # AGAMEMNON_BRAM_ALL_EDGES=1 (to route freely at the cost of unemittable BRAM pips).
    BRAM_COV_ONLY = not os.environ.get("AGAMEMNON_BRAM_ALL_EDGES")
    # BRAM address-APPROACH whitelist (default ON when file present; disable AGAMEMNON_NO_BRAM_APPROACH): a
    # RMUX that (per the vendor) feeds a BramTile IMUX may only be driven by the vendor's conducting approach
    # source -- else nextpnr detours into the boundary via dead edges and the address never reaches the BRAM
    # (silicon: reads word 0). chipdb/bram_approach.csv from harvest_bram_approach.py. Mirrors exit-feeder wl.
    _BAP_ALLOWED = {}                 # (dx,dy,dr) boundary-RMUX -> set of allowed (sx,sy,sr) vendor sources
    _bram_bnd_rmux = set()
    _bap = os.path.join(DATA, "bram_approach.csv")
    if os.environ.get("AGAMEMNON_BRAM_APPROACH") and os.path.exists(_bap):   # opt-in (can route-fail if too tight)
        _er = list(csv.DictReader(open(_bap)))
        for r in _er:                 # boundary RMUX = a RMUX whose output feeds a BramTile(13,4) IMUX
            if r["dst_res"].startswith("IMUX") and r["dst_x"] == "13" and r["dst_y"] == "4":
                _bram_bnd_rmux.add((r["src_x"], r["src_y"], r["src_res"]))
        for r in _er:
            k = (r["dst_x"], r["dst_y"], r["dst_res"])
            if k in _bram_bnd_rmux:
                _BAP_ALLOWED.setdefault(k, set()).add((r["src_x"], r["src_y"], r["src_res"]))
        print("AGRV2K arch: BRAM address-approach whitelist: %d boundary RMUX(es)" % len(_bram_bnd_rmux))
    # SILICON-PROVEN BRAM final-hop whitelist (chipdb/bram_wl.csv from build_bram_wl.py, sourced from the
    # bram_conduction_campaign per-bit toggling paths + vendor route.tx fallback): restrict each
    # BramTILE(13,4) address IMUX to ONLY its conduction-proven feeder RMUX. Stops nextpnr choosing
    # config-accepting-but-DEAD entry pips (e.g. RMUX12->IMUX03, RMUX58->IMUX06-in-context) that pinned the
    # open read to a partial address width. Default ON when the file is present; disable AGAMEMNON_NO_BRAM_WL=1.
    _BRAM_FINAL_DST = set(); _BRAM_FINAL_OK = set()
    _bwl = os.path.join(DATA, "bram_wl.csv")
    if os.path.exists(_bwl) and not os.environ.get("AGAMEMNON_NO_BRAM_WL"):
        for r in csv.DictReader(open(_bwl)):
            if r["dst_res"].startswith("IMUX") and r["dst_x"] == "13" and r["dst_y"] == "4":
                dk = (r["dst_x"], r["dst_y"], _padres(r["dst_res"]))
                _BRAM_FINAL_DST.add(dk)
                _BRAM_FINAL_OK.add((r["src_x"], r["src_y"], _padres(r["src_res"])) + dk)
        print("AGRV2K arch: BRAM final-hop whitelist: %d IMUX terminals restricted to proven feeders"
              % len(_BRAM_FINAL_DST))
    import json as _json
    _BRES = None
    _brj4 = os.path.join(DATA, "bram_resolver.json")
    if BRAM_COV_ONLY and os.path.exists(_brj4):
        _BRES = _json.load(open(_brj4))
    _BRAM_EXACT_CFG = set()
    _bpc_exact = os.path.join(DATA, "bram_pip_cfg.csv")
    if os.path.exists(_bpc_exact):
        for _r in csv.DictReader(open(_bpc_exact)):
            _BRAM_EXACT_CFG.add((_r["dst_res"], _r["src_res"], int(_r["ddx"]), int(_r["ddy"])))
    def _bram_resolvable(dres, sres, ddx, ddy):
        """True if the BramTile sel resolver can emit config for this edge (else prune so nextpnr reroutes)."""
        dm = re.match(r"(IMUX|RMUX)(\d+)", dres); sm = re.match(r"([A-Za-z]+)(\d+)", sres)
        if dm and sm and ((dm.group(1) + str(int(dm.group(2))), sm.group(1) + str(int(sm.group(2))),
                           ddx, ddy) in _BRAM_EXACT_CFG):
            return True
        if _BRES is None: return True
        if not (dm and sm): return True
        dfam, didx, sfam, sidx = dm.group(1), int(dm.group(2)), sm.group(1), int(sm.group(2))
        go = didx % _BRES["NPI"][dfam]
        for k in ("|".join(map(str, (dfam, didx, sfam, sidx, ddx, ddy))),
                  "|".join(map(str, (dfam, go, sfam, sidx, ddx, ddy))),
                  "|".join(map(str, (dfam, sfam, ddx, ddy, sidx % 16)))):
            if k in _BRES["L0"] or k in _BRES["L1"] or k in _BRES["L2"]: return True
        return False
    # Port B has multiple graph-adjacent choices for some terminal muxes, but only
    # one route has been exercised with a dynamic, address-swept x2 vendor image.
    # Restrict both the final input hop and first output hop to that checked-in
    # corridor.  This applies to every edge source, including generic-RRG rows and
    # the BRAM supplement, so an alternate cannot leak in through their union.
    _BRAM_CORRIDOR_DST = set(); _BRAM_CORRIDOR_SRC = set(); _BRAM_CORRIDOR_OK = set()
    _bcor = os.path.join(DATA, "bram_portb_corridors.csv")
    if os.path.exists(_bcor):
        for _r in csv.DictReader(open(_bcor)):
            _s = (int(_r["src_x"]), int(_r["src_y"]), _padres(_r["src_res"]))
            _d = (int(_r["dst_x"]), int(_r["dst_y"]), _padres(_r["dst_res"]))
            _BRAM_CORRIDOR_OK.add(_s + _d)
            if _r["port"] == "AddressB": _BRAM_CORRIDOR_DST.add(_d)
            if _r["port"] == "DataOutB": _BRAM_CORRIDOR_SRC.add(_s)
        print("AGRV2K arch: Port-B silicon corridor: %d input + %d output terminals restricted"
              % (len(_BRAM_CORRIDOR_DST), len(_BRAM_CORRIDOR_SRC)))
    _BRAM_EXIT_SRC = set(); _BRAM_EXIT_OK = set()
    _bxcor = os.path.join(DATA, "bram_portb_exit_corridors.csv")
    # This table is an MCU-readback route, not a universal fabric-read corridor.
    # Applying it to ordinary BRAM consumers strands local DataOutB sinks after
    # the qualified BufMUX->RMUX terminal.  Enable it only for the matching
    # probe/readback transport; normal Port-B builds retain the strict general
    # graph beyond the silicon-qualified first output hop.
    if os.environ.get("AGAMEMNON_BRAM_PORTB_MCU_EXIT") and os.path.exists(_bxcor):
        for _r in csv.DictReader(open(_bxcor)):
            _s = (int(_r["src_x"]), int(_r["src_y"]), _padres(_r["src_res"]))
            _d = (int(_r["dst_x"]), int(_r["dst_y"]), _padres(_r["dst_res"]))
            _BRAM_EXIT_SRC.add(_s); _BRAM_EXIT_OK.add(_s + _d)
        print("AGRV2K arch: Port-B full exit corridor: %d source nodes restricted"
              % len(_BRAM_EXIT_SRC))
    _BRAM_ENTRY_DST = set(); _BRAM_ENTRY_OK = set()
    _becor = os.path.join(DATA, "bram_portb_entry_corridors.csv")
    if os.environ.get("AGAMEMNON_BRAM_PORTB_EXIT") and os.path.exists(_becor):
        for _r in csv.DictReader(open(_becor)):
            _s = (int(_r["src_x"]), int(_r["src_y"]), _padres(_r["src_res"]))
            _d = (int(_r["dst_x"]), int(_r["dst_y"]), _padres(_r["dst_res"]))
            _BRAM_ENTRY_DST.add(_d); _BRAM_ENTRY_OK.add(_s + _d)
        print("AGRV2K arch: Port-B full entry corridor: %d destination nodes restricted"
              % len(_BRAM_ENTRY_DST))
    def _outside_bram_corridor(r):
        _s = (int(r["src_x"]), int(r["src_y"]), _padres(r["src_res"]))
        _d = (int(r["dst_x"]), int(r["dst_y"]), _padres(r["dst_res"]))
        if (_d in _BRAM_CORRIDOR_DST or _s in _BRAM_CORRIDOR_SRC) and _s + _d not in _BRAM_CORRIDOR_OK:
            return True
        if _d in _BRAM_ENTRY_DST and _s + _d not in _BRAM_ENTRY_OK:
            return True
        return _s in _BRAM_EXIT_SRC and _s + _d not in _BRAM_EXIT_OK
    _bram_epr = 0
    _sel_pruned = 0
    _PHYS_PAD_TERM = {}
    _PHYS_INPUT_ENTRY = {}
    _PHYS_INPUT_CONT = {}
    for _pf_name in ("padfeed_L48_top.csv", "padfeed_L48_left.csv"):
        _pf_phys = os.path.join(DATA, _pf_name)
        if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_pf_phys):
            for _r in csv.DictReader(open(_pf_phys)):
                _PHYS_PAD_TERM.setdefault((int(_r["padtile_x"]), int(_r["padtile_y"]),
                                           int(_r["iomux_z"])), set()).add(
                    "RMUX%02d" % int(_r["padfeed_rmux"]))
    # A captured implicit IOMUX hop is stronger evidence than a route.tx terminal alone: without the
    # hop's selector bits the image is accepted but the physical pad may be static. Where one or more
    # vendor-hop rows exist for a pad, expose only those feeders to physical-PCF routing.
    _hop_phys = os.path.join(DATA, "iomux_hop_vendor.csv")
    if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_hop_phys):
        _verified_top = {}
        for _r in csv.DictReader(_line for _line in open(_hop_phys)
                                 if not _line.lstrip().startswith("#")):
            _verified_top.setdefault((int(_r["pad_x"]), int(_r["pad_y"]), int(_r["z"])), set()).add(
                "RMUX%02d" % int(_r["feeder_R"]))
        _PHYS_PAD_TERM.update(_verified_top)
    _pi_phys = os.path.join(DATA, "pad_input_L48.csv")
    if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_pi_phys):
        for _r in csv.DictReader(open(_pi_phys)):
            _PHYS_INPUT_ENTRY[(int(_r["pad_x"]), int(_r["pad_y"]), "InputMUX%02d" % int(_r["inputmux"]))] = \
                (int(_r["dst_x"]), int(_r["dst_y"]), "RMUX%02d" % int(_r["dst_rmux"]))
    _pir_phys = os.path.join(DATA, "pad_input_route_L48.csv")
    if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_pir_phys):
        for _r in csv.DictReader(open(_pir_phys)):
            _sk = (int(_r["src_x"]), int(_r["src_y"]), _r["src_res"])
            _PHYS_INPUT_CONT.setdefault(_sk, set()).add(
                (int(_r["dst_x"]), int(_r["dst_y"]), _r["dst_res"]))
    for fn in edge_files:
        path = os.path.join(DATA, fn)
        if not os.path.exists(path):
            continue
        for r in csv.DictReader(open(path)):
            r["src_res"] = _padres(r["src_res"]); r["dst_res"] = _padres(r["dst_res"])
            # The compact conduction corpus omits tile-type columns; infer them
            # from the already loaded wire database so it can serve as a topology
            # supplement without duplicating hundreds of thousands of strings.
            if "src_tile" not in r:
                # ``tile_type`` is keyed with the CSV's string coordinates.  An
                # integer lookup silently classified every supplemental perimeter
                # edge as LogicTILE and could re-add a physical-IO edge that the
                # enumerated RRG pass had correctly rejected.
                r["src_tile"] = tile_type.get((r["src_x"], r["src_y"]), "LogicTILE")
                r["dst_tile"] = tile_type.get((r["dst_x"], r["dst_y"]), "LogicTILE")
            if _outside_bram_corridor(r):
                _bram_epr += 1; continue
            if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
                if r["dst_tile"] == "IOTILE" \
                   and fam(r["dst_res"]) == "IOMUX" and fam(r["src_res"]) == "RMUX":
                    _z = int(r["dst_res"][5:])
                    _want = _PHYS_PAD_TERM.get((int(r["dst_x"]), int(r["dst_y"]), _z))
                    if _want and r["src_res"] not in _want:
                        skipped += 1; continue
                if r["src_tile"] == "IOTILE" and fam(r["src_res"]) == "InputMUX":
                    _ik = (int(r["src_x"]), int(r["src_y"]), r["src_res"])
                    _iwant = _PHYS_INPUT_ENTRY.get(_ik)
                    if _iwant and (int(r["dst_x"]), int(r["dst_y"]), r["dst_res"]) != _iwant:
                        skipped += 1; continue
                _ck = (int(r["src_x"]), int(r["src_y"]), r["src_res"])
                _cwant = _PHYS_INPUT_CONT.get(_ck)
                if _cwant and (int(r["dst_x"]), int(r["dst_y"]), r["dst_res"]) not in _cwant:
                    skipped += 1; continue
            if (BRAM_COV_ONLY and _BRES and r["dst_x"] == "13" and r["dst_y"] == "4"
                    and fam(r["dst_res"]) in ("IMUX", "RMUX")
                    and not _bram_resolvable(r["dst_res"], r["src_res"], int(r["dst_x"]) - int(r["src_x"]),
                                             int(r["dst_y"]) - int(r["src_y"]))):
                _bram_epr += 1; continue          # BramTile edge the resolver can't emit -> prune (reroute)
            _bnd = (r["dst_x"], r["dst_y"], r["dst_res"])   # BRAM address-approach whitelist
            if _bnd in _bram_bnd_rmux and (r["src_x"], r["src_y"], r["src_res"]) not in _BAP_ALLOWED.get(_bnd, ()):
                _bram_epr += 1; continue          # feeding a BRAM-feeder RMUX from a non-vendor (dead) source
            # SILICON-PROVEN final-hop restriction: into a characterized (13,4) address IMUX ONLY via its
            # conduction-proven feeder (bram_wl.csv). Drops dead entry pips so nextpnr routes the conducting one.
            _fk = (r["dst_x"], r["dst_y"], r["dst_res"])
            if _fk in _BRAM_FINAL_DST and (r["src_x"], r["src_y"], r["src_res"]) + _fk not in _BRAM_FINAL_OK:
                _bram_epr += 1; continue
            # FEEDBACK-TARGET restriction: OMUX->IMUX (feedback crossbar) only to vendor-conducting pairs.
            if FB_ALLOWED and fam(r["src_res"]) == "OMUX" and fam(r["dst_res"]) == "IMUX" \
               and (r["src_res"], r["dst_res"]) not in FB_ALLOWED:
                skipped += 1; continue
            # SILICON dead-pair blacklist: drop intra-tile OMUX->IMUX edges proven non-conducting by the sweep.
            if XBAR_DEAD and fam(r["src_res"]) == "OMUX" and fam(r["dst_res"]) == "IMUX" \
               and (r["src_res"], r["dst_res"]) in XBAR_DEAD:
                skipped += 1; continue
            # EXPERIMENT (AGAMEMNON_FB_OFFSET3=1): restrict the OMUX->IMUX crossbar to IMUX OFFSET-3 targets
            # (dst_idx%4==3 = input D) -- the offset the vendor uses for conducting cell-to-cell reads. Tests
            # whether "route cell-to-cell reads to offset-3" alone makes shift/FSM read correct.
            if os.environ.get("AGAMEMNON_FB_OFFSET3") and fam(r["src_res"]) == "OMUX" \
               and fam(r["dst_res"]) == "IMUX" and int(r["dst_res"][4:]) % 4 != 3:
                skipped += 1; continue
            # BLACKLIST: checked-in silicon-negative evidence plus any temporary experiment edges.
            # This runs before the trust gate and therefore overrides every positive evidence source.
            if _blacklisted(r):
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
            if CLEAN_SEL_GATE and not _clean_sel_encodable(r):
                _sel_pruned += 1; continue
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
                       delay=pip_delay(r, fn), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
            seen_pip.add(nm); n_pip += 1
    _mode = " [OBSERVED-ONLY]" if OBSERVED_ONLY else (
            " [CONDUCTION-GATE: observed U conducting U closed-form]"
            if os.environ.get("AGAMEMNON_CONDUCTION_GATE") else (" [TRUSTED]" if TRUSTED else ""))
    if SOFT: _mode += " [SOFT-PREFER conducting, penalty=%sns]" % os.environ.get("AGAMEMNON_SOFT_PENALTY", "30")
    print("AGRV2K arch: added %d pips (%d skipped: endpoint absent; %d dropped: enumerated%s; "
          "%d exit in-edges pruned by whitelist; %d uncertain selector encodings pruned)"
          % (n_pip, skipped, dropped_enum, _mode, exit_pruned, _sel_pruned))

    # ---- 4b. Dense ripple-register local feedback -----------------------------------------------
    # In ripple mode pinC is occupied by Cin, so a counter bit cannot use the normal Qin/pinC
    # self-feedback path.  The vendor instead presents that slice's Q on OMUX[3z+1] and routes it to
    # the same slice's B input, IMUX[4z+1].  The route is present in the vendor 24-bit counter and the
    # block-clean selector corpus is unanimous at every slice index across all 132 logic tiles.  A few
    # coordinates (including the X1Y1 inter-tile-carry site) were nevertheless absent from the topology
    # union, which made a correctly placed chain unroutable.  Replicate this exact local topology only
    # for hard-carry builds; the ordinary Q presentation bridge below supplies OMUX[3z+1], while the
    # normal bitgen resolver emits the observed IMUX selector pair.
    if os.environ.get("AGAMEMNON_HW_CARRY"):
        _cfd = ctx.getDelayFromNS(0.05)
        n_cf = 0
        for (x, y), tt in tile_type.items():
            if tt != "LogicTILE":
                continue
            for z in range(16):
                s = W(x, y, "OMUX%02d" % (3 * z + 1))
                t = W(x, y, "IMUX%02d" % (4 * z + 1))
                nm = "%s.%s" % (s, t)
                if s in wireset and t in wireset and nm not in seen_pip:
                    ctx.addPip(name=nm, type="CARRY_QFB", srcWire=s, dstWire=t,
                               delay=_cfd, loc=Loc(int(x), int(y), 0))
                    seen_pip.add(nm); n_cf += 1
        print("AGRV2K arch: added %d replicated ripple Q->B feedback pips" % n_cf)

    # ---- 4c. FF-FEEDBACK BRIDGE (fixes counter-freeze for wide sequential) --------------------------------
    # DATA-PROVEN root cause: the ONLY intra-slice FF-Q->own-LUT feedback wire is OMUX[3z+1] (OMUX[3z+1]->IMUX
    # = 70752 edges; OMUX[3z+0]/[3z+2] have ZERO IMUX edges -- they only reach RMUX/mesh). But the bel presents
    # Q on OMUX[3z+2] (a mesh-output wire), so a registered cell's self-feedback had NO intra-slice path and the
    # router detoured it inter-tile (dead) -> every counter/accumulator interior bit froze. FIX: add a bridge
    # pip OMUX[3z+2]->OMUX[3z+1] per slice so nextpnr can route Q to the feedback wire; the existing
    # OMUX[3z+1]->IMUX pips then carry it to the slice's own LUT inputs (intra-slice, conducting). Physically
    # this is CFG_OMUX<z> presenting Q on BOTH [3z+1] (feedback) and [3z+2] (external mesh) -- the vendor
    # multi-hot pattern (AGAMEMNON_VENDOR_OUT_SLICE proves sels {0,1}); bitgen emits sel=1 for this bridge.
    # AGAMEMNON_NO_FFBRIDGE=1 disables (A/B). Zero regression for combinational designs (no self-feedback net).
    if not os.environ.get("AGAMEMNON_NO_FFBRIDGE"):
        _fbd = ctx.getDelayFromNS(0.05)
        n_fb = 0
        for (x, y), tt in tile_type.items():
            if tt != "LogicTILE": continue
            for z in range(16):
                s = W(x, y, "OMUX%02d" % (3 * z + 2)); t = W(x, y, "OMUX%02d" % (3 * z + 1))
                if s in wireset and t in wireset:
                    nm = "%s.%s" % (s, t)
                    if nm not in seen_pip:
                        ctx.addPip(name=nm, type="OMUXFB", srcWire=s, dstWire=t, delay=_fbd,
                                   loc=Loc(int(x), int(y), 0))
                        seen_pip.add(nm); n_fb += 1
        print("AGRV2K arch: added %d FF-feedback bridge pips (OMUX[3z+2]->OMUX[3z+1])" % n_fb)

    # ---- 4d. INTERNAL Qin FEEDBACK (the CORRECT counter-freeze fix, 2026-07-05) ---------------------------
    # Vendor alta_slice: `pinC = modeMux ? Cin : (FeedbackMux ? Qin : C)`. A registered cell's self-feedback
    # (q <= f(q,...)) reads its OWN FF Q via the INTERNAL Qin mux -- it is NEVER routed through the fabric
    # mesh. The old bridge/crossbar theory (4c) tried to ROUTE self-feedback (Q->OMUX[3z+1]->IMUX crossbar),
    # which is the DEAD enum path -> every interior counter/accumulator bit froze. FIX: model Qin as ONE cheap
    # intra-slice pip Q(OMUX[3z+2]) -> C-input(IMUX[4z+2] = I[2] = pinC). nextpnr routes the self-feedback over
    # this single pip instead of the multi-hop dead mesh detour; bitgen recognizes the pip and emits
    # CFG_LUTCMUX[2z]=1 (Qin) instead of a crossbar sel (the byte-exact bit, chipdb/slice_cfg.csv). I[2] is the
    # ONLY Qin-capable LUT input (INIT weight-4 bit = pinC), so LUT-input permutation must land the feedback on
    # I[2]; the pip being the sole/cheapest feedback path steers it there. AGAMEMNON_NO_QINFB disables (A/B).
    # Zero regression for combinational designs (no self-feedback net exists to route).
    if not os.environ.get("AGAMEMNON_NO_QINFB"):
        _qfd = ctx.getDelayFromNS(0.01)   # near-zero: internal path, always cheaper than any routed feedback
        n_qf = 0
        for (x, y), tt in tile_type.items():
            if tt != "LogicTILE": continue
            for z in range(16):
                s = W(x, y, "OMUX%02d" % (3*z + 2)); t = W(x, y, "IMUX%02d" % (4*z + 2))
                if s in wireset and t in wireset:
                    nm = "%s.%s" % (s, t)
                    if nm not in seen_pip:
                        ctx.addPip(name=nm, type="QINFB", srcWire=s, dstWire=t, delay=_qfd,
                                   loc=Loc(int(x), int(y), 0))
                        seen_pip.add(nm); n_qf += 1
        # The two silicon-positive left-bank source slices expose Q on +1 instead
        # of +2.  Their FeedbackMux is the same internal Qin path and therefore
        # terminates at pin C without traversing the harvested crossbar.
        for x, y, z in sorted(_LEFT_VOUT):
            s = W(x, y, "OMUX%02d" % (3*z + 1)); t = W(x, y, "IMUX%02d" % (4*z + 2))
            nm = "%s.%s" % (s, t)
            if s in wireset and t in wireset and nm not in seen_pip:
                ctx.addPip(name=nm, type="QINFB", srcWire=s, dstWire=t,
                           delay=_qfd, loc=Loc(x, y, z))
                seen_pip.add(nm); n_qf += 1
        print("AGRV2K arch: added %d internal Qin-feedback pips (OMUX[3z+2]->IMUX[4z+2]=pinC)" % n_qf)

    # ---- 4b. PACKAGE pad-feed pips (LogicTile->IOTile hop into a pad-feed RMUX) ----
    # The RRG enumerates almost none of the vertical LogicTile(y=11|12).RMUX -> IOTILE(y=13).RMUX pad-feed
    # hops (only 1 of the 10 real vendor top-row feeds is present as 'observed'), so nextpnr cannot route a
    # fabric signal INTO a top-row pad-feed RMUX for most pads -> no logic GPIO output on the top edge.
    # We add the exact vendor pad-feed edges (chipdb/padfeed_L48_top.csv, decoded from the vendor pintest2
    # build) as routable ROUTE pips so nextpnr can complete the chain fabric -> feeder RMUX -> IOTILE
    # pad-feed RMUX -> IOMUX{z} -> pad; bitgen emits the matching CFG_RMUX codeword from the same table
    # (PADFEED_TOP). Guarded by AGAMEMNON_PADFEED_TOP so normal builds are byte-identical (no new pips).
    if os.environ.get("AGAMEMNON_PADFEED_TOP"):
        # AGAMEMNON_PADFEED_ONLY="x,y,z": add ONLY that pad's vendor pad-feed pip (so nextpnr routes the
        # exact vendor-proven feeder, not an alternate RMUX->IOMUX that happens to exist in the RRG).
        _only = os.environ.get("AGAMEMNON_PADFEED_ONLY")
        _only = tuple(int(v) for v in _only.split(",")) if _only else None
        n_pf = 0
        for _pf_name in ("padfeed_L48_top.csv", "padfeed_L48_left.csv"):
            pf = os.path.join(DATA, _pf_name)
            if not os.path.exists(pf):
                continue
            for r in csv.DictReader(open(pf)):
                if _only and (int(r["padtile_x"]), int(r["padtile_y"]), int(r["iomux_z"])) != _only:
                    continue
                s = W(str(r["src_x"]), str(r["src_y"]), r["src_res"])
                t = W(str(r["padtile_x"]), str(r["padtile_y"]), "RMUX%02d" % int(r["padfeed_rmux"]))
                if s not in wireset or t not in wireset:
                    continue
                nm = "%s.%s" % (s, t)
                if nm in seen_pip:
                    continue
                ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                           delay=_wire_delay(r["src_res"]),
                           loc=Loc(int(r["padtile_x"]), int(r["padtile_y"]), 0))
                seen_pip.add(nm); n_pf += 1
                # The same vendor record identifies the fixed terminal from the
                # destination pad-feed RMUX to this package pad's IOMUX slot.
                u = W(str(r["padtile_x"]), str(r["padtile_y"]),
                      "IOMUX%02d" % int(r["iomux_z"]))
                tnm = "%s.%s" % (t, u)
                if u in wireset and tnm not in seen_pip:
                    ctx.addPip(name=tnm, type="ROUTE", srcWire=t, dstWire=u,
                               delay=_wire_delay("RMUX%02d" % int(r["padfeed_rmux"])),
                               loc=Loc(int(r["padtile_x"]), int(r["padtile_y"]), 0))
                    seen_pip.add(tnm); n_pf += 1
        print("AGRV2K arch: PACKAGE PAD-FEED mode -> added %d feeder/terminal pip(s)" % n_pf)
        # VENDOR IOTILE RMUX->IOMUX TERMINALS: the enumerated RRG has no fan-in into most top-row IOMUX
        # pad wires (only a few IOTILEs were in the corpus), so nextpnr can't route the last hop
        # RMUX{R}->IOMUX{z} into an OPAD bel for those pads. iomux_term_vendor.csv holds the REAL vendor
        # RMUX->IOMUX terminal edges harvested from pintest4/5 route.tx (silicon-conducting). Add them as
        # ROUTE pips so the router can complete fabric->...->RMUX{R}->IOMUX{z}->pad. The IOMUX driver
        # (source-select) is still emitted by io_emit at the config tile; this pip is the routed terminal.
        itv = os.path.join(DATA, "iomux_term_vendor.csv")
        n_it = 0
        if os.path.exists(itv):
            for r in csv.DictReader(open(itv)):
                if os.environ.get("AGAMEMNON_PHYSICAL_IO") \
                   and fam(r["dst_res"]) == "IOMUX" and fam(r["src_res"]) == "RMUX":
                    _z = int(r["dst_res"][5:])
                    _want = _PHYS_PAD_TERM.get((int(r["dst_x"]), int(r["dst_y"]), _z))
                    if _want and r["src_res"] not in _want:
                        continue
                s = W(r["src_x"], r["src_y"], r["src_res"]); t = W(r["dst_x"], r["dst_y"], r["dst_res"])
                if s not in wireset or t not in wireset:
                    continue
                nm = "%s.%s" % (s, t)
                if nm in seen_pip:
                    continue
                ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                           delay=_wire_delay(r["src_res"]), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                seen_pip.add(nm); n_it += 1
            print("AGRV2K arch: added %d vendor IOTILE RMUX->IOMUX terminal pip(s)" % n_it)

        # Complete vendor-routed left-bank corridors.  The broad route corpus did
        # not yet include every pintest5 hop, so a strict graph could reach the
        # correct pad feeder over a different, selector-clean but nonconducting
        # path.  These are literal consecutive nodes from that vendor route; the
        # block-clean selector table independently carries every configurable
        # upstream codeword, while PADFEED_EXACT handles the final IOTILE fields.
        _lp = os.path.join(DATA, "padout_L48_left_corridors.csv")
        _nlp = 0
        if os.environ.get("AGAMEMNON_PHYSICAL_IO") and os.path.exists(_lp):
            for _r in csv.DictReader(open(_lp)):
                _s, _t = _r["src_wire"], _r["dst_wire"]
                _nm = "%s.%s" % (_s, _t)
                if _s not in wireset or _t not in wireset or _nm in seen_pip:
                    continue
                _dm = re.match(r"X(\d+)Y(\d+)_", _t)
                if not _dm:
                    continue
                ctx.addPip(name=_nm, type="PADOUT", srcWire=_s, dstWire=_t,
                           delay=_wire_delay(_s.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); _nlp += 1
            print("AGRV2K arch: added %d exact left-bank corridor pip(s)" % _nlp)

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
                if _outside_bram_corridor(r):
                    m_skip += 1; continue
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
                           delay=_wire_delay(r["src_res"]), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
                seen_pip.add(nm); n_mpip += 1
        print("AGRV2K arch: added %d MCU-edge pips (%d skipped); bits=%s"
              % (n_mpip, m_skip, sorted(set(bit_entry) & set(bit_exit))))

    # The AHB read-data bus is physically wider than the original GPIO-loopback
    # harvest.  mcu_hrdata_lanes.csv records all 32 vendor-routed hrdata endpoints,
    # including the BBMUXW family and the second east-edge row.  ``bel_bit`` is an
    # internal, collision-free BEL id (20..22 are already the three qualified AHB
    # input BELs); ``logical_bit`` is the actual hrdata bit and is consumed by the
    # packer/verification mapping.
    _hrlane_csv = os.path.join(DATA, "mcu_hrdata_lanes.csv")
    _n_hrlane = 0; _hrlane_skip = 0
    if os.path.exists(_hrlane_csv):
        for _r in csv.DictReader(open(_hrlane_csv)):
            _bit = int(_r["bel_bit"])
            _src = W(_r["src_x"], _r["src_y"], _r["src_res"])
            _edge = W(_r["edge_x"], _r["edge_y"], _r["edge_res"])
            _sink = W(0, 5, _r["sink_res"])
            if _src not in wireset or _edge not in wireset or _sink not in wireset:
                _hrlane_skip += 1
                continue
            for _a, _b in ((_src, _edge), (_edge, _sink)):
                _nm = "%s.%s" % (_a, _b)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_a, dstWire=_b,
                               delay=_wire_delay(_a.rsplit("_", 1)[-1]),
                               loc=Loc(int(_r["edge_x"]), int(_r["edge_y"]), 0))
                    seen_pip.add(_nm); n_mpip += 1
            bit_exit[_bit] = _sink
            _n_hrlane += 1
        print("AGRV2K arch: loaded %d/32 exact AHB hrdata lane(s) (%d skipped)"
              % (_n_hrlane, _hrlane_skip))

    # External AHB response controls occupy the two flattened sink slots just
    # before HRDATA. Their exact RMUX->BBMUX->SinkPseudo routes and selector
    # pairs come from the control-plane oracle.
    _response_csv = os.path.join(DATA, "mcu_ahb_response_controls.csv")
    _n_response = 0; _response_skip = 0
    if os.path.exists(_response_csv):
        for _r in csv.DictReader(open(_response_csv)):
            _bit = int(_r["bel_bit"])
            _src = W(_r["src_x"], _r["src_y"], _r["src_res"])
            _edge = W(_r["edge_x"], _r["edge_y"], _r["edge_res"])
            _sink = W(0, 5, _r["sink_res"])
            if _src not in wireset or _edge not in wireset or _sink not in wireset:
                _response_skip += 1
                continue
            for _a, _b in ((_src, _edge), (_edge, _sink)):
                _nm = "%s.%s" % (_a, _b)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_a, dstWire=_b,
                               delay=_wire_delay(_a.rsplit("_", 1)[-1]),
                               loc=Loc(int(_r["edge_x"]), int(_r["edge_y"]), 0))
                    seen_pip.add(_nm); n_mpip += 1
            bit_exit[_bit] = _sink
            _n_response += 1
        print("AGRV2K arch: loaded %d/2 exact AHB response control lane(s) (%d skipped)"
              % (_n_response, _response_skip))

    # Full-width MCU-to-fabric AHB write-data sources recovered from the same
    # simultaneous vendor loopback.  The BEL output is the per-lane UFMTILE
    # BufMUX root; for lanes with an explicit InputMUX, add that zero-config hard
    # hop here.  The remaining path into the LogicTile mesh is already present in
    # corpus_conduction.csv from the vendor route.
    _hwlane_csv = os.path.join(DATA, "mcu_hwdata_lanes.csv")
    _n_hwlane = 0; _hwlane_skip = 0
    if os.path.exists(_hwlane_csv):
        for _r in csv.DictReader(open(_hwlane_csv)):
            _bit = int(_r["bel_bit"])
            _entry = W(_r["entry_x"], _r["entry_y"], _r["entry_res"])
            if _entry not in wireset:
                _hwlane_skip += 1
                continue
            _next_res = _r.get("next_res", "")
            if _next_res:
                _next = W(_r["entry_x"], _r["entry_y"], _next_res)
                if _next not in wireset:
                    _hwlane_skip += 1
                    continue
                _nm = "%s.%s" % (_entry, _next)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_entry, dstWire=_next,
                               delay=_wire_delay(_r["entry_res"]),
                               loc=Loc(int(_r["entry_x"]), int(_r["entry_y"]), 0))
                    seen_pip.add(_nm); n_mpip += 1
            bit_entry[_bit] = _entry
            _n_hwlane += 1
        print("AGRV2K arch: loaded %d/32 exact AHB hwdata lane(s) (%d skipped)"
              % (_n_hwlane, _hwlane_skip))

    # Remaining External AHB request controls. HWRITE and HTRANS[1] retain
    # their historical BEL ids; the other controls use collision-free ids.
    _request_csv = os.path.join(DATA, "mcu_ahb_request_controls.csv")
    _n_request = 0; _request_skip = 0
    if os.path.exists(_request_csv):
        for _r in csv.DictReader(open(_request_csv)):
            _bit = int(_r["bel_bit"])
            _entry = W(_r["entry_x"], _r["entry_y"], _r["entry_res"])
            if _entry not in wireset:
                _request_skip += 1
                continue
            _next_res = _r.get("next_res", "")
            if _next_res:
                _next = W(_r["entry_x"], _r["entry_y"], _next_res)
                if _next not in wireset:
                    _request_skip += 1
                    continue
                _nm = "%s.%s" % (_entry, _next)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_entry, dstWire=_next,
                               delay=_wire_delay(_r["entry_res"]),
                               loc=Loc(int(_r["entry_x"]), int(_r["entry_y"]), 0))
                    seen_pip.add(_nm); n_mpip += 1
            bit_entry[_bit] = _entry
            _n_request += 1
        print("AGRV2K arch: loaded %d/10 exact AHB request control lane(s) (%d skipped)"
              % (_n_request, _request_skip))

    # Preserve every non-BEL routing hop observed in the simultaneous control
    # oracle. Rows touching alta_slice are logical cell arcs and remain the
    # placer/packer responsibility; all other rows are physical pips.
    _control_paths_csv = os.path.join(DATA, "mcu_ahb_control_oracle_paths.csv")
    _n_control_path = 0; _control_path_skip = 0
    if os.path.exists(_control_paths_csv):
        for _r in csv.DictReader(open(_control_paths_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            if "_alta_slice" in _src or "_alta_slice" in _dst:
                continue
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _control_path_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_control_path += 1
        print("AGRV2K arch: loaded %d AHB control oracle hop(s) (%d skipped)"
              % (_n_control_path, _control_path_skip))

    # Protocol-valid address-to-read-data oracles: expose all 32 HADDR bits as
    # fixed MCU_DIN roots.  The original table covers [27:2]; the full identity
    # oracle contributes the six formerly missing lanes without renumbering the
    # already released BELs.
    _n_halane = 0; _halane_skip = 0
    for _halane_name in ("mcu_haddr_lanes.csv", "mcu_haddr_missing_lanes.csv"):
        _halane_csv = os.path.join(DATA, _halane_name)
        if not os.path.exists(_halane_csv):
            continue
        for _r in csv.DictReader(open(_halane_csv)):
            _entry = W(_r["entry_x"], _r["entry_y"], _r["entry_res"])
            if _entry not in wireset:
                _halane_skip += 1
                continue
            _next_res = _r.get("next_res", "")
            if _next_res:
                _next = W(_r["entry_x"], _r["entry_y"], _next_res)
                if _next not in wireset:
                    _halane_skip += 1
                    continue
                _nm = "%s.%s" % (_entry, _next)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_entry, dstWire=_next,
                               delay=_wire_delay(_r["entry_res"]),
                               loc=Loc(int(_r["entry_x"]), int(_r["entry_y"]), 0))
                    seen_pip.add(_nm); n_mpip += 1
            bit_entry[int(_r["bel_bit"])] = _entry
            _n_halane += 1
    print("AGRV2K arch: loaded %d/32 exact AHB haddr source lane(s) (%d skipped)"
          % (_n_halane, _halane_skip))

    # Preserve the six new HADDR-to-HRDATA oracle corridors.  This both supplies
    # boundary pips absent from the older corpus and gives the strict smoke a
    # completely vendor-observed path for the newly recovered lanes.
    _hamissing_paths = os.path.join(DATA, "mcu_haddr_missing_paths.csv")
    _n_hamissing_path = 0; _hamissing_path_skip = 0
    if os.path.exists(_hamissing_paths):
        for _r in csv.DictReader(open(_hamissing_paths)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _hamissing_path_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_hamissing_path += 1
        print("AGRV2K arch: loaded %d missing-HADDR oracle hop(s) (%d skipped)"
              % (_n_hamissing_path, _hamissing_path_skip))

    # Native L48 x9 positive control: preserve the complete HADDR[2:5] to BRAM
    # AddressA[3:6] ingress.  The general MCU-entry gate intentionally drops
    # unrestricted BufMUX fanout, and the BramTile coverage gate intentionally
    # drops unqualified terminal choices; this one silicon-positive vendor
    # path supplies exact selector fields for every hop in both gates.
    _x9_haddr_paths = os.path.join(DATA, "bram_x9_haddr_paths.csv")
    _n_x9_haddr = 0; _x9_haddr_skip = 0
    if os.path.exists(_x9_haddr_paths):
        for _r in csv.DictReader(open(_x9_haddr_paths)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _x9_haddr_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="BRAMX9", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_x9_haddr += 1
        print("AGRV2K arch: loaded %d x9 HADDR-to-BRAM hop(s) (%d skipped)"
              % (_n_x9_haddr, _x9_haddr_skip))

    # Active-low MCU reset source routed into an ordinary LUT input by the
    # resetn^HADDR[2] vendor oracle.  This is intentionally a data-path source;
    # dedicated tile asynchronous-reset controls remain a separate model.
    _reset_path_csv = os.path.join(DATA, "mcu_resetn_fabric_path.csv")
    _n_reset_path = 0; _reset_path_skip = 0
    if os.path.exists(_reset_path_csv):
        _reset_root = None
        for _r in csv.DictReader(open(_reset_path_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            if _reset_root is None:
                _reset_root = _src
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _reset_path_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_reset_path += 1
        if _reset_root in wireset:
            bit_entry[120] = _reset_root
        else:
            _reset_path_skip += 1
        print("AGRV2K arch: loaded %d reset-to-fabric hop(s) (%d skipped)"
              % (_n_reset_path, _reset_path_skip))

    # MCU system-control stop observation. This is exposed strictly as a data
    # source on the isolated vendor corridor; no clock-gating semantics are
    # inferred from the signal name.
    _stop_path_csv = os.path.join(DATA, "mcu_stop_path.csv")
    _n_stop_path = 0; _stop_path_skip = 0
    if os.path.exists(_stop_path_csv):
        _stop_root = None
        for _r in csv.DictReader(open(_stop_path_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            if _stop_root is None:
                _stop_root = _src
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _stop_path_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_stop_path += 1
        if _stop_root in wireset:
            bit_entry[258] = _stop_root
        else:
            _stop_path_skip += 1
        print("AGRV2K arch: loaded %d stop-observation hop(s) (%d skipped)"
              % (_n_stop_path, _stop_path_skip))

    # One independently recovered GPIO5 boundary unit. Keep data, output-enable,
    # and return-input as separate typed hard ports so placement cannot silently
    # substitute the older GPIO4 loopback BELs. The table contains only literal
    # consecutive vendor-route nodes; it does not expose the full GPIO matrix.
    _gpio5_path_name = ("mcu_gpio5_loop_l48_paths.csv"
                        if DEV.name == "AGRV2KL48" else "mcu_gpio5_loop_paths.csv")
    _gpio5_path_csv = os.path.join(DATA, _gpio5_path_name)
    _n_gpio5 = 0; _gpio5_skip = 0
    if os.path.exists(_gpio5_path_csv):
        _gpio5_paths = collections.defaultdict(list)
        for _r in csv.DictReader(open(_gpio5_path_csv)):
            _gpio5_paths[_r["signal"]].append(_r)
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _gpio5_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_gpio5 += 1
        _gpio5_data = _gpio5_paths.get("gpio5_io_out_data", [])
        _gpio5_enable = _gpio5_paths.get("gpio5_io_out_en", [])
        _gpio5_input = _gpio5_paths.get("gpio5_io_in", [])
        if _gpio5_data and _gpio5_data[0]["src_wire"] in wireset:
            bit_entry[259] = _gpio5_data[0]["src_wire"]
        else:
            _gpio5_skip += 1
        if _gpio5_enable and _gpio5_enable[0]["src_wire"] in wireset:
            bit_entry[260] = _gpio5_enable[0]["src_wire"]
        else:
            _gpio5_skip += 1
        if _gpio5_input and _gpio5_input[-1]["dst_wire"] in wireset:
            bit_exit[261] = _gpio5_input[-1]["dst_wire"]
        else:
            _gpio5_skip += 1
        print("AGRV2K arch: loaded %d GPIO5 boundary hop(s) from %s (%d skipped)"
              % (_n_gpio5, _gpio5_path_name, _gpio5_skip))

    # Read-only analog hard-block routes. Vendor route.tx names the ADC cell,
    # not the individual output pin, so DB0 and EOC both appear as
    # `X22Y7_alta_adc00`. Distinct synthetic source wires preserve the two
    # isolated oracle-net identities and bind each to its recovered first hop.
    # This prevents the open router from swapping those exact corridors; it is
    # not a general output-pin encoding claim (DB1 also uses InputMUX01).
    for (_analog_csv, _analog_root, _analog_exit, _analog_type, _analog_port,
         _analog_label, _analog_z) in (
            ("analog_adc0_db0_path.csv", "X22Y7_ADCDBSOURCE00", "X22Y7_InputMUX100",
             "AGRV2K_ADC0_DB0", "DB", "ADC0 DB0", 0),
            ("analog_adc0_eoc_path.csv", "X22Y7_ADCEOCSOURCE00", "X22Y7_BufMUX100",
             "AGRV2K_ADC0_EOC", "EOC", "ADC0 EOC", 1),
            ("analog_adc0_db1_path.csv", "X22Y7_ADCDBSOURCE01", "X22Y7_InputMUX101",
             "AGRV2K_ADC0_DB1", "DB", "ADC0 DB1", 2)):
        _analog_path_csv = os.path.join(DATA, _analog_csv)
        if not os.path.exists(_analog_path_csv):
            continue
        if _analog_root not in wireset:
            ctx.addWire(name=_analog_root, type=fam(_analog_root.rsplit("_", 1)[-1]),
                        x=22, y=7)
            wireset.add(_analog_root); n_wire += 1
        if _analog_exit not in wireset:
            ctx.addWire(name=_analog_exit, type=fam(_analog_exit.rsplit("_", 1)[-1]),
                        x=22, y=7)
            wireset.add(_analog_exit); n_wire += 1
        _n_analog = 0; _analog_skip = 0; _path_root = None
        for _r in csv.DictReader(open(_analog_path_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            if _path_root is None:
                _path_root = _src
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _analog_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="ANALOG", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_analog += 1
        if _path_root == _analog_root and _path_root in wireset:
            _analog_bel = "X22Y7_%s00" % _analog_type
            ctx.addBel(name=_analog_bel, type=_analog_type,
                       loc=Loc(22, 7, _analog_z), gb=False, hidden=False)
            ctx.addBelOutput(bel=_analog_bel, name=_analog_port, wire=_path_root)
        else:
            _analog_skip += 1
        print("AGRV2K arch: loaded %d %s hop(s) (%d skipped)"
              % (_n_analog, _analog_label, _analog_skip))

    # Fabric-to-core local interrupts. Each isolated vendor oracle drives one
    # lane from a retained LUT and observes the same net on a GPIO probe,
    # proving the complete LUT-output-to-hard-sink corridor.
    for _local_int_bit in range(4):
        _local_int_csv = os.path.join(
            DATA, "mcu_local_int%d_path.csv" % _local_int_bit)
        _n_local_int = 0; _local_int_skip = 0
        if not os.path.exists(_local_int_csv):
            continue
        _local_int_sink = None
        for _r in csv.DictReader(open(_local_int_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            _local_int_sink = _dst
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _local_int_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_local_int += 1
        if _local_int_sink in wireset:
            bit_exit[121 + _local_int_bit] = _local_int_sink
        else:
            _local_int_skip += 1
        print("AGRV2K arch: loaded %d local_int[%d] hop(s) (%d skipped)"
              % (_n_local_int, _local_int_bit, _local_int_skip))

    # Safety-ordered first slice of the fabric AHB master: MCU/system response
    # inputs into ordinary fabric logic.
    _slave_response_bits = {
        "slave_ahb_hreadyout": 125,
        "slave_ahb_hresp": 126,
        "slave_ahb_hrdata[0]": 127,
    }
    _slave_response_csv = os.path.join(DATA, "mcu_slave_ahb_response_paths.csv")
    _n_slave_response = 0; _slave_response_skip = 0
    _slave_response_roots = {}
    if os.path.exists(_slave_response_csv):
        for _r in csv.DictReader(open(_slave_response_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            if int(_r["step"]) == 0:
                _slave_response_roots[_r["signal"]] = _src
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _slave_response_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_slave_response += 1
        for _signal, _bit in _slave_response_bits.items():
            _root = _slave_response_roots.get(_signal)
            if _root in wireset:
                bit_entry[_bit] = _root
            else:
                _slave_response_skip += 1
        print("AGRV2K arch: loaded %d fabric-master response hop(s) (%d skipped)"
              % (_n_slave_response, _slave_response_skip))

    # Time-boxed four-lane HRDATA groups. Each vendor oracle consumes four
    # response bits in one LUT, avoiding the failed full-width oracle's 32-LUT
    # placement collapse. Load every promoted bounded group by filename.
    _slave_hrdata_grouped = os.path.join(
        DATA, "mcu_slave_ahb_hrdata_grouped_full_paths.csv")
    _slave_hrdata_csvs = ([ _slave_hrdata_grouped ]
        if os.path.exists(_slave_hrdata_grouped) else sorted(
            os.path.join(DATA, _name) for _name in os.listdir(DATA)
            if re.fullmatch(r"mcu_slave_ahb_hrdata\d+_\d+_paths\.csv", _name)))
    _n_slave_hrdata = 0; _slave_hrdata_skip = 0
    _slave_hrdata_roots = {}
    for _slave_hrdata_csv in _slave_hrdata_csvs:
        for _r in csv.DictReader(open(_slave_hrdata_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            if int(_r["step"]) == 0:
                _slave_hrdata_roots[_r["signal"]] = _src
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _slave_hrdata_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_slave_hrdata += 1
    for _signal, _root in _slave_hrdata_roots.items():
        _lane_match = re.fullmatch(r"slave_ahb_hrdata\[(\d+)\]", _signal)
        if _lane_match and _root in wireset:
            bit_entry[133 + int(_lane_match.group(1))] = _root
        else:
            _slave_hrdata_skip += 1
    if _slave_hrdata_csvs:
        print("AGRV2K arch: loaded %d bounded fabric-master HRDATA hop(s) (%d skipped)"
              % (_n_slave_hrdata, _slave_hrdata_skip))

    # Fabric-master request qualifiers. The oracle uses one retained LUT as a
    # shared source for all 11 sinks, proving a conflict-free simultaneous
    # route tree without yet claiming independent sources or bus semantics.
    _slave_request_bits = {
        "slave_ahb_hsel": 165,
        "slave_ahb_hready": 166,
        "slave_ahb_htrans[0]": 167,
        "slave_ahb_htrans[1]": 168,
        "slave_ahb_hsize[0]": 169,
        "slave_ahb_hsize[1]": 170,
        "slave_ahb_hsize[2]": 171,
        "slave_ahb_hburst[0]": 172,
        "slave_ahb_hburst[1]": 173,
        "slave_ahb_hburst[2]": 174,
        "slave_ahb_hwrite": 175,
    }
    _slave_request_csv = os.path.join(
        DATA, "mcu_slave_ahb_request_control_paths.csv")
    _n_slave_request = 0; _slave_request_skip = 0
    _slave_request_sinks = {}
    if os.path.exists(_slave_request_csv):
        for _r in csv.DictReader(open(_slave_request_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            _slave_request_sinks[_r["signal"]] = _dst
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _slave_request_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_slave_request += 1
        for _signal, _bit in _slave_request_bits.items():
            _sink = _slave_request_sinks.get(_signal)
            if _sink in wireset:
                bit_exit[_bit] = _sink
            else:
                _slave_request_skip += 1
        print("AGRV2K arch: loaded %d fabric-master request-control hop(s) (%d skipped)"
              % (_n_slave_request, _slave_request_skip))

    # Full fabric-master request payload route tree. The vendor oracle fans a
    # single safe-idle value onto every HADDR/HWDATA sink through OMUX00/02.
    _slave_payload_csv = os.path.join(
        DATA, "mcu_slave_ahb_request_payload_paths.csv")
    _n_slave_payload = 0; _slave_payload_skip = 0
    _slave_payload_sinks = {}
    if os.path.exists(_slave_payload_csv):
        for _r in csv.DictReader(open(_slave_payload_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            _slave_payload_sinks[_r["signal"]] = _dst
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _slave_payload_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_slave_payload += 1
        for _lane in range(32):
            for _name, _bit in (("slave_ahb_haddr[%d]" % _lane, 176 + _lane),
                                ("slave_ahb_hwdata[%d]" % _lane, 208 + _lane)):
                _sink = _slave_payload_sinks.get(_name)
                if _sink in wireset:
                    bit_exit[_bit] = _sink
                else:
                    _slave_payload_skip += 1
        print("AGRV2K arch: loaded %d fabric-master request-payload hop(s) (%d skipped)"
              % (_n_slave_payload, _slave_payload_skip))

    # All MCU-to-fabric DMA response channels. These inputs are observational
    # and cannot initiate a DMA transfer by themselves.
    _dma_response_bits = {
        "ext_dma_DMACCLR[0]": 128,
        "ext_dma_DMACTC[0]": 129,
        "ext_dma_DMACCLR[1]": 252,
        "ext_dma_DMACCLR[2]": 253,
        "ext_dma_DMACCLR[3]": 254,
        "ext_dma_DMACTC[1]": 255,
        "ext_dma_DMACTC[2]": 256,
        "ext_dma_DMACTC[3]": 257,
    }
    _dma_response_csv = os.path.join(DATA, "mcu_dma_response_all_paths.csv")
    _n_dma_response = 0; _dma_response_skip = 0
    _dma_response_roots = {}
    if os.path.exists(_dma_response_csv):
        for _r in csv.DictReader(open(_dma_response_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            if int(_r["step"]) == 0:
                _dma_response_roots[_r["signal"]] = _src
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _dma_response_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_dma_response += 1
        for _signal, _bit in _dma_response_bits.items():
            _root = _dma_response_roots.get(_signal)
            if _root in wireset:
                bit_entry[_bit] = _root
            else:
                _dma_response_skip += 1
        print("AGRV2K arch: loaded %d DMA-response hop(s) (%d skipped)"
              % (_n_dma_response, _dma_response_skip))

    # All fabric-to-MCU DMA request endpoints.  The bounded vendor oracle drove
    # all sixteen request bits from one retained LUT, so this graph proves a
    # shared branch tree only; separate-source routability is deliberately not
    # inferred from it.
    _dma_request_bits = {
        "ext_dma_DMACBREQ[0]": 130,
        "ext_dma_DMACLBREQ[0]": 131,
        "ext_dma_DMACSREQ[0]": 132,
        "ext_dma_DMACLSREQ[0]": 133,
        "ext_dma_DMACBREQ[1]": 240,
        "ext_dma_DMACBREQ[2]": 241,
        "ext_dma_DMACBREQ[3]": 242,
        "ext_dma_DMACLBREQ[1]": 243,
        "ext_dma_DMACLBREQ[2]": 244,
        "ext_dma_DMACLBREQ[3]": 245,
        "ext_dma_DMACSREQ[1]": 246,
        "ext_dma_DMACSREQ[2]": 247,
        "ext_dma_DMACSREQ[3]": 248,
        "ext_dma_DMACLSREQ[1]": 249,
        "ext_dma_DMACLSREQ[2]": 250,
        "ext_dma_DMACLSREQ[3]": 251,
    }
    _dma_request_csv = os.path.join(DATA, "mcu_dma_request_all_paths.csv")
    _n_dma_request = 0; _dma_request_skip = 0
    _dma_request_sinks = {}
    if os.path.exists(_dma_request_csv):
        for _r in csv.DictReader(open(_dma_request_csv)):
            _src = _r["src_wire"]; _dst = _r["dst_wire"]
            _dma_request_sinks[_r["signal"]] = _dst
            _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
            if _src not in wireset or _dst not in wireset or not _dm:
                _dma_request_skip += 1
                continue
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                           loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                seen_pip.add(_nm); n_mpip += 1
            _n_dma_request += 1
        for _signal, _bit in _dma_request_bits.items():
            _sink = _dma_request_sinks.get(_signal)
            if _sink in wireset:
                bit_exit[_bit] = _sink
            else:
                _dma_request_skip += 1
        print("AGRV2K arch: loaded %d DMA-request hop(s) (%d skipped)"
              % (_n_dma_request, _dma_request_skip))

    # Alternate endpoint fan-ins selected by the simultaneous HADDR->HRDATA
    # vendor route.  They feed the same fixed SinkMUXPseudo wires/BELs as the
    # HWDATA oracle but use a different conflict-free RMUX assignment.
    _haexit_csv = os.path.join(DATA, "mcu_hrdata_addr_lanes.csv")
    _n_haexit = 0; _haexit_skip = 0
    if os.path.exists(_haexit_csv):
        for _r in csv.DictReader(open(_haexit_csv)):
            _src = W(_r["src_x"], _r["src_y"], _r["src_res"])
            _edge = W(_r["edge_x"], _r["edge_y"], _r["edge_res"])
            _sink = W(0, 5, _r["sink_res"])
            if _src not in wireset or _edge not in wireset or _sink not in wireset:
                _haexit_skip += 1
                continue
            for _a, _b in ((_src, _edge), (_edge, _sink)):
                _nm = "%s.%s" % (_a, _b)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_a, dstWire=_b,
                               delay=_wire_delay(_a.rsplit("_", 1)[-1]),
                               loc=Loc(int(_r["edge_x"]), int(_r["edge_y"]), 0))
                    seen_pip.add(_nm); n_mpip += 1
            _n_haexit += 1
        print("AGRV2K arch: loaded %d/32 alternate HADDR->HRDATA endpoint(s) (%d skipped)"
              % (_n_haexit, _haexit_skip))

    # Two lanes in the simultaneous vendor corridor use the LUT's alternate
    # OMUX[3z+0] output (the other three inserted buffers use the default +2
    # output).  Represent the selectable output as a short internal pip so a
    # per-cell route can choose it without globally changing every slice BEL.
    for _x, _y, _z in ((14, 10, 3), (14, 9, 7)):
        _src = W(_x, _y, "OMUX%02d" % (3 * _z + 2))
        _dst = W(_x, _y, "OMUX%02d" % (3 * _z + 0))
        if _src in wireset and _dst in wireset:
            _nm = "%s.%s" % (_src, _dst)
            if _nm not in seen_pip:
                ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay("OMUX"), loc=Loc(_x, _y, _z))
                seen_pip.add(_nm); n_mpip += 1

    # PIN_25/PIN_26 in the silicon-positive pintest2 route use F on OMUX[3z+0]
    # and Q on OMUX[3z+1], not the ordinary registered +2 presentation.  The
    # bridge represents the shared physical presentation selected by the
    # vendor's exact {0,1} CFG_OMUX pattern.
    if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
        for _x, _y, _si, _di in ((14, 11, 13, 12), (14, 11, 16, 15)):
            _src = W(_x, _y, "OMUX%02d" % _si); _dst = W(_x, _y, "OMUX%02d" % _di)
            _nm = "%s.%s" % (_src, _dst)
            if _src in wireset and _dst in wireset and _nm not in seen_pip:
                ctx.addPip(name=_nm, type="PADOUT", srcWire=_src, dstWire=_dst,
                           delay=_wire_delay("OMUX"), loc=Loc(_x, _y, 0))
                seen_pip.add(_nm); n_mpip += 1

    # ---- 5b. BRAM routing pips (BramTILE <-> fabric boundary + intra-BRAM crossbar) ----
    # Harvested from the vendor oracle_bram/logic_db/route.tx (decoded) -> chipdb/bram9k_edges.csv (92 edges:
    # 32 BRAM<->LogicTILE(14,4) boundary + clock spine + 60 intra-BRAM IMUX chains). These are the analog of
    # the MCU-edge pips: the RRG does not enumerate the BramTILE boundary, so without them nextpnr cannot
    # route a placed BRAM's data/addr/clock in or its DataOut back to the mesh. INPUTS enter via LogicTILE(14,4)
    # RMUX -> BramTILE IMUX; OUTPUTS leave via BramTILE BufMUX -> (14,4) RMUX; CLOCK via ClkdisTILE(13,0)
    # BufMUX05 -> BramTILE SeamMUX. Loaded as ROUTE pips (guarded on wireset). Guarded: file absent -> skip.
    # Coverage prune: a BramTile IMUX/RMUX-dst crossbar pip is only kept if bitgen can emit its config
    # (chipdb/bram_pip_cfg.csv, harvest_bram_pip_cfg.py). This forces nextpnr to route BRAM data/addr
    # through edges we can configure -- same principle as the LogicTile far-link legal-fanin prune -- so
    # every routed BramTile pip is silicon-correct. Non-crossbar edges (BufMUX/SeamMUX/clock) always kept.
    import re as _re
    _bram_cov = set()
    _bpc = os.path.join(DATA, "bram_pip_cfg.csv")
    if os.path.exists(_bpc):
        for r in csv.DictReader(open(_bpc)):
            _bram_cov.add((r["dst_res"], r["src_res"], int(r["ddx"]), int(r["ddy"])))
    bram_csv = os.path.join(DATA, "bram9k_edges.csv")
    _bram_input_terminals = set()
    _bram_bel_csv = os.path.join(DATA, "bram9k_bel.csv")
    if os.path.exists(_bram_bel_csv):
        for _r in csv.DictReader(open(_bram_bel_csv)):
            if _r["port"] not in {"DataOutA", "DataOutB"}:
                _bram_input_terminals.add(_r["res"])
    n_bpip = 0; b_skip = 0; b_prune = 0; b_terminal_prune = 0
    if os.path.exists(bram_csv):
        for r in csv.DictReader(open(bram_csv)):
            if _outside_bram_corridor(r):
                b_prune += 1; continue
            s = W(r["src_x"], r["src_y"], r["src_res"]); t = W(r["dst_x"], r["dst_y"], r["dst_res"])
            if s not in wireset or t not in wireset:
                b_skip += 1; continue
            # An IMUX terminal is a physical BRAM input, not a general-purpose transit wire.  The vendor
            # selector graph contains terminal->terminal alternatives, but exposing those alternatives to
            # router2 makes one live input's sink path reserve another live input's terminal (dual-port
            # AddressB[1]/AddressB[2] was the first reproducible collision).  Every affected destination has
            # an independently characterized RMUX feeder, which is what simultaneous vendor bus routes use.
            # Keep the selector encodings in bram_pip_cfg.csv for analysis, but do not offer a BRAM input pin
            # as routing fabric for another pin.
            if r["src_res"] in _bram_input_terminals:
                b_terminal_prune += 1; continue
            if (BRAM_COV_ONLY and _BRES and r["dst_tile"] == "BramTILE"
                    and _re.match(r"(IMUX|RMUX)\d+$", r["dst_res"])
                    and not _bram_resolvable(r["dst_res"], r["src_res"], int(r["dst_x"]) - int(r["src_x"]),
                                             int(r["dst_y"]) - int(r["src_y"]))):
                b_prune += 1; continue          # crossbar edge the resolver can't emit -> prune
            # SILICON-PROVEN final-hop restriction: a characterized (13,4) address IMUX is fed ONLY by its
            # conduction-proven feeder (bram_wl.csv) -> drop dead entry pips (e.g. RMUX58->IMUX06) so nextpnr
            # takes the conducting one (RMUX40->IMUX06). Only touches the 9 characterized address terminals.
            _fk = (r["dst_x"], r["dst_y"], _padres(r["dst_res"]))
            if _fk in _BRAM_FINAL_DST and (r["src_x"], r["src_y"], _padres(r["src_res"])) + _fk not in _BRAM_FINAL_OK:
                b_prune += 1; continue
            nm = "%s.%s" % (s, t)
            if nm in seen_pip:
                continue
            ctx.addPip(name=nm, type="ROUTE", srcWire=s, dstWire=t,
                       delay=_wire_delay(r["src_res"]), loc=Loc(int(r["dst_x"]), int(r["dst_y"]), 0))
            seen_pip.add(nm); n_bpip += 1
        print("AGRV2K arch: added %d BRAM routing pip(s) (%d skipped, %d pruned:no-config, "
              "%d pruned:input-terminal-transit)" % (n_bpip, b_skip, b_prune, b_terminal_prune))

    # ---- 5c. BRAM bel: an ALTA_BRAM9K on the BramTILE with each port pin bound to the harvested wire ----
    # chipdb/bram9k_bel.csv (port,bit,x,y,res) = the port->BramTILE-terminal map harvested from the vendor
    # oracle_bram_rw route.tx (harvest_bram_bel.py). Without this bel nextpnr cannot PLACE a BRAM cell; the
    # 5b pips give it something to route to/from. INPUT ports (Address/DataIn/We/Re/ByteEn/Clk/ClkEn) enter
    # via BramTILE IMUX/KMUX/TileClk wires; DataOut leaves via BufMUX. Guarded: file absent -> skip.
    _BRAM_SCALAR = {"WeA", "WeB", "ReA", "ReB", "Clk0", "Clk1", "ClkEn0", "ClkEn1"}
    _BRAM_OUT = {"DataOutA", "DataOutB"}
    bram_bel_csv = os.path.join(DATA, "bram9k_bel.csv")
    if os.path.exists(bram_bel_csv):
        _btpins = {}
        for r in csv.DictReader(open(bram_bel_csv)):
            _btpins.setdefault((int(r["x"]), int(r["y"])), []).append(r)
        n_bram_bel = 0; bb_skip = 0
        for (bx, by), pins in _btpins.items():
            bel = W(bx, by, "BRAM")
            ctx.addBel(name=bel, type="ALTA_BRAM9K", loc=Loc(bx, by, 0), gb=False, hidden=False)
            for r in pins:
                w = W(r["x"], r["y"], r["res"])
                if w not in wireset: bb_skip += 1; continue
                port, bit = r["port"], int(r["bit"])
                pin = port if port in _BRAM_SCALAR else "%s[%d]" % (port, bit)
                if port in _BRAM_OUT:
                    ctx.addBelOutput(bel=bel, name=pin, wire=w)
                else:
                    ctx.addBelInput(bel=bel, name=pin, wire=w)
            n_bram_bel += 1
        print("AGRV2K arch: added %d BRAM bel(s) (%d pins skipped)" % (n_bram_bel, bb_skip))

    # ---- 6. alta_mcu bels: one MCU bel PER GPIO bit at the MCU location (UFMTILE 0,5) ----
    # Each GPIO bit crosses the MCU<->fabric edge on its OWN wires (harvested from the vendor route.tx of
    # the loopback + lutmcu oracles): DIN = the fabric-entry BufMUX wire the MCU drives; DOUT = the
    # fabric-exit SinkMUXPseudo wire the MCU reads. The router threads MCU-out -> fabric LUT -> MCU-in
    # for each bit independently. One MCU cell in the netlist per bit; nextpnr places each on its bel.
    # Placed at UFMTILE(10,5) distinguished by z=bit (the fabric-crossing corner where entry/exit muxes
    # live -> keeps the LUT local, route short, sel-encoding errors few). Bit 0 = the proven single-bit
    # path (GPIO4_1/2, RMUX93/RMUX19/BBMUXS02); bit 1 = GPIO4_3/4, RMUX17/RMUX02/BBMUXS04.
    # MCU-edge tile: a PHYSICAL silicon constant (the MCU<->fabric crossing corner), not a free choice --
    # but named + env-overridable (AGAMEMNON_MCU_XY="x,y") rather than a scattered magic number, so a
    # different package/part revision can point it elsewhere without hunting literals.
    MCUX, MCUY = OPTIONS.coordinates("AGAMEMNON_MCU_XY")
    n_mbel = 0
    _typed_mcu = {
        102: "MCU_AHB_HREADY",
        103: "MCU_AHB_HTRANS0",
        104: "MCU_AHB_HSIZE0",
        105: "MCU_AHB_HSIZE1",
        106: "MCU_AHB_HSIZE2",
        107: "MCU_AHB_HBURST0",
        108: "MCU_AHB_HBURST1",
        109: "MCU_AHB_HBURST2",
        110: "MCU_AHB_HREADYOUT",
        111: "MCU_AHB_HRESP",
        120: "MCU_RESETN",
        121: "MCU_LOCAL_INT0",
        122: "MCU_LOCAL_INT1",
        123: "MCU_LOCAL_INT2",
        124: "MCU_LOCAL_INT3",
        125: "MCU_SLAVE_AHB_HREADYOUT",
        126: "MCU_SLAVE_AHB_HRESP",
        127: "MCU_SLAVE_AHB_HRDATA0",
        128: "MCU_DMA_CLR0",
        129: "MCU_DMA_TC0",
        130: "MCU_DMA_BREQ0",
        131: "MCU_DMA_LBREQ0",
        132: "MCU_DMA_SREQ0",
        133: "MCU_DMA_LSREQ0",
        240: "MCU_DMA_BREQ1",
        241: "MCU_DMA_BREQ2",
        242: "MCU_DMA_BREQ3",
        243: "MCU_DMA_LBREQ1",
        244: "MCU_DMA_LBREQ2",
        245: "MCU_DMA_LBREQ3",
        246: "MCU_DMA_SREQ1",
        247: "MCU_DMA_SREQ2",
        248: "MCU_DMA_SREQ3",
        249: "MCU_DMA_LSREQ1",
        250: "MCU_DMA_LSREQ2",
        251: "MCU_DMA_LSREQ3",
        252: "MCU_DMA_CLR1",
        253: "MCU_DMA_CLR2",
        254: "MCU_DMA_CLR3",
        255: "MCU_DMA_TC1",
        256: "MCU_DMA_TC2",
        257: "MCU_DMA_TC3",
        258: "MCU_STOP",
        259: "MCU_GPIO5_OUT_DATA1",
        260: "MCU_GPIO5_OUT_EN1",
        261: "MCU_GPIO5_IN2",
        134: "MCU_SLAVE_AHB_HRDATA1",
        135: "MCU_SLAVE_AHB_HRDATA2",
        136: "MCU_SLAVE_AHB_HRDATA3",
        137: "MCU_SLAVE_AHB_HRDATA4",
        138: "MCU_SLAVE_AHB_HRDATA5",
        139: "MCU_SLAVE_AHB_HRDATA6",
        140: "MCU_SLAVE_AHB_HRDATA7",
        141: "MCU_SLAVE_AHB_HRDATA8",
        142: "MCU_SLAVE_AHB_HRDATA9",
        143: "MCU_SLAVE_AHB_HRDATA10",
        144: "MCU_SLAVE_AHB_HRDATA11",
        145: "MCU_SLAVE_AHB_HRDATA12",
        146: "MCU_SLAVE_AHB_HRDATA13",
        147: "MCU_SLAVE_AHB_HRDATA14",
        148: "MCU_SLAVE_AHB_HRDATA15",
        149: "MCU_SLAVE_AHB_HRDATA16",
        150: "MCU_SLAVE_AHB_HRDATA17",
        151: "MCU_SLAVE_AHB_HRDATA18",
        152: "MCU_SLAVE_AHB_HRDATA19",
        153: "MCU_SLAVE_AHB_HRDATA20",
        154: "MCU_SLAVE_AHB_HRDATA21",
        155: "MCU_SLAVE_AHB_HRDATA22",
        156: "MCU_SLAVE_AHB_HRDATA23",
        157: "MCU_SLAVE_AHB_HRDATA24",
        158: "MCU_SLAVE_AHB_HRDATA25",
        159: "MCU_SLAVE_AHB_HRDATA26",
        160: "MCU_SLAVE_AHB_HRDATA27",
        161: "MCU_SLAVE_AHB_HRDATA28",
        162: "MCU_SLAVE_AHB_HRDATA29",
        163: "MCU_SLAVE_AHB_HRDATA30",
        164: "MCU_SLAVE_AHB_HRDATA31",
        165: "MCU_SLAVE_AHB_HSEL",
        166: "MCU_SLAVE_AHB_HREADY",
        167: "MCU_SLAVE_AHB_HTRANS0",
        168: "MCU_SLAVE_AHB_HTRANS1",
        169: "MCU_SLAVE_AHB_HSIZE0",
        170: "MCU_SLAVE_AHB_HSIZE1",
        171: "MCU_SLAVE_AHB_HSIZE2",
        172: "MCU_SLAVE_AHB_HBURST0",
        173: "MCU_SLAVE_AHB_HBURST1",
        174: "MCU_SLAVE_AHB_HBURST2",
        175: "MCU_SLAVE_AHB_HWRITE",
    }
    # A "bit" with BOTH entry+exit is a GPIO loopback pin (type MCU, DIN+DOUT). A bit with only an entry
    # is an MCU->fabric bus INPUT (type MCU_DIN, e.g. an AHB signal hwdata/hwrite/htrans); with only an
    # exit it's a fabric->MCU OUTPUT (type MCU_DOUT, e.g. GPIO observability or hrdata). This lets the AHB
    # slave model many MCU-driven bus inputs + a readback, not just DIN/DOUT pairs.
    for bit in sorted(set(bit_entry) | set(bit_exit)):
        has_e = bit in bit_entry; has_x = bit in bit_exit
        typ = _typed_mcu.get(
            bit, "MCU" if (has_e and has_x) else ("MCU_DIN" if has_e else "MCU_DOUT")
        )
        mcubel = "X%dY%d_%s%d" % (MCUX, MCUY, typ, bit)
        ctx.addBel(name=mcubel, type=typ, loc=Loc(MCUX, MCUY, bit), gb=False, hidden=False)
        if has_e:
            _entry_pin = "RESETN" if typ == "MCU_RESETN" else "DIN"
            ctx.addBelOutput(bel=mcubel, name=_entry_pin, wire=bit_entry[bit])   # MCU -> fabric
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

if "ctx" in globals() and "Loc" in globals():
    build_arch(ctx, Loc)
