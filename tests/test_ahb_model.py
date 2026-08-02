import os
from pathlib import Path
import shutil
import subprocess

import pytest

from agamemnon.sim.ahb import AhbSlaveModel


BASE = 0x60000000
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


def test_ahb_word_byte_and_halfword_transfers():
    model = AhbSlaveModel(base=BASE, words=4)
    assert not model.transact(address=BASE, write=True, data=0x11223344).resp
    assert model.transact(address=BASE).rdata == 0x11223344
    model.transact(address=BASE + 1, write=True, size=0, data=0xAA)
    assert model.transact(address=BASE).rdata == 0x1122AA44
    model.transact(address=BASE + 2, write=True, size=1, data=0xBEEF)
    assert model.transact(address=BASE).rdata == 0xBEEFAA44


def test_ahb_wait_states_and_error_responses():
    model = AhbSlaveModel(base=BASE, words=2, wait_states=2)
    model.transact(address=BASE, write=True, data=0xA5A55A5A)
    assert model.transact(address=BASE).rdata == 0xA5A55A5A
    assert model.transact(address=BASE + 1, size=1).resp  # misaligned halfword
    assert model.transact(address=BASE + 8).resp          # out of range
    assert model.transact(address=BASE, size=3).resp      # unsupported 64-bit transfer


def test_ahb_error_write_does_not_modify_memory():
    model = AhbSlaveModel(base=BASE, words=1)
    model.transact(address=BASE, write=True, data=0x12345678)
    assert model.transact(address=BASE + 1, write=True, size=2, data=0).resp
    assert model.transact(address=BASE).rdata == 0x12345678


def test_synthesizable_ahb_model_parses_as_systemverilog(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    source = ROOT / "agamemnon" / "sim" / "ahb_slave_model.v"
    result = subprocess.run(
        [compiler, "-g2012", "-s", "agamemnon_ahb_slave_model", "-o",
         str(tmp_path / "ahb_model.vvp"), str(source)],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("testbench", [
    "tb_ahb_slave_model_wait.v",
    "tb_ahb_slave_model_back_to_back.v",
])
def test_synthesizable_ahb_model_protocol_regressions(tmp_path, testbench):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    source = ROOT / "agamemnon" / "sim" / "ahb_slave_model.v"
    bench = ROOT / "examples" / "designs" / testbench
    output = tmp_path / (testbench + ".vvp")
    compile_result = subprocess.run(
        [compiler, "-g2012", "-o", str(output), str(source), str(bench)],
        env=env, capture_output=True, text=True,
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run_result = subprocess.run(
        [runner, str(output)], env=env, capture_output=True, text=True,
    )
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert "PASS:" in run_result.stdout
