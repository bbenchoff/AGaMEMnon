"""Pinned contract for the silicon-qualified exact 16-bit word/byte bank."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION = ROOT / "qualification"
ROUTED = QUALIFICATION / "mcu_ahb_register_bank16_word_byte_waited_routed.json"
FIRMWARE = QUALIFICATION / "mcu_ahb_bank16_word_byte_waited_test.c"
RUNNER = QUALIFICATION / "run_mcu_ahb_bank16_word_byte_waited.py"
LEDGER = QUALIFICATION / "mcu_ahb_bank16_write_isolation_evidence.jsonl"

SELECTOR_CORRIDOR = {
    "X14Y12_OMUX11.X14Y12_RMUX01",
    "X14Y12_RMUX01.X15Y12_RMUX17",
    "X15Y12_RMUX17.X15Y12_IMUX57",
    "X15Y12_OMUX44.X15Y12_RMUX73",
    "X15Y12_RMUX73.X15Y11_RMUX00",
    "X15Y11_RMUX00.X14Y11_IMUX08",
}
HWRITE_CORRIDOR = {
    "X14Y12_OMUX02.X14Y12_RMUX15",
    "X14Y12_RMUX15.X15Y12_RMUX68",
    "X15Y12_RMUX68.X16Y12_RMUX80",
    "X16Y12_RMUX80.X16Y11_RMUX43",
    "X16Y11_RMUX43.X14Y11_RMUX89",
    "X14Y11_RMUX89.X14Y11_IMUX09",
}


def top():
    return json.loads(ROUTED.read_text(encoding="utf-8"))["modules"]["top"]


def pips(net):
    fields = net["attributes"]["ROUTING"].split(";")
    return {fields[index + 1] for index in range(0, len(fields), 3)
            if fields[index + 1]}


def test_selector_and_hwrite_use_the_silicon_passing_physical_corridors():
    design = top()
    cells, nets = design["cells"], design["netnames"]
    assert cells["high_request"]["attributes"]["NEXTPNR_BEL"] == \
        "X14Y12_SLICE3"
    assert int(cells["high_request"]["parameters"]["INIT"], 2) == 0x3200
    assert cells["high_request_buffer"]["attributes"]["NEXTPNR_BEL"] == \
        "X15Y12_SLICE14"
    assert int(cells["high_request_buffer"]["parameters"]["INIT"], 2) == 0xCCCC
    assert SELECTOR_CORRIDOR <= (pips(nets["high_request"]) |
                                 pips(nets["high_request_buffer"]))
    assert HWRITE_CORRIDOR <= pips(nets["hwrite_word0"])
    assert "X14Y12_OMUX02.X14Y12_RMUX19" not in pips(nets["hwrite_word0"])


def test_high_byte_token_retains_the_ready_qualified_handshake():
    design = top()
    cells, nets = design["cells"], design["netnames"]
    stage = cells["pending_high_stage"]
    assert stage["attributes"]["NEXTPNR_BEL"] == "X14Y11_SLICE2"
    assert stage["connections"]["I"] == [
        nets["high_request_buffer"]["bits"][0],
        nets["hwrite_word0"]["bits"][0],
        nets["write_ready_f"]["bits"][0],
        nets["reset_request"]["bits"][0],
    ]
    assert int(stage["parameters"]["INIT"], 2) == 0x0080
    assert int(cells["write_wait_stage"]["parameters"]["INIT"], 2) == 0xCDCD
    assert int(cells["capture8"]["parameters"]["INIT"], 2) == 0x0B08


def test_oracle_qualifies_word_and_two_byte_lanes_but_not_halfword():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    assert "word[0] = p" in firmware
    assert "byte[0]" in firmware and "byte[1]" in firmware
    assert "byte[2]" in firmware and "byte[3]" in firmware
    assert "word[1]" in firmware and "word[2]" in firmware and "word[3]" in firmware
    assert "Halfword behavior is deliberately outside this experiment" in firmware
    assert "data[1:11] == [0] * 9 + [100]" in runner


def test_silicon_record_binds_the_promoted_artifacts_and_boundaries():
    records = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    record = next(row for row in records if row.get("trial_id") ==
                  "mcu-ahb-register-bank16-word-byte-waited-silicon-20260815")
    assert record["result"] == "pass_exact_16_bit_word_and_byte_semantics"
    assert "Four complete 100-pattern runs" in record["observed"]
    assert "Halfword transfers were deliberately not tested" in record["scope"]
    assert "not a generic 16-bit register-bank claim" in record["consequence"]
    for field, path in (("routed_sha256", ROUTED), ("test_sha256", FIRMWARE),
                        ("runner_sha256", RUNNER)):
        assert record[field] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record["silicon_routed_sha256"] != record["routed_sha256"]
    silicon_form = json.loads(ROUTED.read_text(encoding="utf-8"))
    silicon_form["creator"] = \
        "Next Generation Place and Route (Version nextpnr-0.10-82-g2b560ad0)"
    encoded = (json.dumps(silicon_form, indent=2) + "\n").encode("utf-8")
    assert hashlib.sha256(encoded).hexdigest() == record["silicon_routed_sha256"]
