#!/usr/bin/env python3
"""LogicTile mesh crossbar resolver, built from the DECODED vendor tile template.

Source of truth: `tools/agamemnon/archdec_cfg/alta_tile_agr_cfg.csv` (the vendor per-LogicTile config
template, decoded via the AsciiEncrypt codec). It enumerates, for every dest mux instance
(CFG_RMUXk / CFG_IMUXk / CFG_OMUXk / ...), the complete fan-in as a (W_row, B_col) grid whose cells
name the exact config-chain sel bit. See MESH_TEMPLATE_FOUND.md / MESH_TEMPLATE_INTEGRATION.md.

Two capabilities:
  1. legal_sels(fam, inst)  -> the exact set of sel bits that instance's mux can drive (its fan-in).
     Use this to PRUNE the nextpnr arch to only real edges (the far-link fix: nextpnr otherwise picks
     mux inputs that do not physically exist).
  2. resolve(dst_fam, dst_idx, src_fam, src_idx, dx, dy) -> (lo_sel, hi_sel) absolute sel pair.
     A routed edge lights TWO chain bits (a lo + a hi) at block = dst_group_offset*BS (BS: RMUX 10,
     IMUX 12). The local (lo,hi) is looked up from a majority table learned off the vendor corpus
     (mesh_resolver_table.json); the block offset is the deterministic go*BS rule (holds 99.81%).

Config-bit location (byte,mask) still comes from chipdb/pips_full.csv (unchanged, silicon-proven).
"""
import os, csv, re, json, collections

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(os.path.dirname(HERE))
CFGDIR = os.path.join(os.path.dirname(HERE), "archdec_cfg")
CHIPDB = os.path.join(os.path.dirname(HERE), "chipdb")
TEMPLATE = os.path.join(CFGDIR, "alta_tile_agr_cfg.csv")
TABLE = os.path.join(HERE, "mesh_resolver_table.json")

BS = {"RMUX": 10, "IMUX": 12}          # sel block size per family (block = group_offset * BS)
NODES_PER_INST = {"RMUX": 6, "IMUX": 4}  # dst_idx // this = instance ; dst_idx % this = group_offset


def parse_template(path=TEMPLATE):
    """-> dict: (fam, inst) -> {sel: (W_row, B_col)}  for every mux in the tile template."""
    fanin = collections.defaultdict(dict)
    rows = list(csv.reader(open(path)))
    for line in rows[1:]:
        if not line or not line[0].startswith("W"):
            continue
        w = int(line[0][1:])
        for b, cell in enumerate(line[1:]):
            m = re.match(r"(CFG_[A-Za-z]+)(\d+)<(\d+)>", cell.strip())
            if not m:
                continue
            fam = m.group(1)[4:]           # strip 'CFG_'
            inst = int(m.group(2))
            sel = int(m.group(3))
            fanin[(fam, inst)][sel] = (w, b)
    return dict(fanin)


_FANIN = None
_TABLE = None


def _load():
    global _FANIN, _TABLE
    if _FANIN is None:
        _FANIN = parse_template()
    if _TABLE is None:
        _TABLE = json.load(open(TABLE)) if os.path.exists(TABLE) else {"full": {}, "modl": {}}
    return _FANIN, _TABLE


def legal_sels(fam, inst):
    """Exact set of sel bits mux (fam,inst) can drive = its physical fan-in. () if unknown."""
    fanin, _ = _load()
    return set(fanin.get((fam, inst), {}).keys())


def instance_of(fam, dst_idx):
    n = NODES_PER_INST[fam]
    return dst_idx // n, dst_idx % n         # (instance, group_offset)


