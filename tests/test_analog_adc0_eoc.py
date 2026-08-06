import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_adc0_eoc_route_is_exact_typed_and_read_only():
    paths = rows("analog_adc0_eoc_path.csv")
    cfg = rows("analog_adc0_eoc_pip_cfg.csv")
    assert len(paths) == 8
    assert len(cfg) == 6
    assert paths[0]["src_wire"] == "X22Y7_ADCEOCSOURCE00"
    assert paths[0]["dst_wire"] == "X22Y7_BufMUX100"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo143"
    assert cfg[-1]["cfg_group"] == "BBMUXS2"

    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '"AGRV2K_ADC0_EOC"' in arch
    assert '"analog_adc0_eoc_pip_cfg.csv"' in bitgen
    assert "module AGRV2K_ADC0_EOC" in prims


def test_adc0_eoc_smoke_uses_only_a_source_and_known_observation_sink():
    smoke = (ROOT / "examples" / "designs" / "analog_adc0_eoc_route_smoke.v").read_text(encoding="utf-8")
    assert "AGRV2K_ADC0_EOC adc_source" in smoke
    assert 'BEL="X10Y5_MCU2"' in smoke
    assert "MCU observation" in smoke
    assert "alta_adc" not in smoke


def test_adc0_eoc_evidence_is_route_only_and_hardware_unqualified():
    evidence = ROOT / "qualification" / "analog_adc0_eoc_route_evidence.jsonl"
    record = json.loads(evidence.read_text(encoding="utf-8").splitlines()[-1])
    assert record["build"] == "pass"
    assert record["selector_checks"] == 59
    assert record["exact_fields"] == 6
    assert record["routed_pips"] == 8
    assert record["unmapped_pips"] == 0
    assert record["hardware"] == "not-run"
