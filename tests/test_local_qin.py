"""Cycle-level checks for observed enabled state across ordinary Qin lowering."""
import copy
import json

import pytest

from agamemnon.engine.qin_pack import lower_local_qin_feedback, permute_selffb_to_inputD


def settle(module, state, enable, data):
    values = {2: enable, 3: data, **state}
    pending = [c for c in module["cells"].values() if c["type"] == "LUT"]
    while pending:
        progress = False
        for cell in pending[:]:
            bits = cell["connections"]["I"]
            if any(isinstance(b, int) and b not in values for b in bits):
                continue
            index = sum((int(b) if isinstance(b, str) else values[b]) << i
                        for i, b in enumerate(bits))
            values[cell["connections"]["Q"][0]] = (int(cell["parameters"]["INIT"], 2) >> index) & 1
            pending.remove(cell)
            progress = True
        assert progress, "Combinational cycle or missing input"
    return values


@pytest.mark.parametrize("count", [1, 2, 3, 4])
@pytest.mark.parametrize("observer", ["top", "register"])
def test_enabled_state_preserves_preedge_output_and_downstream_latency(tmp_path, count, observer):
    cells = {}
    outputs = []
    for i in range(count):
        q, d, captured = 10 + i * 3, 11 + i * 3, 12 + i * 3
        # I0=old state, I1=enable, I2=data; output = enable ? data : old state.
        init = sum((((row >> 2) & 1) if row & 2 else row & 1) << row for row in range(16))
        cells[f"state_lut{i}"] = dict(type="LUT", parameters={"INIT": f"{init:016b}"},
            attributes={}, port_directions={"I": "input", "Q": "output"},
            connections={"I": [q, 2, 3, "0"], "Q": [d]})
        cells[f"state_ff{i}"] = dict(type="DFF", port_directions={"D": "input", "Q": "output"},
            connections={"D": [d], "Q": [q]})
        if observer == "register":
            cells[f"observer{i}"] = dict(type="DFF", port_directions={"D": "input", "Q": "output"},
                connections={"D": [q], "Q": [captured]})
        outputs.append(q if observer == "top" else captured)
    original = {"cells": cells, "ports": {"out": {"direction": "output", "bits": outputs}}}
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"modules": {"top": copy.deepcopy(original)}}))
    lower_local_qin_feedback(path)
    permute_selffb_to_inputD(path)
    lowered = json.loads(path.read_text())["modules"]["top"]
    states = [{c["connections"]["Q"][0]: 0 for c in module["cells"].values()
               if c["type"] == "DFF"} for module in (original, lowered)]
    for enable, data in [(0, 0), (1, 1), (0, 0), (0, 1), (1, 0), (0, 1), (1, 1)]:
        settled = [settle(m, s, enable, data) for m, s in zip((original, lowered), states)]
        observed = [[v[b] for b in m["ports"]["out"]["bits"]]
                    for m, v in zip((original, lowered), settled)]
        assert observed[0] == observed[1], "Lowering changed a pre-edge register observation"
        states = [{c["connections"]["Q"][0]: v[c["connections"]["D"][0]]
                   for c in m["cells"].values() if c["type"] == "DFF"}
                  for m, v in zip((original, lowered), settled)]
        assert states[0] == states[1], "Lowering changed downstream register latency"


def test_local_qin_all_lut_axes_and_consumers_survive_permutation(tmp_path):
    from agamemnon.engine.qin_pack import _perm_init
    for pin in range(4):
        data = {"modules": {"top": {"cells": {
            "lut": {"type": "LUT", "parameters": {"INIT": f"{0xb7e2:016b}"},
                    "connections": {"I": [10, 11, 12, 13], "Q": [20]}},
            "ff": {"type": "DFF", "connections": {"Q": [10+pin], "D": [20]}},
        }, "ports": {"q": {"direction": "output", "bits": [10+pin]}}}}}
        p = tmp_path / f"pin{pin}.json";p.write_text(json.dumps(data))
        lower_local_qin_feedback(p)
        lowered = json.loads(p.read_text())["modules"]["top"]
        assert lowered["ports"] == data["modules"]["top"]["ports"]
        lut = lowered["cells"]["lut"]
        assert lut["connections"]["I"][2] == 10+pin
        for assignment in range(16):
            index = sum(((assignment >> (net-10)) & 1) << i
                        for i, net in enumerate(lut["connections"]["I"]))
            assert (int(lut["parameters"]["INIT"], 2) >> index) & 1 == (0xb7e2 >> assignment) & 1


@pytest.mark.parametrize("fault", [None, "wrong_q", "wrong_pin", "no_tag", "unused_c", "live_f"])
def test_local_qin_routed_protocol_rejects_wrong_physical_shapes(fault):
    from agamemnon.engine.features.register_input import validate_module_register_inputs
    cell = dict(type="GENERIC_SLICE", parameters={"FF_USED": "1", "INIT": f"{0x0f0f:016b}"},
                attributes={"AGRV2K_REGISTER_INPUT_MODE": "LOCAL_QIN_I2", "agamemnon_local_qin_feedback": "1"},
                connections={"CLK": [2], "Q": [10], "F": [], "I": ["0", "0", 10, "0"]})
    module = {"cells": {"state": cell}, "netnames": {"clock": {"bits": [2]}, "q": {"bits": [10]}, "f": {"bits": [11]}}}
    if fault == "wrong_q": cell["connections"]["I"][2] = "1"
    if fault == "wrong_pin": cell["connections"]["I"] = ["0", "0", "0", 10]
    if fault == "no_tag": del cell["attributes"]["agamemnon_local_qin_feedback"]
    if fault == "unused_c": cell["parameters"]["INIT"] = f"{0xaaaa:016b}"
    if fault == "live_f": cell["connections"]["F"] = [11]
    if fault:
        with pytest.raises(SystemExit): validate_module_register_inputs(module)
    else:
        assert validate_module_register_inputs(module)["state"].mode == "LOCAL_QIN_I2"
