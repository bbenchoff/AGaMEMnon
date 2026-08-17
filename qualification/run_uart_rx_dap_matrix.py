#!/usr/bin/env python3
"""Build and run the SRAM-only UART0 RX matrix through DAP CDC serial."""

from pathlib import Path
import argparse
import hashlib
import re
import shutil
import subprocess
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AGM = ROOT.parent / "AG32-Docs" / "tools" / "agm_supra"
EXPECTED_FABRIC_SHA256 = (
    "ca3f9f9475330733b68551dcd399c056febadf04aa34c8fed9bcf1b38ad4448b"
)
BAUDS = (9600, 38400, 115200)
PATTERN = bytes((0xFF, 0x55, 0x41, 0x00)) * 16


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
    elf = output_dir / "uart_rx_dap_probe.elf"
    binary = output_dir / "uart_rx_dap_probe.bin"
    subprocess.run([
        gcc, "-march=" + march, "-mabi=ilp32", "-Os", "-g", "-nostdlib",
        "-ffreestanding", "-fno-builtin", "-ffunction-sections",
        "-fdata-sections", "-I", ROOT / "mcu", "-T", ROOT / "agamemnon/sdk/link_sram.ld",
        "-Wl,--gc-sections", ROOT / "agamemnon/sdk/startup.S",
        HERE / "uart_rx_dap_probe.c", "-o", elf,
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


def mailbox(log, count=27):
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


def run_profile(image, probe, port, baud, log_dir):
    arm_log = openocd((
        "reset halt", "load_image %s 0x20002000 bin" % win(image),
        "load_image %s 0x20000000 bin" % win(probe),
        "reg pc 0x20000000", "reg sp 0x20020000",
        "mww 0x20001000 0x00000000 27", "resume", "sleep 1000", "halt",
        "mdw 0x20001000 7", "mww 0x2000100c %d" % baud,
        "mww 0x20001014 1", "resume", "shutdown",
    ))
    ready = mailbox(arm_log, 7)
    if ready[:3] != [0x55415258, 0x40200001, 0x000F0002]:
        raise RuntimeError("UART probe did not arm: %r" % ready)

    import serial
    with serial.Serial(port, baud, timeout=0.2, write_timeout=2) as stream:
        time.sleep(0.25)
        if stream.write(PATTERN) != len(PATTERN):
            raise RuntimeError("short DAP CDC serial write")
        stream.flush()
        time.sleep(1.0)

    read_log = openocd(("halt", "mdw 0x20001000 27", "reset", "shutdown"))
    data = mailbox(read_log)
    passed = (
        data[:9] == [0x55415258, 0x40200001, 0x000F0002, baud,
                     0x52454144, 1, 0, 64, 0]
        and data[10:26] == [0x004155FF] * 16
        and data[26] == 0xC0FFEE30
    )
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / ("uart_rx_%d_arm.log" % baud)).write_text(arm_log, encoding="utf-8")
        (log_dir / ("uart_rx_%d_read.log" % baud)).write_text(read_log, encoding="utf-8")
    print("baud=%d received=%d error=%d FR=0x%08x verdict=%s" %
          (baud, data[7], data[8], data[9], "PASS" if passed else "FAIL"))
    if not passed:
        raise RuntimeError("UART RX mismatch at %d baud: %r" % (baud, data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fabric", type=Path)
    parser.add_argument("--port")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / ".tmp/uart_rx_dap_probe")
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
        raise SystemExit("UART RX fabric image hash mismatch")
    try:
        for baud in BAUDS:
            run_profile(args.fabric, probe, args.port, baud, args.log_dir)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
