import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

from agamemnon.engine.qin_pack import (
    expand_uniform_bram_init,
    externalize_multi_selffb,
    permute_pad_inputs_high,
    permute_reads_to_inputD,
    permute_selffb_to_inputD,
    split_shared_qualified_bram_inputs,
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


def test_externalize_multi_selffb_leaves_a_lone_feedback_cell_untouched(tmp_path):
    """The exact single-site qualified placement must be unaffected.

    Every retained golden that relies on ``permute_selffb_to_inputD`` pinning
    a lone own-Q cell to X14Y11_SLICE7 must see byte-identical qin_pack
    behaviour, so the externalizer is a strict no-op when there is at most
    one feedback loop.
    """
    path = tmp_path / "one_feedback_cell.json"
    original = _self_feedback_netlist()
    path.write_text(json.dumps(original), encoding="utf-8")

    assert externalize_multi_selffb(path) == 0
    assert json.loads(path.read_text()) == original
    # The untouched single-cell case still gets the exact qualified pin.
    assert permute_selffb_to_inputD(path) == 1
    lut = json.loads(path.read_text())["modules"]["top"]["cells"]["lut"]
    assert lut["attributes"]["BEL"] == "X14Y11_SLICE7"


def test_externalize_multi_selffb_breaks_loops_with_an_external_identity_lut(tmp_path):
    """Own-Q feedback beyond the qualified single site is routed externally.

    Mirrors the silicon-qualified 16-lane construction in
    docs/MCU_AHB_REGISTER_BANK.md ("Exact 16-bit held-scratch checkpoint",
    trial mcu-ahb-register-bank16-external-feedback-waited-silicon-20260815):
    an explicit combinational identity LUT sits between a state cell's own Q
    and its own next-state input, so the state LUT never reads its own Q
    directly and the four-site direct-D admission gate never has to see it.
    """
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

    assert externalize_multi_selffb(path) == 2
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]

    # Neither state LUT reads its own registered Q net directly any more.
    assert 5 not in cells["lut"]["connections"]["I"]
    assert 15 not in cells["lut2"]["connections"]["I"]

    buffers = {name: c for name, c in cells.items()
               if c.get("attributes", {}).get("agamemnon_external_selffb_buffer") == "1"}
    assert len(buffers) == 2
    for name, buf in buffers.items():
        assert buf["type"] == "LUT"
        assert buf["parameters"]["INIT"] == "1010101010101010"
        assert buf["connections"]["I"][0] in (5, 15)

    # The buffered nets close the loop: lut's own Q (5) feeds one buffer,
    # whose output now sits where lut's own-Q input used to be.
    buffer_out_of = {buf["connections"]["I"][0]: buf["connections"]["Q"][0]
                     for buf in buffers.values()}
    assert cells["lut"]["connections"]["I"][0] == buffer_out_of[5]
    assert cells["lut2"]["connections"]["I"][0] == buffer_out_of[15]

    # permute_selffb_to_inputD no longer sees any own-Q feedback: no tag,
    # no BEL, and the four-site admission gate is never invoked.
    assert permute_selffb_to_inputD(path) == 0
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert "agamemnon_direct_d_feedback" not in cells["lut"].get("attributes", {})
    assert "agamemnon_direct_d_feedback" not in cells["lut2"].get("attributes", {})
    assert "BEL" not in cells["lut"].get("attributes", {})
    assert "BEL" not in cells["lut2"].get("attributes", {})

    # permute_reads_to_inputD picks up each buffer output as an ordinary
    # cell-to-cell read and moves it onto the general I[3] corridor -- and
    # each buffer's own single input (itself a read of the original own-Q
    # net) is the same general corridor, so all four LUTs move: the two
    # state cells plus the two buffers.
    assert permute_reads_to_inputD(path) == 4
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert cells["lut"]["connections"]["I"][3] == buffer_out_of[5]
    assert cells["lut2"]["connections"]["I"][3] == buffer_out_of[15]


def test_externalize_multi_selffb_is_idempotent(tmp_path):
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

    assert externalize_multi_selffb(path) == 2
    assert externalize_multi_selffb(path) == 0


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


def test_shared_qualified_bram_inputs_receive_distinct_identity_drivers(tmp_path):
    path = tmp_path / "shared_bram_input.json"
    data = {"modules": {"top": {"cells": {
        "source": {
            "type": "DFF",
            "port_directions": {"D": "input", "Q": "output"},
            "connections": {"D": [4], "Q": [5]},
        },
        "mem": {
            "type": "ALTA_BRAM9K",
            "port_directions": {"AddressA": "input", "DataInA": "input"},
            "connections": {
                "AddressA": ["0", "0", "0", "0", 5],
                "DataInA": ["0", 5, 5],
            },
        },
    }}}}
    path.write_text(json.dumps(data), encoding="utf-8")

    assert split_shared_qualified_bram_inputs(path) == 1
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    memory = cells["mem"]["connections"]
    assert memory["AddressA"][4] == 5
    assert memory["DataInA"][2] == 5  # unconstrained padded lane is untouched
    assert memory["DataInA"][1] != 5
    buffer = next(
        cell for cell in cells.values()
        if cell.get("attributes", {}).get("agamemnon_bram_terminal_buffer") == "1"
    )
    assert buffer["parameters"]["INIT"] == "1010101010101010"
    assert buffer["connections"] == {
        "I": [5, "0", "0", "0"], "Q": [memory["DataInA"][1]]
    }
    assert split_shared_qualified_bram_inputs(path) == 0
