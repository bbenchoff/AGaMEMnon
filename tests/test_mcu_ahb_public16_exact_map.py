"""Production contract for the exact silicon-qualified public16 map."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "qualification"
BASE = Q / "mcu_ahb_register_bank16_public_scratch4_routed.json"
PUBLIC = Q / "mcu_ahb_register_bank_complete_byte_waited_routed.json"
ROUTED = Q / "mcu_ahb_public16_exact_map_routed.json"
COMPOSER = Q / "compose_mcu_ahb_public16_exact_map.py"
CHECKER = Q / "check_mcu_ahb_public16_exact_map.py"
GENERATOR = Q / "generate_mcu_ahb_bank16_read_word0_structural.py"
STRUCTURAL = Q / "mcu_ahb_public16_exact_map_structural.v"
FIRMWARE = Q / "mcu_ahb_public16_exact_map_test.c"
RUNNER = Q / "run_mcu_ahb_public16_exact_map.py"
LEDGER = Q / "mcu_ahb_public16_evidence.jsonl"
MAINTENANCE = Q / "mcu_ahb_exact_map_maintenance.json"


def sha(path):
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_text_hash_contract_is_canonical_lf():
    spec = importlib.util.spec_from_file_location("public16_composer", COMPOSER)
    composer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(composer)
    expected = hashlib.sha256(b"first\nsecond\n").hexdigest()
    assert composer.text_sha256(b"first\r\nsecond\r") == expected
    assert composer.text_sha256(b"first\nsecond\n") == expected


def top(path):
    return json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]


def test_composer_is_hash_pinned_and_honours_explicit_output(tmp_path):
    output = tmp_path / "public16.json"
    before = ROUTED.read_bytes()
    result = subprocess.run(
        [sys.executable, str(COMPOSER), "--out", str(output)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert output.read_bytes() == before == ROUTED.read_bytes()
    assert str(output) in result.stdout
    source = COMPOSER.read_text(encoding="utf-8")
    assert "BASE_SHA256" in source and "PUBLIC_SHA256" in source
    assert "OUTPUT_SHA256" in source
    assert sha(BASE) == "97f164a72b22ea2f076f889ee771b577f482384469266dc489e0b2f243590610"
    assert sha(PUBLIC) == "2eaaff39770df92f42da8e4498437ab415e90a904fb9d5381542452e5548894b"
    assert sha(ROUTED) == "aa7ff307b6d59035928bf79306a3e55a69434e9458672a36ed51a7abe162c5fe"


def test_composer_uses_packaged_strict_snapshot_on_clean_checkout(
        tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("public16_clean_composer", COMPOSER)
    composer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(composer)
    monkeypatch.setattr(composer, "DEVDB", tmp_path / "absent-generated-devdb")
    assert composer.text_sha256(composer.compose()) == composer.OUTPUT_SHA256


def test_checker_proves_reviewed_composition_boundary():
    result = subprocess.run([sys.executable, str(CHECKER)], cwd=ROOT,
                            check=True, capture_output=True, text=True)
    assert "101-cell +4 base retained" in result.stdout
    assert "18 exact added cells" in result.stdout
    assert "119 unique BELs, 103 routed nets" in result.stdout
    assert "structural source regenerated exactly" in result.stdout

    base, candidate = top(BASE), top(ROUTED)
    added = set(candidate["cells"]) - set(base["cells"])
    assert len(base["cells"]) == 101
    assert len(candidate["cells"]) == 119
    assert len(added) == 18
    assert all(name.startswith("public_") for name in added)
    mutated = {name for name in base["cells"]
               if base["cells"][name] != candidate["cells"][name]}
    assert mutated == {"write_wait_stage", "read_gate0", "read_gate1",
                       "read_gate2", "read_gate3", "read_gate6"}
    assert all(candidate["cells"][f"capture{index}"] ==
               base["cells"][f"capture{index}"] for index in range(16))
    assert all(candidate["cells"][f"feedback_buffer{index}"] ==
               base["cells"][f"feedback_buffer{index}"] for index in range(16))


def test_structural_fixture_is_mechanically_regenerated():
    spec = importlib.util.spec_from_file_location("bank16_structural_generator",
                                                  GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text, emitted = module.generate(ROUTED)
    assert emitted == 118
    assert text.encode("ascii") == STRUCTURAL.read_bytes()


def test_pack_regression_pins_public16_image():
    manifest = json.loads((Q / "pack_regression.json").read_text(encoding="utf-8"))
    row = next(item for item in manifest["artifacts"]
               if item["routed"] ==
               "qualification/mcu_ahb_public16_exact_map_routed.json")
    assert row == {
        "routed": "qualification/mcu_ahb_public16_exact_map_routed.json",
        "routed_sha256":
            "aa7ff307b6d59035928bf79306a3e55a69434e9458672a36ed51a7abe162c5fe",
        "bitstream_sha256":
            "3fd36e5b3a7f79c6da195315921658e44343513de9a85960c99e3cf638aff481",
        "environment": {"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"},
    }


def test_oracle_is_explicitly_sram_only_and_compiler_audited():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for spelling in ("word[0]", "word[1]", "word[2]", "word[3]",
                     "half[2]", "byte[4]", "byte[5]", "0xc0ffee1au"):
        assert spelling in firmware
    for spelling in ("--execute-sram", "expected 99,944-byte",
                     "_start is not exactly 0x20000000", "cleanup()",
                     '"lw", "lbu", "lhu", "sw", "sh", "sb", "fence"'):
        assert spelling in runner
    assert "finally:" in runner
    assert "flash" not in runner.lower()


def test_silicon_record_binds_every_production_artifact():
    records = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    record = next(row for row in records if row["trial_id"] ==
                  "mcu-ahb-public16-exact-map-silicon-20260815")
    assert record["result"] == "pass_exact_public16_composed_map"
    assert record["hardware"] is True and record["flash_written"] is False
    assert record["runs"] == 4 and record["board_reset"] is True
    for field, path in (("base_routed_sha256", BASE),
                        ("public_donor_sha256", PUBLIC),
                        ("routed_sha256", ROUTED),
                        ("source_sha256", STRUCTURAL),
                        ("generator_sha256", GENERATOR),
                        ("test_sha256", FIRMWARE),
                        ("runner_sha256", RUNNER)):
        assert record[field] == sha(path)
    maintained = json.loads(MAINTENANCE.read_text(encoding="utf-8"))["profiles"]["public16"]
    assert maintained["routed_sha256"] == sha(ROUTED)
    assert maintained["composer_sha256"] == sha(COMPOSER)
    assert maintained["checker_sha256"] == sha(CHECKER)
