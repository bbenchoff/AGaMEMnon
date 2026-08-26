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


def test_ag32_wrapper_binds_every_hard_boundary_lane():
    source = (ROOT / "agamemnon" / "rtl" /
              "fabric_ahb_read_master_ag32.v").read_text(encoding="utf-8")
    assert "agamemnon_fabric_ahb_read_master" in source
    controls = [
        "HSEL", "HREADY", "HTRANS0", "HTRANS1", "HSIZE0", "HSIZE1",
        "HSIZE2", "HBURST0", "HBURST1", "HBURST2", "HWRITE",
    ]
    for control in controls:
        assert f"MCU_SLAVE_AHB_{control} " in source
    for lane in range(32):
        assert f"mcu_slave_haddr{lane}(.DOUT(haddr[{lane}]))" in source
        assert f"mcu_slave_hwdata{lane}(.DOUT(hwdata[{lane}]))" in source
        assert f"MCU_SLAVE_AHB_HRDATA{lane} mcu_slave_hrdata{lane}" in source
    assert "MCU_SLAVE_AHB_HREADYOUT" in source
    assert "MCU_SLAVE_AHB_HRESP" in source


def test_ag32_wrapper_reset_idle_zero_wait_simulation(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog/vvp not available")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([
        str(iverilog.parent), str(iverilog.parent.parent / "lib"),
        env.get("PATH", ""),
    ])
    image = tmp_path / "fabric_ahb_read_master_ag32.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s", "tb_fabric_ahb_read_master_ag32",
        "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "agamemnon" / "rtl" / "fabric_ahb_read_master.v"),
        str(ROOT / "agamemnon" / "rtl" / "fabric_ahb_read_master_ag32.v"),
        str(ROOT / "examples" / "designs" /
            "tb_fabric_ahb_read_master_ag32.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert "PASS: AG32 read-master wrapper reset-idle zero-wait binding" in run.stdout
