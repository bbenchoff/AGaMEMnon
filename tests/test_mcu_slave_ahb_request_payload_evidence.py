import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_request_payload_vendor_routes_are_complete_but_not_claimed_open():
    paths = rows("mcu_slave_ahb_request_payload_paths.csv")
    cfg = rows("mcu_slave_ahb_request_payload_pip_cfg.csv")
    assert len(paths) == 301
    assert len(cfg) == 85
    signals = {row["signal"] for row in paths}
    assert signals == ({f"slave_ahb_haddr[{bit}]" for bit in range(32)} |
                       {f"slave_ahb_hwdata[{bit}]" for bit in range(32)})
    roots = Counter(row["src_wire"] for row in paths if row["step"] == "0")
    assert roots == {"X14Y12_OMUX02": 49, "X14Y12_OMUX00": 15}

    records = [json.loads(line) for line in
               (ROOT / "qualification" /
                "mcu_slave_ahb_request_payload_route_evidence.jsonl").read_text(
                    encoding="utf-8").splitlines()]
    assert records[0]["open_build"] == "blocked-dual-output-slice-bel"
    record = records[-1]
    assert record["selector_checks"] == 801
    assert record["exact_fields"] == 85
    assert record["path_edges"] == 301
    assert record["build"] == "pass"
    assert record["routed_pips"] == 85
    assert record["unmapped_pips"] == 0
    assert record["source_scope"] == "one-shared-safe-low-dual-output-source"
    assert record["required_environment"] == {
        "AGAMEMNON_DUAL_LUT_CONST": "14,12,0",
    }
    assert record["hardware"] == "not-run"


def test_request_payload_shared_low_smoke_uses_both_physical_roots():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_request_payload_shared_low_route_smoke.v").read_text(
                 encoding="utf-8")
    assert 'BEL="X14Y12_DUAL_SLICE0"' in smoke
    assert smoke.count("request_low_omux0" ) == 17
    assert smoke.count("request_low_omux2" ) == 51
    assert smoke.count(") MCU_DOUT ") == 64
    assert "AGRV2K_DUAL_LUT_CONST" in smoke
    arch = (ROOT / "agamemnon" / "engine" / "arch.py").read_text(
        encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "bitgen_seq.py").read_text(
        encoding="utf-8")
    registry = (ROOT / "agamemnon" / "engine" / "registry.py").read_text(
        encoding="utf-8")
    assert 'type="AGRV2K_DUAL_LUT_CONST"' in arch
    assert '"mcu_slave_ahb_request_payload_pip_cfg.csv"' in bitgen
    assert "AGAMEMNON_DUAL_LUT_CONST" in registry
