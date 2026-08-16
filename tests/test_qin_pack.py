import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

from agamemnon.engine.qin_pack import (
    expand_uniform_bram_init,
    permute_pad_inputs_high,
    permute_reads_to_inputD,
    permute_selffb_to_inputD,
    wrap_pad_dff_inputs,
    unwrap_bram_old_write_inputs,
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
    assert lut["attributes"]["agamemnon_direct_d_origin"] == "qin-pack-inferred-own-q"
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


def test_existing_direct_d_provenance_is_preserved(tmp_path):
    path = tmp_path / "feedback_explicit.json"
    data = _self_feedback_netlist()
    data["modules"]["top"]["cells"]["lut"]["attributes"] = {
        "agamemnon_direct_d_feedback": "1",
        "agamemnon_direct_d_origin": "explicit-qualified-footprint",
        "BEL": "X14Y11_SLICE4",
    }
    path.write_text(json.dumps(data), encoding="utf-8")

    permute_selffb_to_inputD(path)
    attributes = json.loads(path.read_text())["modules"]["top"]["cells"]["lut"]["attributes"]
    assert attributes["agamemnon_direct_d_origin"] == "explicit-qualified-footprint"
    assert attributes["BEL"] == "X14Y11_SLICE4"


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
    assert {cells[name]["attributes"]["agamemnon_direct_d_origin"]
            for name in ("lut", "lut2")} == {"qin-pack-inferred-own-q"}


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


@pytest.mark.parametrize(
    "pin,target",
    [("PIN_25", 1), ("PIN_26", 2), ("PIN_27", 2), ("PIN_28", 3)],
)
def test_left_pad_exact_pin_permutation_preserves_full_lut_truth(
        tmp_path, monkeypatch, pin, target):
    """Exact left input placement applies even when all LUT pins are pad-fed."""
    path = tmp_path / (pin + ".json")
    initial_inputs = [10, 11, 12, 13]
    initial_init = "0110100110010110"
    cells = {
        "$iopadmap$top.left": {
            "type": "GENERIC_IOB", "connections": {"O": [10]},
        },
        "top1": {"type": "GENERIC_IOB", "connections": {"O": [11]}},
        "top2": {"type": "GENERIC_IOB", "connections": {"O": [12]}},
        "top3": {"type": "GENERIC_IOB", "connections": {"O": [13]}},
        "lut": {
            "type": "LUT", "parameters": {"INIT": initial_init},
            "connections": {"I": list(initial_inputs), "Q": [14]},
        },
    }
    path.write_text(json.dumps({"modules": {"top": {"cells": cells}}}),
                    encoding="utf-8")
    monkeypatch.setenv("AGAMEMNON_PCF_JSON", json.dumps({"left": pin}))
    monkeypatch.setenv("AGAMEMNON_DATA", str(ROOT / "agamemnon" / "chipdb"))

    assert permute_pad_inputs_high(path) > 0
    lut = json.loads(path.read_text())["modules"]["top"]["cells"]["lut"]
    assert lut["connections"]["I"][target] == 10

    def evaluate(inputs, init, values):
        row = sum(values[net] << index for index, net in enumerate(inputs))
        return int(init[15 - row])

    for value in range(16):
        values = {net: (value >> index) & 1
                  for index, net in enumerate(initial_inputs)}
        assert evaluate(initial_inputs, initial_init, values) == evaluate(
            lut["connections"]["I"], lut["parameters"]["INIT"], values
        )
    assert permute_pad_inputs_high(path) == 0


def test_left_pad_exact_pin_collision_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "left_collision.json"
    cells = {
        "$iopadmap$top.a": {
            "type": "GENERIC_IOB", "connections": {"O": [10]},
        },
        "$iopadmap$top.b": {
            "type": "GENERIC_IOB", "connections": {"O": [11]},
        },
        "lut": {
            "type": "LUT", "parameters": {"INIT": "0" * 16},
            "connections": {"I": [10, 11, "0", "0"], "Q": [12]},
        },
    }
    path.write_text(json.dumps({"modules": {"top": {"cells": cells}}}),
                    encoding="utf-8")
    monkeypatch.setenv(
        "AGAMEMNON_PCF_JSON", json.dumps({"a": "PIN_26", "b": "PIN_27"})
    )
    monkeypatch.setenv("AGAMEMNON_DATA", str(ROOT / "agamemnon" / "chipdb"))
    with pytest.raises(SystemExit, match="same LUT target pin"):
        permute_pad_inputs_high(path)


def test_top_pad_exact_pin_permutation_uses_characterized_target(
        tmp_path, monkeypatch):
    path = tmp_path / "pin12.json"
    path.write_text(json.dumps({"modules": {"top": {"cells": {
        "$iopadmap$top.pin_in": {
            "type": "GENERIC_IOB", "connections": {"O": [10]},
        },
        "lut": {
            "type": "LUT", "parameters": {"INIT": "0101010101010101"},
            "connections": {"I": [10, "0", "0", "0"], "Q": [11]},
        },
    }}}}), encoding="utf-8")
    monkeypatch.setenv("AGAMEMNON_PCF_JSON", json.dumps({"pin_in": "PIN_12"}))
    monkeypatch.setenv("AGAMEMNON_DATA", str(ROOT / "agamemnon" / "chipdb"))

    assert permute_pad_inputs_high(path) == 1
    lut = json.loads(path.read_text())["modules"]["top"]["cells"]["lut"]
    assert lut["connections"]["I"][2] == 10
    # Inversion remains inversion after moving logical I[0] to physical I[2].
    for row in range(16):
        assert int(lut["parameters"]["INIT"][15 - row]) == 1 - ((row >> 2) & 1)


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


def test_bram_old_mode_write_input_emulation_is_bypassed(tmp_path):
    path = tmp_path / "bram_old.json"
    cells = {
        "src": {
            "type": "LUT", "port_directions": {"Q": "output"},
            "connections": {"Q": [10]},
        },
        "emulation_ff": {
            "type": "DFF",
            "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
            "connections": {"CLK": [2], "D": [10], "Q": [11]},
        },
        "bram": {
            "type": "ALTA_BRAM9K",
            "parameters": {"INIT_VAL": "1" * 9216},
            "port_directions": {"Clk0": "input", "WeA": "input"},
            "connections": {"Clk0": [2], "WeA": [11]},
        },
    }
    data = {"modules": {"top": {"cells": cells, "netnames": {
        "$auto$mem.cc:1645:emulate_read_first$1": {"bits": [11]},
    }}}}
    path.write_text(json.dumps(data), encoding="utf-8")

    assert unwrap_bram_old_write_inputs(path) == 1
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert cells["bram"]["connections"]["WeA"] == [10]
    assert "emulation_ff" not in cells
    assert unwrap_bram_old_write_inputs(path) == 0


def test_bram_input_bypass_requires_named_emulation_and_matching_clock(tmp_path):
    path = tmp_path / "bram_not_old.json"
    original = {"modules": {"top": {"cells": {
        "ff": {
            "type": "DFF",
            "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
            "connections": {"CLK": [3], "D": [10], "Q": [11]},
        },
        "bram": {
            "type": "ALTA_BRAM9K",
            "parameters": {"INIT_VAL": "1" * 9216},
            "port_directions": {"Clk0": "input", "WeA": "input"},
            "connections": {"Clk0": [2], "WeA": [11]},
        },
    }, "netnames": {
        "$auto$mem.cc:1645:emulate_read_first$1": {"bits": [11]},
    }}}}
    path.write_text(json.dumps(original), encoding="utf-8")

    assert unwrap_bram_old_write_inputs(path) == 0
    assert json.loads(path.read_text()) == original


def test_bram_input_bypass_leaves_patterned_initializer_topology_intact(tmp_path):
    path = tmp_path / "bram_patterned.json"
    original = {"modules": {"top": {"cells": {
        "ff": {
            "type": "DFF",
            "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
            "connections": {"CLK": [2], "D": [10], "Q": [11]},
        },
        "bram": {
            "type": "ALTA_BRAM9K",
            "parameters": {"INIT_VAL": "10" * 4608},
            "port_directions": {"Clk0": "input", "WeA": "input"},
            "connections": {"Clk0": [2], "WeA": [11]},
        },
    }, "netnames": {
        "$auto$mem.cc:1645:emulate_read_first$1": {"bits": [11]},
    }}}}
    path.write_text(json.dumps(original), encoding="utf-8")

    assert unwrap_bram_old_write_inputs(path) == 0
    assert json.loads(path.read_text()) == original


def test_unproven_bram_input_bypass_is_not_in_production_main():
    source = (ROOT / "agamemnon" / "engine" / "qin_pack.py").read_text(
        encoding="utf-8")
    main = source.split('if __name__ == "__main__":', 1)[1]
    assert "unwrap_bram_old_write_inputs(" not in main
    assert "production ``__main__`` path does not call it" in source


def test_uniform_narrow_bram_init_fills_only_unambiguous_physical_bits(tmp_path):
    path = tmp_path / "uniform_init.json"
    data = {"modules": {"top": {"cells": {
        "ones": {"type": "ALTA_BRAM9K", "parameters": {"INIT_VAL": "1x1x"}},
        "zeros": {"type": "ALTA_BRAM9K", "parameters": {"INIT_VAL": "x00x"}},
        "pattern": {"type": "ALTA_BRAM9K", "parameters": {"INIT_VAL": "10xx"}},
    }}}}
    path.write_text(json.dumps(data), encoding="utf-8")

    assert expand_uniform_bram_init(path) == 4
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert cells["ones"]["parameters"]["INIT_VAL"] == "1111"
    assert cells["zeros"]["parameters"]["INIT_VAL"] == "0000"
    assert cells["pattern"]["parameters"]["INIT_VAL"] == "10xx"
    assert expand_uniform_bram_init(path) == 0
