# CONDUCTION-AWARE + EXIT-AWARE DENSE AUTO-PLACER for AHB-read designs (no hand-picked tiles).
# Bind the MCU_DOUT (hrdata) cells to their fixed exit bels, then backtracking-embed the post-pack FF
# dependency graph into the conducting directional tile-graph -- DENSELY (up to AGAMEMNON_TILE_CAP cells
# per tile, since intra-tile packing is silicon-proven). Every FF that DRIVES an hrdata read bit is
# anchored on a tile that conductingly reaches the hrdata exit tile (14,12). Every driver->consumer edge
# is satisfied either INTRA-TILE (same tile -- crossbar conducts) or by a PROVEN conducting inter-tile
# RMUX hop. Candidate tiles are ordered by reverse-BFS distance from the exit so logic clusters near the
# conducting exit lane (minimising inter-tile hops). Reuses the Qin model (self-feedback is internal, not
# a dep edge) + the vendor hrdata feeders (in master_conduction) + soft-prefer routing.
import os, csv, collections
strength = PlaceStrength.STRENGTH_FIXED
DATA      = os.environ["AGAMEMNON_DATA"]
EXIT_TILE = tuple(int(v) for v in os.environ.get("AGAMEMNON_EXIT_TILE", "14,12").split(","))
DOUT_BELS = os.environ.get("AGAMEMNON_DOUT_BELS",
                           "X10Y5_MCU_DOUT10,X10Y5_MCU_DOUT11,X10Y5_MCU_DOUT12,X10Y5_MCU_DOUT13").split(",")

def islogic(x, y):
    if x == 13: return False
    if 1 <= y <= 4: return x in (list(range(1, 13)) + list(range(14, 21)))
    return 14 <= x <= 20 if 5 <= y <= 12 else False

# directional conducting tile-graph = master_conduction (silicon + vendor_recon) U observed RRG
adj = collections.defaultdict(set); srcs = set()
def add_edges(path, only_observed):
    for r in csv.DictReader(open(path)):
        if only_observed and r.get("source") != "observed": continue
        s = (int(r["src_x"]), int(r["src_y"])); t = (int(r["dst_x"]), int(r["dst_y"]))
        if islogic(*s): srcs.add(s)
        if s != t and islogic(*s) and islogic(*t) \
           and r["src_res"].startswith("RMUX") and r["dst_res"].startswith("RMUX"):
            adj[s].add(t)
add_edges(os.path.join(DATA, "master_conduction.csv"), False)
rrg = os.path.join(DATA, "rrg_edges_full.csv")
if not os.environ.get("AGAMEMNON_COND_ONLY") and os.path.exists(rrg):
    add_edges(rrg, True)

# cells + post-pack dependency graph (Qin self-feedback is internal -> NOT a dep edge)
slices = []; douts = []; dins = []; cellobj = {}
for kv in ctx.cells:
    name = str(kv.first); cell = kv.second; cellobj[name] = cell; t = str(cell.type)
    if t == "MCU_DOUT": douts.append((name, cell))
    elif t in ("MCU_DIN", "MCU"): dins.append((name, cell, t))   # MCU-driven control input (freeze/sel)
    elif t == "GENERIC_SLICE" and "PACKER_GND" not in name: slices.append(name)

# exit-driver = the FF that drives each MCU_DOUT's DOUT net. Bind by CELL NAME (h<k>) so AHB bit k =
# hrdata[k] = the design's h<k> -- NOT iteration order (which scrambles the read-bit mapping).
import re as _re
# 8 hrdata exit lanes: bits 0-3 = the PROVEN bels MCU_DOUT10-13 (land in read word-bits 0-3); bits 4-7 =
# the 4 previously-unused bels MCU_DOUT0-3 (harvested exits, conduction UNVERIFIED -- widening the readout
# keyhole 4->8; the extra 4 are what a silicon read now characterizes). h(\d+) so h10+ also parse.
_DBEL = {0: "X10Y5_MCU_DOUT10", 1: "X10Y5_MCU_DOUT11", 2: "X10Y5_MCU_DOUT12", 3: "X10Y5_MCU_DOUT13",
         4: "X10Y5_MCU_DOUT0", 5: "X10Y5_MCU_DOUT1", 6: "X10Y5_MCU_DOUT2", 7: "X10Y5_MCU_DOUT3"}
