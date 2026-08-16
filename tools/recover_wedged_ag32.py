#!/usr/bin/env python3
"""Recover an AG32 whose SRAM program cannot be halted.

An External-AHB fabric slave can accidentally hold HREADY low forever.  In
that state OpenOCD can still reach the RISC-V Debug Module through the ADIv5
access port, but normal target examination and ``reset halt`` fail because the
hart cannot retire the halt request.  Assert ``dmcontrol.ndmreset`` directly,
without executing a core or system-bus transaction, then verify the recovered
hart and device ID.

This is volatile recovery only.  It does not erase or program flash, option
bytes, or the fabric configuration store.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


DEVICE_ID = 0x40200001


def command_prefix(openocd: Path, scripts: Path, config: Path) -> list[str]:
    return [
        str(openocd), "-s", str(scripts), "-c", "set ADAPTER cmsis-dap",
        "-f", str(config),
    ]


def recovery_commands(dap: str) -> list[str]:
    # AP register 0x04 selects a Debug Module register, in byte-addressed AP
    # units. DMCONTROL is DM register 0x10, hence 0x40. AP register 0x0c is
    # the selected register's data window.  dmactive=1, ndmreset=1 is 0x3;
    # retaining dmactive while releasing reset is 0x1.
    select = f"{dap} apreg 0 0x04 0x40"
    return [
        "init",
        select,
        f"{dap} apreg 0 0x0c 0x00000003",
        "sleep 100",
        select,
        f"{dap} apreg 0 0x0c 0x00000001",
        "sleep 500",
        "shutdown",
    ]


def verification_commands() -> list[str]:
    return ["init", "halt", "mdw 0x03000100", "reset", "shutdown"]


def invoke(prefix: list[str], commands: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    argv = list(prefix)
    for command in commands:
        argv.extend(["-c", command])
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def device_id(log: str) -> int | None:
    match = re.search(r"0x03000100:\s+([0-9a-fA-F]{8})", log)
    return int(match.group(1), 16) if match else None


def default_config() -> Path:
    return Path(__file__).resolve().parents[1] / "agamemnon" / "openocd" / "agrv2k.cfg"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--openocd", default=os.environ.get("AGAMEMNON_OPENOCD"),
                   help="AGaMEMnon-patched OpenOCD executable (or set AGAMEMNON_OPENOCD)")
    p.add_argument("--scripts", default=os.environ.get("AGAMEMNON_OOCD_SCRIPTS"),
                   help="OpenOCD scripts directory (or set AGAMEMNON_OOCD_SCRIPTS)")
    p.add_argument("--config", type=Path, default=default_config(),
                   help="AG32 target config; defaults to the open in-tree config")
    p.add_argument("--dap", default="agrv2k.dap",
                   help="DAP object created by the target config")
    p.add_argument("--timeout", type=float, default=30.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.openocd or not args.scripts:
        parser().error("--openocd and --scripts are required (or set their AGAMEMNON_* variables)")
    openocd, scripts, config = Path(args.openocd), Path(args.scripts), Path(args.config)
    for label, path in (("OpenOCD", openocd), ("scripts", scripts), ("config", config)):
        if not path.exists():
            raise SystemExit(f"{label} path does not exist: {path}")
    prefix = command_prefix(openocd, scripts, config)

    recovered = invoke(prefix, recovery_commands(args.dap), args.timeout)
    recovery_log = recovered.stdout + recovered.stderr
    if recovered.returncode:
        sys.stderr.write(recovery_log)
        raise SystemExit("direct Debug Module reset failed")

    verified = invoke(prefix, verification_commands(), args.timeout)
    verification_log = verified.stdout + verified.stderr
    observed = device_id(verification_log)
    if verified.returncode or observed != DEVICE_ID:
        sys.stderr.write(recovery_log + "\n" + verification_log)
        raise SystemExit(
            "reset was issued but target verification failed: device_id=%s"
            % ("missing" if observed is None else f"0x{observed:08x}")
        )
    print(f"recovered AG32 hart; DEVICE_ID=0x{observed:08x}; flash untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
