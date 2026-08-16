"""Production contract for the exact public32 autonomous-event W1C profile."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
Q = ROOT / "qualification"
BASE = Q / "mcu_ahb_public32_exact_map_routed.json"
ROUTED = Q / "mcu_ahb_public32_autoevent_w1c_exact_map_routed.json"
OR_CONTROL = Q / "mcu_ahb_public32_autoevent_w1c_or_control_routed.json"
COMPOSER = Q / "compose_mcu_ahb_public32_autoevent_w1c_exact_map.py"
CHECKER = Q / "check_mcu_ahb_public32_autoevent_w1c_exact_map.py"
GENERATOR = Q / "generate_mcu_ahb_bank16_read_word0_structural.py"
STRUCTURAL = Q / "mcu_ahb_public32_autoevent_w1c_exact_map_structural.v"
FIRMWARE = Q / "mcu_ahb_public32_autoevent_w1c_exact_map_test.c"
RUNNER = Q / "run_mcu_ahb_public32_autoevent_w1c_exact_map.py"
LEDGER = Q / "mcu_ahb_public32_autoevent_w1c_evidence.jsonl"
LOGS = {
    "negative": Q / "mcu_ahb_public32_autoevent_w1c_negative_openocd.log",
    "or_control": Q / "mcu_ahb_public32_autoevent_w1c_or_control_openocd.log",
    "production": [
        Q / "mcu_ahb_public32_autoevent_w1c_openocd_run1.log",
        Q / "mcu_ahb_public32_autoevent_w1c_openocd_run2.log",
        Q / "mcu_ahb_public32_autoevent_w1c_openocd_run3.log",
    ],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(path):
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def top(path):
    return json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]


def test_composer_reproduces_production_and_or_control(tmp_path):
    production, control = tmp_path / "production.json", tmp_path / "or.json"
    result = subprocess.run(
        [sys.executable, str(COMPOSER), "--out", str(production)],
        cwd=Q, check=True, capture_output=True, text=True)
    subprocess.run(
        [sys.executable, str(COMPOSER), "--or-control", "--out", str(control)],
        cwd=Q, check=True, capture_output=True, text=True)
    assert production.read_bytes() == ROUTED.read_bytes()
    assert control.read_bytes() == OR_CONTROL.read_bytes()
    assert "cells=138 routed_nets=106" in result.stdout
    assert sha(BASE) == "ab76df409898241b0e631ac79926345ac4b4cd0783f0e02898d9f95e6525c574"
    assert sha(ROUTED) == "d2368d6209a8f113beb67cc2a2b4d2cdd0b6f3b922fd3005b467009281f849c5"
    assert sha(OR_CONTROL) == "3b840a7100110db781ce63caed10cec8f4af1328fe8c11be294b3cd9d7217198"


def test_checker_proves_the_bounded_autonomous_cone():
    result = subprocess.run([sys.executable, str(CHECKER)], cwd=Q, check=True,
                            capture_output=True, text=True)
    assert "reset-rearmed count==7 one-shot" in result.stdout
    assert "138 unique BELs / 106 routed nets" in result.stdout
    base, candidate = top(BASE), top(ROUTED)
    assert set(candidate["cells"]) - set(base["cells"]) == {
        "autonomous_count7", "autonomous_armed"}
    assert {name for name in base["cells"]
            if base["cells"][name] != candidate["cells"][name]} == {
                "public_set_event"}
    assert candidate["cells"]["autonomous_count7"]["attributes"][
        "NEXTPNR_BEL"] == "X17Y11_SLICE0"
    assert candidate["cells"]["autonomous_armed"]["attributes"][
        "NEXTPNR_BEL"] == "X17Y11_SLICE1"


def test_structural_fixture_is_mechanically_regenerated():
    spec = importlib.util.spec_from_file_location("structural_generator", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text, emitted = module.generate(ROUTED)
    assert emitted == 137
    assert text.encode("ascii") == STRUCTURAL.read_bytes()


def test_pack_regression_pins_both_causal_images():
    manifest = json.loads((Q / "pack_regression.json").read_text(encoding="utf-8"))
    rows = {item["routed"]: item for item in manifest["artifacts"]}
    production = rows[
        "qualification/mcu_ahb_public32_autoevent_w1c_exact_map_routed.json"]
    control = rows[
        "qualification/mcu_ahb_public32_autoevent_w1c_or_control_routed.json"]
    assert production == {
        "routed": "qualification/mcu_ahb_public32_autoevent_w1c_exact_map_routed.json",
        "routed_sha256": "d2368d6209a8f113beb67cc2a2b4d2cdd0b6f3b922fd3005b467009281f849c5",
        "bitstream_sha256": "cb8372e669833ef103638d4f64ad86cf0e841cb448a9350dbafb79ad33ba1a9b",
        "environment": {"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"},
    }
    assert control["routed_sha256"] == \
        "3b840a7100110db781ce63caed10cec8f4af1328fe8c11be294b3cd9d7217198"
    assert control["bitstream_sha256"] == \
        "297a5116cd71c8987f1850a459a940fc16c85d8e3492183b2b6d5bbaddcc1aca"
    assert control["environment"] == production["environment"]


def test_common_oracle_and_runner_encode_three_causal_signatures():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for spelling in ("status_signature", "word[3]=2u", "word[3]=1u",
                     "gpio_reset(0)", "0x4147414du", "half[1]!=0x4147u",
                     "c&~7u"):
        assert spelling in firmware
    for spelling in ('"negative"', '"or-control"', '"production"',
                     '"status_errors": 0x04', '"status_errors": 0x15',
                     '"status_errors": 0x11', "--execute-sram", "finally:"):
        assert spelling in runner
    assert "program " not in runner.lower()


def test_silicon_record_binds_controls_production_and_logs():
    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    assert record["result"] == \
        "pass_exact_public32_autonomous_synchronous_one_shot_w1c"
    assert record["runs"] == {"negative": 1, "or_control": 1, "production": 3}
    assert record["hardware"] is True and record["flash_written"] is False
    assert record["pack"]["unmapped"] == 0
    assert record["routed_sha256"] == sha(ROUTED)
    assert record["or_control_routed_sha256"] == sha(OR_CONTROL)
    for field, path in (("composer_sha256", COMPOSER),
                        ("checker_sha256", CHECKER),
                        ("source_sha256", STRUCTURAL),
                        ("test_sha256", FIRMWARE),
                        ("runner_sha256", RUNNER)):
        assert record[field] == sha(path)
    assert record["silicon_log_hashes"] == {
        "negative": canonical_sha(LOGS["negative"]),
        "or_control": canonical_sha(LOGS["or_control"]),
        "production": [canonical_sha(path) for path in LOGS["production"]],
    }
    assert "not a generic user-net" in record["scope"]
    assert "HCLK-synchronous" in record["scope"]


def test_sdk_profile_registry_and_template_bind_exact_evidence():
    profiles = json.loads((ROOT / "agamemnon" / "sdk" /
                           "qualified_fabric_profiles.json").read_text(
                               encoding="utf-8"))["profiles"]
    profile = profiles["l48-public32-autoevent-w1c-exact-map-2026-08-16"]
    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    template = ROOT / "agamemnon" / "templates" / "mcu-fpga-registers"
    source, routed = template / profile["source"], template / profile["routed"]
    assert sha(source) == profile["source_sha256"] == record["source_sha256"]
    assert sha(routed) == profile["routed_sha256"] == record["routed_sha256"]
    assert profile["image_sha256"] == record["bitstream_sha256"]
    assert profile["compressed_sha256"] == record["compressed_bitstream_sha256"]
    registry = (ROOT / "agamemnon" / "engine" / "registry.py").read_text(
        encoding="utf-8")
    assert profile["claim_constant"] in registry
    assert profile["image_sha256"] in registry
    assert "not a generic user-net" in profile["scope"]


def test_sdk_ships_matching_autoevent_example():
    source = (ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
              "src" / "main_autoevent_w1c.c").read_text(encoding="utf-8")
    for spelling in ("fabric_reset(0u);", "word[3] = 1u;",
                     "result[3] == 1u", "result[4] == 0u",
                     "result[8] == 1u", "result[9] == 0u"):
        assert spelling in source
