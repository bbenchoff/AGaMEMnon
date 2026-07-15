#!/usr/bin/env python3
"""Build a diagnostic devdb without tile-relative-only selector pips.

The release bit generator can encode a routing edge from either a physical
coordinate-specific observation or a unanimous tile-relative replication.
This helper removes only edges in the second class.  Clock, carry, pseudo,
BRAM, IO and other special pips that are not represented in the LogicTile
selector table are preserved unchanged.
"""

from __future__ import annotations

import argparse
import csv
import pickle
import re
import shutil
from pathlib import Path


WIRE = re.compile(r"X(\d+)Y(\d+)_([A-Za-z]+)(\d+)$")


def parse_wire(name: str):
    match = WIRE.fullmatch(name)
    if not match:
        return None
    return int(match[1]), int(match[2]), match[3], int(match[4])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("selector_pickle", type=Path)
    args = parser.parse_args()

    table = pickle.loads(args.selector_pickle.read_bytes())["table"]
    relative = {}
    conflicts = set()
    for (dx, dy, df, di, sf, sx, sy, si), pair in table.items():
        key = (df, di, sf, si, dx - sx, dy - sy)
        pair = tuple(pair)
        if key in relative and relative[key] != pair:
            conflicts.add(key)
        else:
            relative[key] = pair
    for key in conflicts:
        relative.pop(key, None)

    if args.output.exists():
        shutil.rmtree(args.output)
    shutil.copytree(args.source, args.output)
    source_pips = args.source / "dev_pips.csv"
    output_pips = args.output / "dev_pips.csv"
    temporary = output_pips.with_suffix(".tmp")
    removed = kept = 0
    with source_pips.open(newline="", encoding="utf-8") as source, temporary.open(
        "w", newline="", encoding="utf-8"
    ) as output:
        reader = csv.DictReader(source)
        writer = csv.DictWriter(output, fieldnames=reader.fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in reader:
            src = parse_wire(row["src"])
            dst = parse_wire(row["dst"])
            drop = False
            if src and dst:
                sx, sy, sf, si = src
                dx, dy, df, di = dst
                physical = (dx, dy, df, di, sf, sx, sy, si)
                rel = (df, di, sf, si, dx - sx, dy - sy)
                drop = physical not in table and rel in relative
            if drop:
                removed += 1
            else:
                writer.writerow(row)
                kept += 1
    temporary.replace(output_pips)
    print(f"exact-only devdb: kept {kept:,} pips, removed {removed:,} relative-only pips")


if __name__ == "__main__":
    main()
