#!/usr/bin/env python3
"""Attach physical IPAD/OPAD bel constraints to a synthesized generic JSON.

The Python pre-place flow consumes AGAMEMNON_PCF_JSON directly, but a Viaduct
uarch packs before that hook exists.  Encoding the same constraint as the
standard NEXTPNR_BEL cell attribute makes PCF behavior identical in both flows.
"""
import csv
import json
import os
import sys


def main():
    path, pcf_json, data = sys.argv[1:4]
    if os.path.exists(pcf_json):
        constraints = {}
        with open(pcf_json) as f:
            for raw in f:
                fields = raw.split("#", 1)[0].split()
                if not fields:
                    continue
                if len(fields) != 3 or fields[0] != "set_io":
                    raise SystemExit("pcf_bind_json: unsupported PCF line %r" % raw.rstrip())
                constraints[fields[1]] = fields[2]
    else:
        constraints = json.loads(pcf_json)
    bonds = {}
    with open(os.path.join(data, "bondmap_L48.csv")) as f:
        for row in csv.DictReader(f):
            bonds[row["pin"].upper()] = (int(row["x"]), int(row["y"]), int(row["z"]))

    with open(path) as f:
        design = json.load(f)
    modules = design["modules"]
    topname = next((n for n, m in modules.items()
                    if str(m.get("attributes", {}).get("top", "0"))
                    in ("1", "00000000000000000000000000000001")), None)
    if topname is None:
        topname = max(modules, key=lambda n: len(modules[n].get("cells", {})))
    cells = modules[topname]["cells"]

    bound = 0
    for signal, pin in constraints.items():
        xyz = bonds.get(pin.upper())
        if xyz is None:
            raise SystemExit("pcf_bind_json: %s is not bonded in bondmap_L48.csv" % pin)
        matches = [(name, cell) for name, cell in cells.items()
                   if cell.get("type") == "GENERIC_IOB" and name.endswith("." + signal)]
        if len(matches) != 1:
            raise SystemExit("pcf_bind_json: signal %s matched %d GENERIC_IOB cells" % (signal, len(matches)))
        name, cell = matches[0]
        ports = cell.get("port_directions", {})
        if ports.get("O") == "output":
            kind = "IPAD"
        elif ports.get("I") == "input":
            kind = "OPAD"
        else:
            raise SystemExit("pcf_bind_json: cannot determine direction of %s" % signal)
        x, y, z = xyz
        bel = "X%dY%d_%s%d" % (x, y, kind, z)
        cell.setdefault("attributes", {})["NEXTPNR_BEL"] = bel
        print("PCF JSON bind %s (%s) -> %s" % (signal, name, bel))
        bound += 1

    with open(path, "w") as f:
        json.dump(design, f)
    print("pcf_bind_json: bound %d I/O cell(s)" % bound)


if __name__ == "__main__":
    main()