exit_drvs = []
for i, (dn, dc) in enumerate(douts):
    _m = _re.search(r'h(\d+)', dn); _k = int(_m.group(1)) if _m else i
    bel = _DBEL.get(_k, DOUT_BELS[i % len(DOUT_BELS)])
    try:
        avail = ctx.checkBelAvail(bel)     # False if taken; raises if the bel doesn't exist
    except Exception:
        avail = False                      # non-existent bel -> skip (only bits 10-13 exist as MCU_DOUT)
    if not avail:
        print("PIN MCU_DOUT %s -> %s SKIPPED (bel absent/taken; only 4 pure MCU_DOUT lanes exist "
              "bits 10-13 -- widening needs more harvested hrdata exits)" % (dn, bel)); continue
    ctx.bindBel(bel, dc, strength); print("PIN MCU_DOUT %s -> %s (AHB bit %d)" % (dn, bel, _k))
    try:
        net = dc.ports["DOUT"].net
        drv = str(net.driver.cell.name) if net and net.driver and net.driver.cell else None
        if drv in slices: exit_drvs.append(drv); print("  hrdata driven by:", drv)
    except Exception as e:
        print("  DOUT trace failed:", e)

# MCU control INPUTS: bind each MCU_DIN cell to its DIN bel by CELL NAME (din<k> -> MCU_DIN bit k), so the
# observability harness knows which MCU-driven bit is freeze/sel<n>. Bits 0-3 are the proven GPIO-loopback
# entry wires (BufMUX10@(11,5), BufMUX00/02/04@(10,5)); a high-fanout control net (freeze) enters here and
# fans out through the mesh -- the router (not the placer) threads it to the gated FFs.
for i, (dn, dc, dt) in enumerate(dins):
    _m = _re.search(r'din(\d)', dn); _k = int(_m.group(1)) if _m else i
    bel = "X10Y5_%s%d" % (dt, _k)                     # MCU<k> (loopback) or MCU_DIN<k>, per cell type
    ctx.bindBel(bel, dc, strength); print("PIN %s %s -> %s (control bit %d)" % (dt, dn, bel, _k))

def out_net(cell):
    for p in ("Q", "F", "CO", "O"):
        if p in cell.ports and cell.ports[p].net: return cell.ports[p].net
    return None
deps = collections.defaultdict(set)                # driver -> {consumers} (excludes self = Qin internal)
for name in slices:
    net = out_net(cellobj[name])
    if not net: continue
    for u in net.users:
        cn = str(u.cell.name)
        if cn in slices and cn != name: deps[name].add(cn)
indeps = collections.defaultdict(set)
for dr, cs in deps.items():
    for c in cs: indeps[c].add(dr)

# BRAM-aware constraints: a placed ALTA_BRAM9K sits at BramTILE(13,4) and connects to the fabric at its
# boundary tile (14,4) (bram9k_edges: LogicTILE(14,4) RMUX <-> BramTILE IMUX/BufMUX). So FFs that DRIVE
# the BRAM address/data must be placed conducting-to (14,4), and FFs that READ DataOut (the pass-through
# regs) conducting-FROM (14,4). Without this condplace only reasons about slice->slice + exit, placing
# the counter far from the BRAM -> non-conducting address haul (silicon: addr stuck).
BRAM_BND = tuple(int(v) for v in os.environ.get("AGAMEMNON_BRAM_BND", "14,4").split(","))
bram_addr_drivers = set(); bram_out_readers = set()
_IN_PORTS = (["AddressA[%d]" % k for k in range(13)] + ["DataInA[%d]" % k for k in range(18)]
             + ["WeA", "ReA"])
_OUT_PORTS = ["DataOutA[%d]" % k for k in range(18)]
for kv in ctx.cells:
    c = kv.second
    if str(c.type) != "ALTA_BRAM9K": continue
    for pn in _IN_PORTS:                                    # inputs: driver FF must reach the BRAM
        if pn in c.ports and c.ports[pn].net:
            d = c.ports[pn].net.driver
            if d and d.cell and str(d.cell.name) in slices: bram_addr_drivers.add(str(d.cell.name))
    for pn in _OUT_PORTS:                                   # output: reader FF must be fed by the BRAM
        if pn in c.ports and c.ports[pn].net:
            for u in c.ports[pn].net.users:
                if str(u.cell.name) in slices: bram_out_readers.add(str(u.cell.name))
if bram_addr_drivers or bram_out_readers:
    print("BRAM-aware: %d addr/data driver FF(s), %d DataOut reader FF(s) anchored to boundary %s"
          % (len(bram_addr_drivers), len(bram_out_readers), BRAM_BND))
# reachability to/from the BRAM boundary over the conducting tile-graph (multi-hop)
def _bfs(seed, graph):
    dist = {seed: 0}; fr = [seed]
    while fr:
        nf = []
        for u in fr:
            for v in graph.get(u, ()):
                if v not in dist: dist[v] = dist[u] + 1; nf.append(v)
        fr = nf
    return dist
