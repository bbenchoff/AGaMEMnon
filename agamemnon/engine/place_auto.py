# CONDUCTION-AWARE + EXIT-AWARE DENSE AUTO-PLACER for AHB-read designs (no hand-picked tiles).
# Bind the MCU_DOUT (hrdata) cells to their fixed exit bels, then backtracking-embed the post-pack FF
# dependency graph into the conducting directional tile-graph -- DENSELY (up to AGAMEMNON_TILE_CAP cells
# per tile, since intra-tile packing is silicon-proven). Every FF that DRIVES an hrdata read bit is
# anchored on a tile that conductingly reaches the hrdata exit tile (14,12). Every driver->consumer edge
# is satisfied either INTRA-TILE (same tile -- crossbar conducts) or by a PROVEN conducting inter-tile
# RMUX hop. Candidate tiles are ordered by reverse-BFS distance from the exit so logic clusters near the
# conducting exit lane (minimising inter-tile hops). Reuses the Qin model (self-feedback is internal, not
# a dep edge) + the vendor hrdata feeders (in master_conduction) + soft-prefer routing.
import os, csv, collections, json
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

# Bind top-level I/O cells to real package pads from a PCF. Cell names are produced by yosys iopadmap
# as `$iopadmap$top.<port>`. Inputs use the pad's IPAD bel; outputs use its OPAD bel.
_pcf = json.loads(os.environ.get("AGAMEMNON_PCF_JSON", "{}"))
_io_cells = []
_left_input_consumer_bels = {}
_left_input_bel_consumers = {}
if _pcf:
    from agamemnon.engine import device as _device
    from agamemnon.engine import pcf_ports as _pcf_ports
    _dev = _device.device_from_env()
    # Yosys iopadmap does not preserve bracket notation: the bits of
    # `output [3:0] led` arrive as cells named led, led_1, led_2, led_3.  An
    # ordinary `set_io led[0] PIN_25` therefore matched no cell at all, and this
    # loop used to `continue` past the miss -- leaving the pads to the placer,
    # which bound one to an input-only pad bel and the router died much later
    # with "bel 'X14Y13_IPAD0' has no pin 'I'".  Nothing said the constraint had
    # been ignored.  Accept both spellings, and fail closed below on any
    # constraint that binds nothing.  pcf_bind_json.py resolves the same
    # relation authoritatively for the uarch flow, through the JSON port bits.
    _pcf_alias = _pcf_ports.alias_map(_pcf)
    _pcf_seen, _pcf_seen_ports = set(), []
    for kv in ctx.cells:
        _name, _cell = str(kv.first), kv.second
        if str(_cell.type) != "GENERIC_IOB":
            continue
        _port = _name.split("$iopadmap$top.", 1)[-1]
        _pcf_seen_ports.append(_port)
        _key = _pcf_alias.get(_port)
        if _key is None:
            continue
        _pcf_seen.add(_key)
        _pin = _pcf[_key]
        _pad = _dev.pin_to_pad(_pin)
        if _pad is None:
            raise SystemExit("PCF: %s has no physical bond-map entry for %s on %s"
                             % (_port, _pin, _dev.name))
        _x, _y, _z, _edge = _pad
        _is_input = "O" in _cell.ports and _cell.ports["O"].net
        _is_output = "I" in _cell.ports and _cell.ports["I"].net
        if _is_input and _is_output:
            raise SystemExit("PCF: bidirectional port %s is not supported yet" % _port)
        if _is_input:
            _bel = "X%dY%d_IPAD%d" % (_x, _y, _z)
        elif _is_output:
            _bel = "X%dY%d_OPAD%d" % (_x, _y, _z)
        else:
            raise SystemExit("PCF: cannot determine direction of port %s" % _port)
        try:
            ctx.bindBel(_bel, _cell, strength)
        except Exception as _e:
            raise SystemExit("PCF: cannot bind %s (%s) to %s: %s" % (_port, _pin, _bel, _e))
        _io_cells.append((_port, _cell, (_x, _y), _is_input))
        if _is_input and (_x, _y) == (0, 4):
            _targets = {}
            with open(os.path.join(DATA, "pad_input_L48_left_corridors.csv"),
                      newline="", encoding="utf-8") as _stream:
                for _row in csv.DictReader(_stream):
                    if not _row.get("cell_table"):
                        _targets[_row["pin"]] = _row["target_bel"]
            _target = _targets.get(_pin)
            _net = _cell.ports["O"].net
            _users = sorted({str(_u.cell.name) for _u in _net.users
                             if str(_u.cell.type) == "GENERIC_SLICE"})
            if _target is None or len(_users) != 1:
                raise SystemExit(
                    "PCF: left-edge input %s needs one exact corridor consumer; "
                    "target=%s consumers=%s" % (_pin, _target, _users)
                )
            _user = _users[0]
            _prior_target = _left_input_consumer_bels.get(_user)
            if _prior_target is not None and _prior_target != _target:
                raise SystemExit(
                    "PCF: left-edge inputs feeding %s require incompatible exact "
                    "corridor bels %s and %s" % (_user, _prior_target, _target)
                )
            _prior_user = _left_input_bel_consumers.get(_target)
            if _prior_user is not None and _prior_user != _user:
                raise SystemExit(
                    "PCF: left-edge input consumers %s and %s both require exact bel %s"
                    % (_prior_user, _user, _target)
                )
            _left_input_consumer_bels[_user] = _target
            _left_input_bel_consumers[_target] = _user
            print("PIN PCF left-input consumer %s -> %s" % (_user, _target))
        print("PIN PCF %s=%s -> %s" % (_key, _pin, _bel))
    _pcf_missed = sorted(set(_pcf) - _pcf_seen)
    if _pcf_missed:
        raise SystemExit(
            "PCF: %s named no top-level I/O port of this design.  The design's "
            "pads are: %s.  (Yosys names the bits of a vector port `p`, `p_1`, "
            "`p_2`...; both `p[1]` and `p_1` are accepted.)"
            % (", ".join("%s=%s" % (_m, _pcf[_m]) for _m in _pcf_missed),
               ", ".join(sorted(_pcf_seen_ports)) or "(none)"))

