#!/usr/bin/env python3
"""Rebase the exact qualified 16-bit scratch register from +0 to +4.

This is a deliberately tiny qualification composer, not a general register-bank
generator.  It admits exactly two reviewed LUT INIT transitions in the existing
silicon-qualified checkpoint and requires every BEL, route, connection, and
other parameter to remain byte-for-byte equivalent after canonical JSON decode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE / "mcu_ahb_register_bank16_read_word0_gated_routed.json"
DEFAULT_OUT = HERE / "mcu_ahb_register_bank16_public_scratch4_routed.json"
BASE_SHA256 = "1daa7de2d8a5297182b35c21d745900e93bb540bd4ca3320449108dccd3fbef2"
OUTPUT_SHA256 = "97f164a72b22ea2f076f889ee771b577f482384469266dc489e0b2f243590610"
CHANGES = {
    "hwrite_word0_gate": ("0000000001000100", "0000000010001000"),
    "read_word0": ("0001000100010001", "0010001000100010"),
}


def lut(init: str, *inputs: int) -> int:
    index = sum((value & 1) << bit for bit, value in enumerate(inputs))
    return (int(init, 2) >> index) & 1


def compose() -> bytes:
    raw = BASE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise SystemExit("qualified +0 checkpoint hash drifted")
    design = json.loads(raw)
    cells = design["modules"]["top"]["cells"]
    before = json.loads(json.dumps(design))

    for name, (old, new) in CHANGES.items():
        actual = cells[name]["parameters"]["INIT"]
        if actual != old:
            raise SystemExit(
                "%s baseline INIT drifted: expected %s, got %s" %
                (name, old, actual)
            )
        cells[name]["parameters"]["INIT"] = new

    # Prove the two truth-table changes are exactly address +0 -> +4.
    old_write, new_write = CHANGES["hwrite_word0_gate"]
    old_read, new_read = CHANGES["read_word0"]
    for a3 in range(2):
        for a2 in range(2):
            for hwrite in range(2):
                assert lut(old_write, a2, hwrite, 0, a3) == int(
                    bool(hwrite and not a3 and not a2))
                assert lut(new_write, a2, hwrite, 0, a3) == int(
                    bool(hwrite and not a3 and a2))
            assert lut(old_read, a2, a3, 0, 0) == int(
                bool(not a3 and not a2))
            assert lut(new_read, a2, a3, 0, 0) == int(
                bool(not a3 and a2))

    # Fail if the composer ever grows another mutation surface.
    for name, cell in cells.items():
        reference = before["modules"]["top"]["cells"][name]
        if name in CHANGES:
            candidate = json.loads(json.dumps(cell))
            candidate["parameters"]["INIT"] = CHANGES[name][0]
            if candidate != reference:
                raise SystemExit("unexpected mutation outside %s.INIT" % name)
        elif cell != reference:
            raise SystemExit("unexpected mutation in cell %s" % name)
    if design["modules"]["top"]["netnames"] != \
            before["modules"]["top"]["netnames"]:
        raise SystemExit("route or net mutation is forbidden")
    if design["modules"]["top"]["ports"] != \
            before["modules"]["top"]["ports"]:
        raise SystemExit("top-level port mutation is forbidden")

    if len(cells) != 101:
        raise SystemExit("expected exactly 101 placed cells")
    routed = [net for net in design["modules"]["top"]["netnames"].values()
              if net.get("attributes", {}).get("ROUTING")]
    if len(routed) != 83:
        raise SystemExit("expected exactly 83 routed nets")

    encoded = (json.dumps(design, indent=2) + "\n").encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != OUTPUT_SHA256:
        raise SystemExit("+4 candidate hash does not match reviewed artifact")
    return encoded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    encoded = compose()
    args.out.write_bytes(encoded)
    print("wrote %s sha256=%s" %
          (args.out, hashlib.sha256(encoded).hexdigest()))
    print("admitted changes: hwrite_word0_gate + read_word0 INIT, +0 -> +4")


if __name__ == "__main__":
    main()
