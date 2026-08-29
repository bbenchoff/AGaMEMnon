from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from qualification.n58b_hwdata25_i1_hil_s01.classifier import (
    CaptureContractError,
    NEGATIVE_NO_CONDUCTION,
    POSITIVE_EXACT_CONDUCTION,
    REJECT_INVALID_CONTROL,
    UNCLASSIFIED,
    classify,
)


PACKAGE = Path(__file__).resolve().parent
N = 32768


def waveform(block: int = 2048) -> bytes:
    return bytes(value for index in range(N) for value in ((index // block) & 1,))


def test_positive_exact_conduction() -> None:
    result = classify(bytes(N), waveform(), bytes(N))
    assert result["decision"] == POSITIVE_EXACT_CONDUCTION
    assert result["roles"]["candidate"]["transitions"] == 15
    assert len(result["roles"]["candidate"]["complete_high_run_lengths"]) == 7
    assert len(result["roles"]["candidate"]["complete_low_run_lengths"]) == 7


def test_negative_no_conduction_precedes_positive_checks() -> None:
    assert classify(bytes(N), bytes(N), bytes(N))["decision"] == NEGATIVE_NO_CONDUCTION


@pytest.mark.parametrize("role", ["control", "control-recovery"])
def test_any_control_high_rejects(role: str) -> None:
    control = bytearray(N)
    recovery = bytearray(N)
    (control if role == "control" else recovery)[123] = 1
    assert classify(control, waveform(), recovery)["decision"] == REJECT_INVALID_CONTROL


def test_mask_uses_only_gp8_bit_zero() -> None:
    assert classify(bytes([0xFE]) * N, bytes([0xFE]) * N, bytes([0xFE]) * N)["decision"] == NEGATIVE_NO_CONDUCTION


def test_sparse_candidate_is_unclassified() -> None:
    candidate = bytearray(N)
    candidate[N // 2] = 1
    assert classify(bytes(N), candidate, bytes(N))["decision"] == UNCLASSIFIED


def test_short_complete_run_is_unclassified() -> None:
    candidate = bytearray(waveform())
    candidate[5000:5031] = bytes([1]) * 31
    result = classify(bytes(N), candidate, bytes(N))
    assert result["decision"] == UNCLASSIFIED
    assert not result["roles"]["candidate"]["positive_requirements"]["all_complete_high_run_lengths_in_range"]


@pytest.mark.parametrize("role_index", [0, 1, 2])
def test_wrong_capture_length_fails_closed(role_index: int) -> None:
    captures = [bytes(N), waveform(), bytes(N)]
    captures[role_index] = captures[role_index][:-1]
    with pytest.raises(CaptureContractError):
        classify(*captures)


def test_non_bytes_capture_fails_closed() -> None:
    with pytest.raises(CaptureContractError):
        classify(bytes(N), [0] * N, bytes(N))  # type: ignore[arg-type]


def test_audit_rejects_tampered_artifact_in_disposable_copy(tmp_path: Path) -> None:
    package = tmp_path / "package"
    shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns("build", "__pycache__"))
    candidate = package / "artifacts" / "candidate.bin"
    data = bytearray(candidate.read_bytes())
    data[-1] ^= 1
    candidate.write_bytes(data)
    completed = subprocess.run(
        ["python", str(package / "audit_package.py")],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
    )
    assert completed.returncode != 0
    assert "SHA-256 drift" in completed.stderr


def test_audit_rejects_i1_contract_tamper_in_disposable_copy(tmp_path: Path) -> None:
    package = tmp_path / "package"
    shutil.copytree(PACKAGE, package, ignore=shutil.ignore_patterns("build", "__pycache__"))
    manifest_path = package / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["route_contract"]["candidate_sink"]["pin"] = "I0"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    completed = subprocess.run(
        ["python", str(package / "audit_package.py")],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
    )
    assert completed.returncode != 0
    assert "alternate-I1 route contract differs" in completed.stderr


def test_manifest_and_preregistration_are_valid_json() -> None:
    manifest = json.loads((PACKAGE / "package_manifest.json").read_text())
    prereg = json.loads((PACKAGE / "preregistration.json").read_text())
    assert manifest["hardware_execution_authorized_by_this_manifest"] is False
    assert manifest["route_contract"]["candidate_sink"]["pin"] == "I1"
    assert prereg["capture"]["rate_hz"] == 4_000_000
    assert prereg["safety"]["automatic_retry"] is False
