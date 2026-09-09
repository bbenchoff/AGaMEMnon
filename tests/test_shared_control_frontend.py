"""Real-Yosys lowering, preservation, and rejection for shared controls."""

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


def _iverilog():
    return shutil.which("iverilog")


def _synth(tmp_path, source, name, *, native_enable=False, mince=None,
           srst_recovery=None):
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
    if native_enable:
        env["AGRV2K_SHARED_CONTROL_ENABLE"] = "1"
        env["AGAMEMNON_INTERNAL_PORTS"] = "1"
        # Unit tests exercising native recovery opt into the candidate form;
        # production direct synthesis defaults to legacy SRST lowering.
        if srst_recovery is None:
            srst_recovery = 1
    if mince is not None:
        env["AGRV2K_SHARED_CONTROL_MINCE"] = str(mince)
    if srst_recovery is not None:
        env["AGRV2K_SHARED_CONTROL_SRST_RECOVERY"] = str(srst_recovery)
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


def _plain_cells(netlist):
    return [
        cell for cell in netlist["modules"]["top"]["cells"].values()
        if cell["type"] == "DFF"
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


@pytest.mark.parametrize("body", [
    "always @(posedge clk) if (ctrl) q <= d;",
    "always @(posedge clk) if (!ctrl) q <= d;",
    "always @(posedge clk) if (ctrl) q <= 1'b0; else q <= d;",
    "always @(posedge clk) if (ctrl) q <= 1'b1; else q <= d;",
    "always @(posedge clk) if (ctrl) q <= 1'b0; else if (en) q <= d;",
])
def test_enable_and_synchronous_reset_lower_to_plain_ff_d_path(body, tmp_path):
    source = "module top(input clk, ctrl, en, d, output reg q); %s endmodule" % body
    result, netlist = _synth(tmp_path, source, "lowered")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_plain_cells(netlist)) == 1
    assert not _active_cells(netlist)
    cells = netlist["modules"]["top"]["cells"].values()
    assert all("AGRV2K_SHARED_CONTROL_MODE" not in cell.get("attributes", {})
               for cell in cells)
    assert any(cell["type"] == "LUT" for cell in cells)


@pytest.mark.parametrize("body", [
    "always @(negedge clk) if (ctrl) q <= d;",
    "always @(posedge clk or posedge ctrl) if (ctrl) q <= 1'b1; else q <= d;",
    "always @(posedge clk or negedge ctrl) if (!ctrl) q <= 1'b0; else q <= d;",
    "always @(posedge clk or posedge ctrl) if (ctrl) q <= 1'b0; else if (en) q <= d;",
])
def test_unsupported_asynchronous_control_forms_remain_rejected(body, tmp_path):
    source = "module top(input clk, ctrl, en, d, output reg q); %s endmodule" % body
    result, netlist = _synth(tmp_path, source, "unsupported")
    assert netlist is None
    assert result.returncode != 0
    log = result.stdout + result.stderr
    assert "AGAMEMNON shared control: unsupported register control/polarity/value" in log
    assert "unsupported shared register control" in log


RESET_ENABLE_PRIORITY = """
module top(clk, rst, en, d, q);
input wire clk, rst, en;
input wire [7:0] d;
output reg [7:0] q;
always @(posedge clk) begin
    // Reset first: reset must win even when enable is low.
    if (rst) q[0] <= 1'b0; else if (en) q[0] <= d[0];
    if (rst) q[1] <= 1'b1; else if (en) q[1] <= d[1];
    if (rst) q[2] <= 1'b0; else if (en) q[2] <= d[2];
    if (rst) q[3] <= 1'b1; else if (en) q[3] <= d[3];
    // Enable first: reset is sampled only while enable is asserted.
    if (en) q[4] <= rst ? 1'b0 : d[4];
    if (en) q[5] <= rst ? 1'b1 : d[5];
    if (en) q[6] <= rst ? 1'b0 : d[6];
    if (en) q[7] <= rst ? 1'b1 : d[7];
end
endmodule
"""


SRST_RECOVERY_BANK = """
module top(input wire clk, rst, en, input wire [7:0] d, output reg [7:0] q);
always @(posedge clk) begin
    if (rst) q[0] <= 1'b0; else if (en) q[0] <= d[0];
    if (rst) q[1] <= 1'b0; else if (en) q[1] <= d[1];
    if (rst) q[2] <= 1'b0; else if (en) q[2] <= d[2];
    if (rst) q[3] <= 1'b0; else if (en) q[3] <= d[3];
    if (rst) q[4] <= 1'b0; else if (en) q[4] <= d[4];
    if (rst) q[5] <= 1'b0; else if (en) q[5] <= d[5];
    if (rst) q[6] <= 1'b0; else if (en) q[6] <= d[6];
    if (rst) q[7] <= 1'b0; else if (en) q[7] <= d[7];
end
endmodule
"""


