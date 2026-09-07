"""Reproducible behavioral gate for the Area-A addsub16 placement keystone."""

import collections
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "qualification" / "placement_keystone" / "area_a_addsub16_structural"
RESULT = json.loads((CASE / "result.json").read_text(encoding="utf-8"))
CURRENT = json.loads((CASE / "current_result.json").read_text(encoding="utf-8"))


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_lf(path):
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _clean_engine_environment():
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith("AGAMEMNON_") and not key.startswith("AGRV2K_")
    }


def test_frozen_input_and_routed_artifact_are_exact_and_complete():
    source = ROOT / RESULT["input"]["path"]
    routed = ROOT / RESULT["place_route"]["default"]["routed_path"]
    migration = RESULT["n57a_metadata_migration"]
    assert source.stat().st_size == RESULT["input"]["bytes"]
    assert _sha256(source) == RESULT["input"]["sha256"]
    assert routed.stat().st_size == migration["post_migration_routed_bytes"]
    assert _sha256(routed) == migration["post_migration_routed_sha256"]

    module = json.loads(routed.read_text(encoding="utf-8"))["modules"]["top"]
    for key, value in migration["added_top_attributes"].items():
        assert module["attributes"][key] == value
    types = collections.Counter(cell["type"] for cell in module["cells"].values())
    routed_nets = [
        net for net in module["netnames"].values()
        if net.get("attributes", {}).get("ROUTING")
    ]
    assert len(module["cells"]) == RESULT["place_route"]["default"]["placed_cells"]
    assert types["GENERIC_SLICE"] == 158
    assert all(cell.get("attributes", {}).get("NEXTPNR_BEL")
               for cell in module["cells"].values())
    assert len(routed_nets) == RESULT["place_route"]["default"]["routed_nets"]


@pytest.mark.parametrize("historical", [False, True])
def test_route_emission_preserves_current_pass_and_historical_refusal(tmp_path, historical):
    routed = ROOT / (RESULT["place_route"]["default"]["routed_path"] if historical else CURRENT["routed_path"])
    if not historical:
        assert _sha256(routed) == CURRENT["routed_sha256"]
        module = json.loads(routed.read_text())["modules"]["top"]
        assert int(module["cells"]["core_i.reset_commit_lut.s"]["parameters"]["INIT"], 2) == 0x8080
    output = tmp_path / "placement_keystone.bin"
    env = _clean_engine_environment()
    env.update(RESULT["strict_emission"]["environment"])
    completed = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack",
         str(routed), str(output)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    combined = completed.stdout + completed.stderr
    if historical:
        assert completed.returncode != 0
        assert "INIT depends on unconnected I[3]" in combined
        assert not output.exists() and not Path(str(output) + ".comp").exists()
        return
    assert completed.returncode == 0, combined
    assert "REQUALIFICATION BUILD" not in combined
    assert output.stat().st_size == CURRENT["raw_bytes"]
    assert _sha256(output) == CURRENT["raw_sha256"]
    compressed = Path(str(output) + ".comp")
    assert compressed.stat().st_size == CURRENT["compressed_bytes"]
    assert _sha256(compressed) == CURRENT["compressed_sha256"]
    assert "0 legacy-abs, 0 predicted), 0 unmapped" in combined


def test_frozen_route_passes_offline_routed_netlist_validation():
    routed = ROOT / RESULT["place_route"]["default"]["routed_path"]
    completed = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "verify", str(routed),
         "--cycles", str(RESULT["offline_validator"]["cycles"])],
        cwd=ROOT,
        env=_clean_engine_environment(),
        capture_output=True,
        text=True,
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 0, combined
    assert "AHB 0x60000000): [0]" in combined
    assert "MCU_DOUT bind" in combined and ": OK" in combined


def test_compiled_default_vs_legacy_behavioral_ab(tmp_path):
    binary_value = os.environ.get("AGAMEMNON_PLACEMENT_KEYSTONE_NEXTPNR")
    devdb_value = os.environ.get("AGAMEMNON_PLACEMENT_KEYSTONE_DEVDB")
    runtime_value = os.environ.get("AGAMEMNON_PLACEMENT_KEYSTONE_RUNTIME_DIR")
    if not binary_value or not devdb_value or not runtime_value:
        pytest.skip("set the nextpnr, runtime, and strict-devdb paths to run the compiled A/B")

    binary = Path(binary_value)
    devdb = Path(devdb_value)
    assert _sha256(binary) == RESULT["nextpnr"]["binary_sha256"]
    assert _sha256(devdb / "dev_pips.csv") == RESULT["strict_devdb"]["dev_pips_sha256"]
    assert _sha256(devdb / "dev_bels.csv") == RESULT["strict_devdb"]["dev_bels_sha256"]

    source = ROOT / RESULT["input"]["path"]
    common_env = _clean_engine_environment()
    common_env.update(RESULT["place_route"]["common_environment"])
    common_env["PATH"] = runtime_value + os.pathsep + common_env.get("PATH", "")

    def run_arm(name, delta):
        output = tmp_path / (name + ".json")
        env = dict(common_env)
        env.update(delta)
        command = [
            str(binary), "--uarch", "agrv2k", "-o", "chipdb=" + str(devdb),
            "--json", str(source), "--write", str(output), "--router", "router2",
            "--top", "top", "--freq", "10", "--placer", "heap", "--seed", "3",
        ]
        completed = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
        )
        return completed, output

    default, default_output = run_arm("default", {})
    default_log = default.stdout + default.stderr
    assert default.returncode == 0, default_log
    assert _sha256_lf(default_output) == RESULT["place_route"]["default"]["routed_sha256"]
    for marker in RESULT["place_route"]["default"]["required_markers"]:
        assert marker in default_log

    legacy_delta = RESULT["place_route"]["legacy"]["environment_delta"]
    assert legacy_delta == {"AGRV2K_SOFT_RIPPLE_LEGACY": "1"}
    legacy, legacy_output = run_arm("legacy", legacy_delta)
    legacy_log = legacy.stdout + legacy.stderr
    assert legacy.returncode != 0
    assert not legacy_output.exists()
    for marker in RESULT["place_route"]["legacy"]["required_markers"]:
        assert marker in legacy_log
