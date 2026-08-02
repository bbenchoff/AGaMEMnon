import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _tool(name):
    found = shutil.which(name)
    if found:
        return Path(found)
    suite = ROOT.parent / "AG32-Docs" / "tools" / "oss-cad-suite" / "bin"
    for candidate in (suite / name, suite / f"{name}.exe"):
        if candidate.exists():
            return candidate
    return None


def test_read_master_wait_error_and_timeout_protocol(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_master.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s", "tb_fabric_ahb_read_master",
        "-o", str(image),
        str(ROOT / "agamemnon" / "rtl" / "fabric_ahb_read_master.v"),
        str(ROOT / "examples" / "designs" / "tb_fabric_ahb_read_master.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert "PASS: reset-idle read master wait/error/timeout cases" in run.stdout


def test_read_master_cannot_issue_writes():
    source = (ROOT / "agamemnon" / "rtl" /
              "fabric_ahb_read_master.v").read_text(encoding="utf-8")
    assert "assign HWRITE = 1'b0;" in source
    assert "assign HWDATA = 32'b0;" in source
