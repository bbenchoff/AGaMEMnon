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


def test_error_response_is_evidenced_and_fail_closed():
    source = (ROOT / "qualification" / "mcu_ahb_error_id.v").read_text(
        encoding="utf-8")
    assert 'BEL = "X14Y12_SLICE0"' in source
    assert 'BEL = "X14Y12_SLICE1"' in source
    assert 'BEL = "X14Y11_SLICE4"' in source
    assert 'BEL = "X14Y11_SLICE5"' in source
    assert 'BEL = "X14Y11_SLICE6"' in source
    assert "INIT(16'h0088)" in source
    assert "INIT(16'h2222)" in source
    assert "INIT(16'hFCFC)" in source
    assert "INIT(16'hDDDD)" in source

    registry = (ROOT / "agamemnon" / "engine" / "registry.py").read_text(
        encoding="utf-8")
    assert '"AGAMEMNON_DIRECT_D_COMB_F2"' in registry
    assert '"experimental"' in registry

    records = [
        json.loads(line)
        for line in (ROOT / "qualification" /
                     "mcu_ahb_register_bank_evidence.jsonl").read_text(
                         encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["trial_id"]: row for row in records}
    retired = by_id["2026-08-05-l48-error-two-cycle-f2-retired"]
    assert retired["resolution"] == "retired"
    assert retired["verdict"] == "fail"
    assert retired["dead_candidate"] is None
    assert retired["source_wire"] == "X14Y11_OMUX20"
    assert retired["response_wire"] == "X14Y11_OMUX15"
    assert retired["bitstream_sha256"] == (
        "0a5563f474ef3edbe6e89cbd889d7d3c431425ca598f6b65be3edb51adaff429"
    )
    assert by_id[
        "2026-08-05-l48-error-single-cycle-negative"
    ]["resolution"] == "retained_negative"
    assert by_id[
        "2026-08-05-l48-error-constant-high-negative"
    ]["dead_candidate"] is None

    status = (ROOT / "docs" / "STATUS.md").read_text(encoding="utf-8")
    assert "HRESP-to-MCU-access-fault claim is RETIRED" in status
    assert "zero load or store access traps" in status


def test_two_cycle_error_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_error_id.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_error_id", "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_error_id.v"),
        str(ROOT / "examples" / "designs" / "tb_mcu_ahb_error_id.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: deterministic address-selected AHB error endpoint" in run.stdout
