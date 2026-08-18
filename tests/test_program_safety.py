"""Pure, hardware-free safety checks for flash range validation."""
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon import program as P

ROOT = Path(__file__).resolve().parents[1]

# Fixed size of an uncompressed AGaMEMnon fabric image (agamemnon/engine/to_bin.py: hdr[8] +
# raw[99936]). The SRAM-inject path stages one of these at SRAM_IMG before/while firmware runs.
FABRIC_IMAGE_BYTES = 99944


def test_sectors_for_empty_is_empty():
    assert P._sectors_for(P.FLASH_BASE + 0x8100, 0) == []


def test_sram_sp_clears_the_staged_fabric_image_window():
    """SRAM_SP sits inside [SRAM_STUB, SRAM_STUB+0x1000) (the firmware stub) is fine, but it must
    clear the whole staged fabric image window -- a deep firmware call stack growing down from SP
    must not be able to reach into the image before/during FCB streaming. Regression for the case
    where SRAM_SP == 0x20008000 landed inside [0x20002000, 0x2001a668)."""
    image_end = P.SRAM_IMG + FABRIC_IMAGE_BYTES
    assert P.SRAM_SP >= image_end, (
        f"SRAM_SP {P.SRAM_SP:#x} must be >= the end of the staged image {image_end:#x}"
    )
    # Also must not land inside the mailbox/stub region below the image.
    assert not (P.SRAM_STUB <= P.SRAM_SP < image_end)
    assert not (P.RESULT_ADDR <= P.SRAM_SP < image_end)
    # Matches every historical qualification script (top of the 128 KiB SRAM).
    assert P.SRAM_SP == 0x20020000


def test_sdk_link_sram_stack_top_matches_sram_sp():
    """agamemnon/sdk/link_sram.ld's __stack_top is what actually governs the runtime stack for the
    shipped SDK firmware (startup.S does `la sp, __stack_top` unconditionally on entry, which
    overrides any OpenOCD register preset) -- it must stay in lockstep with program.SRAM_SP, not
    just the register-preset constant checked above."""
    text = (ROOT / "agamemnon" / "sdk" / "link_sram.ld").read_text()
    match = re.search(r"__stack_top\s*=\s*(0x[0-9a-fA-F]+)\s*;", text)
    assert match, "link_sram.ld must define __stack_top"
    assert int(match.group(1), 16) == P.SRAM_SP


def test_flash_span_accepts_exact_device():
    assert P._validate_flash_span(P.FLASH_BASE, P.FLASH_SIZE) == P.FLASH_BASE + P.FLASH_SIZE


@pytest.mark.parametrize("addr,size", [
    (P.FLASH_BASE, 0),
    (P.FLASH_BASE - 1, 1),
    (P.FLASH_BASE + P.FLASH_SIZE - 1, 2),
    (P.FLASH_BASE + P.FLASH_SIZE, 1),
])
def test_flash_span_rejects_empty_and_overflow(addr, size):
    with pytest.raises(ValueError):
        P._validate_flash_span(addr, size)


def test_dap_identity_gate_accepts_only_expected_ag32(monkeypatch):
    def result(value, returncode=0):
        text = "" if value is None else f"0x{P.DEVID_ADDR:08x}: {value:08x}\n"
        return SimpleNamespace(returncode=returncode, stdout=text, stderr="")

    monkeypatch.setattr(P, "_oocd", lambda commands: result(P.EXPECTED_DEVICE_ID))
    assert P._require_ag32() == P.EXPECTED_DEVICE_ID

    monkeypatch.setattr(P, "_oocd", lambda commands: result(0xDEADBEEF))
    with pytest.raises(RuntimeError, match="identity check failed"):
        P._require_ag32()

    monkeypatch.setattr(P, "_oocd", lambda commands: result(None, returncode=1))
    with pytest.raises(RuntimeError, match="no response"):
        P._require_ag32()


def test_openocd_timeout_is_single_attempt_and_reports_unknown_state(monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append((args, kwargs))
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(P, "_resolve", lambda: ("openocd", "target.cfg", None))
    monkeypatch.setattr(P.subprocess, "run", timeout)
    with pytest.raises(P.DapProgrammingError, match="state is unknown") as exc:
        P._oocd(["reset halt", "shutdown"], timeout=7)
    assert "not retried" in str(exc.value)
    assert len(calls) == 1


def test_openocd_launch_failure_is_a_clean_dap_error(monkeypatch):
    monkeypatch.setattr(P, "_resolve", lambda: ("missing-openocd", "target.cfg", None))

    def missing(*args, **kwargs):
        raise FileNotFoundError("missing")

    monkeypatch.setattr(P.subprocess, "run", missing)
    with pytest.raises(P.DapProgrammingError, match="could not start OpenOCD"):
        P._oocd(["shutdown"])


def test_sram_disconnect_rejects_partial_mailbox(monkeypatch, tmp_path):
    firmware = tmp_path / "firmware.bin"
    firmware.write_bytes(b"firmware")
    args = SimpleNamespace(firmware=str(firmware), fabric=None, sleep=1, words=1)
    monkeypatch.setattr(P, "_require_ag32", lambda: P.EXPECTED_DEVICE_ID)
    partial = "0x%08x: 000f0002\n" % P.RESULT_ADDR
    monkeypatch.setattr(
        P, "_oocd",
        lambda commands: SimpleNamespace(returncode=1, stdout=partial, stderr="disconnect"),
    )
    with pytest.raises(P.DapProgrammingError, match="partial mailbox output was ignored"):
        P.cmd_sram(args)


def test_flash_verify_requires_a_fresh_successful_exact_length_dump(tmp_path, monkeypatch):
    image = tmp_path / "image.bin"
    image.write_bytes(b"fresh-readback")

    def dump(commands):
        command = next(item for item in commands if item.startswith("dump_image "))
        readback = command.split('"', 2)[1]
        with open(readback, "wb") as stream:
            stream.write(image.read_bytes())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(P, "_oocd", dump)
    assert P._verify_region(P.FLASH_BASE, image) == (
        True, "14 B byte-exact @ 0x80000000"
    )

    monkeypatch.setattr(
        P, "_oocd",
        lambda commands: SimpleNamespace(returncode=1, stdout="", stderr="failed"),
    )
    assert P._verify_region(P.FLASH_BASE, image) == (False, "read-back failed")

    def short_dump(commands):
        command = next(item for item in commands if item.startswith("dump_image "))
        with open(command.split('"', 2)[1], "wb") as stream:
            stream.write(b"short")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(P, "_oocd", short_dump)
    ok, detail = P._verify_region(P.FLASH_BASE, image)
    assert ok is False and "length" in detail
