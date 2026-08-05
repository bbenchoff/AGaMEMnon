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


def test_combined_bank_gpio_reset_structure_and_evidence():
    source = (ROOT / "qualification" /
              "mcu_ahb_register_bank_combined_gpio_reset.v").read_text(
                  encoding="utf-8")
    assert 'BEL = "X10Y5_MCU0"' in source
    assert ".reset_request(reset_request)" in source
    assert "INIT(16'h00D8)" in source
    assert "INIT(16'h00DC)" in source
    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(row for row in records
                  if row["trial_id"] ==
                  "2026-08-05-l48-combined-bank-gpio-reset-pure-open")
    assert record["verdict"] == "pass"
    assert record["bitstream_sha256"] == (
        "dbfb2b368976e868995f61f18f584fd320ec3bfa9e2c61ef51d617716da8ef3d"
    )


def test_combined_bank_gpio_reset_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_register_bank_gpio_reset.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s",
        "tb_mcu_ahb_register_bank_combined_gpio_reset", "-o", str(output),
        str(ROOT / "qualification" /
            "mcu_ahb_register_bank_combined_gpio_reset.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_register_bank_combined_gpio_reset.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: GPIO-resettable combined ID/scratch/counter/W1C bank" in run.stdout
