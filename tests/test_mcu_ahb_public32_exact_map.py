"""Production contract for the silicon-qualified exact public32 map."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "qualification"
BASE = Q / "mcu_ahb_public16_exact_map_routed.json"
ROUTED = Q / "mcu_ahb_public32_exact_map_routed.json"
COMPOSER = Q / "compose_mcu_ahb_public32_exact_map.py"
CHECKER = Q / "check_mcu_ahb_public32_exact_map.py"
GENERATOR = Q / "generate_mcu_ahb_bank16_read_word0_structural.py"
STRUCTURAL = Q / "mcu_ahb_public32_exact_map_structural.v"
FIRMWARE = Q / "mcu_ahb_public32_exact_map_test.c"
RUNNER = Q / "run_mcu_ahb_public32_exact_map.py"
LEDGER = Q / "mcu_ahb_public32_evidence.jsonl"
MAINTENANCE = Q / "mcu_ahb_exact_map_maintenance.json"
SILICON_LOGS = [
    Q / "mcu_ahb_public32_exact_map_openocd.log",
    Q / "mcu_ahb_public32_exact_map_openocd_run2.log",
    Q / "mcu_ahb_public32_exact_map_openocd_run3.log",
]


def sha(path):
    return canonical_text_sha(path)


def canonical_text_sha(path):
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def top(path):
    return json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]


def test_composer_is_hash_pinned_and_reproduces_checkpoint(tmp_path):
    output = tmp_path / "public32.json"
    before = ROUTED.read_bytes()
    result = subprocess.run([sys.executable, str(COMPOSER), "--out", str(output)],
                            cwd=Q, check=True, capture_output=True, text=True)
    assert output.read_bytes() == before == ROUTED.read_bytes()
    assert "136" in result.stdout and "104" in result.stdout
    assert sha(BASE) == "aa7ff307b6d59035928bf79306a3e55a69434e9458672a36ed51a7abe162c5fe"
    assert sha(ROUTED) == "ab76df409898241b0e631ac79926345ac4b4cd0783f0e02898d9f95e6525c574"


def test_checker_proves_reviewed_widening_boundary():
    result = subprocess.run([sys.executable, str(CHECKER)], cwd=Q, check=True,
                            capture_output=True, text=True)
    assert "2 reviewed LUT edits" in result.stdout
    assert "16 exact HRDATA exits" in result.stdout
    assert "canonical ID 0x4147414d" in result.stdout

    base, candidate = top(BASE), top(ROUTED)
    added = set(candidate["cells"]) - set(base["cells"])
    assert added == {"public_id_upper_select"} | {
        f"mcu_h{lane}" for lane in range(16, 32)}
    assert {name for name in base["cells"]
            if base["cells"][name] != candidate["cells"][name]} == {
                "read_gate8", "read_gate14"}


def test_structural_fixture_is_mechanically_regenerated():
    spec = importlib.util.spec_from_file_location("structural_generator", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text, emitted = module.generate(ROUTED)
    assert emitted == 135
    assert text.encode("ascii") == STRUCTURAL.read_bytes()


def test_pack_regression_pins_public32_image():
    manifest = json.loads((Q / "pack_regression.json").read_text(encoding="utf-8"))
    row = next(item for item in manifest["artifacts"]
               if item["routed"] ==
               "qualification/mcu_ahb_public32_exact_map_routed.json")
    assert row == {
        "routed": "qualification/mcu_ahb_public32_exact_map_routed.json",
        "routed_sha256":
            "ab76df409898241b0e631ac79926345ac4b4cd0783f0e02898d9f95e6525c574",
        "bitstream_sha256":
            "ac33ca6b4628258c62137e4c006ca25a222368e39c9a2e2d33a68e7b07dae6f5",
        "environment": {"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"},
    }


def test_oracle_is_exact_32_bit_compiler_audited_and_sram_only():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for spelling in ("0x4147414du", "half[1]!=0x4147u", "byte[3]!=0x41u",
                     "word[1]!=p", "c&~7u", "word[3]=3u"):
        assert spelling in firmware
    for spelling in ("--execute-sram", "expected 99,944-byte",
                     "_start is not exactly 0x20000000", "cleanup()",
                     '"lw", "lbu", "lhu", "sw", "sh", "sb", "fence"'):
        assert spelling in runner
    assert "finally:" in runner
    assert "flash" not in runner.lower()


def test_silicon_record_binds_all_production_artifacts():
    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    assert record["trial_id"] == "mcu-ahb-public32-exact-map-silicon-20260815"
    assert record["result"] == "pass_exact_public32_composed_map"
    assert record["hardware"] is True and record["flash_written"] is False
    assert record["runs"] == 3 and record["board_reset"] is True
    assert record["pack"]["unmapped"] == 0
    assert record["silicon_log_hashes"] == [
        canonical_text_sha(path) for path in SILICON_LOGS
    ]
    for field, path in (("base_routed_sha256", BASE),
                        ("routed_sha256", ROUTED),
                        ("source_sha256", STRUCTURAL),
                        ("generator_sha256", GENERATOR),
                        ("test_sha256", FIRMWARE),
                        ("runner_sha256", RUNNER)):
        assert record[field] == sha(path)
    maintained = json.loads(MAINTENANCE.read_text(encoding="utf-8"))["profiles"]["public32"]
    assert maintained["routed_sha256"] == sha(ROUTED)
    assert maintained["composer_sha256"] == sha(COMPOSER)
    assert maintained["checker_sha256"] == sha(CHECKER)
