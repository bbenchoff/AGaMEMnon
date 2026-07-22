#!/usr/bin/env python3
"""Generate AGRV2K package-to-IOTILE maps from a decoded ``alta-agr.ar``.

The input belongs in the reverse-engineering workbench.  The generated CSVs
and manifest are the small, reviewable products promoted to this repository.
Generation is deliberately strict: duplicate package pins, interior pads, and
unexpected L48 changes are errors.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


PACKAGES = {
    "AGRV2KL100": "bondmap_L100.csv",
    "AGRV2KL64": "bondmap_L64.csv",
    "AGRV2KL48": "bondmap_L48.csv",
    "AGRV2KQ32": "bondmap_Q32.csv",
}
EXPECTED_COUNTS = {
    "AGRV2KL100": 78,
    "AGRV2KL64": 49,
    "AGRV2KL48": 34,
    "AGRV2KQ32": 26,
}
CHIP_RE = re.compile(
    r"^CHIP\s+(\S+)\s*$(.*?)(?=^CHIP\s+\S+\s*$|\Z)", re.MULTILINE | re.DOTALL
)
PIN_RE = re.compile(
    r"PIN_LIST\s*:\s*(PIN_\d+)\s+\S+\s+\S+\s+"
    r"(\d+)\s+(\d+)\s+(\d+)\s*;"
)


def edge_for(x: int, y: int) -> str:
    if x == 0:
        return "LEFT"
    if x == 22:
        return "RIGHT"
    if y == 0:
        return "BOTTOM"
    if y == 13:
        return "TOP"
    raise ValueError(f"I/O coordinate X{x}Y{y} is not on the AGRV2K perimeter")


def parse_package_maps(text: str) -> dict[str, list[dict[str, object]]]:
    blocks = {match.group(1): match.group(2) for match in CHIP_RE.finditer(text)}
    result: dict[str, list[dict[str, object]]] = {}
    for device in PACKAGES:
        if device not in blocks:
            raise ValueError(f"decoded architecture has no CHIP {device}")
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for match in PIN_RE.finditer(blocks[device]):
            pin = match.group(1)
            if pin in seen:
                raise ValueError(f"{device}: duplicate {pin}")
            seen.add(pin)
            x, y, z = (int(match.group(i)) for i in (2, 3, 4))
            rows.append({"pin": pin, "x": x, "y": y, "z": z, "edge": edge_for(x, y)})
        rows.sort(key=lambda row: int(str(row["pin"]).split("_")[1]))
        if len(rows) != EXPECTED_COUNTS[device]:
            raise ValueError(
                f"{device}: decoded {len(rows)} physical pins; expected {EXPECTED_COUNTS[device]}"
            )
        result[device] = rows
    return result


def read_rows(path: Path) -> list[dict[str, object]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return [
            {
                "pin": row["pin"],
                "x": int(row["x"]),
                "y": int(row["y"]),
                "z": int(row["z"]),
                "edge": row["edge"],
            }
            for row in csv.DictReader(stream)
        ]


def generate(source: Path, output: Path, *, check_l48: Path | None = None) -> dict[str, object]:
    raw = source.read_bytes()
    maps = parse_package_maps(raw.decode("utf-8", errors="strict"))
    if check_l48 is not None and read_rows(check_l48) != maps["AGRV2KL48"]:
        raise ValueError(f"decoded L48 map differs from qualified map {check_l48}")
    output.mkdir(parents=True, exist_ok=True)
    for device, filename in PACKAGES.items():
        with (output / filename).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=("pin", "x", "y", "z", "edge"))
            writer.writeheader()
            writer.writerows(maps[device])
    manifest = {
        "schema": 1,
        "generator": "tools/generate_package_maps.py",
        "source_kind": "decoded-alta-agr-architecture",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "devices": {
            device: {
                "file": filename,
                "physical_pin_count": len(maps[device]),
                "qualification": "silicon-qualified" if device == "AGRV2KL48" else "recovered-unqualified",
            }
            for device, filename in PACKAGES.items()
        },
        "notes": [
            "Coordinates are recovered from package PIN_LIST records.",
            "L48 is byte-for-byte regenerated from the independently qualified map.",
            "AGRV2KL100 PIN_73 is NC_73 in the decoded package and is intentionally absent.",
        ],
    }
    (output / "bondmaps.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="decoded alta-agr.ar input")
    parser.add_argument("--output", type=Path, required=True, help="chipdb output directory")
    parser.add_argument(
        "--check-l48", type=Path, help="independently qualified L48 CSV to compare before writing"
    )
    args = parser.parse_args()
    manifest = generate(args.source, args.output, check_l48=args.check_l48)
    for device, entry in manifest["devices"].items():
        print(f"{device}: {entry['physical_pin_count']} pins ({entry['qualification']})")


if __name__ == "__main__":
    main()
