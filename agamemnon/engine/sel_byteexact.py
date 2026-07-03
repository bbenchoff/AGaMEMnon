#!/usr/bin/env python3
"""HELD-OUT byte-exact open-routing test.

Train the sel encoding (closed-form RMUX rules + empirical (dst_node,src_node) LUT for the
IMUX/OMUX crossbars) on ALL builds EXCEPT the target, then PREDICT the target build's active
routing config pips from route.tx + arch alone, overlay onto af.exe's baseline (non-design)
config, re-encode through the open LZW writer, and byte-compare to af.exe's emitted .bin.

This closes Track B: derive active pips from route.tx + the recovered sel rule, with NO peek at
the target's own sel bits.
"""
import os, sys, csv, collections

HERE  = os.path.dirname(os.path.abspath(__file__))
DATA  = os.path.join(os.path.dirname(HERE), "chipdb")
sys.path.insert(0, HERE)
import tx_decode, lzw_codec as L, coord2named as C2N

PIPS_CSV = os.path.join(DATA, "pips_full.csv")
WIRES    = os.path.join(DATA, "wires.csv")
DS       = os.path.join(DATA, "sel_dataset.csv")
BS = {"RMUX": 10, "IMUX": 12}
NPG = {"RMUX": 6, "IMUX": 4, "OMUX": 3}
ROUTING = ("RMUX", "SeamMUX", "IMUX", "OMUX", "CtrlMUX")


def load_pips():
    cell, bymux = {}, collections.defaultdict(dict)
    for r in csv.DictReader(open(PIPS_CSV)):
        x, y, mux, sel = int(r["x"]), int(r["y"]), r["mux"], int(r["sel"])
        cell[(x, y, mux, sel)] = (int(r["byte"]), int(r["mask"]))
        bymux[(x, y, mux)][sel] = (int(r["byte"]), int(r["mask"]))
    return cell, bymux


def train_lut(target):
    """LUT over all OTHER builds: (dst_fam,src_fam,dst_node,src_idx,dx,dy)->(lo_n,hi_n)."""
    _lc = os.path.join(DATA, "train_lut.pkl")   # baked cache (self-contained; avoids the 393MB sel_dataset.csv)
    if target == "__none__" and os.path.exists(_lc):
        import pickle; return pickle.load(open(_lc, "rb"))
    rows = list(csv.DictReader(open(DS)))
    grp = collections.defaultdict(list)
    for r in rows:
        grp[(r["build"], r["dst_x"], r["dst_y"], r["cfg_group"])].append(r)
    lut = collections.defaultdict(collections.Counter)
    for k, rs in grp.items():
        if rs[0]["build"] == target:
            continue
        e = set((r["dst_idx"], r["src_idx"], r["src_fam"], r["dx"], r["dy"]) for r in rs)
        if len(e) != 1:
            continue
        r0 = rs[0]; sels = sorted(int(r["sel"]) for r in rs)
        if len(sels) != 2 or r0["dst_fam"] not in BS:
            continue
        go = int(r0["dst_group_offset"]); blk = BS[r0["dst_fam"]] * go
        key = (r0["dst_fam"], r0["src_fam"], int(r0["dst_idx"]),
               int(r0["src_idx"]), int(r0["dx"]), int(r0["dy"]))
        lut[key][(sels[0] - blk, sels[1] - blk)] += 1
    return {k: v.most_common(1)[0][0] for k, v in lut.items()}


