"""Exact pre-qin DFFE fallback: structure, rejection, and temporal behaviour."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "selective_enable", ROOT / "agamemnon" / "synth" / "selective_enable.py")
selective_enable = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selective_enable)


def _dffe(en, d, q, *, attrs=None):
    return {"type": "DFFE", "parameters": {"INIT": "0"},
            "attributes": dict(attrs or {}),
            "connections": {"CLK": [1], "EN": [en], "D": [d], "Q": [q]}}


def _document():
    return {"modules": {"top": {"ports": {}, "netnames": {}, "cells": {
        "keep": _dffe(10, 20, 30, attrs={"USER": "kept"}),
        "lower": _dffe(11, 21, 31, attrs={
            "AGRV2K_SHARED_CONTROL_MODE": "CLOCK_ENABLE_POS",
            "AGRV2K_CLOCK_ENABLE_NET": "en11",
        }),
    }}}}


def test_stamp_is_stable_exact_and_does_not_touch_non_dffe():
    document = _document()
    document["modules"]["top"]["cells"]["other"] = {"type": "DFF", "attributes": {"X": "1"}}
    counts = selective_enable.stamp_enable_groups(document)
    expected_keep = selective_enable.enable_group_id("top", 10)
    expected_lower = selective_enable.enable_group_id("top", 11)
    assert counts == {expected_keep: 1, expected_lower: 1}
    cells = document["modules"]["top"]["cells"]
    assert cells["keep"]["attributes"][selective_enable.ENABLE_GROUP_ATTRIBUTE] == expected_keep
    assert cells["other"] == {"type": "DFF", "attributes": {"X": "1"}}


def test_lower_one_group_uses_packable_lut_and_preserves_other_dffe():
    document = _document()
    selective_enable.stamp_enable_groups(document)
    before = copy.deepcopy(document["modules"]["top"]["cells"]["keep"])
    group_id = selective_enable.enable_group_id("top", 11)
    report = selective_enable.lower_enable_group_ids(document, [group_id])
    cells = document["modules"]["top"]["cells"]
    assert report == {group_id: 1}
    assert cells["keep"] == before
    assert cells["lower"]["type"] == "DFF"
    assert cells["lower"]["connections"] == {"CLK": [1], "D": [32], "Q": [31]}
    assert cells["lower"]["port_directions"] == {"CLK": "input", "D": "input", "Q": "output"}
    assert cells["lower"]["parameters"] == {"INIT": "0"}
    assert not (set(cells["lower"]["attributes"]) & selective_enable.NATIVE_ENABLE_ATTRIBUTES)
    hold = cells["lower$enable_hold"]
    assert hold["type"] == "LUT"
    assert hold["parameters"]["INIT"] == "1100101011001010"  # 0xCACA
    assert hold["connections"] == {"I": [31, 21, 11, "0"], "Q": [32]}
    assert hold["port_directions"] == {"I": "input", "Q": "output"}


@pytest.mark.parametrize("constant", ["0", "1"])
def test_constant_d_is_stamped_lowered_and_has_the_same_temporal_relation(constant):
    document = _document()
    document["modules"]["top"]["cells"]["lower"]["connections"]["D"] = [constant]
    document["modules"]["top"]["cells"]["lower"]["attributes"]["src"] = "sticky.v:7"
    group_id = selective_enable.enable_group_id("top", 11)
    assert selective_enable.stamp_enable_groups(document)[group_id] == 1
    assert selective_enable.lower_enable_group_ids(document, [group_id]) == {group_id: 1}
    cells = document["modules"]["top"]["cells"]
    hold = cells["lower$enable_hold"]
    assert hold["connections"]["I"] == [31, constant, 11, "0"]
    assert hold["attributes"] == {"src": "sticky.v:7"}
    init = int(hold["parameters"]["INIT"], 2)
    for q in (0, 1):
        for en in (0, 1):
            observed = (init >> (q | ((constant == "1") << 1) | (en << 2))) & 1
            assert observed == (int(constant) if en else q)


def test_constant_enable_is_not_a_native_group_candidate():
    document = _document()
    document["modules"]["top"]["cells"]["lower"]["connections"]["EN"] = ["1"]
    counts = selective_enable.stamp_enable_groups(document)
    assert selective_enable.enable_group_id("top", 11) not in counts
    assert selective_enable.ENABLE_GROUP_ATTRIBUTE not in document["modules"]["top"]["cells"]["lower"]["attributes"]


@pytest.mark.parametrize("q,d,en", [(0, 0, 0), (0, 1, 0), (1, 0, 0), (1, 1, 0),
                                      (0, 0, 1), (0, 1, 1), (1, 0, 1), (1, 1, 1)])
def test_hold_lut_is_temporally_equivalent_to_dffe_transition(q, d, en):
    # This is the actual transition relation after frontend reset lowering:
    # whatever reset priority produced old_d, DFFE is EN ? old_d : Q.
    init = 0xCACA
    index = q | (d << 1) | (en << 2)
    lowered_next_q = (init >> index) & 1
    dffe_next_q = d if en else q
    assert lowered_next_q == dffe_next_q


def test_hold_lut_temporal_equivalence_with_pre_lowered_reset_data(tmp_path):
    """Run the DFFE and generated DFF/LUT transition relations in a simulator."""
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iverilog or not vvp:
        pytest.skip("iverilog and vvp are required")
    source = tmp_path / "equiv.v"
    source.write_text("""
