"""Pure, hardware-free safety checks for flash range validation."""
import subprocess
from types import SimpleNamespace

import pytest

from agamemnon import program as P


def test_sectors_for_empty_is_empty():
    assert P._sectors_for(P.FLASH_BASE + 0x8100, 0) == []


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
