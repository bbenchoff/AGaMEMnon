#!/usr/bin/env python3
"""Reapply a retained vendor-bit differential to a newer framed image.

This is a laboratory isolation helper, not a bitstream-generation path.  A
retained experiment consists of an old framed baseline, a framed hybrid, and
the raw vendor image used to make that hybrid.  For every bit where the old
baseline and vendor differ, the tool selects the bits that the hybrid took
from the vendor and reapplies only those bits to a new framed baseline.

The eight-byte AGaMEMnon frame header is copied from the new baseline and the
fabric CRC is always regenerated after composition.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agamemnon.engine import agasc


FRAME_BYTES = 8


def read_framed(path: Path) -> bytearray:
    data = bytearray(path.read_bytes())
    if len(data) <= FRAME_BYTES:
        raise ValueError(f"{path}: expected an eight-byte header and raw payload")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-base", type=Path, required=True)
    parser.add_argument("--old-base", type=Path, required=True)
    parser.add_argument("--old-hybrid", type=Path, required=True)
    parser.add_argument("--subtract-hybrid", type=Path, action="append", default=[])
    parser.add_argument("--vendor-raw", type=Path, required=True)
    parser.add_argument(
        "--include-tile",
        action="append",
        default=[],
        metavar="X,Y",
        help="retain only named configuration cells in these physical tiles",
    )
    parser.add_argument(
        "--chipdb",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "agamemnon" / "chipdb",
    )
    parser.add_argument(
        "--include-feature",
        action="append",
        default=[],
        metavar="NAME",
        help="with --include-tile, retain only these feature families",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    new_base = read_framed(args.new_base)
    old_base = read_framed(args.old_base)
    old_hybrid = read_framed(args.old_hybrid)
    subtract_hybrids = [read_framed(path) for path in args.subtract_hybrid]
    vendor = args.vendor_raw.read_bytes()
    expected = len(vendor) + FRAME_BYTES
    lengths = {
        len(new_base), len(old_base), len(old_hybrid), expected,
        *(len(image) for image in subtract_hybrids),
    }
    if len(lengths) != 1:
        raise ValueError(
            "image sizes disagree: new=%d old=%d hybrid=%d vendor+header=%d"
            % (len(new_base), len(old_base), len(old_hybrid), expected)
        )

    include_tiles = set()
    for value in args.include_tile:
        try:
            x_text, y_text = value.split(",", 1)
            include_tiles.add((int(x_text, 0), int(y_text, 0)))
        except ValueError as exc:
            raise ValueError(f"invalid --include-tile {value!r}; expected X,Y") from exc
    if args.include_feature and not include_tiles:
        raise ValueError("--include-feature requires at least one --include-tile")
    by_bit = agasc.load_feature_map(str(args.chipdb))[0] if include_tiles else {}

    output = bytearray(new_base)
    selected_bits = 0
    selected_bytes = 0
    for raw_offset, vendor_byte in enumerate(vendor[: agasc.CRC_OFFSET]):
        framed_offset = raw_offset + FRAME_BYTES
        differing = old_base[framed_offset] ^ vendor_byte
        selected = differing & ~(old_hybrid[framed_offset] ^ vendor_byte)
        for subtract in subtract_hybrids:
            selected &= subtract[framed_offset] ^ vendor_byte
        if include_tiles:
            allowed = 0
            for mask in (1, 2, 4, 8, 16, 32, 64, 128):
                feature = by_bit.get((raw_offset, mask))
                if feature is None or feature[:2] not in include_tiles:
                    continue
                family = feature[2].split("[", 1)[0]
                if args.include_feature and family not in args.include_feature:
                    continue
                allowed |= mask
            selected &= allowed
        if not selected:
            continue
        selected_bits += bin(selected).count("1")  # int.bit_count() is 3.10+; keep >=3.8 compatible
        selected_bytes += 1
        output[framed_offset] = (
            (output[framed_offset] & ~selected) | (vendor_byte & selected)
        )

    raw = output[FRAME_BYTES:]
    raw[agasc.CRC_OFFSET :] = struct.pack(
        ">I", agasc.crc32_bzip2(bytes(output[:FRAME_BYTES]) + bytes(raw[: agasc.CRC_OFFSET]))
    )
    output[FRAME_BYTES:] = raw

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(f"selected_bits={selected_bits}")
    print(f"selected_bytes={selected_bytes}")
    print(f"sha256={hashlib.sha256(output).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
