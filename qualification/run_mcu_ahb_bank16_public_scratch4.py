#!/usr/bin/env python3
"""Build-audited, opt-in SRAM-only runner for the exact +4 scratch image."""

from pathlib import Path
import argparse
import re
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGM = ROOT.parent / "AG32-Docs" / "tools" / "agm_supra"
TOOL = Path.home() / ".platformio" / "packages" / "toolchain-agrv" / "bin"


def win(path):
    return str(Path(path).resolve()).replace("\\", "/")


def openocd_base():
    return [
        str(AGM / "openocd" / "bin" / "openocd.exe"),
        "-s", str(AGM / "openocd" / "share" / "openocd" / "scripts"),
        "-c", "set ADAPTER cmsis-dap",
        "-f", str(AGM / "pio" / "agrv2k.cfg"),
    ]


def _require_offset(disassembly, opcode, offset):
    if not re.search(r"\b%s\s+[^,]+,%d\(" % (opcode, offset), disassembly):
        raise RuntimeError("oracle lacks explicit %s offset +%d" %
                           (opcode, offset))


def build_stub():
    out_dir = HERE / "stub_bank16_public_scratch4"
    out_dir.mkdir(parents=True, exist_ok=True)
    elf = out_dir / "probe.elf"
    binary = out_dir / "probe.bin"
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-gcc.exe"),
        "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-o", str(elf),
        str(HERE / "mcu_ahb_bank16_public_scratch4_test.c"),
    ], check=True)
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-objcopy.exe"),
        "-O", "binary", str(elf), str(binary),
    ], check=True)
    nm = subprocess.run([
        str(TOOL / "riscv64-unknown-elf-nm.exe"), str(elf),
    ], check=True, capture_output=True, text=True).stdout
    if not re.search(r"^20000000\s+T\s+_start$", nm, re.MULTILINE):
        raise RuntimeError("_start is not exactly 0x20000000")
    undefined = subprocess.run([
        str(TOOL / "riscv64-unknown-elf-nm.exe"), "-u", str(elf),
    ], check=True, capture_output=True, text=True).stdout.strip()
    if undefined:
        raise RuntimeError("oracle has undefined symbols:\n" + undefined)
    disassembly = subprocess.run([
        str(TOOL / "riscv64-unknown-elf-objdump.exe"), "-d", str(elf),
    ], check=True, capture_output=True, text=True).stdout
    for opcode in ("lw", "lbu", "lhu", "sw", "sh", "sb"):
        if not re.search(r"\b%s\b" % opcode, disassembly):
            raise RuntimeError("compiled oracle lacks opcode %s" % opcode)
    for offset in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13):
        _require_offset(disassembly, "lbu", offset)
    for offset in (0, 2, 4, 6, 8, 12):
        _require_offset(disassembly, "lhu", offset)
    if re.search(r"\blhu\s+[^,]+,(?:1|3|5|7|9|11|13|15)\(", disassembly):
        raise RuntimeError("oracle emitted a misaligned halfword load")
    # These exact stores are the causal core: accepted +4/+5 lanes plus aligned
    # foreign-address rejection controls.  A compiler rewrite must not silently
    # weaken the hardware matrix.
    for opcode, offsets in {
        "sw": (0, 4, 8, 12),
        "sh": (0, 4, 6, 8, 12),
        "sb": (0, 4, 5, 6, 8, 12),
    }.items():
        for offset in offsets:
            _require_offset(disassembly, opcode, offset)
    if binary.stat().st_size >= 0x1000:
        raise RuntimeError("oracle binary overlaps result mailbox: %d bytes" %
                           binary.stat().st_size)
    print("BUILD PASS entry=20000000 size=%d exact-load/store-offsets" %
          binary.stat().st_size)
    return binary


def cleanup_board():
    args = openocd_base()
    for command in ("reset halt", "reset", "shutdown"):
        args += ["-c", command]
    subprocess.run(args, capture_output=True, text=True, timeout=30)


def run(image, log_path=None):
    image = Path(image)
    if image.stat().st_size != 99944:
        raise ValueError("expected a 99,944-byte uncompressed fabric image")
    stub = build_stub()
    args = openocd_base()
    for command in (
        "reset halt",
        "load_image %s 0x20002000 bin" % win(image),
        "load_image %s 0x20000000 bin" % win(stub),
        "reg pc 0x20000000", "reg sp 0x20020000",
        "mww 0x20001000 0x00000000 25", "resume", "sleep 2800", "halt",
        "mdw 0x20001000 25", "reset", "shutdown",
    ):
        args += ["-c", command]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if log_path:
            Path(log_path).write_text(log, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("OpenOCD failed with exit %d\n%s" %
                               (result.returncode, log[-4000:]))
        words = {}
        for match in re.finditer(
                r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
            base = int(match.group(1), 16)
            for index, token in enumerate(match.group(2).split()):
                words[base + 4 * index] = int(token, 16)
        data = [words.get(0x20001000 + 4 * index) for index in range(25)]
        if any(value is None for value in data) or data[24] != 0xC0FFEE24:
            raise RuntimeError("+4 scratch result incomplete\n" + log[-4000:])
        passed = (data[0] == 0x000F0002 and data[1:17] == [0] * 16 and
                  data[17:19] == [32, 160])
        print("FCB=%08x errors=%s patterns=%u observations=%u "
              "upper=%04x/%04x raw=%08x lbu=%08x lhu=%08x verdict=%s" %
              (data[0], data[1:17], data[17], data[18], data[19], data[20],
               data[21], data[22], data[23], "PASS" if passed else "FAIL"))
        return 0 if passed else 1
    finally:
        cleanup_board()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--execute-sram", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.build_only:
        build_stub()
        return
    if not args.execute_sram:
        parser.error("hardware is disabled; explicitly pass --execute-sram")
    if args.image is None:
        parser.error("image is required")
    raise SystemExit(run(args.image, args.log))


if __name__ == "__main__":
    main()
