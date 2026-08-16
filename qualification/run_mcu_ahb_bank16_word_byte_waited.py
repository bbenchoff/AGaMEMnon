#!/usr/bin/env python3
"""Build and run the qualified SRAM-only 16-bit word/byte oracle."""

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
    out_dir = HERE / "bank16_word_byte_stub"
    out_dir.mkdir(parents=True, exist_ok=True)
    elf = out_dir / "probe.elf"
    binary = out_dir / "probe.bin"
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-gcc.exe"),
        "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-o", str(elf),
        str(HERE / "mcu_ahb_bank16_word_byte_waited_test.c"),
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
    args = [
        str(AGM / "openocd" / "bin" / "openocd.exe"),
        "-s", str(AGM / "openocd" / "share" / "openocd" / "scripts"),
        "-c", "set ADAPTER cmsis-dap", "-f", str(AGM / "pio" / "agrv2k.cfg"),
    ]
    for command in [
        "reset halt", f"load_image {win(image)} 0x20002000 bin",
        f"load_image {win(stub)} 0x20000000 bin", "reg pc 0x20000000",
        "reg sp 0x20020000", "resume", "sleep 1600", "halt",
        "mdw 0x20001000 12", "reset", "shutdown",
    ]:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    words = {}
    for match in re.finditer(
            r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        base = int(match.group(1), 16)
        for index, token in enumerate(match.group(2).split()):
            words[base + 4 * index] = int(token, 16)
    data = [words.get(0x20001000 + 4 * index) for index in range(12)]
    if any(value is None for value in data) or data[11] != 0xC0FFEE16:
        raise RuntimeError("word/byte result incomplete\n" + log[-3000:])
    passed = data[0] == 0x000F0002 and data[1:11] == [0] * 9 + [100]
    print("FCB=%08x word=%u low_byte=%u high_byte=%u upper_byte=%u "
          "foreign=%u overwrite=%u" % tuple(data[:7]))
    print("reset_initial=%04x reset_asserted=%04x reset_released=%04x "
          "patterns=%u verdict=%s" %
          tuple(data[7:11] + ["PASS" if passed else "FAIL"]))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_mcu_ahb_bank16_word_byte_waited.py <config.bin>")
    raise SystemExit(run(sys.argv[1]))
