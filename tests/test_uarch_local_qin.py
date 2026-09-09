"""Compiled local-feedback packing and actual routed internal edges."""
import json,os
from pathlib import Path
import pytest
import test_uarch_register_input_legality as support

@pytest.fixture(autouse=True)
def candidate_devdb(monkeypatch):
    if os.environ.get("AGAMEMNON_TEST_LOCAL_QIN_DEVDB"):
        monkeypatch.setattr(support,"DEVDB",Path(os.environ["AGAMEMNON_TEST_LOCAL_QIN_DEVDB"]))


def test_local_qin_fusion_preserves_registered_observer(tmp_path):
    lut=support._lut("state",0x0f0f,["0","0",5,"0"],6,tags=("agamemnon_local_qin_feedback",))
    ff=support._raw_dff("state_ff",2,6,5)
    observer=support._raw_dff("observer",2,5,8)
    design=support._design({"state":lut,"state_ff":ff,"observer":observer},{"clock":2,"q":5,"next":6,"observed":8})
    result,log,out=support._run(tmp_path,"qin_fused",design,"--pack-only")
    assert result.returncode==0,log
    m=json.loads(out.read_text())["modules"]["top"]
    state=m["cells"]["state_LC"]
    assert state["attributes"]["AGRV2K_REGISTER_INPUT_MODE"]=="LOCAL_QIN_I2"
    q=state["connections"]["Q"][0]
    assert state["connections"]["I"][2]==q and not state["connections"]["F"]
    assert any(q in c["connections"].get("I",[]) for n,c in m["cells"].items() if n!="state_LC")


def test_native_enable_and_local_qin_pack_together(tmp_path, monkeypatch):
    """Exercise the C++ fusion path, including DFFE EN lifting.

    The test runs only with the isolated uarch binary/devdb configured by the
    integration job.  It checks the persisted protocols that qin and bitgen
    consume; it makes no silicon-performance claim.
    """
    monkeypatch.setenv("AGRV2K_SHARED_CONTROL_ENABLE", "1")
    monkeypatch.setenv("AGRV2K_NATIVE_ENABLE_LOCAL_QIN", "1")
    from agamemnon.engine.qin_pack import lower_local_qin_feedback

    # This is the same pre-qin shape a mapped ordinary source produces.  Run
    # the actual JSON pass before handing its result to the compiled packer.
    lut = support._lut("state", 0x0f0f, ["0", "0", 5, "0"], 6,
                       tags=("agamemnon_local_qin_feedback",))
    dffe = {
        "hide_name": 0, "type": "DFFE", "parameters": {},
        "attributes": {"AGRV2K_SHARED_CONTROL_MODE": "CLOCK_ENABLE_POS",
                       "AGRV2K_ENABLE_GROUP_ID": "0123456789abcdef"},
        "port_directions": {"CLK": "input", "EN": "input", "D": "input", "Q": "output"},
        "connections": {"CLK": [2], "EN": [3], "D": [6], "Q": [5]},
    }
    # This independent consumer makes Q externally observable while the fused
    # state cell still has no F presentation of the old LUT result.
    observer = support._raw_dff("observer", 2, 5, 8)
    design = support._design({"state": lut, "state_ff": dffe, "observer": observer},
                              {"clock": 2, "enable": 3, "q": 5, "next": 6, "observed": 8})
    pre_qin = tmp_path / "qin_native_enable_pre.json"
    pre_qin.write_text(json.dumps(design), encoding="utf-8")
    assert lower_local_qin_feedback(pre_qin) == 1
    design = json.loads(pre_qin.read_text(encoding="utf-8"))
    lowered = design["modules"]["top"]["cells"]
    assert lowered["state_ff"]["connections"]["EN"] == [3]
    assert lowered["state"]["attributes"]["agamemnon_local_qin_feedback"] == "1"
    result, log, out = support._run(tmp_path, "qin_native_enable", design, "--pack-only")
    assert result.returncode == 0, log
    module = json.loads(out.read_text())["modules"]["top"]
    state = module["cells"]["state_LC"]
    assert state["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] == "LOCAL_QIN_I2"
    assert state["attributes"]["AGRV2K_SHARED_CONTROL_MODE"] == "CLOCK_ENABLE_POS"
    assert state["attributes"]["AGRV2K_ENABLE_GROUP_ID"] == "0123456789abcdef"
    assert state["attributes"]["AGRV2K_CLOCK_ENABLE_NET"] == "enable"
    assert state["connections"]["I"][2] == state["connections"]["Q"][0]
    assert state["connections"]["F"] == []
    assert any(state["connections"]["Q"][0] in cell["connections"].get("I", [])
               for name, cell in module["cells"].items() if name != "state_LC")


@pytest.mark.parametrize("site",["X14Y11_SLICE4","X10Y4_SLICE0","X1Y4_SLICE2"])
def test_local_qin_routes_same_slice_feedback(tmp_path,site):
    state=support._generic("LOCAL_QIN_I2",init=0x0f0f,bel=site,tags=("agamemnon_local_qin_feedback",))
    state["connections"]["I"]=["0","0",20,"0"]
    design=support._design({"state":state},{"clock":2,"q":20})
    result,log,out=support._run(tmp_path,"qin_route",design,"--router","router2")
    assert result.returncode==0,log
    module=json.loads(out.read_text())["modules"]["top"]
    q=module["cells"]["state"]["connections"]["Q"][0]
    routes=[n["attributes"].get("ROUTING","") for n in module["netnames"].values() if n["bits"]==[q]]
    import re
    tile,z=re.fullmatch(r"(X\d+Y\d+)_SLICE(\d+)",site).groups();z=int(z)
    expected=f"{tile}_OMUX{3*z+2:02d}.{tile}_IMUX{4*z+2:02d}"
    assert any(expected in r for r in routes),routes


@pytest.mark.parametrize("flow",[("--no-route","--placer","heap"),("--no-place","--router","router2")])
@pytest.mark.parametrize("fault",["wrong_q","no_tag","unused_c","live_f"])
def test_local_qin_rejects_malformed_native_shape(tmp_path,fault,flow):
    c=support._generic("LOCAL_QIN_I2",init=0x0f0f,tags=("agamemnon_local_qin_feedback",))
    c["connections"]["I"]=["0","0",20,"0"]
    if fault=="wrong_q":c["connections"]["I"][2]="1"
    if fault=="no_tag":del c["attributes"]["agamemnon_local_qin_feedback"]
    if fault=="unused_c":c["parameters"]["INIT"]=f"{0xaaaa:016b}"
    if fault=="live_f":c["connections"]["F"]=[30]
    result,log,_=support._run(tmp_path,"invalid",support._design({"state":c},{"clock":2,"q":20,"f":30}),*flow)
    assert result.returncode!=0 and "LOCAL_QIN_I2" in log,log
