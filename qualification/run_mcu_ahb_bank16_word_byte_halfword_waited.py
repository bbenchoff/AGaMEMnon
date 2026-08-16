#!/usr/bin/env python3
"""Build and run the qualified SRAM-only 16-bit halfword oracle."""

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
    out_dir = HERE / "bank16_word_byte_halfword_stub"
    out_dir.mkdir(parents=True, exist_ok=True)
    elf = out_dir / "probe.elf"
    binary = out_dir / "probe.bin"
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-gcc.exe"),
        "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-o", str(elf),
        str(HERE / "mcu_ahb_bank16_word_byte_halfword_waited_test.c"),
    ], check=True)
    subprocess.run([str(TOOL / "riscv64-unknown-elf-objcopy.exe"),
                    "-O", "binary", str(elf), str(binary)], check=True)
    symbols = subprocess.run([str(TOOL / "riscv64-unknown-elf-nm.exe"), str(elf)],
                             check=True, capture_output=True, text=True).stdout
    if not re.search(r"^20000000\s+T\s+_start$", symbols, re.MULTILINE):
        raise RuntimeError("_start is not at the forced runner PC")
    disassembly = subprocess.run([
        str(TOOL / "riscv64-unknown-elf-objdump.exe"), "-d", str(elf)],
        check=True, capture_output=True, text=True).stdout
    missing = [opcode for opcode in ("sw", "sh", "sb")
               if not re.search(r"\b%s\b" % opcode, disassembly)]
    if missing:
        raise RuntimeError("compiled oracle lacks real store opcode(s): %s" % missing)
    return binary


def run(image):
    image = Path(image)
    if image.stat().st_size != 99944:
        raise ValueError("expected a 99,944-byte uncompressed fabric image")
    stub = build_stub()
    args = [str(AGM / "openocd" / "bin" / "openocd.exe"),
            "-s", str(AGM / "openocd" / "share" / "openocd" / "scripts"),
            "-c", "set ADAPTER cmsis-dap", "-f", str(AGM / "pio" / "agrv2k.cfg")]
    for command in [
        "reset halt", f"load_image {win(image)} 0x20002000 bin",
        f"load_image {win(stub)} 0x20000000 bin", "reg pc 0x20000000",
        "reg sp 0x20020000", "resume", "sleep 1800", "halt",
        "mdw 0x20001000 14", "reset", "shutdown",
    ]:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr
    words = {}
    for match in re.finditer(r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        base = int(match.group(1), 16)
        for index, token in enumerate(match.group(2).split()):
            words[base + 4 * index] = int(token, 16)
    data = [words.get(0x20001000 + 4 * index) for index in range(14)]
    if any(value is None for value in data) or data[13] != 0xC0FFEE16:
        raise RuntimeError("halfword result incomplete\n" + log[-4000:])
    passed = data[0] == 0x000F0002 and data[1:12] == [0] * 11 and data[12] == 100
    print("FCB=%08x word=%u half=%u low=%u high=%u upper_byte=%u "
          "foreign_half=%u foreign_word=%u overwrite=%u" % tuple(data[:9]))
    print("reset_initial=%04x reset_asserted=%04x reset_released=%04x "
          "patterns=%u verdict=%s" % tuple(data[9:13] + ["PASS" if passed else "FAIL"]))
    return 0 if passed else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_mcu_ahb_bank16_word_byte_halfword_waited.py <config.bin>")
    raise SystemExit(run(sys.argv[1]))