module reference(input clk, rst, en, d, output reg q);
  initial q = 0;
  wire old_d = rst ? 1'b1 : d; // reset value/priority already lowered into D
  always @(posedge clk) if (en) q <= old_d;
endmodule
module candidate(input clk, rst, en, d, output reg q);
  initial q = 0;
  wire old_d = rst ? 1'b1 : d;
  wire [3:0] i = {1'b0, en, old_d, q};
  localparam [15:0] HOLD_INIT = 16'hCACA;
  wire hold_d = HOLD_INIT[i];
  always @(posedge clk) q <= hold_d;
endmodule
module bench;
  reg clk=0, rst=0, en=0, d=0; wire a,b;
  reference r(clk,rst,en,d,a); candidate c(clk,rst,en,d,b);
  always #1 clk=~clk;
  integer rv, ev, dv;
  initial begin
    for (rv=0; rv<2; rv=rv+1) for (ev=0; ev<2; ev=ev+1)
      for (dv=0; dv<2; dv=dv+1) begin
        @(negedge clk); rst=rv; en=ev; d=dv;
        @(posedge clk); #0; if (a !== b) $fatal(1, "mismatch");
      end
    $finish;
  end
endmodule
""", encoding="utf-8")
    image = tmp_path / "equiv.out"
    compile_result = subprocess.run([iverilog, "-g2012", "-o", str(image), str(source)],
                                    text=True, capture_output=True, timeout=30)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    run_result = subprocess.run([vvp, str(image)], text=True, capture_output=True, timeout=30)
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr


def test_rejects_unmatched_or_stale_group_without_name_guessing(tmp_path):
    document = _document()
    selective_enable.stamp_enable_groups(document)
    unknown = "0" * 16
    with pytest.raises(selective_enable.SelectiveEnableError, match="not found"):
        selective_enable.lower_enable_group_ids(document, [unknown])
    cell = document["modules"]["top"]["cells"]["lower"]
    cell["attributes"][selective_enable.ENABLE_GROUP_ATTRIBUTE] = "1" * 16
    with pytest.raises(selective_enable.SelectiveEnableError, match="stale or conflicting"):
        selective_enable.lower_enable_group_ids(document, ["1" * 16])
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")
    with pytest.raises(selective_enable.SelectiveEnableError, match="not found"):
        selective_enable.lower_infeasible_groups(source, [unknown], tmp_path / "out.json")


def test_file_adapter_uses_archived_group_ids_and_keeps_archive(tmp_path):
    document = _document()
    selective_enable.stamp_enable_groups(document)
    source = tmp_path / "post_synth_pre_qin.json"
    retry = tmp_path / "retry.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    group_id = selective_enable.enable_group_id("top", 11)
    assert selective_enable.lower_infeasible_groups(source, [group_id], retry) == {group_id: 1}
    archived = json.loads(source.read_text(encoding="utf-8"))
    lowered = json.loads(retry.read_text(encoding="utf-8"))
    assert archived["modules"]["top"]["cells"]["lower"]["type"] == "DFFE"
    assert lowered["modules"]["top"]["cells"]["lower"]["type"] == "DFF"


def test_lowered_observed_d_path_survives_qin_pack(tmp_path):
    """Run the real pre-nextpnr pass on the emitted, direction-complete JSON."""
    document = _document()
    selective_enable.stamp_enable_groups(document)
    group_id = selective_enable.enable_group_id("top", 11)
    selective_enable.lower_enable_group_ids(document, [group_id])
    path = tmp_path / "retry.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    result = subprocess.run([sys.executable, str(ROOT / "agamemnon" / "engine" / "qin_pack.py"), str(path)],
                            cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    lowered = json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    # qin may move the feedback LUT input and permute its INIT, but it must
    # retain the observable DFF D edge and must parse the explicit directions.
    assert lowered["lower"]["connections"]["D"] == [32]
    assert lowered["lower"]["port_directions"] == {"CLK": "input", "D": "input", "Q": "output"}
    assert lowered["lower$enable_hold"]["port_directions"] == {"I": "input", "Q": "output"}
