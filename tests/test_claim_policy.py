import hashlib
import json
from dataclasses import replace

import pytest

from agamemnon.engine.claim_policy import (
    ClaimPolicyError,
    PolicyDecision,
    _permission_error,
    evaluate_policy,
    write_sidecar,
)
from agamemnon.engine.registry import OPTION_CLAIMS, ClaimMetadata, options_from


def _claim(tier="decoded", **changes):
    base = ClaimMetadata(
        evidence_tier=tier,
        claim_domain="configuration",
        claim_scope="test scope",
        policy_version="D0-v1",
        approval_state="approved",
        approved_by="test reviewer",
        review_date="2026-08-06",
        individual_only=False,
        emits=True,
        evidence_refs=("tests/test_claim_policy.py",),
    )
    return replace(base, **changes)


def test_default_release_policy_admits_the_preexisting_v4_surface():
    decision = evaluate_policy(options_from({}))
    assert decision.policy == "release-strict"
    assert {row["maturity"] for row in decision.selected} == {"release"}


@pytest.mark.parametrize("device", ["AGRV2KQ32", "AGRV2KL64", "AGRV2KL100"])
@pytest.mark.parametrize("policy", ["release-strict", "experimental-strict"])
def test_strict_emission_fails_closed_for_unqualified_packages(device, policy):
    with pytest.raises(ClaimPolicyError, match="qualified only for AGRV2KL48"):
        evaluate_policy(options_from({
            "AGAMEMNON_DEVICE": device,
            "AGAMEMNON_STRICT_POLICY": policy,
        }))


def test_missing_metadata_fails_closed():
    assert "missing claim metadata" in _permission_error(
        "option:missing", "release", None, "release-strict", ()
    )


def test_differential_evidence_is_experimental_only():
    claim = _claim("differentially_validated")
    assert "requires statistical or individual" in _permission_error(
        "option:trial", "release", claim, "release-strict", ("trial",)
    )
    assert _permission_error(
        "option:trial", "experimental", claim, "experimental-strict", ("trial",)
    ) is None


def test_statistical_release_floor_and_rule_of_three_are_enforced():
    valid = _claim(
        "statistically_silicon_validated",
        statistical_trials=300,
        statistical_failures=0,
        statistical_images=10,
        statistical_contexts=3,
        statistical_sram_cycles=3,
    )
    assert _permission_error("feature:trial", "release", valid, "release-strict", ()) is None
    assert "statistical tier requires" in _permission_error(
        "feature:trial", "release", replace(valid, statistical_trials=299),
        "release-strict", (),
    )


def test_individual_only_domain_rejects_statistical_admission():
    claim = _claim(
        "statistically_silicon_validated",
        individual_only=True,
        statistical_trials=300,
        statistical_failures=0,
        statistical_images=10,
        statistical_contexts=3,
        statistical_sram_cycles=3,
    )
    assert "individual-only" in _permission_error(
        "feature:clock", "release", claim, "release-strict", ()
    )


def test_experimental_selection_must_be_explicit_and_at_least_differential():
    differential = _claim("differentially_validated")
    assert "explicit feature ID" in _permission_error(
        "option:trial", "experimental", differential, "experimental-strict", ()
    )
    assert "differential or higher" in _permission_error(
        "option:trial", "experimental", _claim("decoded"),
        "experimental-strict", ("trial",),
    )


def test_archival_emission_is_never_strict_and_nonemitting_diagnostic_is_safe():
    assert "archival/unmapped" in _permission_error(
        "option:old", "archival", _claim("decoded"), "experimental-strict", ("old",)
    )
    assert _permission_error(
        "option:trace", "diagnostic", _claim("decoded", emits=False),
        "release-strict", (),
    ) is None


def test_current_decoded_experiment_is_rejected_without_promotion():
    name = "AGAMEMNON_X9_Q5_ALT_EXPERIMENT"
    assert OPTION_CLAIMS[name].evidence_tier == "decoded"
    with pytest.raises(ClaimPolicyError, match="differential or higher"):
        evaluate_policy(options_from({
            "AGAMEMNON_STRICT_POLICY": "experimental-strict",
            "AGAMEMNON_EXPERIMENTAL_FEATURES": name,
            name: "1",
        }))


def test_bram_b4_config_is_differential_experimental_only():
    name = "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG"
    claim = OPTION_CLAIMS[name]
    assert claim.evidence_tier == "differentially_validated"
    assert claim.approval_state == "approved"
    assert claim.approved_by == "Brian Benchoff"
    assert claim.review_date == "2026-08-09"
    assert claim.claim_domain == "configuration"
    assert claim.claim_scope == (
        "B4 config-encoding only; AGRV2KL48 X13Y1..Y4; "
        "behavior and silicon not established"
    )
    with pytest.raises(ClaimPolicyError, match="release-strict requires release maturity"):
        evaluate_policy(options_from({name: "1"}))
    with pytest.raises(ClaimPolicyError, match="explicit feature ID"):
        evaluate_policy(options_from({
            "AGAMEMNON_STRICT_POLICY": "experimental-strict",
            name: "1",
        }))
    decision = evaluate_policy(options_from({
        "AGAMEMNON_STRICT_POLICY": "experimental-strict",
        "AGAMEMNON_EXPERIMENTAL_FEATURES": name,
        name: "1",
    }))
    selected = [row for row in decision.selected if row.get("name") == name]
    assert len(selected) == 1
    assert selected[0]["maturity"] == "experimental"
    assert selected[0]["evidence_tier"] == "differentially_validated"


def test_experimental_sidecar_binds_input_manifest_and_output(tmp_path):
    routed = tmp_path / "routed.json"
    output = tmp_path / "image.bin"
    sidecar = tmp_path / "image.policy.json"
    routed.write_bytes(b'{"modules":{}}\n')
    output.write_bytes(b"image")
    decision = PolicyDecision("experimental-strict", (), ("trial",))
    payload = write_sidecar(sidecar, decision, routed, output)
    loaded = json.loads(sidecar.read_text(encoding="utf-8"))
    assert loaded == payload
    assert loaded["bindings"]["routed_sha256"] == hashlib.sha256(routed.read_bytes()).hexdigest()
    assert loaded["bindings"]["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert len(loaded["bindings"]["registry_manifest_sha256"]) == 64
