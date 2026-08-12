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


def test_soft_uart_interface_is_bounded():
    source = (ROOT / "agamemnon" / "rtl" /
              "mcu_ahb_soft_uart.v").read_text(encoding="utf-8")
    assert "transfer_burst == 3'b000" in source
    assert "transfer_size == 3'd2" in source
    assert "REG_TXDATA" in source
    assert "REG_RXDATA" in source
    assert "REG_STATUS" in source
    assert "REG_DIVISOR" in source
    assert "module agamemnon_mcu_ahb_soft_uart" in source
    assert "haddr & 32'h0000_000f" in source


def test_soft_uart_loopback_simulation(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    env = dict(os.environ)
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        env["PATH"] = os.pathsep.join(
            [str(Path(oss) / "bin"), str(Path(oss) / "lib"), env.get("PATH", "")]
        )
    output = tmp_path / "mcu_ahb_soft_uart.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "tb_mcu_ahb_soft_uart", "-o", str(output),
        str(ROOT / "agamemnon" / "rtl" / "mcu_ahb_soft_uart.v"),
        str(ROOT / "examples" / "designs" / "tb_mcu_ahb_soft_uart.v"),
    ], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = Path(compiler).with_name("vvp.exe" if os.name == "nt" else "vvp")
    runner = str(runtime) if runtime.exists() else shutil.which("vvp")
    if not runner:
        pytest.skip("vvp absent")
    run = subprocess.run([runner, str(output)], env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS: register-backed soft UART loopback" in run.stdout


def test_soft_uart_hard_wrapper_compiles(tmp_path):
    compiler = _iverilog()
    if not compiler:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")
    output = tmp_path / "mcu_ahb_soft_uart_wrapper.vvp"
    result = subprocess.run([
        compiler, "-g2012", "-s", "agamemnon_mcu_ahb_soft_uart",
        "-o", str(output),
        str(ROOT / "agamemnon" / "rtl" / "mcu_ahb_soft_uart.v"),
        str(ROOT / "agamemnon" / "rtl" / "mcu_ahb_port.v"),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
