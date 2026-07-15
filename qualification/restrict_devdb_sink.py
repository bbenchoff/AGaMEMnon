#!/usr/bin/env python3
"""Restrict one devdb wire to explicitly allowed fan-in or fan-out PIPs.

This is an experiment helper for isolated routing-PIP qualification.  It keeps
the CSV schema and quoting compatible with the agrv2k uarch loader while
removing alternate fan-in PIPs to one destination wire.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def restrict(source: Path, output: Path, sink: str, allowed: set[str]):
    with source.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = reader.fieldnames
    if not fields:
        raise ValueError(f"{source}: missing CSV header")
    before = [row for row in rows if row["dst"] == sink]
    kept = [row for row in rows if row["dst"] != sink or row["src"] in allowed]
    after = [row for row in kept if row["dst"] == sink]
    if not before:
        raise ValueError(f"{source}: sink {sink!r} has no input PIPs")
    if {row["src"] for row in after} != allowed:
        raise ValueError(
            f"{source}: requested sources {sorted(allowed)!r}, available "
            f"{sorted(row['src'] for row in before)!r}"
        )
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept)
    return len(before), len(after), len(rows) - len(kept)


def restrict_egress(source: Path, output: Path, source_wire: str, allowed: set[str]):
    with source.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        fields = reader.fieldnames
    if not fields:
        raise ValueError(f"{source}: missing CSV header")
    before = [row for row in rows if row["src"] == source_wire]
    kept = [row for row in rows if row["src"] != source_wire or row["dst"] in allowed]
    after = [row for row in kept if row["src"] == source_wire]
    if not before:
        raise ValueError(f"{source}: source {source_wire!r} has no output PIPs")
    if {row["dst"] for row in after} != allowed:
        raise ValueError(
            f"{source}: requested destinations {sorted(allowed)!r}, available "
            f"{sorted(row['dst'] for row in before)!r}"
        )
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept)
    return len(before), len(after), len(rows) - len(kept)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sink")
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--source-wire")
    parser.add_argument("--dest", action="append", dest="destinations")
    args = parser.parse_args(argv)
    fanin = args.sink is not None or args.sources is not None
    fanout = args.source_wire is not None or args.destinations is not None
    if fanin == fanout:
        parser.error("choose exactly one of --sink/--source or --source-wire/--dest")
    if fanin:
        if not args.sink or not args.sources:
            parser.error("--sink requires at least one --source")
        before, after, removed = restrict(args.input, args.output, args.sink, set(args.sources))
        print(f"{args.sink}: {before} -> {after} input PIPs ({removed} removed)")
    else:
        if not args.source_wire or not args.destinations:
            parser.error("--source-wire requires at least one --dest")
        before, after, removed = restrict_egress(
            args.input, args.output, args.source_wire, set(args.destinations)
        )
        print(f"{args.source_wire}: {before} -> {after} output PIPs ({removed} removed)")


if __name__ == "__main__":
    main()
