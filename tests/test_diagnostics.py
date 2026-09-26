from agamemnon import diagnostics
import os
import sys
import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable symlink integration")
def test_doctor_launches_existing_executable_below_spaced_unicode_path(tmp_path, monkeypatch):
    tool = tmp_path / "SDK smoke ü path" / "nextpnr-generic"
    tool.parent.mkdir()
    tool.symlink_to(sys.executable)
    monkeypatch.setenv("AGAMEMNON_UARCH_NEXTPNR", str(tool))
    monkeypatch.setattr(diagnostics, "_tool", lambda *args, **kwargs: None)
    monkeypatch.setattr(diagnostics, "_serial_ports", lambda: [])

    report = diagnostics.collect(hardware=False)
    check = next(c for c in report["checks"] if c["name"] == "AGRV2K nextpnr")
    assert check["status"] == "PASS"
    assert "Python" in check["detail"]


def test_doctor_reports_independent_capability_tiers(monkeypatch):
    monkeypatch.delenv("AGAMEMNON_UARCH_NEXTPNR", raising=False)
    monkeypatch.setattr(diagnostics, "_tool", lambda *args, **kwargs: None)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: None)
    monkeypatch.setattr(diagnostics, "_serial_ports", lambda: [])

    report = diagnostics.collect(hardware=False)

    assert report["ok"] is True
    assert report["tiers"]["inspect"]["ready"] is True
    assert report["tiers"]["mcu-build"]["ready"] is False
    assert report["tiers"]["fpga-build"]["ready"] is False
    assert report["tiers"]["dap-program"]["ready"] is False
    assert report["tiers"]["usb-program"]["ready"] is True
    assert report["tiers"]["uart-program"]["ready"] is True