if _pcf:
    # The clock IOB is not a package pad and is never named in a PCF, so it used
    # to be left to the placer -- which put it on an output-only pad bel and the
    # router died with "bel 'X8Y0_OPAD3' has no pin 'O'". Whether that happened
    # depended on how many other IOBs were in the design, so a one-output build
    # failed where a two-output build of the same shape succeeded. Bind it.
    for kv in ctx.cells:
        _name, _cell = str(kv.first), kv.second
        if str(_cell.type) != "GENERIC_IOB":
            continue
        _port = _name.split("$iopadmap$top.", 1)[-1]
        if _port in _pcf or _cell.bel is not None:
            continue
        if "clk" not in _port.lower():
            continue
        ctx.bindBel("CLKIN", _cell, strength)
        print("PIN PCF clock %s -> CLKIN" % _port)

# exit-driver = the FF that drives each MCU_DOUT's DOUT net. Bind by CELL NAME (h<k>) so AHB bit k =
# hrdata[k] = the design's h<k> -- NOT iteration order (which scrambles the read-bit mapping).
import re as _re
# All 32 hrdata exits are recovered.  Internal BEL ids 20..22 belong to the
# qualified AHB inputs, so outputs 10..31 continue at BEL ids 23..44.
_DBEL = {k: "X10Y5_MCU_DOUT%d" % (10 + k if k <= 9 else 13 + k) for k in range(32)}
exit_drvs = []
for i, (dn, dc) in enumerate(douts):
    _m = _re.search(r'h(\d+)', dn); _k = int(_m.group(1)) if _m else i
    bel = _DBEL.get(_k)
    if bel is None:
        raise SystemExit("MCU_DOUT %s requests hrdata bit %d; valid range is 0..31" % (dn, _k))
    try:
        avail = ctx.checkBelAvail(bel)     # False if taken; raises if the bel doesn't exist
    except Exception:
        avail = False
    if not avail:
        print("PIN MCU_DOUT %s -> %s SKIPPED (bel absent/taken; valid hrdata range is 0..31)"
              % (dn, bel)); continue
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
    _hm = _re.search(r'hwdata(\d+)', dn)
    _ha = _re.search(r'haddr(\d+)', dn)
    if _hm:
        _hb = int(_hm.group(1)); _k = 20 if _hb == 0 else 44 + _hb
    elif _ha:
        _ab = int(_ha.group(1))
        if 2 <= _ab <= 27:
            _k = 74 + _ab
        elif _ab in (0, 1):
            _k = 112 + _ab
        elif 28 <= _ab <= 31:
            _k = 86 + _ab
        else:
            raise RuntimeError("MCU HADDR bit outside recovered range 0..31: %d" % _ab)
    elif 'hwrite' in dn:
        _k = 21
    elif 'htrans1' in dn:
        _k = 22
    else:
        _m = _re.search(r'din(\d+)', dn); _k = int(_m.group(1)) if _m else i
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

