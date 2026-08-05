import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _iverilog():
    found = shutil.which("iverilog")
    oss = os.environ.get("AGAMEMNON_OSS")
    if not found and oss:
        for name in ("iverilog", "iverilog.exe"):
            candidate = Path(oss) / "bin" / name
            if candidate.is_file():
                return str(candidate)
    return found


def test_local_int1_command_bank_structure_and_evidence():
    source = (ROOT / "qualification" /
              "mcu_ahb_local_int1_bank.v").read_text(encoding="utf-8")
    assert 'BEL = "X14Y12_SLICE0"' in source
    assert 'BEL = "X14Y12_SLICE1"' in source
    assert 'BEL = "X14Y11_SLICE7"' in source
    assert 'BEL = "X15Y11_SLICE4"' in source
    assert 'BEL = "X14Y8_SLICE0"' in source
    assert "INIT(16'h00D8)" in source
    assert "INIT(16'h00DC)" in source
    assert "assign hrdata[0] = 1'b0" in source

    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(row for row in records if row["trial_id"] ==
                  "2026-08-05-l48-ahb-local-int1-command-bank-pure-open")
    assert record["verdict"] == "pass"
    assert record["bitstream_sha256"] == (
        "7dbee13f53451e8d047f5c841de4bf2e9bb01eb10dc912a3ae899f2978ee1732"
    )
    assert record["source_wire"] == "X14Y8_OMUX02"
    assert record["observed_wire"] == "X0Y5_SinkMUXPseudo216"
    assert len(record["path_pips"]) == 8
    assert "no state-read claim" in record["notes"]

    negative_records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_local_int1_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {row["trial_id"] for row in negative_records} == {
        "2026-08-05-l48-local-int1-mask-commit-class-negative",
        "2026-08-05-l48-local-int1-forced-mask-discriminator",
        "2026-08-05-l48-local-int1-subset-readback-negative",
        "2026-08-05-l48-local-int1-direct-read-coupled-negative",
    }
    assert all(row["dead_candidate"] is None for row in negative_records)
    assert sum(row["verdict"] == "pass" for row in negative_records) == 1


def test_local_int1_command_bank_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"),
             env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_local_int1_bank.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_local_int1_bank",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_local_int1_bank.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_local_int1_bank.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: AHB-backed local_int1 pending/mask/ack/re-arm" in run.stdout
