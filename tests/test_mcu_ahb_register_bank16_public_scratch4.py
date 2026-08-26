"""Pinned contract for the exact silicon-qualified +4 scratch profile."""

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
BASE = Q / "mcu_ahb_register_bank16_read_word0_gated_routed.json"
ROUTED = Q / "mcu_ahb_register_bank16_public_scratch4_routed.json"
COMPOSER = Q / "compose_mcu_ahb_bank16_public_scratch4.py"
CHECKER = Q / "check_mcu_ahb_bank16_public_scratch4.py"
STRUCTURAL = Q / "mcu_ahb_register_bank16_public_scratch4_structural.v"
GENERATOR = Q / "generate_mcu_ahb_bank16_read_word0_structural.py"
FIRMWARE = Q / "mcu_ahb_bank16_public_scratch4_test.c"
RUNNER = Q / "run_mcu_ahb_bank16_public_scratch4.py"
LEDGER = Q / "mcu_ahb_bank16_read_isolation_evidence.jsonl"


def top(path):
    return json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_composer_and_checker_reproduce_only_two_reviewed_init_changes(tmp_path):
    output = tmp_path / "candidate.json"
    subprocess.run([sys.executable, str(COMPOSER), "--out", str(output)],
                   cwd=ROOT, check=True)
    assert output.read_bytes() == ROUTED.read_bytes()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run([sys.executable, str(CHECKER)], cwd=ROOT, env=env,
                            check=True, capture_output=True, text=True)
    assert "exactly two INIT changes" in result.stdout
    base, candidate = top(BASE), top(ROUTED)
    assert len(base["cells"]) == len(candidate["cells"]) == 101
    assert sum("ROUTING" in net.get("attributes", {})
               for net in base["netnames"].values()) == 83
    assert base["cells"]["hwrite_word0_gate"]["parameters"]["INIT"] == \
        "0000000001000100"
    assert candidate["cells"]["hwrite_word0_gate"]["parameters"]["INIT"] == \
        "0000000010001000"
    assert base["cells"]["read_word0"]["parameters"]["INIT"] == \
        "0001000100010001"
    assert candidate["cells"]["read_word0"]["parameters"]["INIT"] == \
        "0010001000100010"
    for name, cell in base["cells"].items():
        assert cell["attributes"]["NEXTPNR_BEL"] == \
            candidate["cells"][name]["attributes"]["NEXTPNR_BEL"]
    for name, net in base["netnames"].items():
        assert net.get("attributes", {}).get("ROUTING") == \
            candidate["netnames"][name].get("attributes", {}).get("ROUTING")


