#!/usr/bin/env python3
"""Extract conservative routing delays from decoded vendor ``alta_wire.ar``.

The vendor table is indexed by native wire class, driving mux family and
fanout.  The current open graph does not yet carry a proven native class for
every physical wire index, so the emitted ``source_max_ns`` deliberately takes
the maximum WORST value across every class, fanout row, transition and supplied
PVT table for a source family.  This overestimates some paths but never selects
an optimistic class merely from geometry.
"""

import argparse
import hashlib
import json
import os
import re


FLOAT_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")
FROM_RE = re.compile(r"FROM\s*:\s*[^:;]*:([^:;]+):[^;]*;")


def parse_wire_timing(text):
    """Return ``{wire_class: {source_family: worst_ns}}`` from decoded text."""
    result = {}
    wire_class = source_family = None
    in_worst = False
    found_worst = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("WIRE "):
            wire_class = line.split(None, 1)[1]
            result.setdefault(wire_class, {})
            source_family = None
            in_worst = False
            continue
        match = FROM_RE.fullmatch(line)
        if match:
            source_family = match.group(1)
            continue
        if line == "TABLE WORST":
            if wire_class is None or source_family is None:
                raise ValueError("WORST table lacks WIRE/FROM context")
            in_worst = True
            found_worst = True
            continue
        if line == "END_TABLE":
            in_worst = False
            continue
        if not in_worst:
            continue
        values = [float(value) for value in FLOAT_RE.findall(line)]
        if not values:
            continue
        worst = max(values)
        old = result[wire_class].get(source_family)
        result[wire_class][source_family] = worst if old is None else max(old, worst)
    if not found_worst:
        raise ValueError("no TABLE WORST data found")
    return result


def aggregate(paths):
    classes = {}
    inputs = []
    for path in paths:
        payload = open(path, "rb").read()
        parsed = parse_wire_timing(payload.decode("utf-8"))
        inputs.append({"name": os.path.basename(path),
                       "sha256": hashlib.sha256(payload).hexdigest()})
        for wire_class, families in parsed.items():
            out = classes.setdefault(wire_class, {})
            for family, delay in families.items():
                out[family] = max(out.get(family, 0.0), delay)
    source_max = {}
    for families in classes.values():
        for family, delay in families.items():
            source_max[family] = max(source_max.get(family, 0.0), delay)
    if not source_max:
        raise ValueError("no routing delay records found")
    return {
        "schema": 1,
        "aggregation": "max of every WORST transition and fanout row across all supplied wire classes and PVT tables",
        "inputs": sorted(inputs, key=lambda item: item["name"]),
        "classes": {key: dict(sorted(value.items())) for key, value in sorted(classes.items())},
        "source_max_ns": dict(sorted(source_max.items())),
        "fallback_max_ns": max(source_max.values()),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="decoded *_alta_wire.ar.txt files")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)
    result = aggregate(args.inputs)
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print("wire timing: %d input(s), %d classes, %d source families, fallback %.3f ns" %
          (len(result["inputs"]), len(result["classes"]), len(result["source_max_ns"]),
           result["fallback_max_ns"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
