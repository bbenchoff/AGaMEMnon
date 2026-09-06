import hashlib
import json

import pytest

from agamemnon.cli import _translate_wsl_nextpnr_args
from agamemnon.engine.timing_reports import TimingReports


@pytest.mark.parametrize("payload,status", [
    (None, "missing"), (b"{", "malformed"),
    (b"[]", "incomplete"), (b'{"fmax":{}}', "incomplete"),
    (b'{"fmax":{},"critical_paths":[],"detailed_net_timings":[]}', "available"),
])
def test_reports_never_infer_qualification(tmp_path, payload, status):
    source = tmp_path / "source.json"
    source.write_bytes(b'{"source":1}')
    reports = TimingReports(tmp_path / "image.bin")
    path = reports.begin(source, {"seed": "1"})
    running = json.loads((reports.directory / "manifest.json").read_text())
    assert running["attempts"][0]["status"] == "running"
    if payload is not None:
        from pathlib import Path
        Path(path).write_bytes(payload)
    reports.finish(1, "timing_failed", "Routing complete\nTiming failed")
    manifest = json.loads((reports.directory / "manifest.json").read_text())
    assert manifest["qualification"] is False
    assert manifest["constraint_coverage"] == "not_established"
    row = manifest["attempts"][0]
    assert row["report_status"] == status
    assert row["returncode"] == 1
    assert row["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    if status == "available":
        assert row["clock_fmax_count"] == 0


def test_retries_and_recursive_builds_do_not_reuse_reports(tmp_path):
    source = tmp_path / "source.json"
    paths = []
    for _ in range(2):
        reports = TimingReports(tmp_path / "image.bin")
        for seed in range(2):
            source.write_text(json.dumps({"seed": seed}))
            paths.append(reports.begin(source, {"seed": seed}))
            reports.finish(1, "not_routed", "failed")
        source.unlink()
        for row in reports.manifest["attempts"]:
            saved = reports.directory / row["input"]
            assert json.loads(saved.read_text()) == {"seed": row["seed"]}
    assert len(set(paths)) == 4


def test_wsl_report_path_with_spaces():
    assert _translate_wsl_nextpnr_args([
        "--report", "C:\\build evidence\\attempt.timing.json", "--detailed-timing-report"
    ]) == ["--report", "/mnt/c/build evidence/attempt.timing.json", "--detailed-timing-report"]
