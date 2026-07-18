import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from agamemnon import qualification_report


def test_report_is_explicitly_target_read_only_and_hashes_artifacts(tmp_path, monkeypatch):
    artifact = tmp_path / "route.json"
    artifact.write_bytes(b"qualified fixture")
    monkeypatch.setattr(
        qualification_report.diagnostics,
        "collect",
        lambda hardware: {"ok": True, "hardware_argument": hardware},
    )

    report = qualification_report.build_report([artifact], notes="bench intake")
    assert report["safety"]["target_io"] is False
    assert report["safety"]["target_state_written"] is False
    assert report["doctor"]["hardware_argument"] is False
    assert report["artifacts"] == [{
        "path": str(artifact.resolve()),
        "bytes": len(b"qualified fixture"),
        "sha256": hashlib.sha256(b"qualified fixture").hexdigest(),
    }]
    assert set(report["support_matrix"]["data"]["dimensions"]) == {
        "part", "package", "board", "transport", "feature",
    }


def test_qualify_command_writes_reviewable_json(tmp_path, monkeypatch):
    monkeypatch.setattr(
        qualification_report.diagnostics,
        "collect",
        lambda hardware: {"ok": True},
    )
    output = tmp_path / "report.json"
    qualification_report.cmd_qualify(SimpleNamespace(
        artifact=[], notes=None, output=str(output),
    ))
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["kind"] == "agamemnon-qualification-intake"
    assert data["safety"]["target_state_written"] is False
