import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bus_clock_silicon_probe_uses_a_sampling_safe_divider():
    probe = (ROOT / "examples" / "designs" /
             "mcu_bus_clock_divider.v").read_text(encoding="utf-8")
    assert "MCU_BUS_CLOCK mcu_bus_clock" in probe
    assert "reg [5:0] divider" in probe
    assert "divider <= {divider[4:0], ~divider[5]}" in probe
    assert "MCU_DOUT mcu_h0(.DOUT(divider[5]))" in probe


def test_bus_clock_history_preserves_static_control_and_bounded_pass():
    evidence = ROOT / "qualification" / "mcu_bus_clock_evidence.jsonl"
    records = [json.loads(line) for line in
               evidence.read_text(encoding="utf-8").splitlines()]
    failed, passed = records[0], records[-1]
    assert failed["hardware"] == "fail"
    assert failed["vendor_positive_control"] == "pass"
    assert failed["vendor_samples"] == {"high": 34, "low": 30}
    assert failed["open_samples"] == {"high": 64, "low": 0}
    assert failed["hardware_runs"] == 2
    assert failed["restoration"] == "DEVICE_ID 0x40200001 readable"

    assert passed["trial_id"] == "bus-clock-direct-d-pure-open-20260803"
    assert passed["verdict"] == "pass"
    assert "low=236 high=264" in passed["observed"]
    assert "no frequency or deterministic-reset claim" in passed["notes"]


def _tool(name):
    found = shutil.which(name)
    if found:
        return Path(found)
    directory = (ROOT / ".tmp" / "roadmap-sdk-windows-x64" / "tools" /
                 "oss-cad-suite" / "bin")
    for candidate in (directory / name, directory / f"{name}.exe"):
        if candidate.exists():
            return candidate
    return None


def test_typed_mcu_clock_reset_models_are_behaviorally_usable(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        return
    env = dict(os.environ)
    tool_bin = iverilog.parent
    env["PATH"] = os.pathsep.join([str(tool_bin), str(tool_bin.parent / "lib"),
                                   env.get("PATH", "")])
    image = tmp_path / "clock_reset.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s", "tb_mcu_clock_reset_counter",
        "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "examples" / "designs" / "mcu_clock_reset_counter.v"),
        str(ROOT / "examples" / "designs" / "tb_mcu_clock_reset_counter.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         text=True, capture_output=True)
    assert "PASS: typed MCU clock/reset simulation" in run.stdout


def test_constant_ready_ahb_endpoint_simulates(tmp_path):
    iverilog = _tool("iverilog")
    vvp = _tool("vvp")
    if not iverilog or not vvp:
        return
    env = dict(os.environ)
    tool_bin = iverilog.parent
    env["PATH"] = os.pathsep.join([str(tool_bin), str(tool_bin.parent / "lib"),
                                   env.get("PATH", "")])
    image = tmp_path / "constant_ahb.vvp"
    subprocess.run([
        str(iverilog), "-g2012", "-s", "tb_mcu_ahb_constant_slave",
        "-o", str(image),
        str(ROOT / "agamemnon" / "sim" / "mcu_fabric_prims_sim.v"),
        str(ROOT / "examples" / "designs" / "mcu_ahb_constant_slave.v"),
        str(ROOT / "examples" / "designs" / "tb_mcu_ahb_constant_slave.v"),
    ], check=True, cwd=ROOT, env=env)
    run = subprocess.run([str(vvp), str(image)], check=True, cwd=ROOT, env=env,
                         text=True, capture_output=True)
    assert "PASS: constant-ready OKAY AHB endpoint" in run.stdout
