#!/usr/bin/env python3
"""Build and run the SRAM-only HSIZE1 route oracle."""

from pathlib import Path
import os
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AG32 = ROOT.parent / "AG32-Docs"
AGM = Path(os.environ.get("AGAMEMNON_AGM", AG32 / "tools" / "agm_supra"))
TOOL = Path.home() / ".platformio" / "packages" / "toolchain-agrv" / "bin"


def win(path):
    return str(Path(path).resolve()).replace("\\", "/")


def build_stub():
    out_dir = ROOT / "tools" / "lab" / "mcu_ahb_hsize1_logic_probe_stub"
    out_dir.mkdir(parents=True, exist_ok=True)
    elf = out_dir / "probe.elf"
    binary = out_dir / "probe.bin"
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-gcc.exe"),
        "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-o", str(elf),
        str(HERE / "mcu_ahb_hsize1_logic_probe_test.c"),
    ], check=True)
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-objcopy.exe"),
        "-O", "binary", str(elf), str(binary),
    ], check=True)
    return binary


def run(image):
    image = Path(image)
    if image.stat().st_size != 99944:
        raise ValueError("expected a 99,944-byte uncompressed fabric image")
    stub = build_stub()
    oocd = AGM / "openocd" / "bin" / "openocd.exe"
    scripts = AGM / "openocd" / "share" / "openocd" / "scripts"
    cfg = AGM / "pio" / "agrv2k.cfg"
    commands = [
        "reset halt", f"load_image {win(image)} 0x20002000 bin",
        f"load_image {win(stub)} 0x20000000 bin", "reg pc 0x20000000",
        "reg sp 0x20020000", "resume", "sleep 1200", "halt",
        "mdw 0x20001000 6", "reset", "shutdown",
    ]
    args = [str(oocd), "-s", str(scripts), "-c", "set ADAPTER cmsis-dap",
            "-f", str(cfg)]
    for command in commands:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    words = {}
    for match in re.finditer(
            r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        base = int(match.group(1), 16)
        for index, token in enumerate(match.group(2).split()):
            words[base + 4 * index] = int(token, 16)
    data = [words.get(0x20001000 + 4 * index) for index in range(6)]
    if any(value is None for value in data) or data[5] != 0xC0FFEE16:
        raise RuntimeError("HSIZE1 result incomplete\n" + log[-3000:])
    passed = data == [0x000F0002, 0, 0, 0, 256, 0xC0FFEE16]
    print("FCB=%08x word_errors=%u half_errors=%u byte_errors=%u "
          "patterns=%u verdict=%s" % tuple(data[:5] + ["PASS" if passed else "FAIL"]))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_mcu_ahb_hsize1_logic_probe.py <config.bin>")
    raise SystemExit(run(sys.argv[1]))
