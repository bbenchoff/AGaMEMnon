#!/usr/bin/env python3
"""Recover exact routing selector pairs from node-local mux blocks.

The streamed selector dataset associates a routed edge with every active
selector in its destination CFG group.  RMUX groups contain six independent
10-bit blocks; IMUX groups contain four independent 12-bit blocks.  Filtering
to the destination node's block attributes the selector pair without assuming
that the whole CFG group contains only one routed edge.

The input can be several gigabytes, so recovery is intentionally streaming.
Runtime output contains only conflict-free physical observations; conflicting
keys are retained in diagnostic output but are never promoted by majority.
"""

from __future__ import annotations

import argparse
import collections
import csv
import pickle
from pathlib import Path


BLOCK_SIZE = {"RMUX": 10, "IMUX": 12}


def edge_key(row):
    return (
        int(row["dst_x"]),
        int(row["dst_y"]),
        row["dst_fam"],
        int(row["dst_idx"]),
        row["src_fam"],
        int(row["src_x"]),
        int(row["src_y"]),
        int(row["src_idx"]),
    )


def sample_key(row):
    return (row["build"],) + edge_key(row)


def recover(path: Path):
    observations = collections.defaultdict(collections.Counter)
    rejected = collections.Counter()
    current = None
    local_sels = set()

    def finish():
        if current is None:
            return
        if len(local_sels) == 2:
            observations[current[1:]][tuple(sorted(local_sels))] += 1
        else:
            rejected[len(local_sels)] += 1

    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            family = row["dst_fam"]
            if family not in BLOCK_SIZE:
                continue
            key = sample_key(row)
            if key != current:
                finish()
                current = key
                local_sels = set()
            block = BLOCK_SIZE[family] * int(row["dst_group_offset"])
            sel = int(row["sel"])
            if block <= sel < block + BLOCK_SIZE[family]:
                local_sels.add(sel - block)
        finish()

    table = {}
    consistent = total = 0
    by_family = collections.Counter()
    for key, counts in observations.items():
        pair, count = counts.most_common(1)[0]
        samples = sum(counts.values())
        table[key] = {
            "pair": pair,
            "count": count,
            "samples": samples,
            "variants": len(counts),
        }
        total += 1
        if len(counts) == 1:
            consistent += 1
        by_family[(key[2], "keys")] += 1
        by_family[(key[2], "consistent")] += len(counts) == 1
    stats = {
        "keys": total,
        "consistent_keys": consistent,
        "rejected_samples_by_sel_count": dict(rejected),
        "by_family": dict(by_family),
    }
    return table, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="write only conflict-free physical edge-to-pair data for bitgen",
    )
    args = parser.parse_args(argv)
    table, stats = recover(args.dataset)
    payload = {"version": 1, "stats": stats, "table": table}
    if args.runtime:
        payload["table"] = {
            key: value["pair"]
            for key, value in table.items()
            if value["variants"] == 1
        }
    with args.output.open("wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
    print(stats)
    print(
        "wrote %d edge pairs to %s (%d bytes)"
        % (len(payload["table"]), args.output, args.output.stat().st_size)
    )


if __name__ == "__main__":
    main()
