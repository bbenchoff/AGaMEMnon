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


def test_counter3_structure_and_evidence():
    source = (ROOT / "qualification" / "mcu_ahb_counter3_register.v").read_text(
        encoding="utf-8")
    assert 'BEL = "X14Y11_SLICE4"' in source
    assert 'BEL = "X14Y11_SLICE6"' in source
    assert 'BEL = "X14Y11_SLICE7"' in source
    assert 'BEL = "X17Y12_SLICE0"' in source
    assert "AGRV2K_DISTRIBUTION_ROOT = 1" in source
    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(row for row in records
                  if row["trial_id"] ==
                  "2026-08-04-l48-counter3-register-pure-open")
    assert record["verdict"] == "pass"
    assert record["bitstream_sha256"] == (
        "2724a8f0df1cc2686d65b21e74d64f529344579320d06ec6eb60967c5e716f2c"
    )


def test_counter3_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_counter3_register.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_counter3_register", "-o",
        str(output), str(ROOT / "qualification" /
                         "mcu_ahb_counter3_register.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_counter3_register.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: standalone three-bit counter register" in run.stdout
