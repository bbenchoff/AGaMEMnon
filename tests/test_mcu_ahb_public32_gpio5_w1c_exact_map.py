"""Production contract for the exact public32 GPIO5 level-set W1C profile."""

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
ROUTED = Q / "mcu_ahb_public32_gpio5_w1c_exact_map_routed.json"
OR_CONTROL = Q / "mcu_ahb_public32_gpio5_w1c_or_control_routed.json"
COMPOSER = Q / "compose_mcu_ahb_public32_gpio5_w1c_exact_map.py"
CHECKER = Q / "check_mcu_ahb_public32_gpio5_w1c_exact_map.py"
GENERATOR = Q / "generate_mcu_ahb_bank16_read_word0_structural.py"
STRUCTURAL = Q / "mcu_ahb_public32_gpio5_w1c_exact_map_structural.v"
FIRMWARE = Q / "mcu_ahb_public32_gpio5_w1c_exact_map_test.c"
RUNNER = Q / "run_mcu_ahb_public32_gpio5_w1c_exact_map.py"
LEDGER = Q / "mcu_ahb_public32_gpio5_w1c_evidence.jsonl"
MAINTENANCE = Q / "mcu_ahb_exact_map_maintenance.json"
LOGS = {
    "negative": Q / "mcu_ahb_public32_gpio5_w1c_negative_openocd.log",
    "or_control": Q / "mcu_ahb_public32_gpio5_w1c_or_control_openocd.log",
    "production": [
        Q / "mcu_ahb_public32_gpio5_w1c_openocd_run1.log",
        Q / "mcu_ahb_public32_gpio5_w1c_openocd_run2.log",
        Q / "mcu_ahb_public32_gpio5_w1c_openocd_run3.log",
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
    production = tmp_path / "production.json"
    control = tmp_path / "or.json"
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
    assert sha(ROUTED) == "a067a7328b06c20bc6c050bcd7e968cafdda9471ed57477c771652c48bb2d3ea"
    assert sha(OR_CONTROL) == "fd788250f6ff9b0fa9373e477472bc8d59ece2a0c914e3704c545f63ed5751a6"


def test_checker_proves_the_bounded_event_cone():
    result = subprocess.run([sys.executable, str(CHECKER)], cwd=Q, check=True,
                            capture_output=True, text=True)
    assert "old bit1 set branch removed only in production" in result.stdout
    assert "138 BELs/106 nets" in result.stdout
    base, candidate = top(BASE), top(ROUTED)
    assert set(candidate["cells"]) - set(base["cells"]) == {
        "mcu_gpio5_status_set", "public_status_gpio5_relay"}
    assert {name for name in base["cells"]
            if base["cells"][name] != candidate["cells"][name]} == {
                "public_set_event"}
    assert candidate["cells"]["mcu_gpio5_status_set"]["type"] == \
        "MCU_GPIO5_OUT_DATA0"
    assert candidate["cells"]["mcu_gpio5_status_set"]["attributes"][
        "NEXTPNR_BEL"] == "X10Y5_MCU_GPIO5_OUT_DATA0262"


def test_structural_fixture_is_mechanically_regenerated():
    spec = importlib.util.spec_from_file_location("structural_generator", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text, emitted = module.generate(ROUTED)
    assert emitted == 137
    assert text.encode("ascii") == STRUCTURAL.read_bytes()


def test_pack_regression_pins_the_production_image():
    manifest = json.loads((Q / "pack_regression.json").read_text(encoding="utf-8"))
    row = next(item for item in manifest["artifacts"]
               if item["routed"] ==
               "qualification/mcu_ahb_public32_gpio5_w1c_exact_map_routed.json")
    assert row == {
        "routed": "qualification/mcu_ahb_public32_gpio5_w1c_exact_map_routed.json",
        "routed_sha256":
            "a067a7328b06c20bc6c050bcd7e968cafdda9471ed57477c771652c48bb2d3ea",
        "bitstream_sha256":
            "22350353960954803d647099f94327daf6f882381fb13ad0460ca8fb9060d69a",
        "environment": {"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"},
    }
    control = next(item for item in manifest["artifacts"]
                   if item["routed"] ==
                   "qualification/mcu_ahb_public32_gpio5_w1c_or_control_routed.json")
    assert control["routed_sha256"] == \
        "fd788250f6ff9b0fa9373e477472bc8d59ece2a0c914e3704c545f63ed5751a6"
    assert control["bitstream_sha256"] == \
        "12a2ccf38938674159813aad550026459e84f96215d06b544d0b105c37e8cfdf"
    assert control["environment"] == row["environment"]


def test_common_oracle_and_runner_encode_all_three_causal_modes():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for spelling in ("status_source(1)", "word[3]=2u", "word[3]=1u",
                     "GPIO_DIR(GPIO5)=(1u<<0)", "GPIO_DIR(GPIO5)=0u",
                     "0x4147414du", "half[1]!=0x4147u", "c&~7u"):
        assert spelling in firmware
    for spelling in ('"negative"', '"or-control"', '"production"',
                     '"status_errors": 162', '"status_errors": 2',
                     '"status_errors": 0', "--execute-sram", "finally:",
                     "mww 0x40019004 0", "mww 0x40019400 0"):
        assert spelling in runner
    assert "flash" not in "\n".join(
        line for line in runner.lower().splitlines()
        if "reject" not in line and "no command" not in line and
        "any(" not in line and "for command" not in line)


def test_silicon_record_binds_controls_production_and_logs():
    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    assert record["result"] == "pass_exact_public32_gpio5_level_set_w1c"
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
        "public32_gpio5_w1c"]
    assert maintained["routed_sha256"] == sha(ROUTED)
    assert maintained["composer_sha256"] == sha(COMPOSER)
    assert maintained["checker_sha256"] == sha(CHECKER)
    assert record["silicon_log_hashes"] == {
        "negative": canonical_sha(LOGS["negative"]),
        "or_control": canonical_sha(LOGS["or_control"]),
        "production": [canonical_sha(path) for path in LOGS["production"]],
    }
    assert "not a package-pin input" in record["scope"]
    assert "not" in record["scope"] and "asynchronous" in record["scope"]


def test_sdk_profile_and_registry_bind_the_exact_evidence():
    profiles = json.loads((ROOT / "agamemnon" / "sdk" /
                           "qualified_fabric_profiles.json").read_text(
                               encoding="utf-8"))["profiles"]
    profile = profiles["l48-public32-gpio5-w1c-exact-map-2026-08-15"]
    record = json.loads(LEDGER.read_text(encoding="utf-8").strip())
    template = ROOT / "agamemnon" / "templates" / "mcu-fpga-registers"
    source = template / profile["source"]
    routed = template / profile["routed"]
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
    assert "not a package-pin input" in profile["scope"]


def test_sdk_ships_a_matching_gpio5_firmware_example_and_register_names():
    template = ROOT / "agamemnon" / "templates" / "mcu-fpga-registers"
    source = (template / "src" / "main_gpio5_w1c.c").read_text(encoding="utf-8")
    header = (ROOT / "agamemnon" / "sdk" / "include" / "ag32.h").read_text(
        encoding="utf-8")
    for spelling in ("APBCLK_GPIO5", "GPIO5_DATA", "GPIO5_DIR", "GPIO5_AFSEL"):
        assert spelling in source and spelling in header
    for spelling in ("status_source(0u);", "status_source(1u);",
                     "GPIO5_DIR &= ~(1u << 0)", "result[7] == 1u",
                     "result[8] == 0u"):
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
    # main_gpio5_w1c.c reproducibly read 0xf7 (3/3). The loop must instead
    # keep sampling until coverage is actually observed (bounded, so a
    # genuinely stuck or miswired counter still fails closed instead of
    # spinning forever), which makes the pass/fail outcome depend on real
    # counter behavior rather than on incidental instruction timing.
    source = (ROOT / "agamemnon" / "templates" / "mcu-fpga-registers" /
              "src" / "main_gpio5_w1c.c").read_text(encoding="utf-8")
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
