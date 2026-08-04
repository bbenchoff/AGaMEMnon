import json

from agamemnon.engine.qin_pack import (
    permute_pad_inputs_high,
    permute_reads_to_inputD,
    permute_selffb_to_inputD,
    wrap_pad_dff_inputs,
)


def _self_feedback_netlist(extra_input="0"):
    return {"modules": {"top": {"cells": {
        "lut": {
            "type": "LUT", "parameters": {"INIT": "0101010101010101"},
            "attributes": {},
            "connections": {"I": [5, extra_input, "0", "0"], "Q": [6]},
        },
        "ff": {"type": "DFF", "connections": {"D": [6], "Q": [5]}},
    }}}}


def test_self_feedback_is_lowered_to_direct_input_d(tmp_path):
    path = tmp_path / "feedback.json"
    path.write_text(json.dumps(_self_feedback_netlist()), encoding="utf-8")

    assert permute_selffb_to_inputD(path) == 1
    lut = json.loads(path.read_text())["modules"]["top"]["cells"]["lut"]
    assert lut["connections"]["I"] == ["0", "0", "0", 5]
    assert lut["parameters"]["INIT"] == "0000000011111111"
    assert lut["attributes"]["agamemnon_direct_d_feedback"] == "1"
    assert lut["attributes"]["BEL"] == "X14Y11_SLICE7"
    assert permute_selffb_to_inputD(path) == 0


