import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_first_fabric_master_response_slice_is_exact_and_typed():
    path = rows("mcu_slave_ahb_response_paths.csv")
    cfg = rows("mcu_slave_ahb_response_pip_cfg.csv")
    assert len(path) == len(cfg) == 6
    assert {row["src_wire"] for row in path if row["step"] == "0"} == {
        "X13Y9_BufMUX14", "X13Y9_BufMUX15", "X13Y9_BufMUX16"}
    assert {row["dst_wire"] for row in path if row["step"] == "1"} == {
        "X14Y9_IMUX01", "X14Y9_IMUX02", "X14Y9_IMUX03"}

    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "features" /
              "mcu_ahb.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '125: "MCU_SLAVE_AHB_HREADYOUT"' in arch
    assert '126: "MCU_SLAVE_AHB_HRESP"' in arch
    assert '127: "MCU_SLAVE_AHB_HRDATA0"' in arch
    assert '"mcu_slave_ahb_response_pip_cfg.csv"' in bitgen
    for name in ("HREADYOUT", "HRESP", "HRDATA0"):
        assert f"module MCU_SLAVE_AHB_{name}" in prims


def test_response_smoke_pins_vendor_input_order():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_response_route_smoke.v").read_text(encoding="utf-8")
    assert 'BEL="X14Y9_SLICE0"' in smoke
    assert ".I({hrdata0, hreadyout, hresp, 1'b0})" in smoke