_radj = collections.defaultdict(set)
for s, ts in adj.items():
    for t in ts: _radj[t].add(s)
dist_to_bram = _bfs(BRAM_BND, _radj)    # hops from a tile TO the BRAM boundary (addr drivers)
dist_from_bram = _bfs(BRAM_BND, adj)    # hops FROM the BRAM boundary to a tile (DataOut readers)
to_bram = set(dist_to_bram); from_bram = set(dist_from_bram)

# ================================ DENSE MODE (opt-in, SILICON-UNVALIDATED) ============================
# AGAMEMNON_DENSE_PACK=1 enables the dense/exit-clustered placement (per-tile caps, reverse-BFS ordering,
# reserved feeder tile, intra-tile dep edges). It ROUTES on CPU up to 32-bit LFSRs BUT was REFUTED on
# silicon 2026-07-05: the 3-bit counter read distinct=2 (dead carry) vs distinct=4 with the default. The
# placer only guarantees tile-ADJACENCY conduction (adj), not which PIP the router picks; the dense/
# reverse-BFS tile assignment leads the router onto config-accepting-but-DEAD carry pips. DEFAULT stays
# the PROVEN behavior: 1 cell/tile, sorted(srcs) candidate order, strict inter-tile-conducting edges,
# no reserved exclusion -- byte-for-byte the pre-2026-07-05 logic (silicon distinct=4). Do NOT enable
# dense for silicon until it is gated on ACTUAL pip conduction (AGAMEMNON_CONDUCTION_GATE) + re-proven.
DENSE = bool(os.environ.get("AGAMEMNON_DENSE_PACK"))
# EVEN-SLOT binding (AGAMEMNON_EVENSLOT): bind cells to slots 0,2,4,..,14 so a consecutive-cell shift chain
# rides EVEN->EVEN intra-tile crossbar links -- the CONDUCTING regime (silicon-proven 2026-07-11). Consecutive
# slots 0->1 are the DEAD odd-slot crossbar (silently froze earlier dense packs). Caps 8 cells/tile.
EVENSLOT = bool(os.environ.get("AGAMEMNON_EVENSLOT"))
CAP      = int(os.environ.get("AGAMEMNON_TILE_CAP", ("8" if EVENSLOT else "4") if DENSE else "1"))
EXIT_CAP = int(os.environ.get("AGAMEMNON_EXIT_TILE_CAP", "3")) if DENSE else 1
def tcap(tile): return EXIT_CAP if tile == EXIT_TILE else CAP
if DENSE:
    # reverse-BFS distance from the exit tile over the conducting graph (cluster near exit).
    radj = collections.defaultdict(set)
    for s, ts in adj.items():
        for t in ts: radj[t].add(s)
    dist = {EXIT_TILE: 0}; frontier = [EXIT_TILE]
    while frontier:
        nf = []
        for t in frontier:
            for p in radj.get(t, ()):
                if p not in dist and islogic(*p): dist[p] = dist[t] + 1; nf.append(p)
        frontier = nf
    def reaches_exit(tile): return tile in dist
    RESERVED = set()
    for tok in os.environ.get("AGAMEMNON_RESERVED_TILES", "14,8").split(";"):
        tok = tok.strip()
        if tok: RESERVED.add(tuple(int(v) for v in tok.split(",")))
    cand = sorted((t for t in srcs if t in dist and t not in RESERVED), key=lambda t: (dist[t], t))
    if EXIT_TILE not in cand and EXIT_TILE in dist and EXIT_TILE not in RESERVED: cand.insert(0, EXIT_TILE)
    def edge_ok(ta, tb): return ta == tb or tb in adj.get(ta, ())   # dense: allow intra-tile crossbar
else:
    # PROVEN default (pre-dense): sorted candidate tiles, strict inter-tile-conducting edges only.
    def reaches_exit(tile): return tile == EXIT_TILE or EXIT_TILE in adj.get(tile, ())
    cand = sorted(srcs)
    def edge_ok(ta, tb): return tb in adj.get(ta, ())              # strict inter-tile conducting hop
