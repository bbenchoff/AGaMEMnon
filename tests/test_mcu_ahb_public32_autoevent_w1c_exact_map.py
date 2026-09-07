"""Production contract for the exact public32 autonomous-event W1C profile."""

import hashlib
import importlib.util
import json
from pathlib import Path
import re
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
MAINTENANCE = Q / "mcu_ahb_exact_map_maintenance.json"
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
    return canonical_sha(path)


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
        "bitstream_sha256": "6d01c463eca293e09989f141f62220f43a896d148a5be10d6196d4eed4698e9e",
        "environment": {"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"},
    }
    assert control["routed_sha256"] == \
        "3b840a7100110db781ce63caed10cec8f4af1328fe8c11be294b3cd9d7217198"
    assert control["bitstream_sha256"] == \
        "a81b02a8c02d6efe54a9dabbc3f001aea0d8aaa555d2fa2d21e826757a71d0c7"
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
    for field, path in (("source_sha256", STRUCTURAL),
                        ("test_sha256", FIRMWARE),
                        ("runner_sha256", RUNNER)):
        assert record[field] == sha(path)
    maintained = json.loads(MAINTENANCE.read_text(encoding="utf-8"))["profiles"][
        "public32_autoevent_w1c"]
    assert maintained["routed_sha256"] == sha(ROUTED)
    assert maintained["composer_sha256"] == sha(COMPOSER)
    assert maintained["checker_sha256"] == sha(CHECKER)
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
    evidence_path, trial = profile["evidence"].split("#")
    current = next(row for row in json.loads(
        (ROOT / evidence_path).read_text(encoding="utf-8"))["records"]
        if row["trial_id"] == trial)
    assert record["bitstream_sha256"] == current["previous_bitstream_sha256"]
    assert profile["image_sha256"] == current["bitstream_sha256"]
    assert profile["compressed_sha256"] == current["compressed_sha256"]
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


def _coverage_loop_condition(source):
    """Pull the `for (...)` condition clause of the free-running-counter
    coverage-sampling loop (the one that fills `word[2]` samples into
    `seen` immediately before `result[6] = seen;`)."""
    needle = "uint32_t counter = word[2];"
    idx = source.index(needle)
    for_start = source.rindex("for (", 0, idx)
    for_end = source.index(")", for_start)
    clauses = source[for_start + len("for ("):for_end].split(";")
    assert len(clauses) == 3, source[for_start:for_end]
    return clauses[1].strip()


def test_counter_coverage_self_check_is_robust_to_poll_timing():
    # 2026-08-16 CHANGELOG: this self-check's claim (`result[6] == 0xff`,
    # every one of the free-running counter's 8 states observed) was timing
    # -sensitive to each firmware's own exact instruction count -- a fixed
    # 512-iteration trip count only "proves" coverage for whichever exact
    # CPU/AHB wait-state timing it happened to be tuned against.
    # main_autoevent_w1c.c varied run to run (0xf5/0xfd/0xff). The loop must
    # instead keep sampling until coverage is actually observed (bounded, so
    # a genuinely stuck or miswired counter still fails closed instead of
    # spinning forever), which makes the pass/fail outcome depend on real
    # counter behavior rather than on incidental instruction timing.
    source = (ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
              "src" / "main_autoevent_w1c.c").read_text(encoding="utf-8")
    condition = _coverage_loop_condition(source)
    assert "seen" in condition and "0xff" in condition, (
        "coverage loop must exit on OBSERVED full coverage (seen == 0xff), "
        "not purely on a fixed trip count picked to match one build's "
        "instruction timing: " + condition
    )
    bound = int(re.search(r"<\s*([0-9]+)", condition).group(1))
    assert bound >= 4096, (
        f"safety cap ({bound}) is too tight to reliably out-soak "
        "CPU<->fabric clock-domain-crossing jitter"
    )
    # The final verdict must still require full, exact coverage -- the fix
    # must not relax what counts as a pass.
    assert "result[6] == 0xffu" in source
