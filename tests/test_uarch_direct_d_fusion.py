"""Raw Qin-shaped LUT/DFF fusion must preserve external F observations."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_uarch_register_input_legality import _design, _lut, _raw_dff, _run


def _observed_feedback(count=1):
    cells, names = {}, {}
    for index in range(count):
        q, f, observed = 10 + index*3, 11 + index*3, 12 + index*3
        lut = _lut("feedback%d" % index, 0x00ff, ["0", "0", "0", q], f)
        lut["attributes"].update({
            "agamemnon_direct_d_feedback": "1",
            "agamemnon_direct_d_observe_f": "1",
            "agamemnon_direct_d_origin": "qin-pack-inferred-own-q",
            "AGRV2K_NATIVE_DIRECT_D_POOL": "X14Y11_SLICE4_7_V1",
            "AGRV2K_NATIVE_DIRECT_D_COUNT": str(count),
        })
        cells["feedback%d" % index] = lut
        cells["state%d" % index] = _raw_dff("state", 2, f, q)
        cells["observer%d" % index] = _lut("observer", 0xaaaa, [f, "0", "0", "0"], observed)
        names.update({"q%d" % index: q, "f%d" % index: f, "observed%d" % index: observed})
    return _design(cells, names)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_raw_direct_d_fusion_preserves_registered_q_and_observed_f(tmp_path, count):
    result, log, output = _run(tmp_path, "observed", _observed_feedback(count), "--pack-only")
    assert result.returncode == 0, log
    module = json.loads(output.read_text())["modules"]["top"]
    cells = module["cells"]
    for index in range(count):
        fused = cells["feedback%d_LC" % index]
        assert int(fused["parameters"]["FF_USED"], 2) == 1
        assert fused["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] == "DIRECT_D_I3"
        assert fused["connections"]["Q"] == module["netnames"]["q%d" % index]["bits"]
        assert fused["connections"]["I"][3:] == fused["connections"]["Q"]
        assert fused["connections"]["F"] == module["netnames"]["f%d" % index]["bits"]
        assert cells["observer%d_LC" % index]["connections"]["I"][:1] == fused["connections"]["F"]
        assert "state%d" % index not in cells


@pytest.mark.parametrize("fault", ["second_dff", "wrong_feedback"])
def test_raw_direct_d_fusion_rejects_ambiguous_or_wrong_feedback(tmp_path, fault):
    design = _observed_feedback()
    cells = design["modules"]["top"]["cells"]
    if fault == "second_dff":
        cells["second"] = _raw_dff("second", 2, 11, 99)
    else:
        cells["feedback0"]["connections"]["I"][3] = "0"
    result, log, _ = _run(tmp_path, fault, design, "--pack-only")
    assert result.returncode != 0
    assert "direct-D" in log or "DIRECT_D" in log


def test_native_direct_d_buffers_single_unreachable_mcu_input(tmp_path):
    design = _observed_feedback()
    cells = design["modules"]["top"]["cells"]
    cells["feedback0"]["parameters"]["INIT"] = format(0x00cc, "016b")
    cells["feedback0"]["connections"]["I"][1] = 50
    cells["mcu_hwrite"] = {
        "type": "MCU_DIN", "parameters": {}, "attributes": {},
        "port_directions": {"DIN": "output"}, "connections": {"DIN": [50]}}
    design["modules"]["top"]["netnames"]["hwrite"] = {
        "bits": [50], "attributes": {}, "hide_name": 0}
    result, log, output = _run(tmp_path, "single_entry", design, "--pack-only")
    assert result.returncode == 0, log
    module = json.loads(output.read_text())["modules"]["top"]
    fused = module["cells"]["feedback0_LC"]
    hwrite = module["netnames"]["hwrite"]["bits"][0]
    assert fused["connections"]["I"][1] != hwrite
    bridge = next(cell for cell in module["cells"].values()
                  if cell.get("connections", {}).get("F") == [fused["connections"]["I"][1]])
    assert hwrite in bridge["connections"]["I"]
    assert int(bridge["parameters"]["FF_USED"], 2) == 0


@pytest.mark.parametrize("maxfo", [2, 4])
def test_fanout_split_direct_d_still_fuses_with_observed_f(tmp_path, maxfo):
    design = _observed_feedback()
    cells = design["modules"]["top"]["cells"]
    for index in range(12):
        observer = json.loads(json.dumps(cells["observer0"]))
        observer["connections"]["Q"] = [100 + index]
        cells["extra%d" % index] = observer
    path = tmp_path / "before_split.json"
    path.write_text(json.dumps(design))
    splitter = Path(__file__).parents[1] / "agamemnon/engine/fanout_split.py"
    subprocess.run([sys.executable, str(splitter), str(path), str(maxfo)],
                   check=True, capture_output=True)
    split = json.loads(path.read_text())
    assert split["modules"]["top"]["cells"]["state0"]["connections"]["D"] == [11]
    result, log, output = _run(tmp_path, "split_fusion", split, "--pack-only")
    assert result.returncode == 0, log
    fused = json.loads(output.read_text())["modules"]["top"]["cells"]["feedback0_LC"]
    assert int(fused["parameters"]["FF_USED"], 2) == 1
    assert fused["connections"]["I"][3:] == fused["connections"]["Q"]
    assert len(fused["connections"]["F"]) == 1