def test_variant_structural_fixture_is_generator_reproducible():
    spec = importlib.util.spec_from_file_location("bank16_structural_generator",
                                                  GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text, emitted = module.generate(ROUTED)
    assert emitted == 100
    assert text.encode("ascii") == STRUCTURAL.read_bytes()


def test_pack_regression_pins_candidate_hashes():
    manifest = json.loads((Q / "pack_regression.json").read_text(encoding="utf-8"))
    row = next(item for item in manifest["artifacts"]
               if item["routed"] ==
               "qualification/mcu_ahb_register_bank16_public_scratch4_routed.json")
    assert row["routed_sha256"] == sha(ROUTED) == \
        "97f164a72b22ea2f076f889ee771b577f482384469266dc489e0b2f243590610"
    assert row["bitstream_sha256"] == \
        "2aa4d1d65c57c1ae28612f5743b08a7683179786e2d467c20166add1fba60882"
    assert row["environment"] == {"AGAMEMNON_HSE": "8",
                                  "AGAMEMNON_SYSCLK": "10"}


def test_production_oracle_is_explicitly_sram_only_and_compiler_audited():
    firmware = FIRMWARE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for spelling in ("word[1]", "half[2]", "byte[4]", "byte[5]",
                     "word[0]", "word[2]", "word[3]", "0xc0ffee24u"):
        assert spelling in firmware
    for spelling in ("exact-load/store-offsets", "--execute-sram",
                     "expected a 99,944-byte", "cleanup_board()"):
        assert spelling in runner
    assert "flash" not in runner.lower()


def test_registered_profile_replays_source_to_exact_candidate_image(tmp_path):
    oss = ROOT.parent / "AG32-Docs" / "tools" / "oss-cad-suite"
    if not (oss / "bin" / "yosys.exe").exists():
        pytest.skip("sibling OSS CAD Suite is not installed")
    output = tmp_path / "plus4.bin"
    env = dict(os.environ)
    for name in list(env):
        if name.startswith("AGAMEMNON_"):
            del env[name]
    env.update({"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10",
                "AGAMEMNON_OSS": str(oss)})
    result = subprocess.run([
        sys.executable, "-m", "agamemnon.cli", "build", str(STRUCTURAL),
        "--uarch", "--qualified-checkpoint",
        "mcu-ahb-bank16-public-scratch4", "--output", str(output),
    ], cwd=ROOT, env=env, check=True, capture_output=True, text=True,
       timeout=120)
    assert "exact raw/compressed hashes verified" in result.stdout
    assert sha(output) == \
        "2aa4d1d65c57c1ae28612f5743b08a7683179786e2d467c20166add1fba60882"
    assert sha(Path(str(output) + ".comp")) == \
        "dd20ea9549bf0d5f0c4dc09988a2696aeab57cb4f299ac12c136e4842e04e516"
    # The exact hard-boundary corridor map now gates both architecture and
    # emission. The former x=13 blind-formula fallback is absent from strict
    # routing, while this qualified checkpoint and both image hashes remain
    # byte-identical. Keep the zero-debt assertion tight: any future legacy,
    # predicted, or unmapped selector is a real review event.
    assert "0 legacy-abs, 0 predicted), 0 unmapped" in result.stdout


def test_qualified_profile_rejects_raw_paths_and_ambient_escape_knobs(tmp_path):
    clean = {name: value for name, value in os.environ.items()
             if not name.startswith("AGAMEMNON_")}
    clean.update({"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "10"})
    base = [sys.executable, "-m", "agamemnon.cli", "build", str(STRUCTURAL),
            "--uarch", "--output", str(tmp_path / "rejected.bin")]
    raw_path = subprocess.run(
        base + ["--qualified-checkpoint", str(ROUTED)], cwd=ROOT, env=clean,
        capture_output=True, text=True)
    assert raw_path.returncode == 2
    assert "unknown qualified route profile" in raw_path.stdout
    escaped = dict(clean)
    escaped["AGAMEMNON_ALLOW_UNMAPPED"] = "1"
    ambient = subprocess.run(
        base + ["--qualified-checkpoint",
                "mcu-ahb-bank16-public-scratch4"],
        cwd=ROOT, env=escaped, capture_output=True, text=True)
    assert ambient.returncode == 2
    assert "forbids ambient option" in ambient.stdout


def test_silicon_record_binds_exact_scope_and_every_production_artifact():
    records = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    record = next(row for row in records if row["trial_id"] ==
                  "mcu-ahb-register-bank16-public-scratch4-silicon-20260815")
    assert record["result"] == "pass_exact_16_bit_plus4_rebased_scratch_semantics"
    assert record["hardware"] is True and record["flash_written"] is False
    assert record["runs"] == 3
    assert "public ID/counter/W1C coexistence" in record["scope"]
    for field, path in (("base_routed_sha256", BASE),
                        ("routed_sha256", ROUTED),
                        ("composer_sha256", COMPOSER),
                        ("checker_sha256", CHECKER),
                        ("source_sha256", STRUCTURAL),
                        ("generator_sha256", GENERATOR),
                        ("test_sha256", FIRMWARE),
                        ("runner_sha256", RUNNER)):
        assert record[field] == sha(path)
