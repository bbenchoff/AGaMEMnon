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
HADDR0_PATHS = ROOT / "agamemnon" / "chipdb" / "mcu_haddr0_logic_paths.csv"
HADDR1_PATHS = ROOT / "agamemnon" / "chipdb" / "mcu_haddr1_logic_paths.csv"


def _iverilog():
    found = shutil.which("iverilog")
    oss = os.environ.get("AGAMEMNON_OSS")
    if not found and oss:
        candidate = Path(oss) / "bin" / ("iverilog.exe" if os.name == "nt" else
                                          "iverilog")
        if candidate.is_file():
            return str(candidate)
    return found


def test_wait8_boundary_is_explicit_and_evidenced():
    source = SOURCE.read_text(encoding="utf-8")
    assert "complete-byte writable bank" in source
    assert 'BEL = "X14Y12_SLICE15"' in source
    assert ".F(scratch_commit_now), .Q(scratch_commit_root)" in source
    assert "INIT(16'h00B8)" in source
    assert "scratch[6] <= hwdata[6]" in source

    records = [json.loads(line) for line in LEDGER.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    record = next(row for row in records if row["trial_id"] ==
                  "2026-08-05-l48-combined-bank-one-wait-seven-bit-pure-open")
    assert record["verdict"] == "pass"
    assert "all 256 writes" in record["observed"]
    assert "lane 6 stayed zero" in record["observed"]
    assert "not an eight-bit" in record["notes"]

    complete = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-combined-bank-one-wait-complete-byte")
    assert complete["verdict"] == "pass"
    assert complete["resolution"] == "live_path"
    assert "all 256 values and 128 back-to-back pairs" in complete["observed"]
    assert "total errors zero" in complete["observed"]
    assert "complete eight-bit scratch bank" in complete["notes"]
    assert len(complete["qualified_hwdata6_pips"]) == 6
    assert len(complete["haddr2_relocation_pips"]) == 6
    assert len(complete["lane6_commit_f_pips"]) == 3

    wait8_h8 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait8-hrdata8-explicit-zero")
    assert wait8_h8["verdict"] == "pass"
    assert wait8_h8["resolution"] == "live_path"
    assert "zero low-nine-bit errors" in wait8_h8["observed"]
    assert "512 residual upper observations" in wait8_h8["observed"]
    assert "HRDATA[15:9]" in wait8_h8["notes"]
    assert len(wait8_h8["relocated_hrdata7_pips"]) == 8
    assert len(wait8_h8["zero_path_pips"]) == 7

    wait8_h9 = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-wait8-hrdata9-explicit-zero")
    assert wait8_h9["verdict"] == "pass"
    assert wait8_h9["resolution"] == "live_path"
    assert "bit9 zero" in wait8_h9["observed"]
    assert "HRDATA[15:10]" in wait8_h9["notes"]
    assert len(wait8_h9["zero_path_pips"]) == 8

    wait8_h10 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata10-explicit-zero")
    assert wait8_h10["verdict"] == "pass"
    assert "bit10 zero" in wait8_h10["observed"]
    assert "HRDATA[15:11]" in wait8_h10["notes"]
    assert len(wait8_h10["zero_path_pips"]) == 3

    wait8_h11 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata11-explicit-zero")
    assert wait8_h11["verdict"] == "pass"
    assert "bit11 zero" in wait8_h11["observed"]
    assert "HRDATA[15:12]" in wait8_h11["notes"]
    assert len(wait8_h11["zero_path_pips"]) == 6

    wait8_h12 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata12-explicit-gnd")
    assert wait8_h12["verdict"] == "pass"
    assert "bit12 zero" in wait8_h12["observed"]
    assert "without misusing live scratch6" in wait8_h12["notes"]
    assert len(wait8_h12["scratch6_relocation_pips"]) == 3
    assert len(wait8_h12["zero_path_pips"]) == 4

    wait8_h13 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata13-explicit-zero")
    assert wait8_h13["verdict"] == "pass"
    assert "bit13 zero" in wait8_h13["observed"]
    assert "HRDATA[15:14]" in wait8_h13["notes"]
    assert len(wait8_h13["zero_path_pips"]) == 4

    wait8_h14 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata14-explicit-zero")
    assert wait8_h14["verdict"] == "pass"
    assert "bit14 zero" in wait8_h14["observed"]
    assert "HRDATA15" in wait8_h14["notes"]
    assert len(wait8_h14["zero_path_pips"]) == 6

    wait8_h15_negative = next(row for row in records if row["trial_id"] ==
                              "2026-08-05-l48-wait8-hrdata15-imux-turnaround-negative")
    assert wait8_h15_negative["verdict"] == "fail"
    assert wait8_h15_negative["resolution"] == "retained_negative"
    assert "not a transparent constant route" in wait8_h15_negative["notes"]
    assert len(wait8_h15_negative["candidate_path_pips"]) == 7

    wait8_h15 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata15-explicit-zero")
    assert wait8_h15["verdict"] == "pass"
    assert "bit15 zero" in wait8_h15["observed"]
    assert "without treating live scratch6 as a constant" in wait8_h15["notes"]
    assert len(wait8_h15["zero_path_pips"]) == 7

    wait8_h16 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata16-explicit-zero")
    assert wait8_h16["verdict"] == "pass"
    assert "bit16 zero" in wait8_h16["observed"]
    assert "HRDATA[31:17]" in wait8_h16["notes"]
    assert len(wait8_h16["zero_path_pips"]) == 2

    wait8_h17 = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-wait8-hrdata17-explicit-zero")
    assert wait8_h17["verdict"] == "pass"
    assert "bit17 zero" in wait8_h17["observed"]
    assert "HRDATA[31:18]" in wait8_h17["notes"]
    assert len(wait8_h17["zero_path_pips"]) == 6

    wait8_upper_group = next(row for row in records if row["trial_id"] ==
                             "2026-08-05-l48-wait8-hrdata18-31-route-only-group")
    assert wait8_upper_group["verdict"] == "pass"
    assert wait8_upper_group["qualified_lanes"] == [18, 19, 21, 22, 23, 24,
                                                      25, 26, 28, 29, 30, 31]
    assert wait8_upper_group["remaining_lanes"] == [20, 27]
    assert "individual PASS" in wait8_upper_group["observed"]

    wait8_word32 = next(row for row in records if row["trial_id"] ==
                        "2026-08-05-l48-wait8-word32-complete")
    assert wait8_word32["verdict"] == "pass"
    assert wait8_word32["qualified_lanes"] == [20, 27]
    assert wait8_word32["remaining_lanes"] == []
    assert "exact 32-bit scratch reads had zero errors" in wait8_word32["observed"]
    assert set(wait8_word32["zero_path_pips"]) == {"20", "27"}
    assert all(len(path) == 2 for path in wait8_word32["zero_path_pips"].values())

    haddr0 = next(row for row in records if row["trial_id"] ==
                  "2026-08-05-l48-wait8-haddr0-simultaneous-sticky")
    assert haddr0["verdict"] == "pass"
    assert "odd byte read at +5" in haddr0["observed"]
    assert "ALLOW_BYTE=0" in haddr0["notes"]
    assert len(haddr0["haddr0_path_pips"]) == 4
    assert len(haddr0["scratch6_relocation_pips"]) == 3
    paths = HADDR0_PATHS.read_text(encoding="utf-8")
    assert paths.count("2026-08-05-l48-wait8-haddr0-simultaneous-sticky") == 4
    assert "X13Y12_InputMUX11,X14Y12_RMUX87" in paths

    access_negative = next(row for row in records if row["trial_id"] ==
                           "2026-08-05-l48-wait8-access-pre-gating-negative")
    assert access_negative["verdict"] == "fail"
    assert access_negative["resolution"] == "retained_negative"
    assert "Do not rerun" in access_negative["notes"]

    misaligned = next(row for row in records if row["trial_id"] ==
                      "2026-08-11-l48-misaligned-access-fault-boundary")
    assert misaligned["verdict"] == "pass"
    assert misaligned["resolution"] == "characterized_fail_closed"
    assert "mcause 5" in misaligned["observed"]
    assert "mcause 7" in misaligned["observed"]
    assert "never reach the fabric slave" in misaligned["notes"]
    assert "CPU-unreachable" in misaligned["notes"]

    access = next(row for row in records if row["trial_id"] ==
                  "2026-08-05-l48-wait8-aligned-byte-halfword-complete-bank")
    assert access["verdict"] == "pass"
    assert "scratch subword oracle PASS" in access["observed"]
    assert "class oracle PASS" in access["observed"]
    assert "Misaligned CPU instructions" in access["notes"]
    assert len(access["haddr1_path_pips"]) == 7
    assert HADDR1_PATHS.read_text(encoding="utf-8").count(
        "2026-08-05-l48-wait8-aligned-byte-halfword-complete-bank") == 7

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

    two_wait = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-combined-bank-wait-two-cycle-negative")
    assert two_wait["verdict"] == "fail"
    assert two_wait["resolution"] == "retained_negative"
    assert two_wait["dead_candidate"] is None
    assert "2087" in two_wait["observed"]
    assert "original full-byte wait negative" in two_wait["observed"]
    assert "Do not" in two_wait["notes"]

    ownq_pin = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-combined-bank-wait-lane6-ownq-pin-negative")
    assert ownq_pin["verdict"] == "fail"
    assert ownq_pin["resolution"] == "retained_negative"
    assert ownq_pin["dead_candidate"] is None
    assert "delta2082" in ownq_pin["observed"]
    assert "own-Q pin placement" in ownq_pin["notes"]
    assert "Do not rerun" in ownq_pin["notes"]

    q_witness = next(row for row in records if row["trial_id"] ==
                     "2026-08-05-l48-combined-bank-wait-lane6-q-witness")
    assert q_witness["verdict"] == "pass"
    assert q_witness["resolution"] == "live_path"
    assert q_witness["dead_candidate"] is None
    assert "zero disagreements" in q_witness["observed"]
    assert "127 expected-data errors" in q_witness["observed"]
    assert "stored state" in q_witness["notes"]
    assert "Do not re-probe" in q_witness["notes"]

    separate = next(row for row in records if row["trial_id"] ==
                    "2026-08-05-l48-combined-bank-wait-lane6-separate-storage-negative")
    assert separate["verdict"] == "fail"
    assert separate["resolution"] == "retained_negative"
    assert separate["dead_candidate"] is None
    assert "delta2082" in separate["observed"]
    assert "HWDATA6 ingress corridor" in separate["notes"]
    assert "Do not rerun" in separate["notes"]

    exact_route = next(row for row in records if row["trial_id"] ==
                       "2026-08-05-l48-combined-bank-wait-qualified-hwdata6-route-partial-negative")
    assert exact_route["verdict"] == "fail"
    assert exact_route["resolution"] == "retained_negative"
    assert exact_route["dead_candidate"] is None
    assert "3/256" in exact_route["observed"]
    assert "64/128" in exact_route["observed"]
    assert "one-transfer lane6 commit lag" in exact_route["notes"]
    assert "Do not rerun" in exact_route["notes"]

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


def test_wait8_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_register_bank_wait8.vvp"
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
    assert "PASS: one-write-wait GPIO-resettable complete-byte bank" in run.stdout
