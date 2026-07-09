#!/usr/bin/env python3
# emit_uarch_db.py -- flatten the AGRV2K device graph into dumb CSVs for the C++ Viaduct uarch.
#
# WHY: arch.py is the proven, silicon-validated device-graph generator. It builds the whole fabric
# (wires / bels / bel-pins / pips, incl. IO ring, clock spine, BRAM, MCU edge) by *calling* the
# nextpnr-generic Python API: ctx.addWire/addBel/addBelInput/addBelOutput/addPip + ctx.setLutK.
#
# Rather than re-implement that graph in C++ (duplication = drift = bugs), we run arch.py UNCHANGED
# against a fake `ctx` that RECORDS every call, then dump the recording as flat CSV. The C++ uarch's
# init() then dumb-loads these CSVs and replays them 1:1 into the real ctx. Guaranteed-identical
# graph, zero graph logic in C++, and the "interesting" data (the graph) stays inspectable in AGaMEMnon.
#
# Outputs (into --out dir):
#   dev_meta.csv      key,value            -- lutk, counts, source arch.py, env digest
#   dev_wires.csv     name,type,x,y
#   dev_bels.csv      name,type,x,y,z
#   dev_belpins.csv   bel,pin,wire,dir     -- dir in {in,out,inout}
#   dev_pips.csv      name,type,src,dst,delay_ns,x,y,z
#
# Usage:
#   python emit_uarch_db.py --arch <path/to/arch.py> --data <path/to/chipdb> --out <dir> [--env K=V ...]
# Defaults: --arch = this dir's arch.py, --data = arch.py's own default, --out = ./uarch_db
#
# NOTE ON PARITY: this captures whatever graph arch.py builds UNDER THE GIVEN ENV. To reproduce a
# specific silicon-proven flow, pass the same AGAMEMNON_* env vars that flow used (e.g. conduction
# gating / xbar mode). The de-risk uses the workbench arch.py (current silicon truth) via --arch.

import argparse, csv, os, sys


class Loc:
    """Stand-in for nextpnr's Loc(x,y,z)."""
    __slots__ = ("x", "y", "z")
    def __init__(self, x=0, y=0, z=0):
        self.x, self.y, self.z = int(x), int(y), int(z)


class _NoOp:
    """Absorbs any unexpected ctx.<method>(...) call arch.py might make (e.g. probe blocks)
    without recording it -- returns another _NoOp so chained access/calls stay harmless."""
    def __call__(self, *a, **k): return self
    def __getattr__(self, _): return self
    def __iter__(self): return iter(())
    def __bool__(self): return False


class RecordingCtx:
    """Fake nextpnr Context that records the graph-building calls arch.py makes."""
    def __init__(self):
        self.wires = []      # (name, type, x, y)
        self.bels = []       # (name, type, x, y, z)
        self.belpins = []    # (bel, pin, wire, dir)
        self.pips = []       # (name, type, src, dst, delay_ns, x, y, z)
        self.lutk = None
        self.cells = {}      # probe blocks iterate this -- keep it an empty dict

    # ---- graph construction (the calls we actually care about) ----
    def addWire(self, name, type, x, y, **_):
        self.wires.append((name, type, int(x), int(y)))

    def setLutK(self, k):
        self.lutk = int(k)

    def addBel(self, name, type, loc, gb=False, hidden=False, **_):
        self.bels.append((name, type, loc.x, loc.y, loc.z))

    def addBelInput(self, bel, name, wire, **_):
        self.belpins.append((bel, name, wire, "in"))

    def addBelOutput(self, bel, name, wire, **_):
        self.belpins.append((bel, name, wire, "out"))

    def addBelInout(self, bel, name, wire, **_):
        self.belpins.append((bel, name, wire, "inout"))

    def addPip(self, name, type, srcWire, dstWire, delay=0.0, loc=None, **_):
        lx, ly, lz = (loc.x, loc.y, loc.z) if loc is not None else ("", "", "")
        self.pips.append((name, type, srcWire, dstWire, float(delay), lx, ly, lz))

    def getDelayFromNS(self, ns):
        # arch.py passes the result straight back into addPip(delay=...); carry the ns value through.
        return float(ns)

    # ---- reads that probe blocks may touch: keep them harmless ----
    def checkBelAvail(self, *a, **k): return True
    def bindBel(self, *a, **k): return None

    def __getattr__(self, _):
        # Any other ctx.<attr> arch.py might reference -> harmless no-op.
        return _NoOp()


def main():
    ap = argparse.ArgumentParser(description="Flatten the AGRV2K arch graph to CSV for the C++ uarch.")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--arch", default=os.path.join(here, "arch.py"),
                    help="path to arch.py (the graph generator). Default: this dir's arch.py")
    ap.add_argument("--data", default=None,
                    help="chipdb dir (sets AGAMEMNON_DATA). Default: arch.py's own default")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "uarch_db"),
                    help="output dir for the dev_*.csv files (created if missing)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VAL",
                    help="extra env var to set before running arch.py (repeatable)")
    args = ap.parse_args()

    arch_path = os.path.abspath(args.arch)
    if not os.path.isfile(arch_path):
        sys.exit("emit_uarch_db: arch.py not found: %s" % arch_path)

    if args.data:
        os.environ["AGAMEMNON_DATA"] = os.path.abspath(args.data)
    for kv in args.env:
        if "=" not in kv:
            sys.exit("emit_uarch_db: --env expects KEY=VAL, got %r" % kv)
        k, v = kv.split("=", 1)
        os.environ[k] = v

    os.makedirs(args.out, exist_ok=True)
    ctx = RecordingCtx()

    # exec arch.py with our fake ctx + Loc, and __file__ set so its own DATA/sys.path resolution works.
    ns = {"ctx": ctx, "Loc": Loc, "__file__": arch_path, "__name__": "__arch_emit__"}
    with open(arch_path, "r", encoding="utf-8") as f:
        src = f.read()
    code = compile(src, arch_path, "exec")
    exec(code, ns)  # noqa: S102 -- running our own trusted generator by design

    # ---- write the flat CSVs ----
    def dump(fn, header, rows):
        with open(os.path.join(args.out, fn), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    dump("dev_wires.csv",   ["name", "type", "x", "y"], ctx.wires)
    dump("dev_bels.csv",    ["name", "type", "x", "y", "z"], ctx.bels)
    dump("dev_belpins.csv", ["bel", "pin", "wire", "dir"], ctx.belpins)
    dump("dev_pips.csv",    ["name", "type", "src", "dst", "delay_ns", "x", "y", "z"], ctx.pips)

    env_digest = ";".join("%s=%s" % (k, os.environ[k])
                          for k in sorted(os.environ) if k.startswith("AGAMEMNON_"))
    dump("dev_meta.csv", ["key", "value"], [
        ("lutk", ctx.lutk),
        ("n_wires", len(ctx.wires)),
        ("n_bels", len(ctx.bels)),
        ("n_belpins", len(ctx.belpins)),
        ("n_pips", len(ctx.pips)),
        ("arch_py", arch_path),
        ("agamemnon_env", env_digest),
    ])

    print("emit_uarch_db: wrote %s" % args.out)
    print("  lutk=%s wires=%d bels=%d belpins=%d pips=%d"
          % (ctx.lutk, len(ctx.wires), len(ctx.bels), len(ctx.belpins), len(ctx.pips)))
    if env_digest:
        print("  env: %s" % env_digest)


if __name__ == "__main__":
    main()
