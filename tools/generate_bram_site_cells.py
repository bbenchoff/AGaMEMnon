#!/usr/bin/env python3
"""Generate BramTILE selector-cell maps for one or more physical sites.

The input physical map and recovered ``pos2raw`` helper are research material
and are intentionally not distributed.  The generated ``bram_cell.csv`` is a
derived coordinate-to-frame map and is part of the open chip database.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import re
import sys
from pathlib import Path


HEADER = ["x", "y", "mux", "sel", "byte", "mask"]
CANON = {
    "CFG_SEAMMUX": "CFG_SeamMUX",
    "CFG_CTRLMUX": "CFG_CtrlMUX",
    "CFG_TILECLKENMUX": "CFG_TileClkEnMUX",
    "CFG_TILEASYNCMUX": "CFG_TileAsyncMUX",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--physical-map", type=Path, required=True)
    parser.add_argument(
        "--pos2raw-root", type=Path, required=True,
        help="directory containing the research pos2raw.py and its data",
    )
    parser.add_argument("--sites", default="13,1;13,2;13,3;13,4")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(args.pos2raw_root.resolve()))
    pos2raw = importlib.import_module("pos2raw")
    pos2raw.load_ranks()

    sites = {
        tuple(int(part) for part in item.split(","))
        for item in args.sites.split(";") if item
    }
    rows: list[tuple[int, int, str, int, int, int]] = []
    with args.physical_map.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            xy = (int(row["x"]), int(row["y"]))
            if xy not in sites:
                continue
            feature = row["feature"]
            match = re.fullmatch(r"(CFG_[A-Za-z_]+\d*)(?:\[(\d+)\])?", feature)
            if not match:
                continue
            mux = CANON.get(match.group(1), match.group(1))
            selector = int(match.group(2) or 0)
            try:
                byte, mask = pos2raw.to_byte_mask(
                    int(row["top_wl"]), int(row["top_bl"])
                )
            except Exception:
                continue
            rows.append((xy[0], xy[1], mux, selector, byte, mask))

    rows.sort()
    by_site = {
        site: {(mux, selector) for x, y, mux, selector, _, _ in rows if (x, y) == site}
        for site in sites
    }
    reference_site = sorted(sites)[0]
    reference = by_site[reference_site]
    for site, keys in by_site.items():
        if keys != reference:
            raise ValueError(
                f"selector surface differs: {reference_site}={len(reference)}, "
                f"{site}={len(keys)}, missing={len(reference - keys)}, "
                f"extra={len(keys - reference)}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(
        f"wrote {args.output}: {len(rows)} cells, "
        f"{len(reference)} per site across {len(sites)} sites"
    )


if __name__ == "__main__":
    main()