def test_srst_recovery_toggle_off_retains_legacy_native_lowering_bytes(tmp_path):
    """Toggle 0 must leave SRST forms on the established soft fallback path."""
    first, first_netlist = _synth(
        tmp_path, SRST_RECOVERY_BANK, "legacy_srst", native_enable=True,
        mince=2, srst_recovery=0,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    legacy_bytes = (tmp_path / "legacy_srst.json").read_bytes()
    second, second_netlist = _synth(
        tmp_path, SRST_RECOVERY_BANK, "legacy_srst", native_enable=True,
        mince=2, srst_recovery=0,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert (tmp_path / "legacy_srst.json").read_bytes() == legacy_bytes
    assert first_netlist == second_netlist
    assert not [cell for cell in first_netlist["modules"]["top"]["cells"].values()
                if cell["type"] == "DFFE"]

    recovered, recovered_netlist = _synth(
        tmp_path, SRST_RECOVERY_BANK, "recovered_srst", native_enable=True,
        mince=2, srst_recovery=1,
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    recovered_dffes = [cell for cell in recovered_netlist["modules"]["top"]["cells"].values()
                       if cell["type"] == "DFFE"]
    assert len(recovered_dffes) == 8
    assert all(cell.get("attributes", {}).get("AGRV2K_SHARED_CONTROL_MODE")
               == "CLOCK_ENABLE_POS" for cell in recovered_dffes)


@pytest.mark.parametrize("value", ["", "2", "yes", "-1"])
def test_srst_recovery_rejects_non_boolean_toggle(tmp_path, value):
    result, netlist = _synth(
        tmp_path, SRST_RECOVERY_BANK, "bad_recovery", native_enable=True,
        srst_recovery=value,
    )
    assert netlist is None
    assert result.returncode != 0
    assert "AGRV2K_SHARED_CONTROL_SRST_RECOVERY must be 0 or 1" in (
        result.stdout + result.stderr
    )


@pytest.mark.parametrize("mince", [2, 4, 8])
def test_native_enable_reset_lowering_keeps_only_final_dffe_tags(
        tmp_path, mince):
    """Exercise reset values and both reset/enable priority forms.

    The threshold intentionally changes resource selection, so this test does
    not bake in a particular cell count.  It instead checks the backend
    contract: no clock-enable tag may survive on a soft-lowered plain DFF.
    """
    result, netlist = _synth(
        tmp_path, RESET_ENABLE_PRIORITY, "priority_%d" % mince,
        native_enable=True, mince=mince,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cells = netlist["modules"]["top"]["cells"].values()
    tagged = [
        cell for cell in cells
        if cell.get("attributes", {}).get("AGRV2K_SHARED_CONTROL_MODE")
        == "CLOCK_ENABLE_POS"
    ]
    assert all(cell["type"] == "DFFE" for cell in tagged)
    assert all(set(cell["connections"]) == {"CLK", "D", "EN", "Q"}
               for cell in tagged)


def test_native_enable_rejects_invalid_mince(tmp_path):
    result, netlist = _synth(
        tmp_path, RESET_ENABLE_PRIORITY, "bad_mince",
        native_enable=True, mince=0,
    )
    assert netlist is None
    assert result.returncode != 0
    assert "AGRV2K_SHARED_CONTROL_MINCE must be a positive integer" in (
        result.stdout + result.stderr
    )


def test_native_enable_reset_priority_is_temporally_equivalent(tmp_path):
    """Exhaustively replay reset/enable/data combinations through both forms.

    This compares the native-enable netlist against the source transition
    relation.  It covers both reset values and the reset-first/enable-first
    distinction over every input combination after a defined reset edge.
    """
    iverilog = _iverilog()
    yosys = _yosys()
    if not iverilog or not yosys:
        pytest.skip("yosys and iverilog are required")
    result, netlist = _synth(
        tmp_path, RESET_ENABLE_PRIORITY, "temporal", native_enable=True,
        mince=2,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert netlist is not None

    candidate = tmp_path / "candidate.v"
    prims = ROOT / "agamemnon" / "synth" / "prims_control.v"
    convert = subprocess.run(
        [yosys, "-q", "-p", "read_json %s; delete m:DFFE; read_verilog %s; write_verilog %s" % (
            tmp_path / "temporal.json", prims, candidate,
        )],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    assert convert.returncode == 0, convert.stdout + convert.stderr

    reference = tmp_path / "reference.v"
    reference.write_text(
        RESET_ENABLE_PRIORITY.replace("module top", "module golden"),
        encoding="utf-8",
    )
    bench = tmp_path / "bench.v"
    bench.write_text("""
module LUT #(parameter [15:0] INIT = 0, parameter K = 4) (input [3:0] I, output Q);
  assign Q = INIT[I];
endmodule
module DFF(input CLK, D, output reg Q);
  initial Q = 1'b0;
  always @(posedge CLK) Q <= D;
endmodule
module bench;
  reg clk = 0, rst, en; reg [7:0] d;
  wire [7:0] expected, actual;
  golden reference(.clk(clk), .rst(rst), .en(en), .d(d), .q(expected));
  top candidate(.clk(clk), .rst(rst), .en(en), .d(d), .q(actual));
  always #5 clk = ~clk;
  integer r, e, value;
  initial begin
    rst = 1; en = 0; d = 0; @(posedge clk); #1;
    if (expected !== actual) $fatal(1, "defined reset differs");
    for (r = 0; r < 2; r = r + 1)
      for (e = 0; e < 2; e = e + 1)
        for (value = 0; value < 256; value = value + 1) begin
          @(negedge clk); rst = r; en = e; d = value[7:0];
          @(posedge clk); #1;
          if (expected !== actual)
            $fatal(1, "mismatch rst=%0d en=%0d d=%h expected=%h actual=%h",
                   r, e, value[7:0], expected, actual);
        end
    $finish;
  end
endmodule
""", encoding="utf-8")
    simulation = subprocess.run(
        [iverilog, "-g2012", "-o", str(tmp_path / "sim"), str(reference),
         str(candidate), str(bench)],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    assert simulation.returncode == 0, simulation.stdout + simulation.stderr
    run = subprocess.run(
        [str(tmp_path / "sim")], cwd=ROOT, text=True, capture_output=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
