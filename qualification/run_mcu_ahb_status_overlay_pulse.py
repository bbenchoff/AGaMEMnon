#!/usr/bin/env python3
"""Hash-bound SRAM-only runner for the generic status-overlay matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

import run_mcu_ahb_public32_gpio5_w1c_exact_map as common


HERE = Path(__file__).resolve().parent
TOOL = Path.home() / ".platformio/packages/toolchain-agrv/bin"
MODES = {
    "negative": {
        "image_sha256": "ac33ca6b4628258c62137e4c006ca25a222368e39c9a2e2d33a68e7b07dae6f5",
        "status_errors": 0x04,
    },
    "zero-control": {
        "image_sha256": "8a562b8563b607193e026184ed0da9cb9828e476d1621eda11ac08aa1da84bec",
        "status_errors": 0x00,
    },
    "production": {
        "image_sha256": "a9a10e81aff23afa512445ffacb18eb446283eeb8f0dc2152aa4c7f704652baf",
        "status_errors": 0x01,
    },
}


def build_stub():
    out = HERE / "stub_status_overlay_pulse"
    out.mkdir(exist_ok=True)
    elf, binary = out / "probe.elf", out / "probe.bin"
    source = HERE / "mcu_ahb_status_overlay_pulse_test.c"
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-gcc.exe"),
        "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-o", str(elf), str(source),
    ], check=True)
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-objcopy.exe"),
        "-O", "binary", str(elf), str(binary),
    ], check=True)
    nm = subprocess.run(
        [str(TOOL / "riscv64-unknown-elf-nm.exe"), str(elf)],
        check=True, capture_output=True, text=True,
    ).stdout
    if not re.search(r"^20000000\s+T\s+_start$", nm, re.MULTILINE):
        raise RuntimeError("_start is not exactly 0x20000000")
    if binary.stat().st_size >= 0x1000:
        raise RuntimeError("oracle overlaps mailbox")
    return binary


def run(image, mode, log_path=None):
    old_modes, old_builder = common.MODES, common.build_stub
    common.MODES, common.build_stub = MODES, build_stub
    try:
        return common.run(image, mode, log_path)
    finally:
        common.MODES, common.build_stub = old_modes, old_builder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--execute-sram", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.build_only:
        build_stub()
        return
    if not args.execute_sram or args.image is None:
        parser.error("image and explicit --execute-sram are required")
    raise SystemExit(run(args.image, args.mode, args.log))


if __name__ == "__main__":
    main()
