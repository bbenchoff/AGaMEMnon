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


def test_scratch7_folded_lane6_structure_and_evidence():
    source = (ROOT / "qualification" /
              "mcu_ahb_posted_scratch7_addrtag.v").read_text(encoding="utf-8")
    assert 'BEL = "X14Y12_SLICE15"' in source
    assert ".INIT(16'hBB88)" in source
    assert ".I({scratch[6], 1'b0, write_commit_hi, hwdata[6]})" in source
    assert 'BEL = "X14Y11_SLICE13"' in source

    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    record = next(
        row for row in records
        if row["trial_id"] ==
        "2026-08-04-l48-scratch7-folded-slice15-pure-open"
    )
    assert record["verdict"] == "pass"
    assert record["resolution"] == "live_path"
    assert record["bitstream_sha256"] == (
        "82cbb7301af1b82252f08c1214a3ee12012f46b7a1e173380bcf021fbb1dc2be"
    )


def test_scratch7_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_posted_scratch7.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_posted_scratch7_addrtag",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_posted_scratch7_addrtag.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_posted_scratch7_addrtag.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: seven-bit posted scratch address-tag forwarding" in run.stdout
