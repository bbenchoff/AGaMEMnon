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


def test_controlled_wait_id_structure_and_evidence():
    source = (ROOT / "qualification" /
              "mcu_ahb_controlled_wait_id.v").read_text(encoding="utf-8")
    assert 'BEL = "X14Y12_SLICE0"' in source
    assert 'BEL = "X14Y12_SLICE1"' in source
    assert 'BEL = "X14Y11_SLICE6"' in source
    assert "INIT(16'h0088)" in source
    assert "INIT(16'hDDDD)" in source
    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(row for row in records
                  if row["trial_id"] ==
                  "2026-08-05-l48-controlled-wait-id-pure-open")
    assert record["verdict"] == "pass"
    assert record["bitstream_sha256"] == (
        "c74926db058134b5bd2ae2c8ef216fab601a03931a1dca777868a717326541d0"
    )
    assert record["source_wire"] == "X14Y11_OMUX20"
    negatives = {row["trial_id"]: row for row in records}
    assert negatives[
        "2026-08-05-l48-combined-bank-wait-lane6-negative"
    ]["resolution"] == "retained_negative"
    assert negatives[
        "2026-08-05-l48-combined-bank-wait-capture6-negative"
    ]["dead_candidate"] is None


def test_controlled_wait_id_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_controlled_wait_id.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_controlled_wait_id",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_controlled_wait_id.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_controlled_wait_id.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: controlled one-wait ID endpoint" in run.stdout
