import os
from pathlib import Path
import shutil
import subprocess
from typing import Optional

import pytest


ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "examples" / "peripherals" / "fpga"


def _tool(name: str) -> Optional[Path]:
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        root = Path(oss)
        for candidate in (root / "bin" / f"{name}.exe", root / f"{name}.exe"):
            if candidate.is_file():
                return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def test_combined_fpga_peripheral_simulation(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("Icarus Verilog absent (set AGAMEMNON_OSS or put it on PATH)")

    sources = [
        "timer_tick.v", "gpio_walker.v", "pwm4.v", "uart_tx.v",
        "spi_master.v", "i2c_writer.v", "peripheral_showcase.v",
        "tb_peripheral_showcase.v",
    ]
    image = tmp_path / "peripheral_showcase.vvp"
    env = dict(os.environ)
    if os.environ.get("AGAMEMNON_OSS"):
        oss = Path(os.environ["AGAMEMNON_OSS"])
        env["PATH"] = os.pathsep.join(
            [str(oss / "bin"), str(oss / "lib"), env.get("PATH", "")]
        )

    subprocess.run(
        [str(iverilog), "-g2012", "-s", "tb_peripheral_showcase", "-o", str(image),
         *(str(RTL / source) for source in sources)],
        cwd=ROOT, env=env, check=True,
    )
    result = subprocess.run(
        [str(vvp), str(image)], cwd=ROOT, env=env, check=True,
        capture_output=True, text=True,
    )
    assert "PASS peripheral showcase" in result.stdout
