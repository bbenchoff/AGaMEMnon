"""Experimental carry/reset fusion must preserve both SUM and live COUT."""
import json

import pytest

from test_uarch_carry_drc import CarryJson, _run


def reset_counter(const_axis, constant, active, reset_value, sum_axis, reset_axis=None):
    design = CarryJson()
    names = design.feedback_registered_chain(4)
    reset = design.net("reset_signal")
    design.cells["reset_source"] = dict(
        type="LUT", parameters={"K": "100", "INIT": "1010101010101010"},
        attributes={}, port_directions={"I": "input", "Q": "output"},
        connections={"I": [design.admitted_clock(), "0", "0", "0"], "Q": [reset]})
    if reset_axis is None:
        reset_axis = 1 - sum_axis
    truth = sum((reset_value if ((i >> reset_axis) & 1) == active
                 else (i >> sum_axis) & 1) << i for i in range(16))
    for index, name in enumerate(names):
        fa = design.cells[name]
        q = fa["connections"]["B"]
        fa["connections"][const_axis] = [str(constant)]
        fa["connections"]["B" if const_axis == "A" else "A"] = q
        inputs = ["0"] * 4
        inputs[sum_axis] = fa["connections"]["SUM"][0]
        inputs[reset_axis] = reset
        out = design.net("reset_result_" + str(index))
        design.cells["reset_lut_" + str(index)] = dict(
            type="LUT", parameters={"K": "100", "INIT": format(truth, "016b")},
            attributes={}, port_directions={"I": "input", "Q": "output"},
            connections={"I": inputs, "Q": [out]})
        design.cells["fb_ff_" + str(index)]["connections"]["D"] = [out]
    return design, names


@pytest.mark.parametrize("const_axis", ["A", "B"])
@pytest.mark.parametrize("constant", [0, 1])
@pytest.mark.parametrize("active", [0, 1])
@pytest.mark.parametrize("reset_value", [0, 1])
@pytest.mark.parametrize("sum_axis,reset_axis", [(0, 1), (1, 0), (2, 3), (3, 2)])
def test_reset_folds_only_into_sum_bank(tmp_path, monkeypatch, const_axis,
                                      constant, active, reset_value, sum_axis, reset_axis):
    monkeypatch.setenv("AGRV2K_CARRY_RESET_FUSION", "1")
    design, names = reset_counter(const_axis, constant, active, reset_value, sum_axis, reset_axis)
    design.external_user(design.cells[names[-1]]["connections"]["COUT"][0], name="carry_observer")
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    exporter = cells[names[-1] + "_CARRY_EXPORT"]
    assert exporter["connections"]["F"] == [cells["carry_observer_LC"]["connections"]["I"][0]]
    assert exporter["connections"]["CIN"] == cells[names[-1] + "_CARRY"]["connections"]["COUT"]
    for name in names:
        packed = cells[name + "_CARRY"]
        assert int(packed["parameters"]["FF_USED"], 2) == 1
        axis = 0 if const_axis == "A" else 1
        assert packed["connections"]["I"][axis] == cells["reset_source_LC"]["connections"]["F"][0]
        assert packed["connections"]["I"][1 - axis] == packed["connections"]["Q"][0]
        mask = int(packed["parameters"]["INIT"], 2)
        for row in range(16):
            a, b, carry, bank = ((row >> bit) & 1 for bit in range(4))
            reset = a if const_axis == "A" else b
            if const_axis == "A":
                a = constant
            else:
                b = constant
            expected = ((reset_value if reset == active else a ^ b ^ carry)
                        if bank else int(a + b + carry >= 2))
            assert (mask >> row) & 1 == expected, (name, row, hex(mask))
    assert not any(name.startswith("reset_lut_") or name.startswith("fb_ff_") for name in cells)


