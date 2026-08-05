import os
from pathlib import Path
import shutil
import subprocess

import pytest

from agamemnon.mcu_register_bank import render_header


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


def test_register_bank_rtl_covers_required_register_classes():
    source = (ROOT / "agamemnon" / "rtl" /
              "mcu_ahb_register_bank.v").read_text(encoding="utf-8")
    assert "REG_ID" in source
    assert "REG_SCRATCH" in source
    assert "REG_COUNTER" in source
    assert "REG_STATUS" in source
    assert "STATUS <= (STATUS & ~(write_value & write_mask)) | STATUS_SET" in source
    assert "module agamemnon_mcu_ahb_register_bank" in source
    assert "agamemnon_mcu_ahb_port port_i" in source


def test_register_bank_protocol_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_register_bank.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_register_bank", "-o", str(output),
        str(ROOT / "agamemnon" / "rtl" / "mcu_ahb_register_bank.v"),
        str(ROOT / "examples" / "designs" / "tb_mcu_ahb_register_bank.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: MCU AHB register bank" in run.stdout


def test_register_bank_byte_disabled_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_register_bank_nobyte.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_register_bank_nobyte", "-o", str(output),
        str(ROOT / "agamemnon" / "rtl" / "mcu_ahb_register_bank.v"),
        str(ROOT / "examples" / "designs" / "tb_mcu_ahb_register_bank_nobyte.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: MCU AHB register bank ALLOW_BYTE=0" in run.stdout


def test_register_bank_pipelined_write_timing(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_register_bank_pipelined.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_register_bank_pipelined",
        "-o", str(output),
        str(ROOT / "agamemnon" / "rtl" / "mcu_ahb_register_bank.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_register_bank_pipelined.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: pipelined MCU AHB write boundary timing" in run.stdout


def test_posted_scratch_read_forwarding_timing(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "scratch1_forward.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_pipelined_scratch1_forward",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_pipelined_scratch1_forward.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_pipelined_scratch1_forward.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: posted scratch same-address forwarding" in run.stdout


def test_posted_scratch_address_tag_timing(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "scratch1_addrtag.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_posted_scratch1_addrtag",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_posted_scratch1_addrtag.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_posted_scratch1_addrtag.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: posted scratch address-tag forwarding" in run.stdout


def test_posted_scratch2_address_tag_timing(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "scratch2_addrtag.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_posted_scratch2_addrtag",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_posted_scratch2_addrtag.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_posted_scratch2_addrtag.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: two-bit posted scratch address-tag forwarding" in run.stdout


def test_posted_scratch3_address_tag_timing(tmp_path):
    source = (ROOT / "qualification" / "mcu_ahb_posted_scratch3_addrtag.v").read_text(
        encoding="utf-8")
    assert 'BEL = "X14Y11_SLICE2"' in source
    assert "INIT(16'h2222)" in source
    assert ".I({2'b00, haddr2, scratch[2]})" in source
    assert "INIT(16'hBB88)" in source
    assert ".I({scratch[2], 1'b0, write_commit0, hwdata[2]})" in source
    assert 'BEL = "X14Y12_SLICE1" *) reg write_pending' in source
    assert 'BEL = "X17Y12_SLICE0" *)' in source
    assert "INIT(16'h4444)" in source
    assert ".I({write_pending, addr_pipe, write_pending, addr_pipe})" in source
    assert 'BEL = "X14Y12_SLICE0" *) reg addr_pipe' in source
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "scratch3_addrtag.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_posted_scratch3_addrtag",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_posted_scratch3_addrtag.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_posted_scratch3_addrtag.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: three-bit posted scratch address-tag forwarding" in run.stdout


def test_posted_scratch4_address_tag_timing(tmp_path):
    source = (ROOT / "qualification" / "mcu_ahb_posted_scratch4_addrtag.v").read_text(
        encoding="utf-8")
    assert 'BEL = "X15Y12_SLICE0"' in source
    assert 'BEL = "X14Y11_SLICE3"' in source
    assert "INIT(16'hDD88)" in source
    assert ".I({scratch[3], 1'b0, hwdata[3], write_commit0})" in source
    assert ".I({2'b00, haddr2, scratch[3]})" in source
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "scratch4_addrtag.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_posted_scratch4_addrtag",
        "-o", str(output),
        str(ROOT / "qualification" / "mcu_ahb_posted_scratch4_addrtag.v"),
        str(ROOT / "examples" / "designs" /
            "tb_mcu_ahb_posted_scratch4_addrtag.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: four-bit posted scratch address-tag forwarding" in run.stdout


def test_register_header_is_generated_and_rejects_bad_base(tmp_path):
    checked_in = (ROOT / "examples" / "riscv_mcu" /
                  "fabric_register_bank.h").read_text(encoding="utf-8")
    assert checked_in == render_header()
    assert "AGAMEMNON_FABRIC_STATUS" in checked_in
    with pytest.raises(ValueError, match="aligned"):
        render_header(0x60000001)

    output = tmp_path / "custom.h"
    result = subprocess.run([
        os.sys.executable, "-m", "agamemnon.mcu_register_bank",
        "--base", "0x61000000", "--output", str(output),
    ], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0x61000000" in output.read_text(encoding="utf-8")
