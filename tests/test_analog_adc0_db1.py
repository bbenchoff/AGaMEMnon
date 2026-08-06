import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_adc0_db1_route_is_exact_typed_and_read_only():
    paths = rows("analog_adc0_db1_path.csv")
    cfg = rows("analog_adc0_db1_pip_cfg.csv")
    assert len(paths) == 7
    assert len(cfg) == 5
    assert paths[0]["src_wire"] == "X22Y7_ADCDBSOURCE01"
    assert paths[0]["dst_wire"] == "X22Y7_InputMUX101"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo143"
    assert cfg[-1]["cfg_group"] == "BBMUXS2"

    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '"AGRV2K_ADC0_DB1"' in arch
    assert '"analog_adc0_db1_pip_cfg.csv"' in bitgen
    assert "module AGRV2K_ADC0_DB1" in prims


def test_adc0_db1_smoke_is_read_only():
    smoke = (ROOT / "examples" / "designs" / "analog_adc0_db1_route_smoke.v").read_text(encoding="utf-8")
    assert "AGRV2K_ADC0_DB1 adc_source" in smoke
    assert 'BEL="X10Y5_MCU2"' in smoke
    assert "alta_adc" not in smoke


def test_adc0_db1_evidence_is_route_only_and_hardware_unqualified():
    evidence = ROOT / "qualification" / "analog_adc0_db1_route_evidence.jsonl"
    record = json.loads(evidence.read_text(encoding="utf-8").splitlines()[-1])
    assert record["build"] == "pass"
    assert record["selector_checks"] == 49
    assert record["exact_fields"] == 5
    assert record["routed_pips"] == 7
    assert record["unmapped_pips"] == 0
    assert record["hardware"] == "not-run"
