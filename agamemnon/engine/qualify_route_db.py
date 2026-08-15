#!/usr/bin/env python3
"""Bias a uarch pip database toward a silicon-qualified routed checkpoint."""
import csv
import json
import sys


def routed_pips(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = set()
    for module in data.get("modules", {}).values():
        for net in module.get("netnames", {}).values():
            route = net.get("attributes", {}).get("ROUTING")
            if not route:
                continue
            fields = route.split(";")
            for pos in range(1, len(fields), 3):
                if fields[pos]:
                    result.add(fields[pos])
    return result


def main(argv):
    if len(argv) not in (4, 5) or (len(argv) == 5 and argv[4] != "--filter"):
        raise SystemExit("usage: qualify_route_db.py <checkpoint.json> <dev_pips.csv> <output.csv> [--filter]")
    proven = routed_pips(argv[1])
    with open(argv[2], encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0]) if rows else []
    matched = 0
    selected = []
    available = {row["name"] for row in rows}
    missing = sorted(proven - available)
    if missing and len(argv) == 5:
        raise SystemExit(
            "checkpoint route is not representable by the source device database; "
            "missing %d PIP(s): %s" %
            (len(missing), ", ".join(missing[:8]) + ("..." if len(missing) > 8 else ""))
        )
    for row in rows:
        if row["name"] in proven:
            row["delay_ns"] = "0.001"
            matched += 1
            selected.append(row)
        else:
            row["delay_ns"] = "5.0"
            if len(argv) == 4:
                selected.append(row)
    rows_out = selected
    with open(argv[3], "w", encoding="utf-8", newline="") as f:
        out = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        out.writeheader()
        out.writerows(rows_out)
    print("qualified %d/%d checkpoint pips; %s %d alternatives" %
          (matched, len(proven), "removed" if len(argv) == 5 else "penalized", len(rows) - matched))


if __name__ == "__main__":
    main(sys.argv)
