#!/usr/bin/env python3
"""Run the SRAM-only held-bank oracle for the waited 16-bit candidate.

Only HRDATA[15:0] is claimed. The uninstantiated upper hard-return lanes are
reported diagnostically but are deliberately not required to read zero.
"""

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


def build_stub(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    elf = out_dir / "bank16_external_feedback_waited.elf"
    binary = out_dir / "bank16_external_feedback_waited.bin"
    gcc = TOOL / "riscv64-unknown-elf-gcc.exe"
    objcopy = TOOL / "riscv64-unknown-elf-objcopy.exe"
    subprocess.run([
        str(gcc), "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-o", str(elf),
        str(HERE / "mcu_ahb_bank16_external_feedback_waited_test.c"),
    ], check=True)
    subprocess.run([str(objcopy), "-O", "binary", str(elf), str(binary)], check=True)
    return binary


def run(image):
    image = Path(image)
    if image.stat().st_size != 99944:
        raise ValueError("expected a 99,944-byte uncompressed fabric image")
    stub = build_stub(ROOT / "tools" / "lab" / "bank16_external_feedback_waited_stub")
    oocd = AGM / "openocd" / "bin" / "openocd.exe"
    scripts = AGM / "openocd" / "share" / "openocd" / "scripts"
    cfg = AGM / "pio" / "agrv2k.cfg"
    commands = [
        "reset halt", f"load_image {win(image)} 0x20002000 bin",
        f"load_image {win(stub)} 0x20000000 bin", "reg pc 0x20000000",
        "reg sp 0x20020000", "resume", "sleep 1200", "halt",
        "mdw 0x20001000 10", "reset", "shutdown",
    ]
    args = [str(oocd), "-s", str(scripts), "-c", "set ADAPTER cmsis-dap", "-f", str(cfg)]
    for command in commands:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    words = {}
    for match in re.finditer(r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        base = int(match.group(1), 16)
        for index, token in enumerate(match.group(2).split()):
            words[base + 4 * index] = int(token, 16)
    data = [words.get(0x20001000 + 4 * index) for index in range(10)]
    if any(value is None for value in data) or data[9] != 0xC0FFEE16:
        raise RuntimeError("retention result incomplete\n" + log[-3000:])
    passed = data[0] == 0x000F0002 and data[1] == 100
    passed &= data[2:5] == [0, 0, 0]
    passed &= data[6:9] == [0, 0, 0]
    print("FCB=%08x patterns=%u immediate=%u poison=%u repeat=%u upper_diag=%u" % tuple(data[:6]))
    print("reset_initial=%04x reset_asserted=%04x reset_released=%04x verdict=%s" %
          tuple(data[6:9] + ["PASS" if passed else "FAIL"]))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_mcu_ahb_bank16_external_feedback_waited.py <config.bin>")
    raise SystemExit(run(sys.argv[1]))
