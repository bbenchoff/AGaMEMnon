import csv
import json
from collections import Counter
from pathlib import Path

from agamemnon import cli


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
    record = next(
        item for item in reversed(records)
        if item.get("source_scope") == "one-shared-safe-low-dual-output-source"
    )
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

    dynamic = records[-1]
    assert dynamic["source_scope"] == (
        "one-registered-haddr2-plus-63-shared-safe-low"
    )
    assert dynamic["registered_source_bel"] == "X18Y9_SLICE15"
    assert dynamic["path_edges"] == 5
    assert dynamic["configurable_fields"] == 4
    assert dynamic["selector_checks"] == 40
    assert dynamic["selector_failures"] == 0
    assert dynamic["route_data_pips"] == {
        "total": 159, "configurable_mapped": 95,
        "fixed_endpoints": 64, "unmapped": 0,
    }
    assert dynamic["predicted_pips"] == 0
    assert dynamic["hardware"] == "not-run"
    assert dynamic["holdout_n"] == 0


def test_request_payload_shared_low_smoke_uses_both_physical_roots():
    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_request_payload_shared_low_route_smoke.v").read_text(
                 encoding="utf-8")
    assert 'BEL="X14Y12_DUAL_SLICE0"' in smoke
    assert smoke.count("request_low_omux0" ) == 17
    assert smoke.count("request_low_omux2" ) == 51
    assert smoke.count(") MCU_DOUT ") == 64
    assert "AGRV2K_DUAL_LUT_CONST" in smoke
    arch = (ROOT / "agamemnon" / "engine" / "archgen.py").read_text(
        encoding="utf-8")
    core_logic = (ROOT / "agamemnon" / "engine" / "features" /
                  "core_logic.py").read_text(encoding="utf-8")
    bitgen = (ROOT / "agamemnon" / "engine" / "features" / "mcu_ahb.py").read_text(
        encoding="utf-8")
    registry = (ROOT / "agamemnon" / "engine" / "registry.py").read_text(
        encoding="utf-8")
    assert "CORE_LOGIC_FEATURE.add_architecture" in arch
    assert 'type="AGRV2K_DUAL_LUT_CONST"' in core_logic
    assert '"mcu_slave_ahb_request_payload_pip_cfg.csv"' in bitgen
    assert "AGAMEMNON_DUAL_LUT_CONST" in registry


def test_haddr2_dynamic_route_is_one_exact_registered_lane_and_fails_closed():
    paths = rows("mcu_slave_ahb_haddr2_dynamic_paths.csv")
    cfg = rows("mcu_slave_ahb_haddr2_dynamic_pip_cfg.csv")
    assert len(paths) == 5
    assert len(cfg) == 4
    assert {row["signal"] for row in paths} == {"slave_ahb_haddr[2]"}
    assert [row["step"] for row in paths] == ["0", "1", "2", "3", "4"]
    assert paths[0]["src_wire"] == "X18Y9_OMUX47"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo47"
    assert {row["evidence"] for row in paths + cfg} == {
        "retained-independent-register-haddr2"
    }
    assert sum(len(row["clear_selectors"].split(";")) for row in cfg) == 40

    smoke = (ROOT / "examples" / "designs" /
             "mcu_slave_ahb_haddr2_dynamic_route_smoke.v").read_text(
                 encoding="utf-8")
    assert 'BEL="X18Y9_SLICE15"' in smoke
    assert 'BEL="X14Y12_DUAL_SLICE0"' in smoke
    assert smoke.count(") MCU_DOUT ") == 64
    assert "haddr2(.DOUT(haddr2_dynamic))" in smoke
    assert smoke.count(".FF_USED(1)") == 1

    arch = (ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" /
            "agrv2k.cc").read_text(encoding="utf-8")
    assert "guard_fabric_ahb_haddr2_dynamic_payload(ctx);" in arch
    assert "lock_fabric_ahb_haddr2_dynamic();" in arch
    assert "payload.size() == 64" in arch
    assert "lanes.size() == 64" in arch
    assert "X18Y9_SLICE15" in arch
    assert "all other 63 payload lanes present" in arch
    assert "arbitrary dynamic \"" in arch
    assert "payload topologies fail closed" in arch


def test_haddr2_dynamic_policy_refusal_is_not_retried_as_routing():
    refusal = (
        "ERROR: agrv2k: fabric AHB HADDR[2] matches neither the exact shared "
        "safe-low source nor the exact X18Y9_SLICE15 registered source; arbitrary "
        "dynamic payload topologies fail closed\n"
        "ERROR: Packing design failed.\n"
    )
    assert cli._nonretryable_uarch_failure(refusal)
