#!/usr/bin/env python3
"""Build and run SRAM-only UART0 line-mode and parity-error trials."""

from pathlib import Path
import argparse
import hashlib
import re
import subprocess
import threading
import time

import run_uart_duplex_dap_matrix as base


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXPECTED_FABRIC_SHA256 = (
    "b1701320ea7e653791497db8d10dfa443fe7874b0b7098bc3f6be160a8818380"
)
BAUD = 38400
HOST_TX = bytes((0x7F, 0x55, 0x41, 0x00)) * 64
TARGET_TX = bytes((0x25, 0x5A, 0x43, 0x3C)) * 64
ERROR_TX = bytes((0xFF, 0x55, 0x41, 0x00)) * 16
MODES = (
    ("7E1", 0x56, 7, "E", 1),
    ("8E1", 0x76, 8, "E", 1),
    ("8O1", 0x72, 8, "O", 1),
    ("8N2", 0x78, 8, "N", 2),
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_probe(source, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    gcc = base.find_tool("riscv64-unknown-elf-gcc")
    objcopy = base.find_tool("riscv64-unknown-elf-objcopy")
    nm = base.find_tool("riscv64-unknown-elf-nm")
    major = int(subprocess.run(
        [gcc, "-dumpversion"], check=True, capture_output=True, text=True,
    ).stdout.split(".", 1)[0])
    march = "rv32imac_zicsr" if major >= 12 else "rv32imac"
    elf = output_dir / (source.stem + ".elf")
    binary = output_dir / (source.stem + ".bin")
    subprocess.run([
        gcc, "-march=" + march, "-mabi=ilp32", "-Os", "-g", "-nostdlib",
        "-ffreestanding", "-fno-builtin", "-ffunction-sections",
        "-fdata-sections", "-I", ROOT / "mcu", "-T", ROOT / "agamemnon/sdk/link_sram.ld",
        "-Wl,--gc-sections", ROOT / "agamemnon/sdk/startup.S", source, "-o", elf,
    ], check=True)
    subprocess.run([objcopy, "-O", "binary", elf, binary], check=True)
    symbols = subprocess.run([nm, elf], check=True, capture_output=True, text=True).stdout
    if not re.search(r"^20000000\s+T\s+_start$", symbols, re.MULTILINE):
        raise RuntimeError("probe _start is not exactly 0x20000000")
    if binary.stat().st_size >= 0x1000:
        raise RuntimeError("probe overlaps the mailbox")
    print("BUILD PASS %s size=%d sha256=%s" %
          (source.name, binary.stat().st_size, sha256(binary)))
    return binary


def arm(image, probe, extra=()):
    return base.openocd((
        "reset halt", "load_image %s 0x20002000 bin" % base.win(image),
        "load_image %s 0x20000000 bin" % base.win(probe),
        "reg pc 0x20000000", "reg sp 0x20020000",
        "mww 0x20001000 0x00000000 16", "resume", "sleep 1000", "halt",
        "mdw 0x20001000 7", "mww 0x2000100c %d" % BAUD,
    ) + tuple(extra) + ("mww 0x20001014 1", "resume", "shutdown"))


def save_logs(log_dir, name, arm_log, read_log):
    if not log_dir:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / (name + "_arm.log")).write_text(arm_log, encoding="utf-8")
    (log_dir / (name + "_read.log")).write_text(read_log, encoding="utf-8")


def run_mode(image, probe, port, mode, log_dir):
    import serial

    name, lcr, bits, parity, stops = mode
    arm_log = arm(image, probe, ("mww 0x20001038 %d" % lcr,))
    if base.mailbox(arm_log, 7)[:3] != [0x554D4F44, 0x40200001, 0x000F0002]:
        raise RuntimeError("UART line-mode probe did not arm")
    chunks = []
    with serial.Serial(port, BAUD, bytesize=bits, parity=parity,
                       stopbits=stops, timeout=0.2, write_timeout=5) as stream:
        stream.reset_input_buffer()
        stream.reset_output_buffer()

        def reader():
            deadline = time.monotonic() + 3.0
            while sum(map(len, chunks)) < len(TARGET_TX) and time.monotonic() < deadline:
                data = stream.read(len(TARGET_TX) - sum(map(len, chunks)))
                if data:
                    chunks.append(data)

        thread = threading.Thread(target=reader)
        thread.start()
        stream.write(b"\x7e")
        stream.flush()
        time.sleep(0.02)
        written = stream.write(HOST_TX)
        stream.flush()
        thread.join()
    time.sleep(0.3)
    read_log = base.openocd(("halt", "mdw 0x20001000 16", "reset", "shutdown"))
    data = base.mailbox(read_log, 16)
    passed = (
        written == len(HOST_TX) and b"".join(chunks) == TARGET_TX
        and data[7:10] == [256, 0, 0] and data[10:16] ==
        [0x7E, 0x91, 256, 0xC0FFEE33, lcr, 0]
    )
    save_logs(log_dir, "uart_mode_" + name.lower(), arm_log, read_log)
    print("mode=%s tx=%d rx=%d error=%d mismatch=%d verdict=%s" %
          (name, data[12], data[7], data[8], data[9], "PASS" if passed else "FAIL"))
    if not passed:
        raise RuntimeError("UART line-mode mismatch for %s: %r" % (name, data))


def run_parity_control(image, probe, port, host_parity, expected_errors, log_dir):
    import serial

    name = "matched_even" if expected_errors == 0 else "mismatched_odd"
    arm_log = arm(image, probe)
    if base.mailbox(arm_log, 7)[:3] != [0x55455252, 0x40200001, 0x000F0002]:
        raise RuntimeError("UART parity-error probe did not arm")
    with serial.Serial(port, BAUD, bytesize=8, parity=host_parity,
                       stopbits=1, timeout=0.2, write_timeout=5) as stream:
        stream.reset_input_buffer()
        stream.reset_output_buffer()
        time.sleep(0.05)
        written = stream.write(ERROR_TX)
        stream.flush()
        time.sleep(0.5)
    read_log = base.openocd(("halt", "mdw 0x20001000 16", "reset", "shutdown"))
    data = base.mailbox(read_log, 16)
    passed = (
        written == len(ERROR_TX) and data[7:10] == [64, 0, 0]
        and data[10:16] == [expected_errors, 0, 0, 0, 0, 0xC0FFEE34]
    )
    save_logs(log_dir, "uart_parity_" + name, arm_log, read_log)
    print("parity=%s received=%d parity_errors=%d verdict=%s" %
          (name, data[7], data[10], "PASS" if passed else "FAIL"))
    if not passed:
        raise RuntimeError("UART parity control mismatch for %s: %r" % (name, data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fabric", type=Path)
    parser.add_argument("--port")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / ".tmp/uart_line_mode_probe")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--execute-sram", action="store_true")
    args = parser.parse_args()
    mode_probe = build_probe(HERE / "uart_line_mode_probe.c", args.output_dir)
    error_probe = build_probe(HERE / "uart_parity_error_probe.c", args.output_dir)
    if args.build_only:
        return
    if not args.execute_sram or args.fabric is None or not args.port:
        parser.error("--fabric, --port, and explicit --execute-sram are required")
    if args.fabric.stat().st_size != 99944 or sha256(args.fabric) != EXPECTED_FABRIC_SHA256:
        raise SystemExit("UART line-mode fabric size/hash mismatch")
    try:
        for mode in MODES:
            run_mode(args.fabric, mode_probe, args.port, mode, args.log_dir)
        run_parity_control(args.fabric, error_probe, args.port, "E", 0, args.log_dir)
        run_parity_control(args.fabric, error_probe, args.port, "O", 64, args.log_dir)
    finally:
        base.cleanup()


if __name__ == "__main__":
    main()
