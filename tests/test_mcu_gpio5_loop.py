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
    gpio = (ROOT / "agamemnon" / "engine" / "features" / "mcu_gpio.py").read_text(
        encoding="utf-8"
    )
    carry = (ROOT / "agamemnon" / "engine" / "features" / "carry.py").read_text(
        encoding="utf-8"
    )
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '259: "MCU_GPIO5_OUT_DATA1"' in arch
    assert '260: "MCU_GPIO5_OUT_EN1"' in arch
    assert '261: "MCU_GPIO5_IN2"' in arch
    assert '"mcu_gpio5_loop_paths.csv"' in arch
    assert '"mcu_gpio5_loop_l48_paths.csv"' in arch
    assert 'DEV.name == "AGRV2KL48"' in arch
    assert '"mcu_gpio5_loop_pip_cfg.csv"' in gpio
    assert '"mcu_gpio5_loop_l48_pip_cfg.csv"' in gpio
    assert 'GPIO5 L48 boundary: selected 7 characterized inactive BBMUXS terminal defaults' in gpio
    assert '"MCU_GPIO5_OUT_DATA0", "MCU_GPIO5_OUT_EN0"' in gpio
    assert '"MCU_GPIO5_OUT_DATA1", "MCU_GPIO5_OUT_EN1"' in gpio
    assert '(0, 1, 3, 4, 5, 6, 7)' in gpio
    assert '"BBMUXS%d" % mux, 8' in gpio
    assert '"AGRV2K_CARRY_CRL"' in carry
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

    trial = next(record for record in records
                 if record.get("hardware_runs") == 3)
    assert trial["exact_fields"] == 8
    assert trial["selector_checks"] == 65
    assert trial["routed_pips"] == 9
    assert trial["unmapped_pips"] == 0
    assert trial["hardware"] == "fail"
    assert trial["hardware_runs"] == 3
    assert trial["open_observed_input2_by_state"] == [1, 1, 0, 0]
    assert trial["vendor_observed_input2_by_state"] == [0, 0, 1, 0]
    assert "stuck low" in trial["reason"]


def test_l48_gpio5_lane0_differential_is_explicit_and_fail_closed():
    paths = rows("mcu_gpio5_lane0_l48_paths.csv")
    cfg = rows("mcu_gpio5_lane0_l48_pip_cfg.csv")
    assert len(paths) == 9
    assert len(cfg) == 8
    assert paths[0]["src_wire"] == "X9Y5_BufMUX01"
    assert paths[3]["src_wire"] == "X9Y5_BufMUX09"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo151"
    assert cfg[0]["cfg_group"] == "InputMUX0"
    assert cfg[0]["set_selectors"] == "0"
    assert cfg[3]["cfg_group"] == "InputMUX9"
    assert cfg[3]["set_selectors"] == "0"
    assert cfg[-1]["set_selectors"] == "1;5"

    arch = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '262: "MCU_GPIO5_OUT_DATA0"' in arch
    assert '263: "MCU_GPIO5_OUT_EN0"' in arch
    gpio = (ROOT / "agamemnon" / "engine" / "features" / "mcu_gpio.py").read_text(
        encoding="utf-8"
    )
    assert '"mcu_gpio5_lane0_l48_pip_cfg.csv"' in gpio
    for module in ("MCU_GPIO5_OUT_DATA0", "MCU_GPIO5_OUT_EN0"):
        assert f"module {module}" in prims


def test_l48_gpio5_inactive_terminal_policy_is_silicon_qualified_on_two_lanes():
    evidence = ROOT / "qualification" / "mcu_gpio5_route_evidence.jsonl"
    records = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    by_id = {record.get("trial_id"): record for record in records}

    lane1 = by_id["2026-08-03-l48-gpio5-lane1-pure-open-qualified"]
    lane0 = by_id["2026-08-03-l48-gpio5-lane0-pure-open-qualified"]
    for record in (lane1, lane0):
        assert record["hardware"] == "pass"
        assert record["config_accept"] == "pass"
        assert record["observed_input2_by_state"] == [0, 0, 1, 0]
        assert record["unmapped_pips"] == 0
        assert "BBMUXS0/1/3/4/5/6/7" in record["inactive_terminal_policy"]

    lane0_single = by_id["2026-08-03-l48-gpio5-lane0-bbmuxs1-only"]
    assert lane0_single["hardware"] == "fail"
    assert lane0_single["observed_input2_by_state"] == [1, 1, 0, 0]