# CLUSTER ORDER (AGAMEMNON_CLUSTER_ORDER): the clustering half of the silicon-proven recipe (harvest +
# natsort/cluster + even-slot + hard-gate, 2026-07-11). BFS the cell-connectivity graph from the exit-drivers
# so CONNECTED cells are placed consecutively -> the dense packer co-tiles a connected sub-chain (minimising
# inter-tile crossings), instead of scattering by degree (which forces the router to spill through the mesh).
if os.environ.get("AGAMEMNON_CLUSTER_ORDER"):
    _cadj = collections.defaultdict(set)
    for _d, _cs in deps.items():
        for _c in _cs:
            _cadj[_d].add(_c); _cadj[_c].add(_d)
    _seen = set(); order = []
    _dq = collections.deque()
    for _seed in ([s for s in exit_drvs if s in slices] + sorted(slices)):
        if _seed in _seen:
            continue
        _dq.append(_seed)
        while _dq:
            _u = _dq.popleft()
            if _u in _seen or _u not in slices:
                continue
            _seen.add(_u); order.append(_u)
            for _v in sorted(_cadj.get(_u, ())):
                if _v not in _seen:
                    _dq.append(_v)
else:
    # place the most-constrained first: exit-drivers, then high-degree
    order = sorted(slices, key=lambda n: (0 if n in exit_drvs else 1, -(len(deps[n]) + len(indeps[n]))))
assign = {}; occ = collections.defaultdict(int)     # tile -> #cells placed (dense; up to CAP)
def feasible(cell, tile):
    if occ[tile] >= tcap(tile): return False
    if cell in exit_drvs and not reaches_exit(tile): return False
    if cell in bram_addr_drivers and tile not in to_bram: return False    # must reach BRAM boundary
    if cell in bram_out_readers and tile not in from_bram: return False   # BRAM must reach it
    for c in deps[cell]:                             # cell drives c: cell.tile -> c.tile must conduct
        if c in assign and not edge_ok(tile, assign[c]): return False
    for dr in indeps[cell]:                          # dr drives cell: dr.tile -> cell.tile must conduct
        if dr in assign and not edge_ok(assign[dr], tile): return False
    return True
def bt(i):
    if i == len(order): return True
    cell = order[i]
    cands = cand
    if cell in exit_drvs: cands = [t for t in cands if reaches_exit(t)]
    if cell in bram_out_readers:                                                  # BRAM->reader FF
        cands = sorted([t for t in cands if t in from_bram], key=lambda t: (dist_from_bram[t], t))
    if cell in bram_addr_drivers:
        # Route the address IN via the CONDUCTING x=14 BRAM-I/O column (14,y)->(14,4)->IMUX, matching the
        # vendor + the working DataOut exit -- NOT from (14,4) itself (dead intra-tile) or arbitrary mesh
        # hops. Candidates = the x=14 column ABOVE the boundary (y 5..11), nearest-BRAM first.
        col = os.environ.get("AGAMEMNON_BRAM_COL", "14")
        cx = int(col)
        # STRICTLY above the boundary row (y > BRAM_BND.y): an FF AT (14,4) can't cleanly drive the (14,4)
        # boundary RMUX (nextpnr detours out-and-back via dead edges); placing it above routes straight
        # DOWN the conducting column (14,y)->(14,4)->IMUX, exactly like the vendor.
        colc = [t for t in cands if t[0] == cx and t[1] > BRAM_BND[1] and t in to_bram]
        cands = sorted(colc if colc else [t for t in cands if t in to_bram],
                       key=lambda t: (dist_to_bram[t], t))
    for tile in cands:
        if feasible(cell, tile):
            assign[cell] = tile; occ[tile] += 1
            if bt(i + 1): return True
            del assign[cell]; occ[tile] -= 1
    return False

if bt(0):
    slot = collections.defaultdict(int)             # per-tile slice-index allocator (dense)
    for cell in order:                              # bind in placement order for deterministic slots
        tile = assign[cell]; _si = slot[tile]; slot[tile] += 1
        z = 2 * _si if EVENSLOT else _si            # even-slot -> even->even conducting crossbar (proven)
        b = "X%dY%d_SLICE%d" % (tile[0], tile[1], z)
        ctx.bindBel(b, cellobj[cell], strength)
        print("PIN %s -> %s%s" % (cell[:32], b, " (hrdata-driver)" if cell in exit_drvs else ""))
    ntiles = len(set(assign.values())); mx = max(occ.values()) if occ else 0
    print("PINPROBE ahb_condplace: auto-embedded %d FFs on %d conducting tiles (max %d/tile, dense) + %d "
          "hrdata exits" % (len(assign), ntiles, mx, len(douts)))
else:
    print("PINPROBE ahb_condplace: NO conducting embedding for this dependency graph with the current "
          "map -> auto-placement hit the dead-carry frontier (densify master_conduction, add feeders, or "
          "raise AGAMEMNON_TILE_CAP).")
    raise SystemExit("ahb_condplace: no conducting embedding (dead carry frontier)")
