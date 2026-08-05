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


def test_scratch8_folded_lane7_structure_and_evidence():
    source = (ROOT / "qualification" /
              "mcu_ahb_posted_scratch8_addrtag.v").read_text(encoding="utf-8")
    assert 'BEL = "X14Y11_SLICE0"' in source
    assert ".INIT(16'hCACA)" in source
    assert ".I({1'b0, write_commit_lo, hwdata[7], scratch[7]})" in source
    assert 'BEL = "X14Y11_SLICE15"' in source

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
        "2026-08-04-l48-scratch8-folded-slice0-pure-open"
    )
    assert record["verdict"] == "pass"
    assert record["resolution"] == "live_path"
    assert record["bitstream_sha256"] == (
        "c6f9bf61873ba74a3f50e79c956754c0230f7349913e8e48a3d688aeabd636db"
    )


def test_scratch8_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_posted_scratch8.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_posted_scratch8_addrtag",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_posted_scratch8_addrtag.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_posted_scratch8_addrtag.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: eight-bit posted scratch address-tag forwarding" in run.stdout
