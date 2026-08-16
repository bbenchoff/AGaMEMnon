"""Pinned contract for the silicon-qualified bank16 word-read isolation."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


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
SUBWORD_FIRMWARE = Q / "mcu_ahb_bank16_subword_read_test.c"
SUBWORD_RUNNER = Q / "run_mcu_ahb_bank16_subword_read.py"
STRUCTURAL = Q / "mcu_ahb_register_bank16_read_word0_structural.v"
STRUCTURAL_GENERATOR = Q / "generate_mcu_ahb_bank16_read_word0_structural.py"
ROUTE_REPLAY = ROOT / "agamemnon" / "engine" / "route_replay.py"
CLI = ROOT / "agamemnon" / "cli.py"
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
    records = [json.loads(line) for line in
               LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    record = next(row for row in records if
                  row["trial_id"] ==
                  "mcu-ahb-register-bank16-read-word0-isolation-silicon-20260815")
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


def test_cpu_subword_oracle_is_real_aligned_code_and_evidence_is_bounded():
    firmware = SUBWORD_FIRMWARE.read_text(encoding="utf-8")
    runner = SUBWORD_RUNNER.read_text(encoding="utf-8")
    for spelling in ("LOAD_BU0", "LOAD_BU1", "LOAD_BU2", "LOAD_BU3",
                     "LOAD_HU0", "LOAD_HU2", "0xa53c80f1u"):
        assert spelling in firmware
    assert 'for opcode in ("lw", "lbu", "lhu", "sw", "sh", "sb")' in runner
    assert "oracle emitted a misaligned halfword load" in runner
    assert "mww 0x20001000 0x00000000 17" in runner
    assert "finally:" in runner and "cleanup_board()" in runner

    records = [json.loads(line) for line in
               LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    record = next(row for row in records if
                  row["trial_id"] ==
                  "mcu-ahb-register-bank16-cpu-subword-read-silicon-20260815")
    assert record["result"] == "pass_exact_16_bit_cpu_visible_aligned_subword_reads"
    assert "Three SRAM-only hardware runs" in record["observed"]
    assert "raw HRDATA[31:16]" in record["scope"]
    assert "misaligned halfword loads" in record["scope"]
    assert record["routed_sha256"] == hashlib.sha256(ROUTED.read_bytes()).hexdigest()
    assert record["test_sha256"] == hashlib.sha256(SUBWORD_FIRMWARE.read_bytes()).hexdigest()
    assert record["runner_sha256"] == hashlib.sha256(SUBWORD_RUNNER.read_bytes()).hexdigest()


def test_structural_source_exact_route_replay_reproduces_qualified_image(tmp_path):
    oss = ROOT.parent / "AG32-Docs" / "tools" / "oss-cad-suite"
    if not (oss / "bin" / "yosys.exe").exists():
        pytest.skip("sibling OSS CAD Suite is not installed")
    output = tmp_path / "replay.bin"
    routed = tmp_path / "replay_routed.json"
    env = dict(os.environ)
    for name in list(env):
        if name.startswith("AGAMEMNON_"):
            del env[name]
    env.update({"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10",
                "AGAMEMNON_OSS": str(oss)})
    result = subprocess.run([
        sys.executable, "-m", "agamemnon.cli", "build", str(STRUCTURAL),
        "--uarch", "--qualified-checkpoint", "mcu-ahb-bank16-read-word0",
        "--output", str(output), "--write-routed", str(routed),
    ], cwd=ROOT, env=env, check=True, capture_output=True, text=True,
       timeout=120)
    assert "exact route replay verified cells=101 nets=83" in result.stdout
    assert hashlib.sha256(output.read_bytes()).hexdigest() == \
        "301edbab67a42edcfb958d4dda7f3ffba786d425123a7c27826fccfba6765160"
    assert hashlib.sha256(Path(str(output) + ".comp").read_bytes()).hexdigest() == \
        "5b90b852722c2e78b1d417ca804b42cbadd13e303aa75914f9a51358232f9bae"
    assert "0 legacy-abs, 0 predicted), 0 unmapped" in result.stdout
    assert "not portable canonical RTL" in STRUCTURAL.read_text(encoding="ascii")
    assert STRUCTURAL_GENERATOR.exists()


def test_structural_source_generator_is_byte_reproducible():
    spec = importlib.util.spec_from_file_location("bank16_structural_generator",
                                                  STRUCTURAL_GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text, emitted = module.generate()
    assert emitted == 100
    assert text.encode("ascii") == STRUCTURAL.read_bytes()


def test_source_replay_record_binds_the_exact_fixture_and_fail_closed_tool():
    records = [json.loads(line) for line in
               LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    record = next(row for row in records if row["trial_id"] ==
                  "mcu-ahb-register-bank16-exact-source-route-replay-20260815")
    assert record["result"] == "pass_exact_source_to_qualified_route_reproduction"
    for field, path in (("checkpoint_sha256", ROUTED),
                        ("source_sha256", STRUCTURAL),
                        ("generator_sha256", STRUCTURAL_GENERATOR),
                        ("route_replay_sha256", ROUTE_REPLAY),
                        ("cli_sha256", CLI)):
        canonical = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert record[field] == hashlib.sha256(canonical).hexdigest()
    assert "zero legacy-absolute, predicted or unmapped" in record["observed"]
    assert "not qualify the structural fixture as portable canonical RTL" in record["scope"]
