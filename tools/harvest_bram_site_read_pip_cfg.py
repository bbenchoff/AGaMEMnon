#!/usr/bin/env python3
"""Recover exact selector fields for the sensitized four-site BRAM trees.

The input raw image and path table must come from the same retained vendor
oracle.  For each configurable destination mux this records the complete
destination subfield, not merely the asserted bits.  Bitgen can therefore
replace an inferred selector atomically with the codeword that was exercised
by the 512-address four-site silicon run.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


HEADER = [
    "src_wire", "dst_wire", "cell_table", "x", "y", "cfg_group",
    "clear_selectors", "set_selectors", "evidence",
]
WIRE_RE = re.compile(r"X(\d+)Y(\d+)_(RMUX|IMUX|SeamMUX|CtrlMUX)(\d+)")
NPG = {"RMUX": 6, "IMUX": 4}
BLOCK_SIZE = {"RMUX": 10, "IMUX": 12}
EVIDENCE = "bram-four-site-simultaneous-x18-full-depth-read-20260816"
# HREADY clock-enable branch used by all four arrays.  The first harvest kept
# only address/data/clock nets, but the Y4 terminal selector is also directly
# sensitized by the same full-depth run and is required to replace the stale
# ROM-control baseline atomically.
EXTRA_EDGES = (("X14Y4_RMUX84", "X13Y4_CtrlMUX02"),)


def load_cells(path: Path) -> dict[tuple[int, int, str, int], tuple[int, int]]:
    cells = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = (int(row["x"]), int(row["y"]), row["mux"], int(row["sel"]))
            cells[key] = (int(row["byte"]), int(row["mask"]))
    return cells


def destination_field(
    wire: str, cells: dict[tuple[int, int, str, int], tuple[int, int]]
) -> tuple[int, int, str, list[int]] | None:
    match = WIRE_RE.fullmatch(wire)
    if match is None:
        return None
    x, y, family, index = (
        int(match.group(1)), int(match.group(2)), match.group(3), int(match.group(4))
    )
    if family in NPG:
        cfg = f"CFG_{family}{index // NPG[family]}"
        first = (index % NPG[family]) * BLOCK_SIZE[family]
        selectors = list(range(first, first + BLOCK_SIZE[family]))
    elif family == "CtrlMUX":
        cfg = "CFG_CTRLMUX"
        first = (index // 2) * 24
        selectors = list(range(first, first + 24))
    else:
        cfg = "CFG_SeamMUX"
        selectors = sorted(
            selection
            for cx, cy, mux, selection in cells
            if (cx, cy, mux) == (x, y, cfg)
        )
    return x, y, cfg, selectors


def extract(paths: Path, raw_path: Path, cells_path: Path) -> list[list[object]]:
    raw = raw_path.read_bytes()
    cells = load_cells(cells_path)
    output = {}

    def add_edge(source: str, destination: str) -> None:
        field = destination_field(destination, cells)
        if field is None:
            return
        x, y, cfg, selectors = field
        missing = [
            selection for selection in selectors
            if (x, y, cfg, selection) not in cells
        ]
        if missing:
            raise ValueError(
                f"{destination}: {cfg} has missing cells {missing}"
            )
        set_selectors = [
            selection for selection in selectors
            if raw[cells[(x, y, cfg, selection)][0]]
            & cells[(x, y, cfg, selection)][1]
        ]
        # A mux input may be the all-clear codeword.  Keeping the complete
        # clear field is what distinguishes that valid selection from a
        # zero-bit/fixed hop; do not discard it merely because it sets no
        # cells in the passing image.
        key = (source, destination)
        row = [
            *key, "fabric", x, y, cfg,
            ";".join(map(str, selectors)),
            ";".join(map(str, set_selectors)), EVIDENCE,
        ]
        prior = output.setdefault(key, row)
        if prior != row:
            raise ValueError(f"conflicting recovered codewords for {key}")

    with paths.open(newline="", encoding="utf-8") as stream:
        for path_row in csv.DictReader(stream):
            add_edge(path_row["src_wire"], path_row["dst_wire"])
    for source, destination in EXTRA_EDGES:
        add_edge(source, destination)
    return [output[key] for key in sorted(output)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", type=Path)
    parser.add_argument("raw_image", type=Path)
    parser.add_argument("pips_full", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = extract(args.paths, args.raw_image, args.pips_full)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"wrote {len(rows)} exact four-site selector fields -> {args.output}")


if __name__ == "__main__":
    main()
