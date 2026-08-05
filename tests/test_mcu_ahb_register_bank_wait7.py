import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "qualification" / "mcu_ahb_register_bank_combined_wait.v"
TESTBENCH = (ROOT / "examples" / "designs" /
             "tb_mcu_ahb_register_bank_combined_wait.v")
LEDGER = ROOT / "qualification" / "mcu_ahb_register_bank_evidence.jsonl"


def _iverilog():
    found = shutil.which("iverilog")
    oss = os.environ.get("AGAMEMNON_OSS")
    if not found and oss:
        candidate = Path(oss) / "bin" / ("iverilog.exe" if os.name == "nt" else
                                          "iverilog")
        if candidate.is_file():
            return str(candidate)
    return found


def test_wait7_boundary_is_explicit_and_evidenced():
    source = SOURCE.read_text(encoding="utf-8")
    assert "seven-bit writable bank" in source
    assert 'BEL = "X14Y12_SLICE15"' in source
    assert "INIT(16'h0000)" in source
    assert "scratch <= {hwdata[7], 1'b0, write_data_pipe5" in source

    records = [json.loads(line) for line in LEDGER.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    record = next(row for row in records if row["trial_id"] ==
                  "2026-08-05-l48-combined-bank-one-wait-seven-bit-pure-open")
    assert record["verdict"] == "pass"
    assert "all 256 writes" in record["observed"]
    assert "lane 6 stayed zero" in record["observed"]
    assert "not an eight-bit" in record["notes"]

    early = next(row for row in records if row["trial_id"] ==
                 "2026-08-05-l48-combined-bank-wait-early-high-commit-negative")
    assert early["verdict"] == "fail"
    assert early["resolution"] == "retained_negative"
    assert early["dead_candidate"] is None
    assert "0xc1" in early["observed"]
    assert "Do not rerun" in early["notes"]

    commit_f = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-combined-bank-wait-lane6-commit-f-negative")
    assert commit_f["verdict"] == "fail"
    assert commit_f["resolution"] == "retained_negative"
    assert commit_f["dead_candidate"] is None
    assert "0xe5" in commit_f["observed"]
    assert "0x7c" in commit_f["observed"]
    assert "Do not rerun" in commit_f["notes"]

    subword = next(row for row in records if row["trial_id"] ==
                   "2026-08-05-l48-wait7-aligned-halfword-word-low-byte")
    assert subword["verdict"] == "pass"
    assert "zero low-byte mismatches" in subword["observed"]
    upper = next(row for row in records if row["trial_id"] ==
                 "2026-08-05-l48-wait7-upper-hrdata-undriven-negative")
    assert upper["resolution"] == "retained_negative"
    assert "768/768" in upper["observed"]
    assert "explicit upper-zero" in upper["notes"]

    hrdata8 = next(row for row in records if row["trial_id"] ==
                   "2026-08-05-l48-wait7-hrdata8-explicit-zero")
    assert hrdata8["verdict"] == "pass"
    assert "zero bit8 errors" in hrdata8["observed"]
    assert "0xfffffe00" in hrdata8["observed"]
    assert "Bits9-31 remain undriven" in hrdata8["notes"]
    assert len(hrdata8["gnd_path_pips"]) == 7
    assert len(hrdata8["relocated_hrdata7_pips"]) == 8

    hrdata9 = next(row for row in records if row["trial_id"] ==
                   "2026-08-05-l48-wait7-hrdata9-explicit-zero")
    assert hrdata9["verdict"] == "pass"
    assert "zero low-byte and bits8-9 errors" in hrdata9["observed"]
    assert "0xfffffc00" in hrdata9["observed"]
    assert "Bits10-31 remain undriven" in hrdata9["notes"]
    assert len(hrdata9["gnd_path_pips"]) == 8
    correction = next(row for row in records if row["trial_id"] ==
                      "2026-08-05-l48-wait7-hrdata9-artifact-hash-correction")
    assert correction["resolution"] == "metadata_correction"
    assert correction["supersedes_artifact_hashes_for"] == hrdata9["trial_id"]
    assert correction["firmware_sha256"] == hrdata9["firmware_sha256"]

    hrdata10 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait7-hrdata10-explicit-zero")
    assert hrdata10["verdict"] == "pass"
    assert "zero low-byte and bits8-10 errors" in hrdata10["observed"]
    assert "0xfffff800" in hrdata10["observed"]
    assert "Bits11-31 remain undriven" in hrdata10["notes"]
    assert len(hrdata10["gnd_path_pips"]) == 3

    hrdata11 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait7-hrdata11-explicit-zero")
    assert hrdata11["verdict"] == "pass"
    assert "zero low-byte and bits8-11 errors" in hrdata11["observed"]
    assert "0xfffff000" in hrdata11["observed"]
    assert "Bits12-31 remain undriven" in hrdata11["notes"]
    assert len(hrdata11["gnd_path_pips"]) == 6

    hrdata12 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait7-hrdata12-explicit-zero")
    assert hrdata12["verdict"] == "pass"
    assert "zero low-byte and bits8-12 errors" in hrdata12["observed"]
    assert "0xffffe000" in hrdata12["observed"]
    assert "registered-zero scratch6" in hrdata12["notes"]
    assert len(hrdata12["zero_path_pips"]) == 3

    hrdata13 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait7-hrdata13-explicit-zero")
    assert hrdata13["verdict"] == "pass"
    assert "zero low-byte and bits8-13 errors" in hrdata13["observed"]
    assert "0xffffc000" in hrdata13["observed"]
    assert "free exact sink ingress" in hrdata13["notes"]
    assert len(hrdata13["gnd_path_pips"]) == 4

    hrdata14 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait7-hrdata14-explicit-zero")
    assert hrdata14["verdict"] == "pass"
    assert "zero low-byte and bits8-14 errors" in hrdata14["observed"]
    assert "0xffff8000" in hrdata14["observed"]
    assert "free exact sink ingress" in hrdata14["notes"]
    assert len(hrdata14["gnd_path_pips"]) == 6
    correction14 = next(row for row in records if row["trial_id"] ==
                        "2026-08-05-l48-wait7-hrdata14-artifact-hash-correction")
    assert correction14["resolution"] == "metadata_correction"
    assert correction14["supersedes_artifact_hashes_for"] == hrdata14["trial_id"]
    assert correction14["firmware_sha256"] == hrdata14["firmware_sha256"]

    hrdata15 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait7-hrdata15-exact-halfword")
    assert hrdata15["verdict"] == "pass"
    assert "zero exact-halfword and bits8-15 errors" in hrdata15["observed"]
    assert "0xffff0000" in hrdata15["observed"]
    assert "write_data_pipe5" in hrdata15["notes"]
    assert len(hrdata15["zero_path_pips"]) == 6
    assert len(hrdata15["relocated_pipe5_pips"]) == 6


def test_wait7_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_register_bank_wait7.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_register_bank_combined_wait",
        "-o", str(output), str(SOURCE), str(TESTBENCH),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: one-write-wait GPIO-resettable seven-bit bank" in run.stdout
