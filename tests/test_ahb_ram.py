"""Behavioral contracts for the inferred synchronous AHB RAM interface."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("initial", ["00000000", "a5c369f0"])
def test_full_width_ram_bus_contract(tmp_path, initial):
    compiler, runtime = shutil.which("iverilog"), shutil.which("vvp")
    if not compiler or not runtime:
        pytest.skip("Icarus Verilog is required")
    output = tmp_path / "ram.vvp"
    result = subprocess.run([compiler, "-g2012", "-s", "tb", "-Ptb.INIT=32'h" + initial,
        "-o", str(output), str(ROOT / "agamemnon/rtl/mcu_ahb_ram.v"),
        str(ROOT / "tests/rtl/tb_ahb_ram.v")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([runtime, str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS full-depth/full-word RAM" in result.stdout