@pytest.mark.parametrize("flag", [None, "0", "", "true"])
def test_reset_fusion_requires_explicit_opt_in(tmp_path, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("AGRV2K_CARRY_RESET_FUSION", raising=False)
    else:
        monkeypatch.setenv("AGRV2K_CARRY_RESET_FUSION", flag)
    design, names = reset_counter("A", 0, 1, 0, 1)
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    assert all(int(cells[name + "_CARRY"]["parameters"]["FF_USED"], 2) == 0 for name in names)


@pytest.mark.parametrize("shape", ["sum_fanout", "reset_result_fanout", "lut_keep", "ff_keep",
                                   "fixed_lut", "extra_dependency", "dynamic_operands",
                                   "constant_operands", "ff_parameter", "constant_reset",
                                   "shared_carry_sums", "unknown_truth", "inverted_sum",
                                   "sum_only", "lut_parameter"])
def test_unsupported_reset_shape_stays_on_existing_path(tmp_path, monkeypatch, shape):
    monkeypatch.setenv("AGRV2K_CARRY_RESET_FUSION", "1")
    design, names = reset_counter("A", 0, 1, 0, 1)
    fa = design.cells[names[0]]
    lut = design.cells["reset_lut_0"]
    ff = design.cells["fb_ff_0"]
    if shape == "sum_fanout":
        design.external_user(fa["connections"]["SUM"][0])
    elif shape == "reset_result_fanout":
        design.external_user(lut["connections"]["Q"][0])
    elif shape == "lut_keep":
        lut["attributes"]["keep"] = "1"
    elif shape == "ff_keep":
        ff["attributes"]["keep"] = "1"
    elif shape == "fixed_lut":
        lut["attributes"]["BEL"] = "X14Y10_SLICE0"
    elif shape == "extra_dependency":
        lut["connections"]["I"][2] = design.admitted_clock()
        lut["parameters"]["INIT"] = format(0x4444 ^ 0xF0F0, "016b")
    elif shape == "dynamic_operands":
        fa["connections"]["A"] = [design.admitted_clock()]
    elif shape == "constant_operands":
        fa["connections"]["B"] = ["1"]
    elif shape == "ff_parameter":
        ff["parameters"]["INIT"] = "1"
    elif shape == "lut_parameter":
        lut["parameters"]["user_parameter"] = "1"
    elif shape == "unknown_truth":
        lut["parameters"]["INIT"] = "xxxxxxxxxxxxxxxx"
    elif shape == "inverted_sum":
        lut["parameters"]["INIT"] = format(0x1111, "016b")
    elif shape == "sum_only":
        lut["parameters"]["INIT"] = format(0xCCCC, "016b")
    elif shape == "constant_reset":
        lut["connections"]["I"][0] = "0"
    elif shape == "shared_carry_sums":
        second = design.cells[names[1]]
        second["connections"]["B"] = [design.admitted_clock()]
        lut["connections"]["I"] = [fa["connections"]["SUM"][0], second["connections"]["SUM"][0], "0", "0"]
        lut["parameters"]["INIT"] = format(0x8888, "016b")
        del design.cells["reset_lut_1"]
        del design.cells["fb_ff_1"]
    result, transcript, output = _run(tmp_path, design)
    assert result.returncode == 0, transcript
    cells = json.loads(output.read_text())["modules"]["top"]["cells"]
    assert int(cells[names[0] + "_CARRY"]["parameters"]["FF_USED"], 2) == 0


@pytest.mark.parametrize("conflict", [False, True])
def test_reset_capture_register_bel_participates_in_preflight(tmp_path, monkeypatch, conflict):
    monkeypatch.setenv("AGRV2K_CARRY_RESET_FUSION", "1")
    design, names = reset_counter("A", 1, 1, 0, 1)
    # Clock leaves are not ordinary data sources. Give the reset LUT a legal
    # fabric input so this placement check isolates the capture BEL contract.
    design.cells["reset_source"]["connections"]["I"][0] = design.cells["fb_ff_0"]["connections"]["Q"][0]
    design.cells[names[0]]["attributes"]["BEL"] = "X15Y1_SLICE5"
    design.cells["fb_ff_0"]["attributes"]["BEL"] = "X15Y1_SLICE6" if conflict else "X15Y1_SLICE5"
    result, transcript, output = _run(tmp_path, design, place=True)
    if conflict:
        assert result.returncode != 0
        assert "mutually inconsistent BEL constraints" in transcript
        assert "fused " not in transcript
    else:
        assert result.returncode == 0, transcript
        cells = json.loads(output.read_text())["modules"]["top"]["cells"]
        cell = cells[names[0] + "_CARRY"]
        assert int(cell["parameters"]["FF_USED"], 2) == 1
        assert cell["attributes"]["NEXTPNR_BEL"] == "X15Y1_SLICE5"
