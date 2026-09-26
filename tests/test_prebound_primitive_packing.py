"""Imported physical bindings survive replacement of primitive cells."""
import json

import pytest

import test_uarch_register_input_legality as support


@pytest.mark.parametrize("shape", ["lut", "ff", "fused_lut", "fused_ff", "separate"])
def test_packing_preserves_bound_primitive_location_and_strength(tmp_path, shape):
    lut_bel, ff_bel = "X14Y11_SLICE0", "X14Y11_SLICE1"
    cells = {}
    if shape != "ff":
        cells["logic"] = support._lut("logic", 0, ("x",) * 4, 20)
        if shape in ("lut", "fused_lut", "separate"):
            cells["logic"]["attributes"].update(
                NEXTPNR_BEL=lut_bel, BEL_STRENGTH=format(5, "032b"))
    if shape != "lut":
        cells["state"] = support._raw_dff(
            "state", 2, "0" if shape == "ff" else 20, 21,
            bel=ff_bel if shape in ("ff", "fused_ff", "separate") else None)
    result, log, output = support._run(
        tmp_path, shape, support._design(cells, {"data": 20, "q": 21}),
        "--no-route", "--placer", "heap", "--seed", "1")
    assert result.returncode == 0, log
    packed = json.loads(output.read_text())["modules"]["top"]["cells"]
    expected = {}
    if shape in ("lut", "fused_lut", "separate"):
        expected["logic_LC"] = lut_bel
    if shape in ("ff", "separate"):
        expected["state_DFFLC"] = ff_bel
    if shape == "fused_ff":
        expected["logic_LC"] = ff_bel
    for name, bel in expected.items():
        assert packed[name]["attributes"]["NEXTPNR_BEL"] == bel
        assert int(packed[name]["attributes"]["BEL_STRENGTH"], 2) == 5
    if shape.startswith("fused"):
        assert int(packed["logic_LC"]["parameters"]["FF_USED"], 2) == 1
        assert "state_DFFLC" not in packed
    if shape == "separate":
        assert int(packed["logic_LC"]["parameters"]["FF_USED"], 2) == 0
