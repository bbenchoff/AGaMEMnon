#!/usr/bin/env python3
"""SRAM-only X14Y4 stage-output controls, then external PIN10 experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from measure_bidir_pin25_campaign import _get, _load, _openocd, _pico, _prepare_pico


ROOT = Path(__file__).resolve().parents[1]
LINE_GP = 12
OBS_GP = 8


def _rows(image: Path, port: str) -> dict:
    _prepare_pico(port)
    fcb = _load(image)
    rows = []
    for pull in ("d", "u"):
        for drive_low in (0, 1):
            rows.append({"pull": pull, "drive_low": drive_low,
                         "observed": _get(port, pull, drive_low, (LINE_GP, OBS_GP))})
    return {"fcb": fcb, "rows": rows}


def run(directory: Path, port: str) -> dict:
    result = {"hardware": True, "sram_only": True, "flash_written": False, "arms": {}}
    try:
        for arm in ("const0", "const1"):
            image = directory / f"bidir_pin25_stage_probe_{arm}.bin"
            result["arms"][arm] = _rows(image, port)

        const0_ok = all(row["observed"][OBS_GP] == 0 for row in result["arms"]["const0"]["rows"])
        const1_ok = all(row["observed"][OBS_GP] == 1 for row in result["arms"]["const1"]["rows"])
        calibration = const0_ok and const1_ok
        result["constant_channel_calibrated"] = calibration
        if calibration:
            image = directory / "bidir_pin25_stage_probe_external.bin"
            result["arms"]["external"] = _rows(image, port)
            # Repeat the high-information pull-up sequence after the full matrix.
            result["arms"]["external"]["pullup_toggles"] = [
                {"drive_low": value,
                 "observed": _get(port, "u", value, (LINE_GP, OBS_GP))}
                for value in (0, 1, 0, 1)
            ]

        # Constant controls calibrate both direct stage observation and the
        # downstream OE response: const0 releases (pull-sensitive) and const1
        # drives low.  Only after that gate may external ingress be interpreted.
        c0 = result["arms"]["const0"]["rows"]
        c1 = result["arms"]["const1"]["rows"]
        # This rig's released PIN25 is externally biased high strongly enough
        # to override the Pico's weak pull-down; the earlier constant-OE A/B
        # established that exact behavior.  GP8 is the direct stage probe and
        # remains the primary calibration; GP12 high/low distinguishes the
        # same known release versus drive-low states downstream.
        const0_link = all(row["observed"][LINE_GP] == 1 for row in c0)
        const1_link = all(row["observed"][LINE_GP] == 0 for row in c1)
        external_ok = False
        if calibration:
            external = result["arms"]["external"]["rows"]
            external_ok = all(
                row["observed"][OBS_GP] == row["drive_low"] and
                row["observed"][LINE_GP] ==
                    (0 if row["drive_low"] else (1 if row["pull"] == "u" else 0))
                for row in external
            )
            external_ok = external_ok and [
                row["observed"][OBS_GP]
                for row in result["arms"]["external"]["pullup_toggles"]
            ] == [0, 1, 0, 1]
        result["checks"] = {
            "const0_stage_low_and_pin25_known_high_release_state": const0_ok and const0_link,
            "const1_stage_high_and_link_driven_low": const1_ok and const1_link,
            "external_pin10_controls_stage_and_oe": external_ok,
        }
        result["result"] = "pass" if all(result["checks"].values()) else "negative"
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
