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


def test_direct_d_site_list_is_a_qualified_narrowing_not_a_new_feature():
    name = "AGAMEMNON_DIRECT_D_SITES"
    assert OPTION_CLAIMS[name].evidence_tier == "individually_qualified"
    decision = evaluate_policy(options_from({
        "AGAMEMNON_DIRECT_D": "1",
        name: "X14Y11_SLICE4;X14Y11_SLICE7",
    }))
    selected = [row for row in decision.selected if row.get("name") == name]
    assert len(selected) == 1
    assert selected[0]["value"] == "X14Y11_SLICE4;X14Y11_SLICE7"
    assert selected[0]["maturity"] == "release"


def test_direct_d_site_list_cannot_broaden_the_release_pool():
    with pytest.raises(ClaimPolicyError, match="outside qualified pool: X15Y8_SLICE12"):
        evaluate_policy(options_from({
            "AGAMEMNON_DIRECT_D": "1",
            "AGAMEMNON_DIRECT_D_SITES": "X14Y11_SLICE4;X15Y8_SLICE12",
        }))


def test_direct_d_experiment_site_still_uses_its_own_evidence_gate():
    experiment = "AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT"
    with pytest.raises(ClaimPolicyError, match="differential or higher"):
        evaluate_policy(options_from({
            "AGAMEMNON_STRICT_POLICY": "experimental-strict",
            "AGAMEMNON_EXPERIMENTAL_FEATURES": experiment,
            "AGAMEMNON_DIRECT_D": "1",
            "AGAMEMNON_DIRECT_D_SITES": "X15Y8_SLICE12",
            experiment: "1",
        }))


def test_direct_d_site_list_requires_its_parent_presentation():
    with pytest.raises(ClaimPolicyError, match="requires AGAMEMNON_DIRECT_D=1"):
        evaluate_policy(options_from({
            "AGAMEMNON_DIRECT_D_SITES": "X14Y11_SLICE4",
        }))


def test_research_unsafe_preserves_recovered_direct_d_sites():
    decision = evaluate_policy(options_from({
        "AGAMEMNON_STRICT_POLICY": "research-unsafe",
        "AGAMEMNON_RESEARCH_UNSAFE": "1",
        "AGAMEMNON_DIRECT_D": "1",
        "AGAMEMNON_DIRECT_D_SITES": "X99Y99_SLICE99",
    }))
    assert decision.policy == "research-unsafe"


@pytest.mark.parametrize("device", ["AGRV2KQ32", "AGRV2KL64", "AGRV2KL100"])
@pytest.mark.parametrize("policy", ["release-strict", "experimental-strict"])
def test_pad_free_non_l48_devices_are_build_supported(device, policy):
    """T25: a fabric-logic-only build is package-independent (one shared fabric).

    This used to be a blanket reject of every non-L48 device regardless of
    surface (the T21 finding). The AG32 family shares one AGRV2K fabric, so a
    build that never touches a physical/electrical surface must be admitted
    on every package -- only the physical/electrical claim itself stays
    package-scoped (see test_electrical_surface_still_fails_closed_for_unqualified_packages).
    """
    decision = evaluate_policy(options_from({
        "AGAMEMNON_DEVICE": device,
        "AGAMEMNON_STRICT_POLICY": policy,
    }))
    assert decision.policy == policy


@pytest.mark.parametrize("device", ["AGRV2KQ32", "AGRV2KL64", "AGRV2KL100"])
@pytest.mark.parametrize("policy", ["release-strict", "experimental-strict"])
@pytest.mark.parametrize("electrical_option", [
    "AGAMEMNON_PHYSICAL_IO", "AGAMEMNON_LEDPADS", "AGAMEMNON_PADFEED_TOP",
    "AGAMEMNON_HARDEN_PADFEED", "AGAMEMNON_LEFT_PAD_OUT",
])
def test_electrical_surface_still_fails_closed_for_unqualified_packages(device, policy, electrical_option):
    """The physical/electrical claim itself never auto-transfers off AGRV2KL48."""
    environment = {
        "AGAMEMNON_DEVICE": device,
        "AGAMEMNON_STRICT_POLICY": policy,
        electrical_option: "1",
    }
    if policy == "experimental-strict":
        environment["AGAMEMNON_EXPERIMENTAL_FEATURES"] = electrical_option
    with pytest.raises(ClaimPolicyError, match="qualified only for AGRV2KL48"):
        evaluate_policy(options_from(environment))


