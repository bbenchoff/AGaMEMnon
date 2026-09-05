"""Bind the deliberate OMUX migration to exact, scoped silicon evidence."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon import project
from agamemnon.engine.registry import CONSTANTS

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "qualification/omux_owner_requalification_20260904.json"


def test_omux_migration_binds_exact_retained_artifacts():
    evidence = json.loads(EVIDENCE.read_text())
    registry = json.loads((ROOT / "qualification/pack_regression.json").read_text())
    artifacts = {row["routed"]: row for row in registry["artifacts"]}
    records = evidence["records"]
    assert evidence["schema"] == 1
    assert evidence["changed_artifacts"] == len(records) == 16
    assert evidence["unchanged_artifacts"] == len(artifacts) - len(records) == 42
    assert len({row["routed"] for row in records}) == 16
    assert len({row["bitstream_sha256"] for row in records}) == 16
    for record in records:
        artifact = artifacts[record["routed"]]
        for key in ("routed_sha256", "bitstream_sha256", "environment"):
            assert record[key] == artifact[key]
        canonical = (ROOT / record["routed"]).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(canonical).hexdigest() == record["routed_sha256"]
        assert record["previous_bitstream_sha256"] != record["bitstream_sha256"]
        assert record["hardware"] is True
        assert record["runs"] == 3
        assert record["control_status"] == "PASS"
        assert record["board_reset"] is True
        assert record["flash_written"] is False
        assert record["evidence"].startswith(
            "https://github.com/bbenchoff/AG32-Docs/tree/"
            "3f06059af91c68c8d320eda9dc2e32531c297029/tools/vendor_parity/"
        )
        assert len(record["report_sha256_lf"]) == 64
        assert "No wider package, timing or bus claim" in record["scope"]


def test_current_sdk_profiles_bind_requalification_without_widening_scope():
    evidence = json.loads(EVIDENCE.read_text())
    profiles = json.loads((ROOT / "agamemnon/sdk/qualified_fabric_profiles.json").read_text())["profiles"]
    records = {record["trial_id"]: record for record in evidence["records"]}
    selected = [profile for profile in profiles.values() if "previous_evidence" in profile]
    assert len(selected) == 5
    for profile in selected:
        path, trial = profile["evidence"].split("#")
        assert ROOT / path == EVIDENCE
        record = records[trial]
        assert profile["image_sha256"] == record["bitstream_sha256"]
        assert profile["routed_sha256"] == record["routed_sha256"]
        assert profile["evidence_routed_sha256"] == record["routed_sha256"]
        assert profile["compressed_sha256"] == record["compressed_sha256"]
        assert profile["compressed_bytes"] == record["compressed_bytes"]
        claim = CONSTANTS[profile["claim_constant"]]
        assert claim.value == record["bitstream_sha256"]
        assert ROOT / claim.evidence == EVIDENCE
        old_path, old_trial = profile["previous_evidence"].split("#")
        historical = [json.loads(line) for line in (ROOT / old_path).read_text().splitlines() if line.strip()]
        previous = next(row for row in historical if row["trial_id"] == old_trial)
        assert previous["bitstream_sha256"] == record["previous_bitstream_sha256"]


@pytest.mark.parametrize("profile_name", [
    "l48-complete-byte-waited-2026-08-05",
    "l48-public16-exact-map-2026-08-15",
    "l48-public32-exact-map-2026-08-15",
    "l48-public32-gpio5-w1c-exact-map-2026-08-15",
    "l48-public32-autoevent-w1c-exact-map-2026-08-16",
])
def test_normal_sdk_replays_each_migrated_profile(tmp_path, profile_name):
    destination = tmp_path / "migrated-sdk"
    project.cmd_new(SimpleNamespace(
        name=str(destination), template="mcu-fpga", board="ag32vf303-l48"
    ))
    loaded = project.Project.load(destination)
    loaded.fabric["qualified_profile"] = profile_name
    output = Path(project.build_qualified_fabric(loaded))
    profiles = json.loads((ROOT / "agamemnon/sdk/qualified_fabric_profiles.json").read_text())["profiles"]
    profile = profiles[profile_name]
    assert output.stat().st_size == profile["image_bytes"] == 99944
    assert hashlib.sha256(output.read_bytes()).hexdigest() == profile["image_sha256"]
    compressed = Path(str(output) + ".comp")
    assert compressed.stat().st_size == profile["compressed_bytes"]
    assert hashlib.sha256(compressed.read_bytes()).hexdigest() == profile["compressed_sha256"]
