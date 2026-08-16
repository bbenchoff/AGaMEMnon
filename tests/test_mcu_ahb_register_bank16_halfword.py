"""Pinned contract for the silicon-qualified aligned-halfword bank16 checkpoint."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "qualification"
ROUTED = Q / "mcu_ahb_register_bank16_word_byte_halfword_waited_routed.json"
COMPOSER = Q / "compose_mcu_ahb_bank16_halfword_waited.py"
FIRMWARE = Q / "mcu_ahb_bank16_word_byte_halfword_waited_test.c"
RUNNER = Q / "run_mcu_ahb_bank16_word_byte_halfword_waited.py"
LEDGER = Q / "mcu_ahb_bank16_halfword_evidence.jsonl"

HSIZE0_CORRIDOR = {
    "X13Y12_BufMUX03.X13Y12_InputMUX03",
    "X13Y12_InputMUX03.X14Y12_RMUX41",
    "X14Y12_RMUX41.X14Y12_IMUX15",
}
HTRANS_BUFFER_CORRIDOR = {
    "X15Y8_RMUX02.X15Y9_RMUX19",
    "X15Y9_RMUX19.X15Y12_RMUX94",
    "X15Y12_RMUX94.X15Y12_IMUX58",
}


def top():
    return json.loads(ROUTED.read_text(encoding="utf-8"))["modules"]["top"]


def pips(net):
    fields = net["attributes"]["ROUTING"].split(";")
    return {fields[index + 1] for index in range(0, len(fields), 3)
            if fields[index + 1]}


def test_hsize0_and_htrans_use_the_pinned_corridors():
    design = top()
    cells, nets = design["cells"], design["netnames"]
    assert cells["mcu_hsize0"]["type"] == "MCU_AHB_HSIZE0"
    assert cells["mcu_hsize0"]["attributes"]["NEXTPNR_BEL"] == \
        "X10Y5_MCU_AHB_HSIZE0104"
    assert HSIZE0_CORRIDOR == pips(nets["hsize0"])
    assert HTRANS_BUFFER_CORRIDOR <= pips(nets["htrans1"])
    assert "X14Y9_RMUX55.X14Y12_RMUX47" not in pips(nets["htrans1"])
    assert "X14Y12_RMUX47.X14Y12_IMUX15" not in pips(nets["htrans1"])


def test_halfword_predecode_keeps_the_qualified_handshake():
    cells = top()["cells"]
    high = cells["high_request"]
    assert high["attributes"]["NEXTPNR_BEL"] == "X14Y12_SLICE3"
    assert high["connections"]["I"] == [303953, 303954, 303955, 303960]
    assert int(high["parameters"]["INIT"], 2) == 0x3332
    buffer = cells["high_request_buffer"]
    assert buffer["attributes"]["NEXTPNR_BEL"] == "X15Y12_SLICE14"
    assert buffer["connections"]["I"] == ["0", 303957, 302818, "0"]
    assert int(buffer["parameters"]["INIT"], 2) == 0xC0C0
    assert int(cells["pending_high_stage"]["parameters"]["INIT"], 2) == 0x0080
    assert int(cells["write_wait_stage"]["parameters"]["INIT"], 2) == 0xCDCD
    assert int(cells["capture8"]["parameters"]["INIT"], 2) == 0x0B08


def test_composer_reproduces_the_retained_route(tmp_path):
    output = tmp_path / "routed.json"
    subprocess.run([sys.executable, str(COMPOSER), "--out", str(output)],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    assert output.read_bytes() == ROUTED.read_bytes()


def test_oracle_uses_real_aligned_widths_and_preserves_boundaries():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    assert "word[0] = p" in firmware
    assert "half[0]" in firmware
    assert "half[1]" in firmware and "half[2]" in firmware
    assert "half[4]" in firmware and "half[6]" in firmware
    assert "byte[0]" in firmware and "byte[1]" in firmware
    assert 'for opcode in ("sw", "sh", "sb")' in runner
    assert "data[1:12] == [0] * 11" in runner


def test_silicon_record_binds_artifacts_and_exact_scope():
    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    assert record["result"] == "pass_exact_16_bit_aligned_word_byte_halfword_semantics"
    assert "Four complete 100-pattern runs" in record["observed"]
    assert "Misaligned transfers" in record["scope"]
    assert "not a generic 16-bit register-bank claim" in record["consequence"]
    for field, path in (("routed_sha256", ROUTED), ("composer_sha256", COMPOSER),
                        ("test_sha256", FIRMWARE), ("runner_sha256", RUNNER)):
        assert record[field] == hashlib.sha256(path.read_bytes()).hexdigest()
