import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_stop_observation_route_is_exact_and_typed():
    paths = rows("mcu_stop_path.csv")
    assert len(paths) == 6
    assert paths[0]["src_wire"] == "X13Y5_BufMUX06"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo143"
    assert len(rows("mcu_stop_pip_cfg.csv")) == 5
    arch = (ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon" / "synth" / "prims.v").read_text(encoding="utf-8")
    assert '258: "MCU_STOP"' in arch
    assert '"mcu_stop_pip_cfg.csv"' in bitgen
    assert "module MCU_STOP" in prims


def test_stop_smoke_pins_the_known_observation_sink():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_stop_observation_route_smoke.v").read_text(encoding="utf-8")
    assert 'BEL="X10Y5_MCU2"' in smoke
    assert "MCU_STOP stop_source" in smoke
    assert ".DOUT(stop_state)" in smoke


def test_stop_evidence_is_observational_only():
    evidence = ROOT / "qualification" / "mcu_stop_route_evidence.jsonl"
    records = [json.loads(line) for line in evidence.read_text(encoding="utf-8").splitlines()]
    record = records[-1]
    assert record["build"] == "pass"
    assert record["source_scope"] == "typed-stop-source-to-known-mcu-observation-sink"
    assert record["exact_fields"] == 5
    assert record["selector_checks"] == 40
    assert record["routed_pips"] == 6
    assert record["unmapped_pips"] == 0
    assert record["hardware"] == "not-run"
