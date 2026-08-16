#!/usr/bin/env python3
"""SRAM-only causal A/B/C/D matrix for L48 PIN_25 bidirectional I/O.

Safety is enforced in code: Pico GP12 (physical PIN_25) may only be configured
as an input with pull-down/up, and the only Pico output/set operation permitted
is GP4 (physical PIN_10), the FPGA output-enable control.  The FPGA images can
only release PIN_25 or drive it low.  GP8 observes the qualified PIN_18 fabric
readback output.  Flash is never written and cleanup releases every Pico pin
before resetting the AG32.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time

import serial


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "AG32-Docs"
AGM = DOCS / "tools" / "agm_supra"
OPENOCD = AGM / "openocd" / "bin" / "openocd.exe"
SCRIPTS = AGM / "openocd" / "share" / "openocd" / "scripts"
CONFIG = AGM / "pio" / "agrv2k.cfg"
LOADER = DOCS / "tools" / "pico_gpio_tester" / "fabric_loader.bin"

CONTROL_GP = 4
LINE_GP = 12
OBSERVED_GP = 8


def _slash(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _openocd(commands: list[str], tolerate: bool = False) -> str:
    args = [str(OPENOCD), "-s", str(SCRIPTS), "-c", "set ADAPTER cmsis-dap",
            "-f", str(CONFIG)]
    for command in commands:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    transcript = result.stdout + result.stderr
    if result.returncode and not tolerate:
        raise RuntimeError(transcript[-2000:])
    return transcript


def _safe_command(command: str) -> None:
    fields = command.split()
    if not fields or fields[0] in {"ALLIN", "GET", "PING"}:
        return
    if fields[0] == "EDGES":
        assert int(fields[1]) in {LINE_GP, OBSERVED_GP}, \
            "edge counting is limited to the two input-only observation pins"
        return
    if fields[0] == "MODE":
        gp, mode = int(fields[1]), fields[2]
        if gp == LINE_GP:
            assert mode in {"d", "u"}, "GP12 must remain input-only"
        else:
            assert (gp, mode) == (CONTROL_GP, "o"), "only GP4 may be an output"
        return
    if fields[0] == "SET":
        assert int(fields[1]) == CONTROL_GP, "only GP4 may be driven"
        assert int(fields[2]) in {0, 1}
        return
    raise AssertionError("unreviewed Pico command: " + command)


def _pico(port: str, commands: list[str]) -> list[tuple[str, str]]:
    for command in commands:
        _safe_command(command)
    stream = serial.Serial(port, 115200, timeout=1)
    try:
        time.sleep(0.8)
        stream.reset_input_buffer()
        replies = []
        for command in commands:
            stream.write((command + "\n").encode())
            stream.flush()
            replies.append((command, stream.readline().decode(
                errors="replace").strip()))
            time.sleep(0.12)
        return replies
    finally:
        stream.close()


def _prepare_pico(port: str) -> None:
    _pico(port, ["ALLIN", "MODE 4 o", "SET 4 0"])


def _load(image: Path) -> str:
    assert image.stat().st_size == 99944, image
    transcript = _openocd([
        "reset halt",
        f"load_image {_slash(image)} 0x20002000 bin",
        f"load_image {_slash(LOADER)} 0x20000000 bin",
        "reg pc 0x20000000", "reg sp 0x20020000", "resume",
        "sleep 400", "halt", "mdw 0x20001000 2", "resume", "shutdown",
    ])
    rows = [line for line in transcript.splitlines() if "0x20001000:" in line]
    if not rows or "000f0002" not in rows[-1].lower():
        raise RuntimeError("FCB did not accept image\n" + transcript[-2000:])
    return rows[-1].strip()


def _get(port: str, pull: str, drive_low: int, pins: tuple[int, ...]) -> dict[int, int]:
    commands = ["MODE 12 " + pull, f"SET 4 {drive_low}"]
    commands += [f"GET {pin}" for pin in pins]
    replies = _pico(port, commands)
    values = {}
    for command, reply in replies:
        if command.startswith("GET "):
            match = re.fullmatch(r"GP(\d+)=(\d+)", reply)
            assert match, (command, reply)
            values[int(match.group(1))] = int(match.group(2))
    assert set(values) == set(pins), values
    return values


def _expect(observed: dict[int, int], expected: dict[int, int], label: str,
            failures: list[dict]) -> None:
    if observed != expected:
        failures.append({"row": label, "observed": observed, "expected": expected})


def run(directory: Path, port: str) -> dict:
    images = {arm: directory / f"bidir_pin25_{arm}.bin"
              for arm in ("release", "drive", "dynamic", "readback")}
    result = {"hardware": True, "sram_only": True, "flash_written": False,
              "arms": {}}
    failures = []
    try:
        # A: retained scalar-input control. This board's PIN25 line has a
        # strong external high bias that overrides both weak Pico pulls; its
        # qualified fabric readback is correspondingly low.
        _prepare_pico(port)
        fcb = _load(images["release"])
        rows = []
        for pull in ("d", "u"):
            observed = _get(port, pull, 0, (LINE_GP, OBSERVED_GP))
            expected = {LINE_GP: 1, OBSERVED_GP: 0}
            _expect(observed, expected, "release/" + pull, failures)
            rows.append({"pull": pull, "drive_low": 0, "observed": observed})
        result["arms"]["release"] = {"fcb": fcb, "rows": rows}

        # B: retained NEGATIVE scalar-output control. A scalar constant output
        # does not activate this combined physical site and leaves the
        # externally biased line high. This expected negative is not evidence
        # that constant drive-low works.
        _prepare_pico(port)
        fcb = _load(images["drive"])
        rows = []
        for pull in ("d", "u"):
            observed = _get(port, pull, 0, (LINE_GP,))
            _expect(observed, {LINE_GP: 1}, "drive-negative/" + pull, failures)
            rows.append({"pull": pull, "drive_low": 1, "observed": observed})
        result["arms"]["drive"] = {"fcb": fcb, "rows": rows}

        # C: active-high OE. Release exposes the board's high bias under both
        # pulls; asserted EN drives low. Repeat the transition for causality.
        _prepare_pico(port)
        fcb = _load(images["dynamic"])
        rows = []
        for pull in ("d", "u"):
            for enable in (0, 1):
                observed = _get(port, pull, enable, (LINE_GP,))
                expected = {LINE_GP: 0 if enable else 1}
                _expect(observed, expected, f"dynamic/{pull}/en{enable}", failures)
                rows.append({"pull": pull, "drive_low": enable,
                             "observed": observed})
        for enable, expected_line in ((0, 1), (1, 0), (0, 1), (1, 0)):
            observed = _get(port, "u", enable, (LINE_GP,))
            _expect(observed, {LINE_GP: expected_line}, "dynamic/toggle", failures)
        result["arms"]["dynamic"] = {"fcb": fcb, "rows": rows}

        # D: same line truth table plus fabric readback at qualified PIN_18.
        _prepare_pico(port)
        fcb = _load(images["readback"])
        rows = []
        for pull in ("d", "u"):
            for enable in (0, 1):
                line = 0 if enable else 1
                observed = _get(port, pull, enable, (LINE_GP, OBSERVED_GP))
                expected = {LINE_GP: line, OBSERVED_GP: 1 - line}
                _expect(observed, expected, f"readback/{pull}/en{enable}", failures)
                rows.append({"pull": pull, "drive_low": enable,
                             "observed": observed})
        result["arms"]["readback"] = {"fcb": fcb, "rows": rows}
        result["checks"] = {
            "scalar_input_high_bias_and_readback_low": not any(
                failure["row"].startswith("release/") for failure in failures
            ),
            "scalar_constant_output_remains_nonconducting_negative": not any(
                failure["row"].startswith("drive-negative/") for failure in failures
            ),
            "external_pin10_dynamic_oe": not any(
                failure["row"].startswith("dynamic/") for failure in failures
            ),
            "external_pin10_simultaneous_dynamic_readback": not any(
                failure["row"].startswith("readback/") for failure in failures
            ),
        }
        result["failures"] = failures
        result["result"] = "pass" if not failures else "fail"
        return result
    finally:
        try:
            _pico(port, ["ALLIN"])
        finally:
            _openocd(["init", "reset halt", "reset run", "shutdown"], tolerate=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", type=Path,
                        default=ROOT / "tools" / "lab")
    parser.add_argument("--port", default="COM6")
    args = parser.parse_args()
    result = run(args.directory.resolve(), args.port)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Pico ALLIN, AG32 reset/run, board token may be released")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
