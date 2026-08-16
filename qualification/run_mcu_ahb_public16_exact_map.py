#!/usr/bin/env python3
"""Build-audited, opt-in SRAM-only runner for the exact public16 map."""

from pathlib import Path
import argparse
import re
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGM = ROOT.parent / "AG32-Docs" / "tools" / "agm_supra"
TOOL = Path.home() / ".platformio/packages/toolchain-agrv/bin"


def win(path):
    return str(Path(path).resolve()).replace("\\", "/")


def openocd_base():
    return [str(AGM / "openocd/bin/openocd.exe"), "-s",
            str(AGM / "openocd/share/openocd/scripts"),
            "-c", "set ADAPTER cmsis-dap", "-f", str(AGM / "pio/agrv2k.cfg")]


def build_stub():
    out = HERE / "stub_public16_exact_map"
    out.mkdir(exist_ok=True)
    elf, binary = out / "probe.elf", out / "probe.bin"
    subprocess.run([str(TOOL / "riscv64-unknown-elf-gcc.exe"),
                    "-march=rv32imac", "-mabi=ilp32", "-Os", "-ffreestanding",
                    "-nostdlib", "-Wl,-Ttext=0x20000000", "-Wl,-e,_start",
                    "-Wl,--gc-sections", "-o", str(elf),
                    str(HERE / "mcu_ahb_public16_exact_map_test.c")], check=True)
    subprocess.run([str(TOOL / "riscv64-unknown-elf-objcopy.exe"), "-O", "binary",
                    str(elf), str(binary)], check=True)
    nm = subprocess.run([str(TOOL / "riscv64-unknown-elf-nm.exe"), str(elf)],
                        check=True, capture_output=True, text=True).stdout
    if not re.search(r"^20000000\s+T\s+_start$", nm, re.MULTILINE):
        raise RuntimeError("_start is not exactly 0x20000000")
    undefined = subprocess.run([str(TOOL / "riscv64-unknown-elf-nm.exe"), "-u", str(elf)],
                               check=True, capture_output=True, text=True).stdout.strip()
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
    for command in ("reset halt", "reset", "shutdown"):
        args += ["-c", command]
    subprocess.run(args, capture_output=True, text=True, timeout=30)


def run(image, log_path=None):
    image = Path(image)
    if image.stat().st_size != 99944:
        raise ValueError("expected 99,944-byte uncompressed image")
    stub = build_stub()
    args = openocd_base()
    for command in ("reset halt", "load_image %s 0x20002000 bin" % win(image),
                    "load_image %s 0x20000000 bin" % win(stub),
                    "reg pc 0x20000000", "reg sp 0x20020000",
                    "mww 0x20001000 0x00000000 16", "resume", "sleep 2800", "halt",
                    "mdw 0x20001000 16", "reset", "shutdown"):
        args += ["-c", command]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if log_path:
            Path(log_path).write_text(log, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("OpenOCD failed\n" + log[-4000:])
        words = {}
        for match in re.finditer(r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
            base = int(match.group(1), 16)
            for index, token in enumerate(match.group(2).split()):
                words[base + 4 * index] = int(token, 16)
        data = [words.get(0x20001000 + 4 * i) for i in range(16)]
        if any(value is None for value in data) or data[15] != 0xc0ffee1a:
            raise RuntimeError("incomplete mailbox\n" + log[-4000:])
        passed = data[0] == 0x000f0002 and data[1:9] == [0] * 8 and \
            data[9] == 0xff and data[10] == 8 and data[11:15] == [0x4d, 0, 0, 0]
        print("FCB=%08x errors=%s seen=%02x obs=%u final=%s verdict=%s" %
              (data[0], data[1:9], data[9], data[10], data[11:15],
               "PASS" if passed else "FAIL"))
        return 0 if passed else 1
    finally:
        cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--execute-sram", action="store_true")
    parser.add_argument("--log", type=Path)
    args = parser.parse_args()
    if args.build_only:
        build_stub(); return
    if not args.execute_sram or args.image is None:
        parser.error("image and explicit --execute-sram are required")
    raise SystemExit(run(args.image, args.log))


if __name__ == "__main__":
    main()
