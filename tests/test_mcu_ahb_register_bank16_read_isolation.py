"""Pinned contract for the silicon-qualified bank16 word-read isolation."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "qualification"
BASE = Q / "mcu_ahb_register_bank16_word_byte_halfword_waited_routed.json"
ROUTED = Q / "mcu_ahb_register_bank16_read_word0_gated_routed.json"
COMPOSER = Q / "compose_mcu_ahb_bank16_read_word0_gated.py"
CHECKER = Q / "check_mcu_ahb_bank16_read_word0_gated.py"
ROUTE_PLAN = Q / "mcu_ahb_bank16_read_word0_gate_routes.json"
LOCAL_EXCHANGE = Q / "mcu_ahb_bank16_read_word0_local_exchange.json"
FIRMWARE = Q / "mcu_ahb_bank16_read_word0_gated_test.c"
RUNNER = Q / "run_mcu_ahb_bank16_read_word0_gated.py"
LEDGER = Q / "mcu_ahb_bank16_read_isolation_evidence.jsonl"


def top(path):
    return json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]


def test_composer_reproduces_the_silicon_route_and_all_structural_invariants(tmp_path):
    output = tmp_path / "routed.json"
    result = subprocess.run(
        [sys.executable, str(COMPOSER), "--mode", "real", "--out", str(output)],
        cwd=ROOT, check=True, capture_output=True, text=True)
    assert output.read_bytes() == ROUTED.read_bytes()
    audit = subprocess.run([sys.executable, str(CHECKER)], cwd=ROOT, check=True,
                           capture_output=True, text=True)
    assert "16 feedback paths, 16 MCU sinks" in audit.stdout
    assert "wire ownership" in audit.stdout


def test_read_decoder_and_sixteen_output_gates_are_exact():
    design = top(ROUTED)
    cells = design["cells"]
    decoder = cells["read_word0"]
    assert decoder["attributes"]["NEXTPNR_BEL"] == "X14Y12_SLICE5"
    assert int(decoder["parameters"]["INIT"], 2) == 0x1111
    enable = decoder["connections"]["F"][0]
    for lane in range(16):
        gate = cells[f"read_gate{lane}"]
        assert int(gate["parameters"]["INIT"], 2) == 0x8888
        assert gate["connections"]["I"][1] == enable
    assert all(cells[f"feedback_buffer{lane}"] == top(BASE)["cells"][f"feedback_buffer{lane}"]
               for lane in range(16))


def test_oracle_uses_four_real_word_offsets_and_retains_subword_write_checks():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for spelling in ("word[0]", "word[1]", "word[2]", "word[3]",
                     "half[0]", "byte[0]", "byte[1]"):
        assert spelling in firmware
    assert 'for opcode in ("lw", "sw", "sh", "sb")' in runner
    assert "explicit lw offset" in runner
    assert "mww 0x20001000 0x00000000 17" in runner
    assert "finally:" in runner and "cleanup_board()" in runner


def test_silicon_record_binds_artifacts_and_bounded_scope():
    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    assert record["result"] == "pass_exact_16_bit_read_word_offset_isolation"
    assert "Ten sequential SRAM-only hardware runs" in record["observed"]
    assert "byte-read lane semantics" in record["scope"]
    assert "pinned checkpoint" in record["consequence"]
    for field, path in (("base_routed_sha256", BASE), ("routed_sha256", ROUTED),
                        ("composer_sha256", COMPOSER), ("checker_sha256", CHECKER),
                        ("route_plan_sha256", ROUTE_PLAN),
                        ("local_exchange_sha256", LOCAL_EXCHANGE),
                        ("test_sha256", FIRMWARE), ("runner_sha256", RUNNER)):
        assert record[field] == hashlib.sha256(path.read_bytes()).hexdigest()
