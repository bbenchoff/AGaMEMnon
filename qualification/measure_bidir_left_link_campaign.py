#!/usr/bin/env python3
"""SRAM-only electrical matrix for the retained four-link L48 OE oracle.

The vendor-routed image is used only as an electrical/topology oracle for the
four exact OE corridors already represented by AGaMEMnon.  Pico GP1/2/4/9
drive package inputs; GP12/13/16/17 remain input-only.  Every pad output is a
hard zero behind an XOR-controlled enable, so no image can drive a link high.
Cleanup releases every Pico pin and resets the AG32.  Flash is never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

import serial


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT.parent / "AG32-Docs"
CONTROLS = {"common": 4, "drive0": 1, "drive1": 2, "drive2": 9}
LINK_GPS = (12, 13, 16, 17)


def _slash(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_openocd() -> Path:
    configured = os.environ.get("AGAMEMNON_OPENOCD")
    if configured:
        return Path(configured)
    local = ROOT / ".tmp" / "openocd-win-release" / "bin" / "openocd.exe"
    if local.exists():
        return local
    return DOCS / "tools" / "agm_supra" / "openocd" / "bin" / "openocd.exe"


def _openocd(executable: Path, scripts: Path, config: Path,
             commands: list[str], tolerate: bool = False) -> str:
    args = [str(executable), "-s", str(scripts), "-f", str(config)]
    for command in commands:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    transcript = result.stdout + result.stderr
    if result.returncode and not tolerate:
        raise RuntimeError(transcript[-3000:])
    return transcript


def _safe(command: str) -> None:
    fields = command.split()
    if not fields or fields[0] in {"ALLIN", "PING", "READ"}:
        return
    if fields[0] == "MODE":
        gp, mode = int(fields[1]), fields[2]
        if gp in LINK_GPS:
            assert mode in {"u", "d"}, "link probes must remain input-only"
        else:
            assert gp in CONTROLS.values() and mode == "o", \
                "only reviewed package-input controls may be outputs"
        return
    if fields[0] == "SET":
        assert int(fields[1]) in CONTROLS.values()
        assert int(fields[2]) in {0, 1}
        return
    raise AssertionError("unreviewed Pico command: " + command)


def _pico(port: str, commands: list[str]) -> list[tuple[str, str]]:
    for command in commands:
        _safe(command)
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


def _prepare(port: str) -> None:
    commands = ["ALLIN"]
    for gp in CONTROLS.values():
        commands += [f"MODE {gp} o", f"SET {gp} 0"]
    commands += [f"MODE {gp} u" for gp in LINK_GPS]
    _pico(port, commands)


def _load(executable: Path, scripts: Path, config: Path, loader: Path,
          image: Path) -> str:
    assert image.stat().st_size == 99944, image
    transcript = _openocd(executable, scripts, config, [
        "init", "reset halt",
        f"load_image {_slash(image)} 0x20002000 bin",
        f"load_image {_slash(loader)} 0x20000000 bin",
        "reg pc 0x20000000", "reg sp 0x20020000", "resume",
        "sleep 400", "halt", "mdw 0x20001000 2", "resume", "shutdown",
    ])
    rows = [line for line in transcript.splitlines() if "0x20001000:" in line]
    if not rows or "000f0002" not in rows[-1].lower():
        raise RuntimeError("FCB did not accept image\n" + transcript[-3000:])
    return rows[-1].strip()


def _matrix(port: str, pull: str) -> list[dict]:
    # drive[3]/PIN_20 is not wired to the Pico.  It remains stable, while
    # toggling `common` must invert PIN_28's OE regardless of its static level.
    sequence = [
        (0, (0, 0, 0)), (1, (0, 0, 0)),
        (1, (1, 1, 1)), (0, (1, 1, 1)),
        (1, (1, 1, 1)), (0, (1, 1, 1)),
    ]
    commands = [f"MODE {gp} {pull}" for gp in LINK_GPS]
    for common, drives in sequence:
        commands += [f"SET {CONTROLS['common']} {common}"]
        for name, value in zip(("drive0", "drive1", "drive2"), drives):
            commands += [f"SET {CONTROLS[name]} {value}"]
        commands += ["READ " + ",".join(str(gp) for gp in LINK_GPS)]
    replies = _pico(port, commands)
    reads = [reply for command, reply in replies if command.startswith("READ ")]
    assert len(reads) == len(sequence), reads
    rows = []
    for (common, drives), reply in zip(sequence, reads):
        observed = {int(gp): int(value)
                    for gp, value in re.findall(r"GP(\d+)=(\d+)", reply)}
        assert set(observed) == set(LINK_GPS), (reply, observed)
        rows.append({"common": common, "drive": list(drives),
                     "observed": [observed[gp] for gp in LINK_GPS]})
    return rows


def run(image: Path, port: str, executable: Path, scripts: Path,
        config: Path, loader: Path) -> dict:
    failures = []
    try:
        _prepare(port)
        fcb = _load(executable, scripts, config, loader, image)
        matrices = {}
        for pull in ("u", "d"):
            rows = _matrix(port, pull)
            matrices[pull] = rows
            pin28_values = [row["observed"][3] for row in rows]
            for index, row in enumerate(rows):
                expected_first3 = [
                    0 if row["common"] ^ drive else 1
                    for drive in row["drive"]
                ]
                if pull == "u":
                    if row["observed"][:3] != expected_first3:
                        failures.append({"pull": pull, "row": index,
                                         "expected_first3": expected_first3,
                                         "observed": row["observed"]})
                else:
                    # With the Pico pull-down, a released open-drain line may
                    # legitimately read zero.  Assert only that every enabled
                    # drive-low state is in fact low.
                    for link, (expected, observed) in enumerate(zip(
                            expected_first3, row["observed"][:3])):
                        if expected == 0 and observed != 0:
                            failures.append({"pull": pull, "row": index,
                                             "link": link, "expected": 0,
                                             "observed": observed})
            # common sequence is 0,1,1,0,1,0.  PIN28 must invert exactly when
            # common changes and hold when it does not; its unknown drive3
            # value only chooses the polarity of the first sample.
            if pull == "u":
                for index in range(1, len(rows)):
                    changed = rows[index]["common"] != rows[index - 1]["common"]
                    expected = 1 - pin28_values[index - 1] if changed \
                        else pin28_values[index - 1]
                    if pin28_values[index] != expected:
                        failures.append({"pull": pull, "row": index,
                                         "pin": "PIN_28", "expected": expected,
                                         "observed": pin28_values[index]})
                if set(pin28_values) != {0, 1}:
                    failures.append({"pull": pull, "pin": "PIN_28",
                                     "expected_states": [0, 1],
                                     "observed_states": sorted(set(pin28_values))})
        return {
            "hardware": True, "sram_only": True, "flash_written": False,
            "image_sha256": _sha256(image), "fcb": fcb,
            "controls": CONTROLS, "links": list(LINK_GPS),
            "matrices": matrices, "failures": failures,
            "result": "pass" if not failures else "fail",
        }
    finally:
        try:
            _pico(port, ["ALLIN"])
        finally:
            _openocd(executable, scripts, config,
                     ["init", "reset halt", "reset run", "shutdown"],
                     tolerate=True)


def main() -> int:
    oracle = (DOCS / "tools" / "oracle_node_pinout_l48" /
              "vendor_oe_logic_quad" / "oe_logic_quad_distinct.bin")
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", type=Path, default=oracle)
    parser.add_argument("--port", default="COM6")
    parser.add_argument("--openocd", type=Path, default=_default_openocd())
    parser.add_argument("--scripts", type=Path, default=(
        ROOT / ".tmp" / "openocd-win-release" / "share" / "openocd" / "scripts"))
    parser.add_argument("--config", type=Path,
                        default=ROOT / "agamemnon" / "openocd" / "agrv2k.cfg")
    parser.add_argument("--loader", type=Path, default=(
        DOCS / "tools" / "pico_gpio_tester" / "fabric_loader.bin"))
    args = parser.parse_args()
    result = run(args.image.resolve(), args.port, args.openocd.resolve(),
                 args.scripts.resolve(), args.config.resolve(), args.loader.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Pico ALLIN, AG32 reset/run; no flash write was issued")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
