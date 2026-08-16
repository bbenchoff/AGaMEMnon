"""Pinned contract for the silicon-qualified HADDR[3:2] write isolation."""

import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION = ROOT / "qualification"
BASE = QUALIFICATION / "mcu_ahb_register_bank16_external_feedback_waited_routed.json"
ROUTED = QUALIFICATION / "mcu_ahb_register_bank16_address_write_isolated_waited_routed.json"
COMPOSER = QUALIFICATION / "compose_mcu_ahb_bank16_word0_write_isolation.py"
SOURCE = QUALIFICATION / "mcu_ahb_register_bank16_address_write_isolated_waited.v"
FIRMWARE = QUALIFICATION / "mcu_ahb_bank16_address_write_isolated_waited_test.c"
RUNNER = QUALIFICATION / "run_mcu_ahb_bank16_address_write_isolated_waited.py"
LEDGER = QUALIFICATION / "mcu_ahb_bank16_write_isolation_evidence.jsonl"


def top(path):
    return json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]


def test_composer_reproduces_the_promoted_route(tmp_path):
    spec = importlib.util.spec_from_file_location("bank16_write_isolation", COMPOSER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = tmp_path / ROUTED.name
    module.main()
    assert module.OUT.read_bytes() == ROUTED.read_bytes()


def test_write_gate_consumes_exact_haddr2_haddr3_corridors():
    design = top(ROUTED)
    cells, nets = design["cells"], design["netnames"]
    assert cells["mcu_haddr2"]["attributes"]["NEXTPNR_BEL"] == \
        "X10Y5_MCU_DIN76"
    assert cells["mcu_haddr3"]["attributes"]["NEXTPNR_BEL"] == \
        "X10Y5_MCU_DIN77"

    gate = cells["hwrite_word0_gate"]
    assert gate["attributes"]["NEXTPNR_BEL"] == "X14Y12_SLICE0"
    assert int(gate["parameters"]["INIT"], 2) == 0x0044
    assert gate["connections"]["I"] == [
        nets["haddr2"]["bits"][0],
        nets["hwrite"]["bits"][0],
        302849,
        nets["haddr3"]["bits"][0],
    ]
    assert gate["connections"]["F"] == nets["hwrite_word0"]["bits"]
    assert cells["write_stage"]["connections"]["I"][1] == \
        nets["hwrite_word0"]["bits"][0]
    assert "X13Y12_BufMUX12" in nets["haddr2"]["attributes"]["ROUTING"]
    assert "X13Y12_BufMUX13" in nets["haddr3"]["attributes"]["ROUTING"]


def test_composition_preserves_the_qualified_storage_wait_and_readback():
    base, isolated = top(BASE)["cells"], top(ROUTED)["cells"]
    for lane in range(16):
        assert isolated["capture%d" % lane] == base["capture%d" % lane]
        assert isolated["feedback_buffer%d" % lane] == \
            base["feedback_buffer%d" % lane]
        assert isolated["mcu_h%d" % lane] == base["mcu_h%d" % lane]
    assert isolated["write_wait_stage"] == base["write_wait_stage"]


def test_oracle_and_docs_preserve_the_read_alias_boundary():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")
    assert "+4, +8 and +c span HADDR[3:2]" in firmware
    assert "Reads are not decoded" in firmware
    assert "must still alias" in firmware
    assert "foreign_alias_errors" in firmware
    assert "data[1:9] == [0, 0, 0, 0, 0, 0, 0, 100]" in runner
    assert "not claimed to reproduce that placement" in source


def test_silicon_evidence_claims_write_isolation_not_read_decode():
    records = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    assert len(records) == 1
    record = records[0]
    assert record["result"] == "pass_haddr32_write_commit_isolation"
    assert "foreign_write_errors=0" in record["observed"]
    assert "foreign reads alias +0" in record["scope"]
    assert "Full address isolation remains open" in record["consequence"]
    assert record["silicon_routed_sha256"] != record["routed_sha256"]
    assert "creator provenance string" in record["implementation"]

    for field, path in (
        ("routed_sha256", ROUTED),
        ("source_sha256", SOURCE),
        ("composer_sha256", COMPOSER),
        ("test_sha256", FIRMWARE),
        ("runner_sha256", RUNNER),
    ):
        assert record[field] == hashlib.sha256(path.read_bytes()).hexdigest()

    # The promoted JSON changes only non-emitted creator provenance from the
    # exact file loaded on silicon. Reversing that string must recover its hash.
    silicon_form = json.loads(ROUTED.read_text(encoding="utf-8"))
    silicon_form["creator"] = \
        "Next Generation Place and Route (Version nextpnr-0.10-82-g2b560ad0)"
    encoded = (json.dumps(silicon_form, indent=2) + "\n").encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == record["silicon_routed_sha256"]