def resolve(dst_fam, dst_idx, src_fam, src_idx, dx, dy):
    """-> (lo_sel, hi_sel) absolute sels for the routed edge, or None if unresolved.
    block = group_offset*BS (deterministic); local (lo,hi) from the corpus-majority table."""
    if dst_fam not in BS:
        return None
    _, tbl = _load()
    inst, go = instance_of(dst_fam, dst_idx)
    block = go * BS[dst_fam]
    # hierarchical lookup: exact geometry -> group_offset+src_idx -> modular fallback
    k0 = "|".join(map(str, (dst_fam, dst_idx, src_fam, src_idx, dx, dy)))
    k1 = "|".join(map(str, (dst_fam, go, src_fam, src_idx, dx, dy)))
    k2 = "|".join(map(str, (dst_fam, src_fam, dx, dy, src_idx % 16)))
    lp = tbl.get("L0", {}).get(k0) or tbl.get("L1", {}).get(k1) or tbl.get("L2", {}).get(k2)
    if lp is None:
        return None
    lo, hi = block + lp[0], block + lp[1]
    # guard: the resolved sels must be a legal fan-in of this instance (template check)
    ls = legal_sels(dst_fam, inst)
    if ls and (lo not in ls or hi not in ls):
        return None
    return lo, hi


_PIPS = None


def cfg_bits(x, y, dst_fam, inst, lo, hi):
    """-> [(byte,mask),(byte,mask)] for the two sels, via chipdb/pips_full.csv."""
    global _PIPS
    if _PIPS is None:
        _PIPS = {}
        p = os.path.join(CHIPDB, "pips_full.csv")
        for r in csv.DictReader(open(p)):
            _PIPS[(int(r["x"]), int(r["y"]), r["mux"], int(r["sel"]))] = (int(r["byte"]), int(r["mask"]))
    mux = "CFG_%s%d" % (dst_fam, inst)
    out = []
    for s in (lo, hi):
        bm = _PIPS.get((x, y, mux, s))
        if bm:
            out.append(bm)
    return out


# ------------------------------------------------------------------ self-validation
def _selfcheck():
    fanin, tbl = _load()
    print("template muxes: %d instances; RMUX0 fan-in=%d IMUX0 fan-in=%d"
          % (len(fanin), len(legal_sels("RMUX", 0)), len(legal_sels("IMUX", 0))))
    # cross-check legal_sels vs pips_full
    p = os.path.join(CHIPDB, "pips_full.csv")
    if os.path.exists(p):
        pf = collections.defaultdict(set)
        for r in csv.DictReader(open(p)):
            pf[r["mux"]].add(int(r["sel"]))
        for fam, inst in [("RMUX", 0), ("RMUX", 7), ("IMUX", 0), ("IMUX", 5)]:
            t = legal_sels(fam, inst); q = pf.get("CFG_%s%d" % (fam, inst), set())
            print("  %s%d: template=%d pips=%d  missing_in_pips=%s"
                  % (fam, inst, len(t), len(q), sorted(t - q)[:5]))
    # held-out resolver accuracy from sel_dataset (if present)
    ds = os.path.join(os.path.dirname(HERE), "sel_dataset.csv")
    if not os.path.exists(ds):
        print("sel_dataset.csv absent -> skipping held-out accuracy")
        return
    import csv as _c
    _c.field_size_limit(10 ** 7)
    edges = {}; feat = {}
    for r in _c.DictReader(open(ds, newline="")):
        fam = r["dst_fam"]
        if fam not in BS:
            continue
        k = (r["build"], r["dst_res"], r["src_res"], r["dst_x"], r["dst_y"], r["src_x"], r["src_y"])
        try:
            sel = int(r["sel"])
        except ValueError:
            continue
        edges.setdefault(k, set()).add(sel)
        feat.setdefault(k, (fam, int(r["dst_x"]), int(r["dst_y"]), int(r["dst_idx"]),
                            r["src_fam"], int(r["src_idx"]), int(r["dx"]), int(r["dy"]), r["build"]))
    builds = sorted({feat[k][8] for k in edges})
    test = set(builds[::5])
    for fam in ("RMUX", "IMUX"):
        tot = hit = 0
        for k, v in edges.items():
            f = feat[k]
            if f[0] != fam or f[8] not in test or len(v) != 2:
                continue
            tot += 1
            got = resolve(f[0], f[3], f[4], f[5], f[6], f[7])
            if got and tuple(sorted(got)) == tuple(sorted(v)):
                hit += 1
        if tot:
            print("HELD-OUT %s: byte-exact sel-pair %d/%d = %.1f%%" % (fam, hit, tot, 100 * hit / tot))


if __name__ == "__main__":
    _selfcheck()