# I/O-adjacent logic should stay near its real pads. This is a placement cost, not a hard routing
# promise; nextpnr still proves whether a path exists on the device graph.
io_anchors = collections.defaultdict(list)
for _port, _ioc, _xy, _is_input in _io_cells:
    try:
        if _is_input:
            _net = _ioc.ports["O"].net
            for _u in _net.users:
                _cn = str(_u.cell.name)
                if _cn in slices:
                    io_anchors[_cn].append(_xy)
        else:
            _net = _ioc.ports["I"].net
            _d = _net.driver
            if _d and _d.cell and str(_d.cell.name) in slices:
                io_anchors[str(_d.cell.name)].append(_xy)
    except Exception:
        pass

# A physical multi-LUT cone must converge where both its characterized pad inputs and its output feeder
# exist. For the proven L48 top-edge set that is the LogicTile directly below the single output pad.
# Cluster there on even slice slots: slice0 remains the output/root (known OMUX02->PIN16 path), while
# upstream LUTs occupy the silicon-proven even-slot intra-tile regime. This is deliberately limited to
# physical-PCF builds with one output; the general MCU/BRAM placer remains unchanged.
PHYSICAL_CLUSTER = None
if (os.environ.get("AGAMEMNON_PHYSICAL_IO") and len(slices) > 1
        and not any(_is_input and _xy == (0, 4)
                    for _port, _ioc, _xy, _is_input in _io_cells)):
    _physical_outputs = [_xy for _port, _ioc, _xy, _is_input in _io_cells if not _is_input]
    if len(_physical_outputs) == 1 and _physical_outputs[0][1] == 13:
        PHYSICAL_CLUSTER = (_physical_outputs[0][0], 12)
        print("PHYSICAL-PCF multi-LUT cone: cluster %d cell(s) at X%dY%d on even slots"
              % (len(slices), PHYSICAL_CLUSTER[0], PHYSICAL_CLUSTER[1]))

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
DENSE = bool(os.environ.get("AGAMEMNON_DENSE_PACK")) or PHYSICAL_CLUSTER is not None
# EVEN-SLOT binding (AGAMEMNON_EVENSLOT): bind cells to slots 0,2,4,..,14 so a consecutive-cell shift chain
# rides EVEN->EVEN intra-tile crossbar links -- the CONDUCTING regime (silicon-proven 2026-07-11). Consecutive
# slots 0->1 are the DEAD odd-slot crossbar (silently froze earlier dense packs). Caps 8 cells/tile.
EVENSLOT = bool(os.environ.get("AGAMEMNON_EVENSLOT")) or PHYSICAL_CLUSTER is not None
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
_forced_bel = os.environ.get("AGAMEMNON_PIN")
_forced_cell = _forced_tile = None
if _forced_bel and len(slices) == 1:
    _fm = _re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", _forced_bel)
    if not _fm:
        raise SystemExit("AGAMEMNON_PIN must be X<n>Y<n>_SLICE<n>, got %s" % _forced_bel)
    _forced_cell = slices[0]
    _forced_tile = (int(_fm.group(1)), int(_fm.group(2)))

# AGAMEMNON_PIN_CELLS="<net>=X<n>Y<n>_SLICE<n>;..." pins several flip-flops at
# once, keyed by the NET each one drives.  Cell names cannot be used: yosys emits
# `$auto$ff.cc:337:slice$79`, so matching on a design-level name like `q0` silently
# matches nothing -- which is exactly how an earlier campaign spent a day
# measuring images whose flip-flops were never pinned at all ("pinned 3" when it
# should have said 5).  A conduction experiment needs this: the toggle source has
# to sit on the far side of a geometric cut, or the placer legally puts every cell
# on the near side, nothing crosses the edge under test, and the pad still toggles
# -- a false positive.  AGAMEMNON_PIN only ever handled a single-slice design.
_pin_bel = {}                                   # cell name -> exact bel
_pin_tile = {}                                  # cell name -> (x, y)
_pin_bel_owner = {}                             # exact bel -> cell name

