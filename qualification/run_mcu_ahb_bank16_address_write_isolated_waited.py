#!/usr/bin/env python3
"""SRAM-only runner for the qualified word-zero write-isolation discriminator."""

from pathlib import Path
import re
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGM = ROOT.parent / "AG32-Docs" / "tools" / "agm_supra"
TOOL = Path.home() / ".platformio" / "packages" / "toolchain-agrv" / "bin"


def win(path):
    return str(Path(path).resolve()).replace("\\", "/")


def build_stub():
    out = HERE / "bank16_word0_write_isolation.elf"
    binary = HERE / "bank16_word0_write_isolation_stub.bin"
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-gcc.exe"),
        "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-o", str(out),
        str(HERE / "mcu_ahb_bank16_address_write_isolated_waited_test.c"),
    ], check=True)
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-objcopy.exe"),
        "-O", "binary", str(out), str(binary),
    ], check=True)
    return binary


def main(image):
    image = Path(image)
    if image.stat().st_size != 99944:
        raise SystemExit("expected 99,944-byte uncompressed image")
    stub = build_stub()
    args = [
        str(AGM / "openocd" / "bin" / "openocd.exe"),
        "-s", str(AGM / "openocd" / "share" / "openocd" / "scripts"),
        "-c", "set ADAPTER cmsis-dap", "-f", str(AGM / "pio" / "agrv2k.cfg"),
    ]
    for command in [
        "reset halt", f"load_image {win(image)} 0x20002000 bin",
        f"load_image {win(stub)} 0x20000000 bin", "reg pc 0x20000000",
        "reg sp 0x20020000", "resume", "sleep 1200", "halt",
        "mdw 0x20001000 10", "reset", "shutdown",
    ]:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    words = {}
    for match in re.finditer(r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        base = int(match.group(1), 16)
        for index, token in enumerate(match.group(2).split()):
            words[base + 4 * index] = int(token, 16)
    data = [words.get(0x20001000 + 4 * i) for i in range(10)]
    if any(value is None for value in data) or data[9] != 0xC0FFEE16:
        raise RuntimeError("incomplete result\n" + log[-3000:])
    passed = data[0] == 0x000F0002 and data[1:9] == [0, 0, 0, 0, 0, 0, 0, 100]
    print("FCB=%08x immediate=%u foreign_write=%u foreign_alias=%u overwrite=%u" % tuple(data[:5]))
    print("reset_initial=%04x reset_asserted=%04x reset_blocked=%04x patterns=%u verdict=%s" %
          tuple(data[5:9] + ["PASS" if passed else "FAIL"]))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: run_mcu_ahb_bank16_address_write_isolated_waited.py <config.bin>"
        )
    raise SystemExit(main(sys.argv[1]))
