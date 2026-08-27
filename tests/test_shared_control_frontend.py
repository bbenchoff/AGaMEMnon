"""Real-Yosys preservation and rejection for N4.1 shared controls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "agamemnon" / "synth" / "synth_pads.tcl"


def _yosys():
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for suffix in ("", ".exe"):
            candidate = Path(oss) / "bin" / ("yosys" + suffix)
            if candidate.is_file():
                return str(candidate)
    return shutil.which("yosys")


def _synth(tmp_path, source, name):
    yosys = _yosys()
    if not yosys:
        pytest.skip("yosys is unavailable")
    verilog = tmp_path / (name + ".v")
    output = tmp_path / (name + ".json")
    verilog.write_text(source, encoding="utf-8")
    env = dict(os.environ)
    oss = env.get("AGAMEMNON_OSS")
    if oss:
        env["YOSYSHQ_ROOT"] = oss + os.sep
        env["PATH"] = (
            str(Path(oss) / "bin") + os.pathsep +
            str(Path(oss) / "lib") + os.pathsep + env.get("PATH", "")
        )
    env["AGAMEMNON_YOSYS_TOP"] = "top"
    env["AGAMEMNON_YOSYS_JSON"] = str(output)
    result = subprocess.run(
        [yosys, "-q", "-c", str(SYNTH), str(verilog)],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    netlist = json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    return result, netlist


def _active_cells(netlist):
    return [
        cell for cell in netlist["modules"]["top"]["cells"].values()
        if cell["type"] == "$_DFF_PP0_"
    ]


STANDALONE = """
module top(input wire clk, arst, d, output reg q);
always @(posedge clk or posedge arst)
    if (arst) q <= 1'b0; else q <= d;
endmodule
"""

LUT_FED = """
module top(input wire clk, arst, a, b, output reg q);
always @(posedge clk or posedge arst)
    if (arst) q <= 1'b0; else q <= a ^ b;
endmodule
"""


@pytest.mark.parametrize("source", [STANDALONE, LUT_FED])
def test_bare_async_clear_is_preserved_exactly_through_synthesis(source, tmp_path):
    result, netlist = _synth(tmp_path, source, "preserve")
    assert result.returncode == 0, result.stdout + result.stderr
    cells = _active_cells(netlist)
    assert len(cells) == 1
    cell = cells[0]
    assert cell["attributes"]["AGRV2K_SHARED_CONTROL_MODE"] == \
        "ASYNC_CLEAR_POS_ZERO"
    assert set(cell["connections"]) == {"C", "D", "Q", "R"}
    assert all(len(cell["connections"][port]) == 1 for port in ("C", "D", "Q", "R"))
    if source == LUT_FED:
        assert any(other["type"] == "LUT" for other in netlist["modules"]["top"]["cells"].values())


@pytest.mark.parametrize(
    "source",
    [
        STANDALONE,
        STANDALONE.replace("clk, arst, d", "clock, reset_request, data")
        .replace("posedge clk", "posedge clock")
        .replace("posedge arst", "posedge reset_request")
        .replace("if (arst)", "if (reset_request)")
        .replace("else q <= d", "else q <= data"),
    ],
)
def test_frontend_shape_is_cell_and_net_renaming_invariant(source, tmp_path):
    result, netlist = _synth(tmp_path, source, "renamed")
    assert result.returncode == 0, result.stdout + result.stderr
    cell = _active_cells(netlist)[0]
    assert cell["type"] == "$_DFF_PP0_"
    assert cell["attributes"]["AGRV2K_SHARED_CONTROL_MODE"] == \
        "ASYNC_CLEAR_POS_ZERO"
    assert tuple(sorted(cell["connections"])) == ("C", "D", "Q", "R")


@pytest.mark.parametrize(
    "body",
    [
        "always @(posedge clk or posedge ctrl) if (ctrl) q <= 1'b1; else q <= d;",
        "always @(posedge clk or negedge ctrl) if (!ctrl) q <= 1'b0; else q <= d;",
        "always @(posedge clk) if (ctrl) q <= d;",
        "always @(posedge clk) if (ctrl) q <= 1'b0; else q <= d;",
        "always @(posedge clk or posedge ctrl) if (ctrl) q <= 1'b0; else if (en) q <= d;",
    ],
)
def test_other_control_polarity_value_enable_and_combined_forms_are_rejected(
        body, tmp_path):
    source = "module top(input clk, ctrl, en, d, output reg q); %s endmodule" % body
    result, netlist = _synth(tmp_path, source, "unsupported")
    assert netlist is None
    assert result.returncode != 0
    log = result.stdout + result.stderr
    assert "AGAMEMNON shared control: unsupported register control/polarity/value" in log
    assert "unsupported shared register control" in log
