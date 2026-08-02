import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_gpio5_boundary_unit_is_exact_and_typed():
    paths = rows("mcu_gpio5_loop_paths.csv")
    cfg = rows("mcu_gpio5_loop_pip_cfg.csv")
    assert len(paths) == 9
    assert len(cfg) == 8
    assert {row["signal"] for row in paths} == {
        "gpio5_io_in", "gpio5_io_out_data", "gpio5_io_out_en"}
    assert paths[0]["src_wire"] == "X9Y5_BufMUX02"
    assert paths[3]["src_wire"] == "X9Y5_BufMUX10"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo151"
    assert cfg[-1]["set_selectors"] == "1;4"

    arch = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '259: "MCU_GPIO5_OUT_DATA1"' in arch
    assert '260: "MCU_GPIO5_OUT_EN1"' in arch
    assert '261: "MCU_GPIO5_IN2"' in arch
    assert '"mcu_gpio5_loop_paths.csv"' in arch
    assert '"mcu_gpio5_loop_l48_paths.csv"' in arch
    assert 'DEV.name == "AGRV2KL48"' in arch
    assert '"mcu_gpio5_loop_pip_cfg.csv"' in bitgen
    assert '"mcu_gpio5_loop_l48_pip_cfg.csv"' in bitgen
    assert '"AGRV2K_CARRY_CRL"' in bitgen
    for module in ("MCU_GPIO5_OUT_DATA1", "MCU_GPIO5_OUT_EN1", "MCU_GPIO5_IN2"):
        assert f"module {module}" in prims


def test_gpio5_smoke_retains_two_sources_one_lut_and_one_sink():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_gpio5_loop_route_smoke.v").read_text(encoding="utf-8")
    assert 'BEL="X9Y4_SLICE0"' in smoke
    assert "AGRV2K_CARRY_CRL=1" in smoke
    assert ".I({gpio5_data1, gpio5_oe1, 2'b00})" in smoke
    assert "MCU_GPIO5_IN2 observation_sink" in smoke


def test_gpio5_route_evidence_preserves_exact_route_and_failed_l48_trial():
    evidence = ROOT / "qualification" / "mcu_gpio5_route_evidence.jsonl"
    records = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    route_record = records[0]
    assert route_record["build"] == "pass"
    assert route_record["hardware"] == "not-run"

    trial = records[-1]
    assert trial["exact_fields"] == 8
    assert trial["selector_checks"] == 65
    assert trial["routed_pips"] == 9
    assert trial["unmapped_pips"] == 0
    assert trial["hardware"] == "fail"
    assert trial["hardware_runs"] == 3
    assert trial["open_observed_input2_by_state"] == [1, 1, 0, 0]
    assert trial["vendor_observed_input2_by_state"] == [0, 0, 1, 0]
    assert "stuck low" in trial["reason"]