def test_single_direct_d_feedback_observes_lut_f_but_keeps_q_local(tmp_path):
    path = tmp_path / "feedback_observed.json"
    data = _self_feedback_netlist()
    data["modules"]["top"]["cells"]["observer"] = {
        "type": "MCU_DOUT",
        "port_directions": {"DOUT": "input"},
        "connections": {"DOUT": [5]},
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    assert permute_selffb_to_inputD(path) == 1
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert cells["lut"]["connections"]["I"][3] == 5
    assert cells["observer"]["connections"]["DOUT"] == [6]
    assert cells["lut"]["attributes"]["agamemnon_direct_d_observe_f"] == "1"


def test_multiple_direct_d_feedback_cells_are_not_auto_placed(tmp_path):
    path = tmp_path / "two_feedback_cells.json"
    data = _self_feedback_netlist()
    cells = data["modules"]["top"]["cells"]
    cells["lut2"] = {
        "type": "LUT", "parameters": {"INIT": "0101010101010101"},
        "attributes": {},
        "connections": {"I": [15, "0", "0", "0"], "Q": [16]},
    }
    cells["ff2"] = {"type": "DFF", "connections": {"D": [16], "Q": [15]}}
    path.write_text(json.dumps(data), encoding="utf-8")

    assert permute_selffb_to_inputD(path) == 2
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert "BEL" not in cells["lut"].get("attributes", {})
    assert "BEL" not in cells["lut2"].get("attributes", {})


def test_other_cell_read_does_not_displace_direct_d_feedback(tmp_path):
    path = tmp_path / "feedback_with_read.json"
    data = _self_feedback_netlist(extra_input=8)
    data["modules"]["top"]["cells"]["producer"] = {
        "type": "LUT", "connections": {"I": ["0", "0", "0", "0"], "Q": [8]},
        "parameters": {"INIT": "0000000000000000"},
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    assert permute_selffb_to_inputD(path) == 1
    assert permute_reads_to_inputD(path) == 0
    lut = json.loads(path.read_text())["modules"]["top"]["cells"]["lut"]
    assert lut["connections"]["I"][3] == 5


def test_registered_pad_input_is_wrapped_and_moved_to_input_d(tmp_path):
    path = tmp_path / "netlist.json"
    path.write_text(json.dumps({"modules": {"top": {"cells": {
        "pad": {
            "type": "GENERIC_IOB", "parameters": {}, "attributes": {},
            "port_directions": {"O": "output", "PAD": "inout"},
            "connections": {"O": [2], "PAD": [3]},
        },
        "ff": {
            "type": "DFF", "parameters": {}, "attributes": {},
            "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
            "connections": {"CLK": [4], "D": [2], "Q": [5]},
        },
    }}}}), encoding="utf-8")

    assert wrap_pad_dff_inputs(path) == 1
    assert permute_pad_inputs_high(path) == 1
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    lut = next(c for c in cells.values()
               if c.get("attributes", {}).get("agamemnon_registered_pad_input") == "1")
    assert lut["connections"]["I"] == ["0", "0", "0", 2]
    assert cells["ff"]["connections"]["D"] == lut["connections"]["Q"]

    # The INIT permutation preserves identity of the physical pad now on I[3].
    init = lut["parameters"]["INIT"]
    for row in range(16):
        assert int(init[15 - row]) == ((row >> 3) & 1)


def test_non_pad_dff_is_unchanged(tmp_path):
    path = tmp_path / "netlist.json"
    original = {"modules": {"top": {"cells": {
        "ff": {"type": "DFF", "connections": {"CLK": [2], "D": [3], "Q": [4]}}
    }}}}
    path.write_text(json.dumps(original), encoding="utf-8")
    assert wrap_pad_dff_inputs(path) == 0
    assert json.loads(path.read_text()) == original


def test_existing_pad_lut_gets_explicit_second_sync_stage(tmp_path):
    path = tmp_path / "sync.json"
    path.write_text(json.dumps({"modules": {"top": {"cells": {
        "pad": {"type": "GENERIC_IOB", "connections": {"O": [10]}},
        "pad_lut": {"type": "LUT", "attributes": {},
                    "parameters": {"INIT": "1010101010101010"},
                    "connections": {"I": [10, "0", "0", "0"], "Q": [11]}},
        "sync0": {"type": "DFF", "connections": {"D": [11], "Q": [12]}},
        "sync1": {"type": "DFF", "connections": {"D": [12], "Q": [13]}},
    }}}}), encoding="utf-8")

    assert wrap_pad_dff_inputs(path) == 1
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert cells["pad_lut"]["attributes"]["agamemnon_pad_sync_stage"] == "stage1"
    stage2 = [c for c in cells.values()
              if c.get("attributes", {}).get("agamemnon_pad_sync_stage") == "stage2"]
    assert len(stage2) == 1
    assert cells["sync1"]["connections"]["D"] == stage2[0]["connections"]["Q"]


def test_carry_endpoint_read_is_moved_to_input_d(tmp_path):
    path = tmp_path / "netlist.json"
    path.write_text(json.dumps({"modules": {"top": {"cells": {
        "carry": {
            "type": "AG32_FA",
            "connections": {"A": [2], "B": [3], "CIN": [4],
                            "SUM": [5], "COUT": [6]},
        },
        "consumer": {
            "type": "LUT", "parameters": {"INIT": "1010101010101010"},
            "connections": {"I": [6, "0", "0", "0"], "Q": [7]},
        },
    }}}}), encoding="utf-8")

    assert permute_reads_to_inputD(path) == 1
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert cells["consumer"]["connections"]["I"] == ["0", "0", "0", 6]


def test_carry_endpoint_direct_dff_is_wrapped_then_moved(tmp_path):
    path = tmp_path / "netlist.json"
    path.write_text(json.dumps({"modules": {"top": {"cells": {
        "carry": {
            "type": "AG32_FA",
            "connections": {"A": [2], "B": [3], "CIN": [4],
                            "SUM": [5], "COUT": [6]},
        },
        "ff": {
            "type": "DFF",
            "connections": {"CLK": [7], "D": [6], "Q": [8]},
        },
    }}}}), encoding="utf-8")

    assert wrap_pad_dff_inputs(path) == 1
    assert permute_reads_to_inputD(path) == 1
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    lut = next(c for c in cells.values() if c.get("type") == "LUT")
    assert lut["connections"]["I"] == ["0", "0", "0", 6]
    assert cells["ff"]["connections"]["D"] == lut["connections"]["Q"]
