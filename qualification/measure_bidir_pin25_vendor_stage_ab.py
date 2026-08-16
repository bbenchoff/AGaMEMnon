#!/usr/bin/env python3
"""SRAM-only causal A/B for the PIN10 -> PIN25 OE re-buffer boundary.

A is the retained release-strict direct-mesh image that config-accepts but did
not respond to PIN10.  B differs architecturally by the vendor-observed
X14Y4_SLICE4 identity stage.  GP4 is the sole Pico output (PIN10); GP12/PIN25
and GP8/PIN18 remain input-only.  Both FPGA images can only release PIN25 or
drive a local hard zero.  Flash is never written and the shared campaign
helpers enforce ALLIN plus AG32 reset/run cleanup.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from measure_bidir_pin25_campaign import _get, _load, _openocd, _pico, _prepare_pico


ROOT = Path(__file__).resolve().parents[1]
LINE_GP = 12
OBSERVED_GP = 8


def _matrix(image: Path, port: str) -> dict:
    _prepare_pico(port)
    fcb = _load(image)
    rows = []
    for pull, released in (("d", 0), ("u", 1)):
        for enable in (0, 1):
            observed = _get(port, pull, enable, (LINE_GP, OBSERVED_GP))
            expected_line = 0 if enable else released
            rows.append({
                "pull": pull,
                "drive_low": enable,
                "observed": observed,
                "expected": {LINE_GP: expected_line, OBSERVED_GP: 1 - expected_line},
            })
    toggles = []
    for enable in (0, 1, 0, 1):
        toggles.append({
            "drive_low": enable,
            "observed": _get(port, "u", enable, (LINE_GP, OBSERVED_GP)),
        })
    return {"fcb": fcb, "rows": rows, "pullup_toggles": toggles}


def run(directory: Path, port: str) -> dict:
    direct = directory / "bidir_pin25_readback.bin"
    staged = directory / "bidir_pin25_oe_vendor_stage.bin"
    result = {
        "hardware": True,
        "sram_only": True,
        "flash_written": False,
        "direct_image": str(direct),
        "vendor_stage_image": str(staged),
    }
    try:
        result["direct"] = _matrix(direct, port)
        result["vendor_stage"] = _matrix(staged, port)

        direct_up = [row for row in result["direct"]["rows"] if row["pull"] == "u"]
        staged_rows = result["vendor_stage"]["rows"]
        direct_is_negative = tuple(row["observed"][LINE_GP] for row in direct_up) != (1, 0)
        staged_truth = all(row["observed"] == row["expected"] for row in staged_rows)
        staged_toggle = [row["observed"] for row in result["vendor_stage"]["pullup_toggles"]]
        expected_toggle = [
            {LINE_GP: 1, OBSERVED_GP: 0},
            {LINE_GP: 0, OBSERVED_GP: 1},
            {LINE_GP: 1, OBSERVED_GP: 0},
            {LINE_GP: 0, OBSERVED_GP: 1},
        ]
        result["causal_checks"] = {
            "direct_pullup_does_not_follow_enable": direct_is_negative,
            "vendor_stage_full_dual_pull_truth_table": staged_truth,
            "vendor_stage_repeated_pullup_toggle": staged_toggle == expected_toggle,
        }
        result["result"] = "pass" if all(result["causal_checks"].values()) else "fail"
        return result
    finally:
        try:
            _pico(port, ["ALLIN"])
        finally:
            _openocd(["init", "reset halt", "reset run", "shutdown"], tolerate=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path, default=ROOT / "tools" / "lab")
    parser.add_argument("--port", default="COM6")
    args = parser.parse_args()
    result = run(args.directory.resolve(), args.port)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Pico ALLIN, AG32 reset/run, board token may be released")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
