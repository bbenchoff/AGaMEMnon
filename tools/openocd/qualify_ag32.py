#!/usr/bin/env python3
"""Qualify an AGaMEMnon OpenOCD build on an AG32 and emit JSON evidence.

The flash test is opt-in. It backs up all flash, modifies one complete sector,
verifies it, restores that sector in a finally block, then requires the final
full-flash hash to equal the initial hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from agamemnon import program as P


EXPECTED_DEVICE_ID = 0x40200001
EXPECTED_MISA = 0x40801125
SRAM_SCRATCH = 0x2001FFF0
PATTERN = (0xA5A55A5A, 0x01234567, 0x89ABCDEF, 0x55AA33CC)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def words(log):
    result = {}
    for match in re.finditer(r"(0x[0-9a-fA-F]{8}):\s+((?:[0-9a-fA-F]{8}\s*)+)", log):
        address = int(match.group(1), 16)
        for index, token in enumerate(match.group(2).split()):
            result[address + index * 4] = int(token, 16)
    return result


class Qualification:
    def __init__(self, args):
        self.args = args
        self.checks = []
        self.openocd = str(Path(args.openocd).resolve())
        self.scripts = str(Path(args.scripts).resolve())
        os.environ["AGAMEMNON_OPENOCD"] = self.openocd
        os.environ["AGAMEMNON_OOCD_SCRIPTS"] = self.scripts

    def record(self, name, passed, detail, data=None):
        self.checks.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
            "data": data,
        })
        if not passed:
            raise RuntimeError(f"{name}: {detail}")

    def oocd(self, commands, executable=None, scripts=None, timeout=60):
        command = [executable or self.openocd, "-s", scripts or self.scripts,
                   "-f", str(Path(P.OPEN_CFG).resolve())]
        for item in commands:
            command += ["-c", item]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        log = result.stdout + result.stderr
        if result.returncode:
            raise RuntimeError("\n".join(log.splitlines()[-20:]))
        return log

    def host_and_parser(self):
        result = subprocess.run([self.openocd, "--version"], capture_output=True, text=True)
        version = next((line for line in (result.stdout + result.stderr).splitlines()
                        if "Open On-Chip Debugger" in line), "")
        self.record("version", result.returncode == 0 and bool(version), version)
        parser = subprocess.run(
            [self.openocd, "-c", "target create q riscv -dap definitely_missing",
             "-c", "shutdown"],
            capture_output=True, text=True,
        )
        parser_log = parser.stdout + parser.stderr
        accepted = "definitely_missing" in parser_log and "unknown option" not in parser_log.lower()
        self.record("riscv-dap-parser", accepted, "target create riscv -dap accepted")

    def probe_halt_memory(self):
        log = self.oocd(["reset halt", f"mdw {P.DEVID_ADDR:#x}", "reg misa", "shutdown"])
        memory = words(log)
        device = memory.get(P.DEVID_ADDR)
        self.record("probe-and-halt", device == EXPECTED_DEVICE_ID,
                    f"DEVICE_ID=0x{device or 0:08x}", {"device_id": device})
        misa_match = re.search(r"misa[^:]*:\s*(?:0x)?([0-9a-fA-F]{8})", log)
        misa = int(misa_match.group(1), 16) if misa_match else (
            EXPECTED_MISA if f"misa=0x{EXPECTED_MISA:08x}" in log else None
        )
        self.record("register-access", misa == EXPECTED_MISA,
                    f"misa=0x{misa or 0:08x}", {"misa": misa})

        initial_log = self.oocd(["reset halt", f"mdw {SRAM_SCRATCH:#x} 4", "shutdown"])
        initial_map = words(initial_log)
        initial = tuple(initial_map.get(SRAM_SCRATCH + 4 * i) for i in range(4))
        self.record("sram-read", all(item is not None for item in initial),
                    "read four scratch words", {"before": initial})
        commands = ["reset halt"]
        commands += [f"mww {SRAM_SCRATCH + 4 * i:#x} {value:#x}"
                     for i, value in enumerate(PATTERN)]
        commands += [f"mdw {SRAM_SCRATCH:#x} 4"]
        commands += [f"mww {SRAM_SCRATCH + 4 * i:#x} {value:#x}"
                     for i, value in enumerate(initial)]
        commands += [f"mdw {SRAM_SCRATCH:#x} 4", "shutdown"]
        write_log = self.oocd(commands)
        observed = [
            tuple(int(token, 16) for token in match.split())
            for match in re.findall(
                rf"0x{SRAM_SCRATCH:08x}:\s+((?:[0-9a-fA-F]{{8}}\s*){{4}})",
                write_log,
            )
        ]
        self.record("sram-write-read-restore",
                    len(observed) >= 2 and observed[-2] == PATTERN and observed[-1] == initial,
                    "pattern verified and original words restored")

    def sram_load(self):
        firmware = Path(self.args.firmware).resolve()
        log = self.oocd([
            "reset halt",
            f"load_image {firmware.as_posix()} {P.SRAM_STUB:#x} bin",
            f"reg pc {P.SRAM_STUB:#x}",
            f"reg sp {P.SRAM_SP:#x}",
            "resume", "sleep 100", "halt",
            f"mdw {P.RESULT_ADDR:#x} 4",
            "shutdown",
        ])
        result = words(log)
        signature = tuple(result.get(P.RESULT_ADDR + 4 * i) for i in range(4))
        expected = (0x52563332, EXPECTED_DEVICE_ID, EXPECTED_MISA)
        self.record("sram-load-and-run", signature[:3] == expected,
                    "firmware executed from 0x20000000", {"mailbox": signature})

    def flash(self, directory):
        before = directory / "flash-before.bin"
        after = directory / "flash-after.bin"
        self.oocd(["reset halt",
                   f"dump_image {before.as_posix()} {P.FLASH_BASE:#x} {P.FLASH_SIZE}",
                   "shutdown"], timeout=120)
        before_hash = sha256(before)
        self.record("flash-backup", before.stat().st_size == P.FLASH_SIZE,
                    f"{P.FLASH_SIZE} bytes, sha256={before_hash}")
        if not self.args.destructive_flash_test:
            return before_hash

        address = int(self.args.flash_sector, 0)
        if address % P.SECTOR or not (P.FLASH_BASE <= address <=
                                      P.FLASH_BASE + P.FLASH_SIZE - P.SECTOR):
            raise RuntimeError("--flash-sector must be a complete sector inside main flash")
        offset = address - P.FLASH_BASE
        original = before.read_bytes()[offset:offset + P.SECTOR]
        test = bytearray(original)
        marker = b"AGaMEMnon OpenOCD qualification 9590"
        test[:len(marker)] = marker
        for index in range(64, 320):
            test[index] = (index * 73 + 0x32) & 0xFF
        original_path = directory / "sector-original.bin"
        test_path = directory / "sector-test.bin"
        original_path.write_bytes(original)
        test_path.write_bytes(test)

        def program(path):
            commands = ["reset halt", *P._fc_config(), *P._fc_erase(address),
                        *P._fc_program(address, str(path)), "shutdown"]
            self.oocd(commands, timeout=180)
            verify = directory / "sector-readback.bin"
            self.oocd(["reset halt",
                       f"dump_image {verify.as_posix()} {address:#x} {P.SECTOR}",
                       "shutdown"])
            return verify.read_bytes()

        test_ok = False
        restore_ok = False
        try:
            test_ok = program(test_path) == bytes(test)
        finally:
            restore_ok = program(original_path) == original
        self.record("flash-write-readback", test_ok, f"sector {address:#010x} byte-exact")
        self.record("flash-sector-restore", restore_ok, f"sector {address:#010x} restored")
        self.oocd(["reset halt",
                   f"dump_image {after.as_posix()} {P.FLASH_BASE:#x} {P.FLASH_SIZE}",
                   "shutdown"], timeout=120)
        after_hash = sha256(after)
        self.record("full-flash-restore", before_hash == after_hash,
                    f"before={before_hash}, after={after_hash}")
        return before_hash

    def recovery(self):
        log = self.oocd([
            "reset run", "sleep 100", "reset halt",
            f"mdw {P.DEVID_ADDR:#x}", "resume", "shutdown",
        ])
        device = words(log).get(P.DEVID_ADDR)
        self.record("dap-reset-recovery", device == EXPECTED_DEVICE_ID,
                    "reset/run/reset-halt returned target to debug control")

    def oracle(self):
        if not self.args.oracle:
            return
        oracle = Path(self.args.oracle).resolve()
        digest = sha256(oracle)
        expected = json.loads((Path(__file__).parent / "manifest.json").read_text(
            encoding="utf-8"))["oracle"]["openocd_exe_sha256"]
        self.record("oracle-identity", digest == expected,
                    f"known OS-Q oracle sha256={digest}")
        if self.args.oracle_scripts:
            try:
                log = self.oocd(["reset halt", f"mdw {P.DEVID_ADDR:#x}", "shutdown"],
                                executable=str(oracle),
                                scripts=str(Path(self.args.oracle_scripts).resolve()))
                device = words(log).get(P.DEVID_ADDR)
                self.record("oracle-read-only-probe", device == EXPECTED_DEVICE_ID,
                            f"DEVICE_ID=0x{device or 0:08x}")
            except Exception as exc:
                self.record("oracle-read-only-probe", False, str(exc))

    def run(self):
        started = int(time.time())
        with tempfile.TemporaryDirectory(prefix="agamemnon-qualification-") as temporary:
            directory = Path(temporary)
            self.host_and_parser()
            self.probe_halt_memory()
            self.sram_load()
            flash_hash = self.flash(directory)
            self.recovery()
            self.oracle()
        report = {
            "schema": 1,
            "qualification": "AG32 OpenOCD",
            "started_unix": started,
            "completed_unix": int(time.time()),
            "candidate_sha256": sha256(self.openocd),
            "flash_sha256": flash_hash,
            "destructive_flash_test": self.args.destructive_flash_test,
            "checks": self.checks,
            "result": "PASS",
        }
        output = Path(self.args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"qualification PASS: {output}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--openocd", required=True)
    parser.add_argument("--scripts", required=True)
    parser.add_argument("--firmware", required=True,
                        help="sram_signature.bin or equivalent qualification firmware")
    parser.add_argument("--output", required=True)
    parser.add_argument("--destructive-flash-test", action="store_true")
    parser.add_argument("--flash-sector", default="0x8003f000")
    parser.add_argument("--oracle")
    parser.add_argument("--oracle-scripts")
    return parser.parse_args()


if __name__ == "__main__":
    Qualification(parse_args()).run()
