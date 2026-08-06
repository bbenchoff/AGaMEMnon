import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_hrdata1_4_are_exact_and_typed():
    assert len(rows("mcu_slave_ahb_hrdata1_4_paths.csv")) == 10
    assert len(rows("mcu_slave_ahb_hrdata1_4_pip_cfg.csv")) == 10
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" /
              "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for lane, bit in zip(range(1, 5), range(134, 138)):
        name = f"MCU_SLAVE_AHB_HRDATA{lane}"
        assert f'{bit}: "{name}"' in arch
        assert f"module {name}" in prims
    assert '"mcu_slave_ahb_hrdata1_4_pip_cfg.csv"' in bitgen


def test_hrdata1_4_smoke_uses_recovered_lut_pin_order():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_hrdata1_4_route_smoke.v").read_text(encoding="utf-8")
    assert 'BEL="X14Y9_SLICE0"' in smoke
    assert ".I({hrdata1, hrdata3, hrdata4, hrdata2})" in smoke


def test_hrdata5_8_are_exact_typed_and_use_recovered_pin_order():
    assert len(rows("mcu_slave_ahb_hrdata5_8_paths.csv")) == 12
    assert len(rows("mcu_slave_ahb_hrdata5_8_pip_cfg.csv")) == 12
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for lane, bit in zip(range(5, 9), range(138, 142)):
        name = f"MCU_SLAVE_AHB_HRDATA{lane}"
        assert f'{bit}: "{name}"' in arch
        assert f"module {name}" in prims
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_hrdata5_8_route_smoke.v").read_text(encoding="utf-8")
    assert 'BEL="X14Y8_SLICE0"' in smoke
    assert ".I({hrdata5, hrdata7, hrdata8, hrdata6})" in smoke


def test_hrdata9_12_are_exact_typed_and_use_recovered_pin_order():
    assert len(rows("mcu_slave_ahb_hrdata9_12_paths.csv")) == 12
    assert len(rows("mcu_slave_ahb_hrdata9_12_pip_cfg.csv")) == 12
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for lane, bit in zip(range(9, 13), range(142, 146)):
        name = f"MCU_SLAVE_AHB_HRDATA{lane}"
        assert f'{bit}: "{name}"' in arch
        assert f"module {name}" in prims
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_hrdata9_12_route_smoke.v").read_text(encoding="utf-8")
    assert ".I({hrdata10, hrdata11, hrdata9, hrdata12})" in smoke


def test_hrdata13_16_are_exact_typed_and_use_recovered_pin_order():
    assert len(rows("mcu_slave_ahb_hrdata13_16_paths.csv")) == 12
    assert len(rows("mcu_slave_ahb_hrdata13_16_pip_cfg.csv")) == 12
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for lane, bit in zip(range(13, 17), range(146, 150)):
        name = f"MCU_SLAVE_AHB_HRDATA{lane}"
        assert f'{bit}: "{name}"' in arch
        assert f"module {name}" in prims
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_hrdata13_16_route_smoke.v").read_text(encoding="utf-8")
    assert ".I({hrdata16, hrdata14, hrdata15, hrdata13})" in smoke


def test_hrdata17_20_are_exact_typed_and_use_recovered_pin_order():
    assert len(rows("mcu_slave_ahb_hrdata17_20_paths.csv")) == 8
    assert len(rows("mcu_slave_ahb_hrdata17_20_pip_cfg.csv")) == 8
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for lane, bit in zip(range(17, 21), range(150, 154)):
        name = f"MCU_SLAVE_AHB_HRDATA{lane}"
        assert f'{bit}: "{name}"' in arch
        assert f"module {name}" in prims
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_hrdata17_20_route_smoke.v").read_text(encoding="utf-8")
    assert ".I({hrdata17, hrdata19, hrdata20, hrdata18})" in smoke


def test_all_32_hrdata_lanes_are_exposed_in_bounded_groups():
    groups = ((1, 4), (5, 8), (9, 12), (13, 16),
              (17, 20), (21, 24), (25, 28), (29, 31))
    recovered = {0}
    bitgen = (ROOT / "agamemnon" / "engine" /
              "bitgen_seq.py").read_text(encoding="utf-8")
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    for first, last in groups:
        group = f"{first}_{last}"
        paths = rows(f"mcu_slave_ahb_hrdata{group}_paths.csv")
        recovered.update(int(row["signal"].split("[")[1].rstrip("]"))
                         for row in paths)
        assert f'"mcu_slave_ahb_hrdata{group}_pip_cfg.csv"' in bitgen
        assert (ROOT / "examples" / "designs" /
                f"mcu_slave_ahb_hrdata{group}_route_smoke.v").exists()
    assert recovered == set(range(32))
    for lane in range(1, 32):
        name = f"MCU_SLAVE_AHB_HRDATA{lane}"
        assert f'{133 + lane}: "{name}"' in arch
        assert f"module {name}" in prims


def test_hrdata_route_evidence_is_hardware_free_and_complete():
    records = [json.loads(line) for line in
               (ROOT / "qualification" /
                "mcu_slave_ahb_hrdata_route_evidence.jsonl").read_text(
                    encoding="utf-8").splitlines()]
    assert [record["group"] for record in records] == [
        "1-4", "5-8", "9-12", "13-16",
        "17-20", "21-24", "25-28", "29-31",
        "0-31-simultaneous",
    ]
    assert sum(record["selector_checks"] for record in records[:-1]) == 732
    assert sum(record["routed_pips"] for record in records[:-1]) == 85
    assert records[-1]["selector_checks"] == 904
    assert records[-1]["exact_fields"] == 102
    assert records[-1]["routed_pips"] == 109
    assert records[-1]["required_environment"] == {
        "AGRV2K_STRICT_ALLOW_ODD": "1",
    }
    assert all(record["build"] == "pass" for record in records)
    assert all(record["hardware"] == "not-run" for record in records)
    assert all(record["unmapped_pips"] == 0 for record in records)


def test_simultaneous_full_width_hrdata_artifacts_are_promoted():
    assert len(rows("mcu_slave_ahb_hrdata_grouped_full_paths.csv")) == 102
    assert len(rows("mcu_slave_ahb_hrdata_grouped_full_pip_cfg.csv")) == 102
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_hrdata_grouped_full_route_smoke.v").read_text(
                 encoding="utf-8")
    assert 'BEL="X15Y8_SLICE7"' in smoke
    assert 'BEL="X14Y7_SLICE3"' in smoke
    for lane in range(32):
        assert f"MCU_SLAVE_AHB_HRDATA{lane}" in smoke
