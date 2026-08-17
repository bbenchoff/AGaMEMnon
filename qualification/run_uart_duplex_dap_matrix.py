#!/usr/bin/env python3
"""Build and run SRAM-only UART0 full-duplex trials through DAP CDC."""

from pathlib import Path
import argparse
import hashlib
import re
import shutil
import subprocess
import threading
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGM = ROOT.parent / "AG32-Docs" / "tools" / "agm_supra"
EXPECTED_FABRIC_SHA256 = (
    "b1701320ea7e653791497db8d10dfa443fe7874b0b7098bc3f6be160a8818380"
)
BAUDS = (9600, 38400, 115200)
TRANSFER_BYTES = 4096
HOST_TX = bytes((0xFF, 0x55, 0x41, 0x00)) * (TRANSFER_BYTES // 4)
TARGET_TX = bytes((0xA5, 0x5A, 0xC3, 0x3C)) * (TRANSFER_BYTES // 4)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def win(path):
    return str(Path(path).resolve()).replace("\\", "/")


def find_tool(name):
    found = shutil.which(name) or shutil.which(name.replace("riscv64", "riscv-none"))
    if found:
        return Path(found)
    candidate = Path.home() / ".platformio/packages/toolchain-agrv/bin" / (name + ".exe")
    if candidate.is_file():
        return candidate
    raise RuntimeError("RISC-V tool is unavailable: " + name)


def build_probe(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    gcc = find_tool("riscv64-unknown-elf-gcc")
    objcopy = find_tool("riscv64-unknown-elf-objcopy")
    nm = find_tool("riscv64-unknown-elf-nm")
    major = int(subprocess.run(
        [gcc, "-dumpversion"], check=True, capture_output=True, text=True,
    ).stdout.split(".", 1)[0])
    march = "rv32imac_zicsr" if major >= 12 else "rv32imac"
    elf = output_dir / "uart_duplex_dap_probe.elf"
    binary = output_dir / "uart_duplex_dap_probe.bin"
    subprocess.run([
        gcc, "-march=" + march, "-mabi=ilp32", "-Os", "-g", "-nostdlib",
        "-ffreestanding", "-fno-builtin", "-ffunction-sections",
        "-fdata-sections", "-I", ROOT / "mcu", "-T", ROOT / "agamemnon/sdk/link_sram.ld",
        "-Wl,--gc-sections", ROOT / "agamemnon/sdk/startup.S",
        HERE / "uart_duplex_dap_probe.c", "-o", elf,
    ], check=True)
    subprocess.run([objcopy, "-O", "binary", elf, binary], check=True)
    symbols = subprocess.run(
        [nm, elf], check=True, capture_output=True, text=True,
    ).stdout
    if not re.search(r"^20000000\s+T\s+_start$", symbols, re.MULTILINE):
        raise RuntimeError("probe _start is not exactly 0x20000000")
    if binary.stat().st_size >= 0x1000:
        raise RuntimeError("probe overlaps the mailbox")
    print("BUILD PASS size=%d sha256=%s" % (binary.stat().st_size, sha256(binary)))
    return binary


def openocd_base():
    return [
        str(AGM / "openocd/bin/openocd.exe"),
        "-s", str(AGM / "openocd/share/openocd/scripts"),
        "-c", "set ADAPTER cmsis-dap", "-f", str(AGM / "pio/agrv2k.cfg"),
    ]


def openocd(commands, timeout=120):
    args = openocd_base()
    for command in commands:
        args += ["-c", command]
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    log = result.stdout + result.stderr
    if result.returncode:
        raise RuntimeError("OpenOCD failed\n" + log[-4000:])
    return log


def mailbox(log, count=14):
    words = {}
    for match in re.finditer(
            r"(0x2000[0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        address = int(match.group(1), 16)
        for index, token in enumerate(match.group(2).split()):
            words[address + 4 * index] = int(token, 16)
    result = [words.get(0x20001000 + 4 * index) for index in range(count)]
    if any(value is None for value in result):
        raise RuntimeError("incomplete UART mailbox\n" + log[-4000:])
    return result


def cleanup():
    try:
        openocd(("reset halt", "reset", "shutdown"), timeout=30)
    except Exception:
        pass


def transfer(port, baud):
    import serial

    chunks = []
    errors = []
    with serial.Serial(port, baud, timeout=0.2, write_timeout=10) as stream:
        stream.reset_input_buffer()
        stream.reset_output_buffer()

        def reader():
            deadline = time.monotonic() + max(
                5.0, 3.0 * 10.0 * TRANSFER_BYTES / baud + 1.0)
            while sum(map(len, chunks)) < TRANSFER_BYTES and time.monotonic() < deadline:
                data = stream.read(TRANSFER_BYTES - sum(map(len, chunks)))
                if data:
                    chunks.append(data)
            if sum(map(len, chunks)) != TRANSFER_BYTES:
                errors.append("short read")

        thread = threading.Thread(target=reader)
        thread.start()
        started = time.monotonic()
        stream.write(b"\x7e")
        stream.flush()
        time.sleep(0.02)
        written = stream.write(HOST_TX)
        stream.flush()
        thread.join()
        elapsed = time.monotonic() - started
    received = b"".join(chunks)
    if errors or written != TRANSFER_BYTES or received != TARGET_TX:
        raise RuntimeError(
            "CDC duplex mismatch: wrote=%d read=%d errors=%r" %
            (written, len(received), errors)
        )
    one_way = 10.0 * TRANSFER_BYTES / baud
    if elapsed >= 1.5 * one_way + 0.05:
        raise RuntimeError(
            "transfer did not meet duplex overlap bound: %.6fs >= %.6fs" %
            (elapsed, 1.5 * one_way + 0.05)
        )
    return elapsed, one_way


def run_profile(image, probe, port, baud, log_dir):
    arm_log = openocd((
        "reset halt", "load_image %s 0x20002000 bin" % win(image),
        "load_image %s 0x20000000 bin" % win(probe),
        "reg pc 0x20000000", "reg sp 0x20020000",
        "mww 0x20001000 0x00000000 14", "resume", "sleep 1000", "halt",
        "mdw 0x20001000 7", "mww 0x2000100c %d" % baud,
        "mww 0x20001014 1", "resume", "shutdown",
    ))
    ready = mailbox(arm_log, 7)
    if ready[:3] != [0x55445058, 0x40200001, 0x000F0002]:
        raise RuntimeError("UART duplex probe did not arm: %r" % ready)

    elapsed, one_way = transfer(port, baud)
    time.sleep(0.5)
    read_log = openocd(("halt", "mdw 0x20001000 14", "reset", "shutdown"))
    data = mailbox(read_log)
    passed = (
        data[:11] == [0x55445058, 0x40200001, 0x000F0002, baud,
                      0x52454144, 1, 0, TRANSFER_BYTES, 0, 0, 0x7E]
        and data[11] == 0x91
        and data[12:] == [TRANSFER_BYTES, 0xC0FFEE32]
    )
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / ("uart_duplex_%d_arm.log" % baud)).write_text(
            arm_log, encoding="utf-8")
        (log_dir / ("uart_duplex_%d_read.log" % baud)).write_text(
            read_log, encoding="utf-8")
    print("baud=%d tx=%d rx=%d elapsed=%.6fs one_way=%.6fs verdict=%s" %
          (baud, data[12], data[7], elapsed, one_way, "PASS" if passed else "FAIL"))
    if not passed:
        raise RuntimeError("UART duplex mismatch at %d baud: %r" % (baud, data))
    return elapsed, one_way


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fabric", type=Path)
    parser.add_argument("--port")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / ".tmp/uart_duplex_dap_probe")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--execute-sram", action="store_true")
    args = parser.parse_args()
    probe = build_probe(args.output_dir)
    if args.build_only:
        return
    if not args.execute_sram or args.fabric is None or not args.port:
        parser.error("--fabric, --port, and explicit --execute-sram are required")
    if args.fabric.stat().st_size != 99944:
        raise SystemExit("expected a 99,944-byte uncompressed fabric image")
    if sha256(args.fabric) != EXPECTED_FABRIC_SHA256:
        raise SystemExit("UART duplex fabric image hash mismatch")
    try:
        for baud in BAUDS:
            run_profile(args.fabric, probe, args.port, baud, args.log_dir)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
