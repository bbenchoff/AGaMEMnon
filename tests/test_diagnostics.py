from agamemnon import diagnostics


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