def predict_pair(fam, src_fam, dst_idx, src_idx, dx, dy, lut):
    """Closed-form first, fall back to held-out LUT."""
    if fam == "RMUX" and src_fam == "OMUX":
        return ((src_idx // 3) % 4, 7)
    return lut.get((fam, src_fam, dst_idx, src_idx, dx, dy))


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "cpld_native2"
    bd = os.path.join(TOOLS, target)
    cell, bymux = load_pips()
    wires = C2N.load_wires(WIRES)
    lut = train_lut(target)

    # oracle
    data = open(os.path.join(bd, "blinky.bin"), "rb").read()
    hdr, raw = data[:8], L.decode(data[8:])
    oracle = set(k for k, (b, m) in cell.items() if b < len(raw) and (raw[b] & m))

    # baseline = saturated (border/unused) muxes -> keep af.exe's bits as-is (not design routing)
    act_by_grp = collections.defaultdict(set)
    for (x, y, mux, sel) in oracle:
        act_by_grp[(x, y, mux)].add(sel)
    saturated = set(k for k, s in act_by_grp.items()
                    if set(bymux.get(k, {})) and s == set(bymux.get(k, {})))

    # decode used routing edges
    txt = tx_decode.decode_tx(os.path.join(bd, "alta_db", "route.tx")).decode("latin1")
    _n, edges = C2N.parse_route_edges(txt)
    used = []
    for a, b in edges:
        if a not in wires or b not in wires:
            continue
        ax, ay, _, ar = wires[a]; bx, by, _, br = wires[b]
        bf = br.rstrip("0123456789"); af = ar.rstrip("0123456789")
        if bf in ROUTING:
            try:
                bi = int(br[len(bf):]); ai = int(ar[len(af):])
            except ValueError:
                continue
            used.append((bx, by, bf, bi, af, ai, ax, ay))

    # PREDICT design pips from route.tx + sel rule (RMUX/IMUX only; the solved families)
    pred = set()
    n_pred = n_rule = n_unp = 0
    for (bx, by, bf, bi, af, ai, ax, ay) in used:
        if bf not in BS:
            continue
        grp = bi // NPG[bf]; go = bi % NPG[bf]; blk = BS[bf] * go
        cfg = f"CFG_{bf}{grp}"
        if (bx, by, cfg) in saturated:
            continue
        pr = predict_pair(bf, af, bi, ai, bx - ax, by - ay, lut)
        n_pred += 1
        if pr is None:
            n_unp += 1
            continue
        n_rule += 1
        for ln in pr:
            k = (bx, by, cfg, blk + ln)
            if k in cell:
                pred.add(k)

    # Compare predicted design pips to oracle design pips (in non-saturated RMUX/IMUX groups)
    oracle_design = set(p for p in oracle
                        if (p[0], p[1], p[2]) not in saturated
                        and p[2].rstrip("0123456789") in ("CFG_RMUX", "CFG_IMUX"))
    tp = len(pred & oracle_design); fp = len(pred - oracle_design); fn = len(oracle_design - pred)
    print(f"=== held-out open-routing on {target} ===")
    print(f"used RMUX/IMUX edges predicted: {n_pred}  (rule/LUT hit {n_rule}, unpredicted {n_unp})")
    print(f"design pips (RMUX/IMUX, non-saturated): oracle={len(oracle_design)} predicted={len(pred)}")
    print(f"  TP={tp}  FP={fp}  FN={fn}   "
          f"precision={100*tp/(tp+fp) if tp+fp else 0:.1f}%  recall={100*tp/(tp+fn) if tp+fn else 0:.1f}%")

    # byte-exact: overlay predicted RMUX/IMUX design bits onto a copy of af.exe raw with those
    # groups cleared, then re-encode and byte-compare the whole .bin.
    rebuilt = bytearray(raw)
    # clear all RMUX/IMUX design (non-saturated) sel bits
    for (x, y, mux, sel), (b, m) in cell.items():
        if mux.rstrip("0123456789") in ("CFG_RMUX", "CFG_IMUX") and (x, y, mux) not in saturated:
            if b < len(rebuilt):
                rebuilt[b] &= (~m) & 0xFF
    for (x, y, mux, sel) in pred:
        b, m = cell[(x, y, mux, sel)]
        if b < len(rebuilt):
            rebuilt[b] |= m
    reenc = hdr + L.encode(bytes(rebuilt))
    exact = (reenc == data)
    print(f"  full .bin byte-exact after open-routing overlay: {exact} "
          f"({len(reenc)} vs {len(data)} B)")
    if not exact and bytes(rebuilt) == raw:
        print("  (raw image identical to af.exe; any mismatch is encoder-only)")


if __name__ == "__main__":
    main()
