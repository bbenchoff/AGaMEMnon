#!/usr/bin/env python3
"""Reproduce the routed public32 status-overlay qualification images.

Production uses the ordinary release compositor.  ``--zero-control`` changes
only the final user LUT which drives ``status_set`` to constant zero; every
placed cell, route, core edit, and removed qualification hook remains
identical.  That is the causal silicon control for the user-owned event.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agamemnon.engine import status_overlay


HERE = Path(__file__).resolve().parent
OVERLAY = HERE / "mcu_ahb_status_overlay_pulse_checkpoint.json"


def build(zero_control=False):
    design, report = status_overlay.compose(OVERLAY)
    if zero_control:
        top = design["modules"]["top"]
        event_bit = top["netnames"][report["event_net"]]["bits"][0]
        drivers = [
            (name, cell) for name, cell in top["cells"].items()
            if cell.get("type") == "GENERIC_SLICE" and
            cell.get("connections", {}).get("F") == [event_bit]
        ]
        if len(drivers) != 1 or not drivers[0][0].startswith(
                status_overlay.PREFIX):
            raise status_overlay.StatusOverlayError(
                "zero control requires exactly one user LUT event driver")
        drivers[0][1]["parameters"]["INIT"] = "0" * 16
        report["zero_control_cell"] = drivers[0][0]
    return design, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zero-control", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    design, report = build(args.zero_control)
    with args.out.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(design, output, indent=2)
        output.write("\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
