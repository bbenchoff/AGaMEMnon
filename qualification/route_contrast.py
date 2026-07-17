#!/usr/bin/env python3
"""Contrast routed nextpnr JSONs without turning correlation into truth.

The useful conservative set is: PIPs absent from every passing route and
present in at least N failing routes.  This set is suitable for an experiment
against a copied devdb; it is *not* dead-edge evidence.  Only an isolated
hardware trial may promote a member to ``dead_edges_silicon.csv``.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Set, Union


def routed_pips(path: Union[str, Path]) -> Set[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    modules = data.get("modules", {})
    if not modules:
        raise ValueError(f"{path}: no modules")
    module = modules.get("top") or next(iter(modules.values()))
    result: set[str] = set()
    for net in module.get("netnames", {}).values():
        fields = net.get("attributes", {}).get("ROUTING", "").split(";")
        # nextpnr serializes each route item as wire;pip;strength.  A root has
        # an empty pip field and therefore falls out naturally here.
        for index in range(1, len(fields), 3):
            pip = fields[index]
            if "." in pip:
                result.add(pip)
    return result


def contrast(pass_paths, fail_paths, min_fail=2):
    passing = [routed_pips(path) for path in pass_paths]
    failing = [routed_pips(path) for path in fail_paths]
    pass_count = Counter(pip for route in passing for pip in route)
    fail_count = Counter(pip for route in failing for pip in route)
    candidates = [
        (pip, pass_count[pip], count)
        for pip, count in fail_count.items()
        if pass_count[pip] == 0 and count >= min_fail
    ]
    return sorted(candidates, key=lambda row: (-row[2], row[0]))


def filter_devdb(input_path, output_path, candidates):
    rejected = {row[0] for row in candidates}
    kept = removed = 0
    with Path(input_path).open(newline="", encoding="utf-8") as src, \
            Path(output_path).open("w", newline="", encoding="utf-8") as dst:
        reader = csv.reader(src)
        writer = csv.writer(dst, lineterminator="\n")
        header = next(reader)
        writer.writerow(header)
        for row in reader:
            if row and row[0] in rejected:
                removed += 1
                continue
            writer.writerow(row)
            kept += 1
    return kept, removed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passing", nargs="+", required=True, metavar="ROUTED_JSON")
    parser.add_argument("--failing", nargs="+", required=True, metavar="ROUTED_JSON")
    parser.add_argument("--min-fail", type=int, default=2)
    parser.add_argument("--csv", help="write the contrast table")
    parser.add_argument("--filter-devdb", nargs=2, metavar=("INPUT", "OUTPUT"),
                        help="copy dev_pips.csv while omitting contrast candidates")
    args = parser.parse_args(argv)
    if args.min_fail < 1:
        parser.error("--min-fail must be positive")
    candidates = contrast(args.passing, args.failing, args.min_fail)
    if args.csv:
        with Path(args.csv).open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(("pip", "pass_routes", "fail_routes"))
            writer.writerows(candidates)
    if args.filter_devdb:
        kept, removed = filter_devdb(*args.filter_devdb, candidates)
        print(f"devdb: kept {kept}, removed {removed} correlated candidate PIPs")
    print(f"contrast: {len(candidates)} candidate PIPs; correlation only, not dead-edge evidence")
    for pip, pass_n, fail_n in candidates[:20]:
        print(f"  fail={fail_n} pass={pass_n} {pip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
