#!/usr/bin/env python3
"""Build-audited SRAM-only runner for the exact bank16 read-gate oracle."""

from pathlib import Path
import argparse
import re
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGM = ROOT.parent / "AG32-Docs" / "tools" / "agm_supra"
TOOL = Path.home() / ".platformio" / "packages" / "toolchain-agrv" / "bin"
MASKS = {0x0, 0x1, 0x3, 0x5, 0xF}


def win(path):
    return str(Path(path).resolve()).replace("\\", "/")


def openocd_base():
    return [str(AGM / "openocd" / "bin" / "openocd.exe"),
            "-s", str(AGM / "openocd" / "share" / "openocd" / "scripts"),
            "-c", "set ADAPTER cmsis-dap", "-f", str(AGM / "pio" / "agrv2k.cfg")]


def build_stub(mask):
    out_dir = HERE / ("stub_%x" % mask)
    out_dir.mkdir(parents=True, exist_ok=True)
    elf = out_dir / "probe.elf"
    binary = out_dir / "probe.bin"
    subprocess.run([
        str(TOOL / "riscv64-unknown-elf-gcc.exe"),
        "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
        "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
        "-Wl,--gc-sections", "-DREAD_MASK=0x%x" % mask,
        "-o", str(elf), str(HERE / "mcu_ahb_bank16_read_word0_gated_test.c"),
    ], check=True)
    subprocess.run([str(TOOL / "riscv64-unknown-elf-objcopy.exe"),
                    "-O", "binary", str(elf), str(binary)], check=True)
    nm = subprocess.run([str(TOOL / "riscv64-unknown-elf-nm.exe"), str(elf)],
                        check=True, capture_output=True, text=True).stdout
    if not re.search(r"^20000000\s+T\s+_start$", nm, re.MULTILINE):
        raise RuntimeError("_start is not exactly 0x20000000")
    undefined = subprocess.run([str(TOOL / "riscv64-unknown-elf-nm.exe"),
                                "-u", str(elf)], check=True,
                               capture_output=True, text=True).stdout.strip()
    if undefined:
        raise RuntimeError("oracle has undefined symbols:\n" + undefined)
    disassembly = subprocess.run([
        str(TOOL / "riscv64-unknown-elf-objdump.exe"), "-d", str(elf)],
        check=True, capture_output=True, text=True).stdout
    missing = [opcode for opcode in ("lw", "sw", "sh", "sb")
               if not re.search(r"\b%s\b" % opcode, disassembly)]
    if missing:
        raise RuntimeError("compiled oracle lacks opcode(s): %s" % missing)
    for immediate in (0, 4, 8, 12):
        if not re.search(r"\blw\s+[^,]+,%d\(" % immediate, disassembly):
            raise RuntimeError("oracle lacks explicit lw offset %d" % immediate)
    if binary.stat().st_size >= 0x1000:
        raise RuntimeError("oracle binary overlaps result mailbox: %d bytes" %
                           binary.stat().st_size)
    return binary


def cleanup_board():
    args = openocd_base()
    for command in ("reset halt", "reset", "shutdown"):
        args += ["-c", command]
    subprocess.run(args, capture_output=True, text=True, timeout=30)


def run(image, mask, log_path=None):
    image = Path(image)
    if image.stat().st_size != 99944:
        raise ValueError("expected a 99,944-byte uncompressed fabric image")
    stub = build_stub(mask)
    args = openocd_base()
    for command in [
        "reset halt", "load_image %s 0x20002000 bin" % win(image),
        "load_image %s 0x20000000 bin" % win(stub), "reg pc 0x20000000",
        # SRAM survives a core reset.  Clear the result mailbox so a failed
        # repeat of the same mask cannot accidentally parse the prior run's
        # sentinel and zero counters as fresh evidence.
        "reg sp 0x20020000", "mww 0x20001000 0x00000000 17",
        "resume", "sleep 2800", "halt",
        "mdw 0x20001000 17", "reset", "shutdown",
    ]:
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
        data = [words.get(0x20001000 + 4 * index) for index in range(17)]
        if any(value is None for value in data) or data[16] != 0xC0FFEE17:
            raise RuntimeError("read-decode result incomplete\n" + log[-4000:])
        passed = (data[0] == 0x000F0002 and data[1:11] == [0] * 10 and
                  data[11:14] == [0] * 3 and data[14] == 64 and data[15] == mask)
        print("mask=%x FCB=%08x read0=%u foreign_read=%u preservation=%u "
              "phase_pair=%u half=%u low=%u high=%u rejected_write=%u "
              "overwrite=%u reset_errors=%u" % tuple([mask] + data[:11]))
        print("reset_initial=%04x reset_asserted=%04x reset_released=%04x "
              "patterns=%u verdict=%s" % tuple(data[11:15] +
                                                ["PASS" if passed else "FAIL"]))
        return 0 if passed else 1
    finally:
        cleanup_board()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path, nargs="?")
    parser.add_argument("--mask", type=lambda value: int(value, 0), default=0x1)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--build-only", action="store_true",
                        help="compile and audit the SRAM stub without hardware")
    args = parser.parse_args()
    if args.mask not in MASKS:
        parser.error("--mask must be one of 0x0, 0x1, 0x3, 0x5, 0xf")
    if args.build_only:
        print(build_stub(args.mask))
        return
    if args.image is None:
        parser.error("image is required unless --build-only is used")
    raise SystemExit(run(args.image, args.mask, args.log))


if __name__ == "__main__":
    main()
