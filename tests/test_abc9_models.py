"""ABC9 LUT4 model provenance and lowering checks; no hardware required."""
import json
import shutil
import subprocess

import pytest


ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
SYNTH = ROOT / "agamemnon" / "synth"


def _yosys_or_skip():
    yosys = shutil.which("yosys")
    if yosys:
        return yosys
    wsl = shutil.which("wsl")
    if wsl:
        try:
            probe = subprocess.run([wsl, "--exec", "yosys", "-V"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        else:
            if probe.returncode == 0:
                return None  # Use the verified WSL Yosys below.
    pytest.skip("Yosys unavailable natively and through WSL")


@pytest.mark.parametrize("available", [False, True])
def test_wsl_launcher_alone_does_not_establish_yosys_availability(monkeypatch, available):
    monkeypatch.setattr(shutil, "which", lambda name: "wsl.exe" if name == "wsl" else None)
    def probe(command, **kwargs):
        assert command == ["wsl.exe", "--exec", "yosys", "-V"]
        return subprocess.CompletedProcess(command, 0 if available else 1)
    monkeypatch.setattr(subprocess, "run", probe)
    if available:
        assert _yosys_or_skip() is None
    else:
        with pytest.raises(pytest.skip.Exception, match="Yosys unavailable"):
            _yosys_or_skip()


def test_abc9_model_has_only_recovered_lut_arcs_and_no_hardblock_claims():
    model = (SYNTH / "ag32_abc9_model.v").read_text(encoding="utf-8")
    hook = (SYNTH / "abc9_ag32.tcl").read_text(encoding="utf-8")
    assert "(* abc9_lut = 1, lib_whitebox *)" in model
    for arc in ("(I0 => O) = 608;", "(I1 => O) = 565;",
                "(I2 => O) = 474;", "(I3 => O) = 149;"):
        assert arc in model
    assert "abc9_box" not in model
    assert "module AG32_FA" not in model
    assert "yosys abc9\n" in hook
    assert "AG32_FA" in hook and "DFFE" in hook
    uarch = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    assert "SLICE_LUT_TO_F_NS[4] = {0.608, 0.565, 0.474, 0.149}" in uarch
    assert "I[0]/I[1]/I[2]/I[3]" in model


def test_abc9_maps_ordinary_logic_to_existing_lut_path(tmp_path):
    """The optional hook must produce $lut/LUTs consumable by cells_map.v."""
    yosys = _yosys_or_skip()
    source = tmp_path / "ordinary.v"
    output = tmp_path / "ordinary.json"
    source.write_text("""\
module top(input a, b, c, d, output y);
  assign y = (a & b) ^ (c | d);
endmodule
""", encoding="utf-8")
    def wsl_path(path):
        value = str(path).replace("\\", "/")
        if yosys:
            return value
        if value.startswith("/mnt/"):
            return value
        drive, rest = value.split(":/", 1)
        return "/mnt/" + drive.lower() + "/" + rest

    wsource = wsl_path(source)
    wmodel = wsl_path(SYNTH / "ag32_abc9_model.v")
    wcells = wsl_path(SYNTH / "cells_map.v")
    woutput = wsl_path(output)
    script = "; ".join((
        "read_verilog -lib -specify " + wmodel,
        "read_verilog " + wsource,
        "hierarchy -top top", "proc", "opt", "techmap -map +/techmap.v", "opt",
        "abc9",
        "techmap -D LUT_K=4 -map " + wcells, "write_json " + woutput,
    ))
    command = ([yosys, "-Q", "-p", script] if yosys else
               ["wsl", "--exec", "yosys", "-Q", "-p", script])
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout[-4000:]
    cells = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    assert any(cell["type"] == "LUT" for cell in cells.values())


def test_abc9_full_hook_leaves_dedicated_carry_for_existing_packer(tmp_path):
    """ABC9 must not absorb AG32_FA before the normal carry packer sees it."""
    yosys = _yosys_or_skip()

    def tool_path(path):
        value = str(path).replace("\\", "/")
        if yosys or value.startswith("/mnt/"):
            return value
        drive, rest = value.split(":/", 1)
        return "/mnt/" + drive.lower() + "/" + rest

    output = tmp_path / "carry.json"
    script = tool_path(SYNTH / "synth_pads.tcl")
    source = tool_path(ROOT / "examples" / "designs" / "carry_add4.v")
    output_arg = tool_path(output)
    env = dict(**__import__("os").environ,
               AGAMEMNON_ABC9="1", AGAMEMNON_HW_CARRY="1",
               AGAMEMNON_YOSYS_TOP="carry_add4", AGAMEMNON_YOSYS_JSON=output_arg)
    command = ([yosys, "-q", "-c", script, source] if yosys else
               ["wsl", "--exec", "env", "AGAMEMNON_ABC9=1", "AGAMEMNON_HW_CARRY=1",
                "AGAMEMNON_YOSYS_TOP=carry_add4", "AGAMEMNON_YOSYS_JSON=" + output_arg,
                "yosys", "-q", "-c", script, source])
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-4000:]
    cells = json.loads(output.read_text(encoding="utf-8"))["modules"]["carry_add4"]["cells"]
    assert sum(cell["type"] == "AG32_FA" for cell in cells.values()) == 5
