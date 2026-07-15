import json

from agamemnon.engine.qin_pack import (
    permute_pad_inputs_high,
    permute_reads_to_inputD,
    wrap_pad_dff_inputs,
)


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
