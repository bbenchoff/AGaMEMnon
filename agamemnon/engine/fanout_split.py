#!/usr/bin/env python3
"""Net-replication pass for the conducting-fabric fanout limit (run AFTER qin_pack, BEFORE nextpnr).

A single fabric tile can only fan a net out to a few conducting neighbours, so a high-fanout net (e.g. a
counter's low bit feeding every higher bit's carry) route-FAILS against the conduction-gated devdb. This
splits any net whose driver is a LUT/DFF and whose data-fanout > MAXFO by DUPLICATING the driver: each copy
computes the same value (same inputs) and drives a <=MAXFO subset of the sinks. Register replication is
sound because the copies share the same D/clock; for a Qin self-feedback FF the copy must read ITS OWN Q
(not the original's) or it becomes a 1-cycle follower -> so any input reading the original's output net is
repointed to the copy's output. MCU_DOUT readout sinks stay on the original net. Usage: fanout_split.py
<synth.json> [MAXFO=3].
"""
import json, sys, collections

def main():
    path = sys.argv[1]
    MAXFO = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    d = json.load(open(path))
    # pick the design top: the module with attributes.top=1, else "top", else the one with the most cells
    mods = d["modules"]
    topname = next((n for n, m in mods.items() if str(m.get("attributes", {}).get("top", "0")) in ("1", "00000000000000000000000000000001")), None)
    if topname is None:
        topname = "top" if "top" in mods else max(mods, key=lambda n: len(mods[n].get("cells", {})))
    mod = mods[topname]
    cells = mod["cells"]

    maxbit = 0
    for c in cells.values():
        for bits in c["connections"].values():
            for b in bits:
                if isinstance(b, int):
                    maxbit = max(maxbit, b)
    nextbit = [maxbit + 1]

    def build():
        drv = {}                       # bit -> (cellname, port)
        users = collections.defaultdict(list)   # bit -> [(cellname, port, idx)]
        for n, c in cells.items():
            pd = c.get("port_directions", {})
            for p, bits in c["connections"].items():
                for i, b in enumerate(bits):
                    if not isinstance(b, int):
                        continue
                    if pd.get(p) == "output":
                        drv[b] = (n, p)
                    else:
                        users[b].append((n, p, i))
        return drv, users

    # Iterate to convergence: replicating a driver makes its copies re-read the SAME upstream nets, which
    # pushes THEIR fanout back up, so one pass isn't enough. Repeat until no net exceeds MAXFO (or a cap).
    made = 0
    nets_touched = set()
    for _pass in range(40):
        drv, users = build()
        targets = [b for b, us in users.items()
                   if len(us) > MAXFO and b in drv and cells[drv[b][0]]["type"] in ("LUT", "DFF")]
        if not targets:
            break
        rep_ctr = collections.Counter()
        for b in targets:
            nets_touched.add(b)
            dc = drv[b][0]
            rest = users[b][MAXFO:]   # first MAXFO stay on the original driver; split the rest
            while rest:
                grp = rest[:MAXFO]
                rest = rest[MAXFO:]
                rep_ctr[dc] += 1
                nb = nextbit[0]; nextbit[0] += 1
                rep = json.loads(json.dumps(cells[dc]))   # deep copy (same inputs -> same value)
                for p, bits in rep["connections"].items():   # output -> new bit; self-feedback input follows
                    for k, bb in enumerate(bits):
                        if bb == b:
                            bits[k] = nb
                cells["%s$fo%d" % (dc, rep_ctr[dc])] = rep
                for (n, p, i) in grp:
                    cells[n]["connections"][p][i] = nb
                made += 1
    if made:
        json.dump(d, open(path, "w"))
    print("fanout_split: MAXFO=%d, replicated %d driver copies across %d nets in %d pass(es)"
          % (MAXFO, made, len(nets_touched), _pass))

if __name__ == "__main__":
    main()