def test_research_unsafe_still_admits_electrical_surface_on_unqualified_packages():
    """research-unsafe is the one policy the per-surface gate never applies to."""
    decision = evaluate_policy(options_from({
        "AGAMEMNON_STRICT_POLICY": "research-unsafe",
        "AGAMEMNON_RESEARCH_UNSAFE": "1",
        "AGAMEMNON_DEVICE": "AGRV2KL100",
        "AGAMEMNON_PHYSICAL_IO": "1",
    }))
    assert decision.policy == "research-unsafe"


def test_part_must_name_a_known_family_part():
    with pytest.raises(ClaimPolicyError, match="unknown AG32 family part"):
        evaluate_policy(options_from({"AGAMEMNON_PART": "BOGUS"}))


def test_part_must_match_the_selected_device():
    with pytest.raises(ClaimPolicyError, match="package AGRV2KL48 does not match AGAMEMNON_DEVICE=AGRV2KL100"):
        evaluate_policy(options_from({
            "AGAMEMNON_DEVICE": "AGRV2KL100",
            "AGAMEMNON_PART": "AG32VF303CCT6",
        }))


def test_part_consistent_with_device_is_admitted_on_a_pad_free_build():
    decision = evaluate_policy(options_from({
        "AGAMEMNON_DEVICE": "AGRV2KL100",
        "AGAMEMNON_PART": "AG32VF407VGT6",
    }))
    assert decision.policy == "release-strict"
    part_row = next(row for row in decision.selected if row.get("name") == "AGAMEMNON_PART")
    assert part_row["value"] == "AG32VF407VGT6"
    assert part_row["evidence_tier"] == "individually_qualified"


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


def test_research_unsafe_requires_explicit_gate_and_preserves_unqualified_data():
    with pytest.raises(ClaimPolicyError, match="AGAMEMNON_RESEARCH_UNSAFE=1"):
        evaluate_policy(options_from({"AGAMEMNON_STRICT_POLICY": "research-unsafe"}))
    decision = evaluate_policy(options_from({
        "AGAMEMNON_STRICT_POLICY": "research-unsafe",
        "AGAMEMNON_RESEARCH_UNSAFE": "1",
        "AGAMEMNON_DEVICE": "AGRV2KL100",
        "AGAMEMNON_XBAR_FULL": "1",
        "AGAMEMNON_MESH_TEMPLATE": "1",
    }))
    assert decision.policy == "research-unsafe"
    selected = {row.get("name") for row in decision.selected}
    assert {"AGAMEMNON_RESEARCH_UNSAFE", "AGAMEMNON_XBAR_FULL", "AGAMEMNON_MESH_TEMPLATE"} <= selected


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


def test_experimental_sidecar_accepts_parent_validated_routed_snapshot_digest(tmp_path):
    routed = tmp_path / "routed.json"
    output = tmp_path / "image.bin"
    sidecar = tmp_path / "image.policy.json"
    routed.write_bytes(b'{"validated":true}\n')
    snapshot_digest = hashlib.sha256(routed.read_bytes()).hexdigest()
    routed.write_bytes(b'{"mutated":true}\n')
    output.write_bytes(b"image")
    decision = PolicyDecision("experimental-strict", (), ("trial",))
    payload = write_sidecar(
        sidecar,
        decision,
        routed,
        output,
        routed_sha256=snapshot_digest,
    )
    assert payload["bindings"]["routed_sha256"] == snapshot_digest
