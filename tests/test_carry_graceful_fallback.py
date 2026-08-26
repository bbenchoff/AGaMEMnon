"""Dedicated carry is allocated per arithmetic chain, before generic lowering."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "agamemnon" / "synth" / "synth_pads.tcl"


MIXED_ADDERS = r"""
module top(
    input  [39:0] a40, b40,
    input  [23:0] a24, b24,
    input   [7:0] a8,  b8,
    output [39:0] y40,
    output [23:0] y24,
    output  [7:0] y8
);
    assign y40 = a40 + b40;
    assign y24 = a24 + b24;
    assign y8  = a8  + b8;
endmodule
"""

MIXED_COUNTERS = r"""
module top(input clk, output q40, q24, q8);
    reg [39:0] c40;
    reg [23:0] c24;
    reg  [7:0] c8;
    always @(posedge clk) begin
        c40 <= c40 + 1'b1;
        c24 <= c24 + 1'b1;
        c8  <= c8  + 1'b1;
    end
    assign q40 = c40[39];
    assign q24 = c24[23];
    assign q8  = c8[7];
endmodule
"""


def _yosys():
    if os.environ.get("AGAMEMNON_OSS"):
        for suffix in ("", ".exe"):
            candidate = Path(os.environ["AGAMEMNON_OSS"]) / "bin" / ("yosys" + suffix)
            if candidate.exists():
                return str(candidate)
    return shutil.which("yosys")


def _synth(tmp_path: Path, source_text: str, *, hard_carry: bool, explicit_top: bool = True):
    yosys = _yosys()
    if not yosys:
        pytest.skip("yosys is not available")
    source = tmp_path / "mixed.v"
    output = tmp_path / "mixed.json"
    source.write_text(source_text, encoding="utf-8")
    env = dict(os.environ)
    if hard_carry:
        env["AGAMEMNON_HW_CARRY"] = "1"
    else:
        env.pop("AGAMEMNON_HW_CARRY", None)
    env["AGAMEMNON_YOSYS_LUT_K"] = "4"
    env["AGAMEMNON_YOSYS_JSON"] = str(output)
    if explicit_top:
        env["AGAMEMNON_YOSYS_TOP"] = "top"
    else:
        env.pop("AGAMEMNON_YOSYS_TOP", None)
    result = subprocess.run(
        [yosys, "-q", "-c", str(SYNTH), str(source)],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, json.loads(output.read_text(encoding="utf-8")) if output.exists() else None


def _cell_types(netlist):
    return [cell["type"] for cell in netlist["modules"]["top"]["cells"].values()]


def test_mixed_carry_chains_use_one_qualified_chain_and_lut_fallback(tmp_path):
    result, netlist = _synth(tmp_path, MIXED_ADDERS, hard_carry=True)
    assert result.returncode == 0, result.stdout + result.stderr
    types = _cell_types(netlist)

    # The greatest eligible chain wins deterministically.  The 40-bit chain is
    # oversized and the additional 8-bit chain remains ordinary LUT logic.
    assert types.count("AG32_FA") == 24
    assert "LUT" in types


def test_oversized_chain_alone_degrades_instead_of_refusing(tmp_path):
    source = r"""
module top(input [39:0] a, b, output [39:0] y);
    assign y = a + b;
endmodule
"""
    result, netlist = _synth(tmp_path, source, hard_carry=True)
    assert result.returncode == 0, result.stdout + result.stderr
    types = _cell_types(netlist)
    assert "AG32_FA" not in types
    assert "LUT" in types


def test_multiple_short_chains_share_the_qualified_nine_site_footprint(tmp_path):
    source = r"""
module top(input [2:0] a, b, c, d, output [2:0] y0, y1);
    assign y0 = a + b;
    assign y1 = c + d;
endmodule
"""
    result, netlist = _synth(tmp_path, source, hard_carry=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _cell_types(netlist).count("AG32_FA") == 6


def test_disabled_carry_keeps_all_arithmetic_on_the_ordinary_path(tmp_path):
    result, netlist = _synth(tmp_path, MIXED_ADDERS, hard_carry=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AG32_FA" not in _cell_types(netlist)


def test_default_top_inference_never_synthesizes_a_blank_design(tmp_path):
    source = r"""
module top(input clk, output q);
    reg [7:0] state;
    always @(posedge clk) state <= state + 1'b1;
    assign q = state[7];
endmodule
"""
    result, netlist = _synth(
        tmp_path, source, hard_carry=False, explicit_top=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    types = _cell_types(netlist)
    assert types.count("DFF") == 8
    assert types.count("GENERIC_IOB") == 2


def test_mixed_counter_netlist_reaches_uarch_pack_without_global_carry_refusal(tmp_path):
    npr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not npr or not Path(npr).exists():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the agrv2k nextpnr build")
    result, netlist = _synth(tmp_path, MIXED_COUNTERS, hard_carry=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _cell_types(netlist).count("AG32_FA") == 24

    synth_json = tmp_path / "mixed.json"
    packed_json = tmp_path / "packed.json"
    devdb = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_tiered"
    pack_env = dict(os.environ)
    npr_runtime = pack_env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if npr_runtime:
        pack_env["PATH"] = npr_runtime + os.pathsep + pack_env.get("PATH", "")
    packed = subprocess.run(
        [npr, "--uarch", "agrv2k", "-o", f"chipdb={devdb}",
         "--json", str(synth_json), "--write", str(packed_json), "--pack-only"],
        cwd=ROOT, env=pack_env, text=True, capture_output=True, timeout=120,
    )
    log = packed.stdout + packed.stderr
    assert packed.returncode == 0, log
    assert "carry placement: 1 chain(s), 25 cells clustered in qualified relative shape" in log
    assert "dedicated carry requires" not in log
