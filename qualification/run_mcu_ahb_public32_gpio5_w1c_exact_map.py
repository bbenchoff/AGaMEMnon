#!/usr/bin/env python3
"""Build-audited SRAM-only causal runner for the GPIO5 W1C profile."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import subprocess


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGM = ROOT.parent / "AG32-Docs" / "tools" / "agm_supra"
TOOL = Path.home() / ".platformio/packages/toolchain-agrv/bin"
MODES = {
    "negative": {
        "image_sha256": "ac33ca6b4628258c62137e4c006ca25a222368e39c9a2e2d33a68e7b07dae6f5",
        "status_errors": 162,
    },
    "or-control": {
        "image_sha256": "fe34d0b05e773b0fbd803f3a1809c4177afb3317d1049939e101a5cfc5e4d681",
        "status_errors": 2,
    },
    "production": {
        "image_sha256": "bc338504e5b30fb9036d29f91c2cca6e384ef85ba2bde8ba8e79c62f05f4eb33",
        "status_errors": 0,
    },
}


def win(path):
    return str(Path(path).resolve()).replace("\\", "/")


def openocd_base():
    return [str(AGM / "openocd/bin/openocd.exe"), "-s",
            str(AGM / "openocd/share/openocd/scripts"),
            "-c", "set ADAPTER cmsis-dap", "-f", str(AGM / "pio/agrv2k.cfg")]


def build_stub():
    out = HERE / "stub_public32_gpio5_w1c"
    out.mkdir(exist_ok=True)
    elf, binary = out / "probe.elf", out / "probe.bin"
    subprocess.run([str(TOOL / "riscv64-unknown-elf-gcc.exe"),
                    "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
                    "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
                    "-Wl,--gc-sections", "-o", str(elf),
                    str(HERE / "mcu_ahb_public32_gpio5_w1c_exact_map_test.c")],
                   check=True)
    subprocess.run([str(TOOL / "riscv64-unknown-elf-objcopy.exe"), "-O", "binary",
                    str(elf), str(binary)], check=True)
    nm = subprocess.run([str(TOOL / "riscv64-unknown-elf-nm.exe"), str(elf)],
                        check=True, capture_output=True, text=True).stdout
    if not re.search(r"^20000000\s+T\s+_start$", nm, re.MULTILINE):
        raise RuntimeError("_start is not exactly 0x20000000")
    undefined = subprocess.run([str(TOOL / "riscv64-unknown-elf-nm.exe"), "-u",
                                str(elf)], check=True, capture_output=True,
                               text=True).stdout.strip()
    if undefined:
        raise RuntimeError("undefined symbols: " + undefined)
    dis = subprocess.run([str(TOOL / "riscv64-unknown-elf-objdump.exe"), "-d", str(elf)],
                         check=True, capture_output=True, text=True).stdout
    for opcode in ("lw", "lbu", "lhu", "sw", "sh", "sb", "fence"):
        if not re.search(r"\b%s\b" % opcode, dis):
            raise RuntimeError("oracle lacks opcode " + opcode)
    if binary.stat().st_size >= 0x1000:
        raise RuntimeError("oracle overlaps mailbox")
    print("BUILD PASS entry=20000000 size=%d opcodes-audited" % binary.stat().st_size)
    return binary


def cleanup():
    args = openocd_base()
    # Return GPIO5 DATA0 low and output-enable low even if parsing or execution
    # failed, then reset the board. No command in this runner writes flash.
    for command in ("reset halt", "mww 0x40019004 0", "mww 0x40019400 0",
                    "reset", "shutdown"):
        args += ["-c", command]
    subprocess.run(args, capture_output=True, text=True, timeout=30)


def run(image, mode, log_path=None):
    image = Path(image)
    expected = MODES[mode]
    data = image.read_bytes()
    if len(data) != 99_944:
        raise ValueError("expected 99,944-byte uncompressed image")
    if hashlib.sha256(data).hexdigest() != expected["image_sha256"]:
        raise ValueError("image hash does not match mode " + mode)
    stub = build_stub()
    args = openocd_base()
    commands = ("reset halt", "load_image %s 0x20002000 bin" % win(image),
                "load_image %s 0x20000000 bin" % win(stub),
                "reg pc 0x20000000", "reg sp 0x20020000",
                "mww 0x20001000 0x00000000 17", "resume", "sleep 3000", "halt",
                "mdw 0x20001000 17", "reset", "shutdown")
    if any("flash" in command.lower() or "program" in command.lower()
           for command in commands):
        raise RuntimeError("destructive OpenOCD command rejected")
    for command in commands:
        args += ["-c", command]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if log_path:
            canonical_log = "\n".join(
                line.rstrip() for line in log.replace("\r\n", "\n")
                .replace("\r", "\n").split("\n"))
            Path(log_path).write_text(canonical_log, encoding="utf-8", newline="\n")
        if result.returncode:
            raise RuntimeError("OpenOCD failed\n" + log[-4000:])
        words = {}
        for match in re.finditer(
                r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
            address = int(match.group(1), 16)
            for index, token in enumerate(match.group(2).split()):
                words[address + 4 * index] = int(token, 16)
        mailbox = [words.get(0x20001000 + 4 * i) for i in range(17)]
        if any(value is None for value in mailbox) or mailbox[16] != 0xc0ffee32:
            raise RuntimeError("incomplete mailbox\n" + log[-4000:])
        errors = mailbox[1:10]
        passed = (mailbox[0] == 0x000f0002 and
                  errors[:5] == [0] * 5 and
                  errors[5] == expected["status_errors"] and
                  errors[6:] == [0] * 3 and mailbox[10] == 0xff and
                  mailbox[11] == 8 and
                  mailbox[12:16] == [0x4147414d, 0, 0, 0])
        print("mode=%s FCB=%08x errors=%s seen=%02x obs=%u final=%s verdict=%s" %
              (mode, mailbox[0], errors, mailbox[10], mailbox[11],
               ["%08x" % value for value in mailbox[12:16]],
               "PASS" if passed else "FAIL"))
        return 0 if passed else 1
    finally:
        cleanup()


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
