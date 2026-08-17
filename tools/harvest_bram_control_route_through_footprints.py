#!/usr/bin/env python3
"""Extract experimental BRAM control/address identity-slice bytes from an oracle.

The four-site x18 oracle routes HREADY and HWRITE through five physical I3
identity slices and two AddressA lanes through implicit identity slices.  This
deliberately records only the four LUT/permutation bytes at each site.  The
matching final-input and downstream routing selectors remain owned by
``bram_site_read_pip_cfg.csv`` and are enabled by the same experimental profile.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from agamemnon.engine.physmap import init_bit_pos


HEADER = [
    "x", "y", "z", "init", "source_wire", "dest_wire", "byte", "value",
    "write_mask", "selector_mask", "sparse_policy",
]
SITES = (
    (14, 9, 9, "X14Y9_RMUX41", "X14Y9_IMUX39"),
    (14, 8, 14, "X14Y8_RMUX47", "X14Y8_IMUX59"),
    (14, 8, 9, "X14Y8_RMUX71", "X14Y8_IMUX39"),
    (14, 7, 14, "X14Y7_RMUX41", "X14Y7_IMUX59"),
    (14, 5, 7, "X14Y5_RMUX41", "X14Y5_IMUX31"),
    (14, 5, 4, "X14Y5_RMUX41", "X14Y5_IMUX19"),
    (14, 4, 3, "X14Y4_RMUX47", "X14Y4_IMUX15"),
)


def extract(raw_path: Path) -> list[list[object]]:
    raw = raw_path.read_bytes()
    rows: list[list[object]] = []
    owned: set[int] = set()
    for x, y, z, source, destination in SITES:
        bytes_at_site = sorted({init_bit_pos(x, y, z, bit)[0] for bit in range(16)})
        if len(bytes_at_site) != 4:
            raise ValueError(f"X{x}Y{y} slice{z}: expected four LUT bytes")
        for byte in bytes_at_site:
            if byte in owned:
                raise ValueError(f"byte {byte} is owned by multiple control slices")
            owned.add(byte)
            rows.append([
                x, y, z, 0xFF00, source, destination, byte, raw[byte],
                0xFF, 0, "fail_closed",
            ])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_image", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = extract(args.raw_image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"wrote {len(rows)} experimental control route-through rows -> {args.output}")


if __name__ == "__main__":
    main()