def _claim_pin_bel(_cname, _bel_name, _origin):
    """Merge mandatory placement claims without silent overwrite/collision."""
    _prior_bel = _pin_bel.get(_cname)
    if _prior_bel is not None and _prior_bel != _bel_name:
        raise SystemExit(
            "%s: cell %s is already required at %s, cannot also pin it to %s"
            % (_origin, _cname, _prior_bel, _bel_name)
        )
    _prior_cell = _pin_bel_owner.get(_bel_name)
    if _prior_cell is not None and _prior_cell != _cname:
        raise SystemExit(
            "%s: cells %s and %s both require exact bel %s"
            % (_origin, _prior_cell, _cname, _bel_name)
        )
    _bm = _re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", _bel_name)
    if not _bm:
        raise SystemExit("%s: bad target bel %s" % (_origin, _bel_name))
    _pin_bel[_cname] = _bel_name
    _pin_bel_owner[_bel_name] = _cname
    _pin_tile[_cname] = (int(_bm.group(1)), int(_bm.group(2)))

for _cname, _bel_name in _left_input_consumer_bels.items():
    if _cname not in slices:
        raise SystemExit("left-edge input consumer %s is not a placeable slice" % _cname)
    _claim_pin_bel(_cname, _bel_name, "left-edge input corridor")
_pin_spec = os.environ.get("AGAMEMNON_PIN_CELLS", "").strip()
if _pin_spec:
    _pin_want = {}
    for _entry in _pin_spec.replace(",", ";").split(";"):
        if not _entry.strip():
            continue
        if "=" not in _entry:
            raise SystemExit("AGAMEMNON_PIN_CELLS entry %r is not <net>=<bel>" % _entry)
        _net_name, _bel_name = (part.strip() for part in _entry.split("=", 1))
        if not _re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", _bel_name):
            raise SystemExit("AGAMEMNON_PIN_CELLS: %r is not X<n>Y<n>_SLICE<n>" % _bel_name)
        _pin_want[_net_name] = _bel_name
    for kv in ctx.nets:
        _net_name, _net = str(kv.first), kv.second
        if _net_name not in _pin_want:
            continue
        _drv = getattr(_net, "driver", None)
        _dcell = getattr(_drv, "cell", None) if _drv is not None else None
        if _dcell is None or str(_dcell.type) != "GENERIC_SLICE":
            continue
        _cname = str(_dcell.name)
        if _cname not in slices:
            continue
        _bel_name = _pin_want.pop(_net_name)
        _bm = _re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", _bel_name)
        _claim_pin_bel(_cname, _bel_name, "AGAMEMNON_PIN_CELLS")
        print("PIN CELLS %s (%s) -> %s" % (_net_name, _cname[:40], _bel_name))
    if _pin_want:
        raise SystemExit(
            "AGAMEMNON_PIN_CELLS: %s named no net driven by a placeable slice; "
            "an unpinned experiment measures the wrong thing, so this is fatal. "
            "Placeable nets: %s"
            % (", ".join(sorted(_pin_want)),
               ", ".join(sorted(str(kv.first) for kv in ctx.nets)[:40])))
if len(set(_pin_bel.values())) != len(_pin_bel):
    raise SystemExit("two placement constraints pinned different cells to the same bel")
if (_forced_cell in _pin_bel and _pin_bel[_forced_cell] != _forced_bel):
    raise SystemExit(
        "AGAMEMNON_PIN conflicts with mandatory exact placement %s for %s"
        % (_pin_bel[_forced_cell], _forced_cell)
    )

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
    if PHYSICAL_CLUSTER is not None:
        cands = [PHYSICAL_CLUSTER]
    if cell == _forced_cell:
        cands = [_forced_tile]
    if cell in _pin_tile:
        cands = [_pin_tile[cell]]
    if io_anchors.get(cell):
        cands = sorted(cands, key=lambda t: (sum(abs(t[0]-a[0]) + abs(t[1]-a[1])
                                                      for a in io_anchors[cell]), t))
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
        tile = assign[cell]
        if cell in _pin_bel:                        # explicit bel: do not consume a slot index
            b = _pin_bel[cell]
        else:
            _si = slot[tile]; slot[tile] += 1
            z = 2 * _si if EVENSLOT else _si        # even-slot -> even->even conducting crossbar (proven)
            b = _forced_bel if cell == _forced_cell else "X%dY%d_SLICE%d" % (tile[0], tile[1], z)
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
