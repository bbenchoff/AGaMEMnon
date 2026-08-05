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


def test_combined_bank_structure_and_evidence():
    source = (ROOT / "qualification" /
              "mcu_ahb_register_bank_combined.v").read_text(encoding="utf-8")
    assert 'BEL = "X17Y12_SLICE0"' in source
    assert "AGRV2K_DISTRIBUTION_ROOT = 1" in source
    assert 'BEL = "X15Y11_SLICE14"' in source
    assert "counter <= counter + 1'b1" in source
    assert "any_write_commit" in source
    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(row for row in records
                  if row["trial_id"] ==
                  "2026-08-05-l48-combined-register-bank-pure-open")
    assert record["verdict"] == "pass"
    assert record["bitstream_sha256"] == (
        "4af8dde3c5b680434b3fc4515a9158880b9cc37042238f0ff57db509ef402a7c"
    )
    negative = next(row for row in records
                    if row["trial_id"] ==
                    "2026-08-05-l48-combined-bank-hrdata0-s12-negative")
    assert negative["resolution"] == "causal_isolation"
    assert negative["dead_candidate"] is None


def test_combined_bank_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_register_bank_combined.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_register_bank_combined",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_register_bank_combined.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_register_bank_combined.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: combined byte ID/scratch/counter/W1C bank" in run.stdout
