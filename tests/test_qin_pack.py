import json

from agamemnon.engine.qin_pack import permute_pad_inputs_high, wrap_pad_dff_inputs


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
