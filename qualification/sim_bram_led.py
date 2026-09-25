#!/usr/bin/env python3
"""Adjudicate a self-checking BRAM design offline: simulate its ROUTED netlist and count LED edges.

The rando-corpus / vendor-witness BRAM designs (tools/vendor_witness/gen_bram_modes.py and the
bram_*_kat corpus) all end in the same oracle: a free-running heartbeat on the LED that a `failed`
flag gates off. On the board the Pico counts LED edges; here the routed-netlist simulator
(agamemnon.engine.verify_netlist, vendor BRAM semantics for x18/x9/x4/x2/x1) produces the same
observable, plus everything the board cannot show: the first cycle the check flags, and the BRAM
port operations around it.

    python qualification/sim_bram_led.py design.routed.json --cycles 40000 --edge-cycles 8192
    python qualification/sim_bram_led.py design.routed.json --watch bad_a,failed --window 8

Prints: LED rising edges and their period, the first rise of each watched net (default: every
net named bad*, failed), and the BRAM port records for a window of cycles before the first watched
rise. Exit code 0 when the LED rate matches --edge-cycles within --tolerance, 1 otherwise.
No board, no vendor binaries, no absolute paths.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from agamemnon.engine import verify_netlist as V  # noqa: E402


def led_net(document):
    top = document["modules"]["top"]
    nid = {}
    for nm, ni in top["netnames"].items():
        for b in ni.get("bits", []):
            nid[b] = nm
    for cn, c in top["cells"].items():
        if c.get("type") == "GENERIC_IOB" and c["connections"].get("I"):
            if cn.endswith("led") or ".led" in cn or cn.endswith(".q"):
                return nid[c["connections"]["I"][0]]
    for cn, c in top["cells"].items():
        if c.get("type") == "GENERIC_IOB" and c["connections"].get("I"):
            return nid[c["connections"]["I"][0]]
    raise SystemExit("no output pad (GENERIC_IOB with an I connection) in the routed JSON")


def presented_q_nets(document):
    """Registered nets routed through an OMUX[3z+2]->OMUX[3z+0] presentation pip: (name, pip)."""
    import re
    top = document["modules"]["top"]
    nid = {}
    for nm, ni in top["netnames"].items():
        for b in ni.get("bits", []):
            nid[b] = nm
    q_nets = set()
    for c in top["cells"].values():
        if c.get("type") == "GENERIC_SLICE" and int(c["parameters"].get("FF_USED", "0"), 2):
            for b in c["connections"].get("Q", []):
                q_nets.add(nid.get(b))
    pat = re.compile(r"^(X\d+Y\d+)_OMUX(\d+)\.(X\d+Y\d+)_OMUX(\d+)$")
    out = []
    for nm, ni in top["netnames"].items():
        if nm not in q_nets:
            continue
        for tok in ni.get("attributes", {}).get("ROUTING", "").split(";"):
            m = pat.match(tok.strip())
            if m and m.group(1) == m.group(3) and int(m.group(2)) % 3 == 2 and int(m.group(2)) - int(m.group(4)) == 2:
                out.append((nm, tok.strip()))
    return out


def qf_scan(a):
    document = json.load(open(a.routed, encoding="utf-8"))
    top = document["modules"]["top"]
    led = led_net(document)
    watch = sorted(n for n in top["netnames"] if n.startswith("bad") or n == "failed")
    canon = V._canonical_net_names(document, watch)
    nid = {}
    for nm, ni in top["netnames"].items():
        for b in ni.get("bits", []):
            nid[b] = nm
    targets = presented_q_nets(document)
    edges0, first0 = run_once(document, a.routed, a.cycles, led, canon, (), a.unconnected_data)
    print("qf-scan: %s baseline %s; %d registered nets presented on OMUX[3z+0]"
          % (os.path.basename(a.routed), classify(edges0, first0, a.cycles, a.edge_cycles), len(targets)))
    for nm, pip in targets:
        cn = nid[top["netnames"][nm]["bits"][0]]
        edges, first = run_once(document, a.routed, a.cycles, led, canon, (), a.unconnected_data, qf_alias=(cn,))
        print("  %-14s %-34s reads F instead of Q -> %s" % (nm, pip, classify(edges, first, a.cycles, a.edge_cycles)))
    return 0


def run_once(document, routed, cycles, led, watch_canon, dead_nets=(), unconnected_data=0, qf_alias=()):
    """One simulation: (rising-edge cycles, {watched: first rise cycle})."""
    state = {"led": 0, "edges": [], "first": {}}

    def probe(cycle, value):
        v = value(led)
        if v and not state["led"]:
            state["edges"].append(cycle)
        state["led"] = v
        for name, cn in watch_canon.items():
            if name not in state["first"] and value(cn):
                state["first"][name] = cycle

    V.sim_routed(routed, cycles, document=document, probe=probe,
                 bram_unconnected_data=unconnected_data, dead_nets=dead_nets, qf_alias=qf_alias)
    return state["edges"], state["first"]


def classify(edges, first, cycles, edge_cycles):
    if first:
        return "FAIL-FLAG@%d" % min(first.values())
    if len(edges) < 2:
        return "NO-EDGES" if not edges else "ONE-EDGE"
    period = (edges[-1] - edges[0]) / float(len(edges) - 1)
    if edge_cycles and abs(period - edge_cycles) <= 0.05 * edge_cycles:
        return "NORMAL"
    if edge_cycles and abs(period - edge_cycles / 2) <= 0.05 * edge_cycles / 2:
        return "2x-RATE"
    return "PERIOD=%.0f" % period


def kill_scan(a):
    document = json.load(open(a.routed, encoding="utf-8"))
    top = document["modules"]["top"]
    led = led_net(document)
    watch = sorted(n for n in top["netnames"] if n.startswith("bad") or n == "failed")
    canon = V._canonical_net_names(document, watch)
    routed_nets = sorted(nm for nm, ni in top["netnames"].items()
                         if ni.get("attributes", {}).get("ROUTING") and ni.get("bits"))
    nid = {}
    for nm, ni in top["netnames"].items():
        for b in ni.get("bits", []):
            nid[b] = nm
    edges0, first0 = run_once(document, a.routed, a.cycles, led, canon, (), a.unconnected_data)
    base = classify(edges0, first0, a.cycles, a.edge_cycles)
    print("kill-scan: %s baseline %s (%d edges); %d routed nets"
          % (os.path.basename(a.routed), base, len(edges0), len(routed_nets)))
    by_class = {}
    for nm in routed_nets:
        cn = nid[top["netnames"][nm]["bits"][0]]
        edges, first = run_once(document, a.routed, a.cycles, led, canon, (cn,), a.unconnected_data)
        cls = classify(edges, first, a.cycles, a.edge_cycles)
        by_class.setdefault(cls, []).append(nm)
    for cls in sorted(by_class, key=lambda c: (c != "NORMAL", c)):
        names = by_class[cls]
        print("  %-14s %3d nets: %s" % (cls, len(names), ", ".join(names[:40]) + (" ..." if len(names) > 40 else "")))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("routed")
    ap.add_argument("--cycles", type=int, default=40000)
    ap.add_argument("--edge-cycles", type=float, default=None,
                    help="expected clock cycles per LED rising edge (corpus cycles_per_led_edge)")
    ap.add_argument("--tolerance", type=float, default=0.05)
    ap.add_argument("--watch", default=None, help="comma list of nets whose first rise to report")
    ap.add_argument("--window", type=int, default=6, help="BRAM records to dump before the first rise")
    ap.add_argument("--unconnected-data", type=int, default=0, choices=(0, 1),
                    help="value an unconnected DataIn lane presents to a write")
    ap.add_argument("--trace", default=None, help="comma list of nets to print whenever they change")
    ap.add_argument("--kill-scan", action="store_true",
                    help="kill every routed net in turn (its consumers read 1, as a dead pip would make "
                         "them) and classify the LED symptom each produces: which single conduction "
                         "failure reproduces what the board saw")
    ap.add_argument("--kill", default=None, help="comma list of nets to kill in one run")
    ap.add_argument("--qf-alias", default=None,
                    help="comma list of registered nets whose consumers read the driver's LUT output F "
                         "instead of Q (a pip that really reads the slice's OMUX[3z+1] wire)")
    ap.add_argument("--qf-scan", action="store_true",
                    help="apply --qf-alias to every registered net routed through an OMUX[3z+2]->OMUX[3z+0] "
                         "presentation pip, one at a time, and classify the LED symptom")
    a = ap.parse_args(argv)

    if a.kill_scan:
        return kill_scan(a)
    if a.qf_scan:
        return qf_scan(a)

    document = json.load(open(a.routed, encoding="utf-8"))
    top = document["modules"]["top"]
    led = led_net(document)
    names = list(top["netnames"])
    watch = ([w for w in a.watch.split(",") if w] if a.watch else
             sorted(n for n in names if n.startswith("bad") or n == "failed"))
    canon = V._canonical_net_names(document, [n for n in watch if n in top["netnames"]])
    trace = [t for t in (a.trace.split(",") if a.trace else []) if t in top["netnames"]]
    canon_trace = V._canonical_net_names(document, trace) if trace else {}

    state = {"led": 0, "edges": [], "first_rise": {}, "records": [], "last_trace": None}

    def probe(cycle, value):
        v = value(led)
        if v and not state["led"]:
            state["edges"].append(cycle)
        state["led"] = v
        for name, cn in canon.items():
            if name not in state["first_rise"] and value(cn):
                state["first_rise"][name] = cycle
        if canon_trace:
            vals = tuple(value(canon_trace[t]) for t in trace)
            if vals != state["last_trace"]:
                print("  trace @%-6d %s" % (cycle, " ".join("%s=%d" % (t, v) for t, v in zip(trace, vals))))
                state["last_trace"] = vals

    def bram_probe(cycle, brams):
        for bram in brams:
            state["records"].append((cycle, bram["name"], dict(bram["last"])))
        keep = (a.window + 2) * max(1, len(brams))
        if len(state["records"]) > 4 * keep:
            del state["records"][:-keep]
        if state["first_rise"] and "dump" not in state:
            state["dump"] = list(state["records"][-keep:])

    kill = []
    if a.kill:
        kill = list(V._canonical_net_names(document, [k for k in a.kill.split(",") if k]).values())
    reads, bind = V.sim_routed(a.routed, a.cycles, document=document, probe=probe,
                               bram_probe=bram_probe, bram_unconnected_data=a.unconnected_data,
                               dead_nets=kill)
    edges = state["edges"]
    period = None
    if len(edges) >= 2:
        period = (edges[-1] - edges[0]) / float(len(edges) - 1)
    print("sim_bram_led: %s over %d cycles (unconnected DataIn lanes read %d)"
          % (os.path.basename(a.routed), a.cycles, a.unconnected_data))
    print("  LED rising edges: %d  first at cycle %s  mean period %s"
          % (len(edges), edges[0] if edges else "-", ("%.1f" % period) if period else "-"))
    for name in watch:
        print("  %-10s first rise @ %s" % (name, state["first_rise"].get(name, "never")))
    if "dump" in state:
        print("  BRAM port records before the first watched rise (cycle, port, op):")
        for cycle, bname, last in state["dump"]:
            for tag, rec in last.items():
                if not rec.get("en"):
                    continue
                op = []
                if rec.get("we"):
                    op.append("WRITE row=%d blk=%d din=%05x mask=%05x -> %05x" % (
                        rec["row"], rec["blk"], rec["din"], rec["mask"], rec["new"]))
                if rec.get("re"):
                    op.append("READ  row=%d blk=%d" % (rec["row"], rec["blk"]))
                print("    @%-6d %s.%s out=%05x %s" % (cycle, bname, tag, rec["out"], "; ".join(op) or "idle"))
    if a.edge_cycles:
        ok = period is not None and abs(period - a.edge_cycles) <= a.tolerance * a.edge_cycles \
            and not state["first_rise"]
        expected_edges = a.cycles / a.edge_cycles
        print("  VERDICT: %s (expected ~%.1f edges at one per %.0f cycles)"
              % ("PASS" if ok else "FAIL", expected_edges, a.edge_cycles))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
