"""Fail-closed D0 maturity/evidence policy for bitstream emission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from agamemnon.engine.features import FEATURES
from agamemnon.engine.registry import (
    CONSTANTS,
    CONSTANT_CLAIMS,
    OPTIONS,
    OPTION_CLAIMS,
    POLICY_VERSION,
    ClaimMetadata,
    manifest,
)


class ClaimPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class PolicyDecision:
    policy: str
    selected: tuple[dict, ...]
    explicit_experimental: tuple[str, ...]

    def to_dict(self):
        return {
            "policy": self.policy,
            "policy_version": POLICY_VERSION,
            "explicit_experimental": list(self.explicit_experimental),
            "selected": list(self.selected),
        }


def _permission_error(name, maturity, claim, policy, explicit):
    if not isinstance(claim, ClaimMetadata):
        return "%s: missing claim metadata (fail closed)" % name
    if claim.evidence_tier not in {
        "decoded", "differentially_validated",
        "statistically_silicon_validated", "individually_qualified",
    }:
        return "%s: missing or invalid evidence tier (fail closed)" % name
    if claim.conflict_count or claim.unknown_count or claim.negative_conflict:
        return "%s: claim metadata records conflicts, unknowns, or negative contradiction" % name
    if claim.individual_only and claim.evidence_tier == "statistically_silicon_validated":
        return "%s: individual-only domain cannot be admitted by statistical evidence" % name
    if claim.evidence_tier == "statistically_silicon_validated":
        if (
            claim.statistical_trials is None or claim.statistical_trials < 300
            or claim.statistical_failures != 0
            or claim.statistical_images is None or claim.statistical_images < 10
            or claim.statistical_contexts is None or claim.statistical_contexts < 3
            or claim.statistical_sram_cycles is None or claim.statistical_sram_cycles < 3
            or 3.0 / claim.statistical_trials > 0.01
        ):
            return "%s: statistical tier requires >=300 zero-failure trials, 10 images, 3 contexts, 3 SRAM cycles, and a <=1%% rule-of-three bound" % name
    if claim.evidence_tier == "individually_qualified" and not claim.evidence_refs:
        return "%s: individual qualification requires an oracle/evidence reference" % name
    if not claim.emits and maturity == "diagnostic":
        return None
    if maturity == "archival":
        return "%s: archival/unmapped emission is incompatible with strict policy" % name
    if policy == "release-strict":
        if maturity != "release":
            return "%s: release-strict requires release maturity" % name
        if claim.evidence_tier not in {
            "statistically_silicon_validated", "individually_qualified",
        }:
            return "%s: release-strict requires statistical or individual evidence after review" % name
        if claim.approval_state not in {"approved", "preexisting_v4"} or not claim.approved_by or not claim.review_date:
            return "%s: release-strict requires recorded approval and review" % name
        return None
    if policy == "experimental-strict":
        if maturity == "release":
            return _permission_error(name, maturity, claim, "release-strict", explicit)
        if maturity == "diagnostic" and not claim.emits:
            return None
        if name not in explicit and name.removeprefix("option:") not in explicit:
            return "%s: experimental-strict requires an explicit feature ID" % name
        if claim.evidence_tier not in {
            "differentially_validated", "statistically_silicon_validated",
            "individually_qualified",
        }:
            return "%s: experimental-strict requires differential or higher evidence" % name
        return None
    return "unsupported strict policy %r" % policy


def _option_is_active(name, spec, options):
    environment = options.environ
    if spec.maturity == "release":
        return True
    if name not in environment:
        return False
    value = options.raw(name)
    if spec.kind == "flag":
        return bool(value)
    # Experimental tuning defaults describe the legacy baseline and are not a
    # new experimental selection unless the caller changes them.
    return value not in (None, "") and value != spec.default


def evaluate_policy(options, features=FEATURES, include_constants=True):
    policy = options.raw("AGAMEMNON_STRICT_POLICY")
    explicit = tuple(sorted({
        item.strip() for item in options.raw("AGAMEMNON_EXPERIMENTAL_FEATURES").split(",")
        if item.strip()
    }))
    selected = []
    errors = []

    # Routing-wave rows are not options and must not inherit the blanket
    # release qualification of sel_edge_pairs.agdb. Resolve their exact
    # row-tiered claims from the same admission loader used by architecture
    # and bitgen. An empty bootstrap manifest contributes no selected claim.
    from agamemnon.engine import routing_admission
    packaged_chipdb = Path(__file__).resolve().parent.parent / "chipdb"
    chipdb_root = options.raw("AGAMEMNON_DATA", str(packaged_chipdb))
    try:
        routing_rows = routing_admission.selected_rows(options, chipdb_root)
        routing_binding = routing_admission.selected_binding(
            options, chipdb_root, routing_rows
        )
    except routing_admission.RoutingAdmissionError as exc:
        routing_rows = ()
        routing_binding = None
        errors.append(str(exc))

    # The first release is deliberately package-scoped.  Decoded bond maps for
    # the other AGRV2K packages remain useful architecture data, but none has
    # the L48 silicon/electrical qualification required to emit a strict image.
    # Keep that research surface inspectable while failing before synthesis or
    # bitstream emission whenever a build selects an unqualified package.
    device = options.raw("AGAMEMNON_DEVICE")
    if device != "AGRV2KL48":
        errors.append(
            "option:AGAMEMNON_DEVICE=%s: strict emission is qualified only "
            "for AGRV2KL48; Q32, L64, and L100 remain recovered, "
            "unqualified post-release package data" % device
        )

    for feature in features:
        descriptor = feature.descriptor
        claim = ClaimMetadata(
            evidence_tier=descriptor.evidence_tier,
            claim_domain="electrical" if descriptor.feature_id in {"clocks", "physical_io"} else "configuration",
            claim_scope="preexisting V4 release scope",
            policy_version=POLICY_VERSION,
            approval_state="preexisting_v4",
            approved_by="Brian Benchoff",
            review_date="2026-08-05",
            individual_only=descriptor.feature_id in {"clocks", "physical_io"},
            emits=True,
            evidence_refs=descriptor.evidence,
        )
        name = "feature:%s" % descriptor.feature_id
        error = _permission_error(name, descriptor.maturity, claim, policy, explicit)
        if error:
            errors.append(error)
        selected.append({"kind": "feature", "name": descriptor.feature_id,
                         "maturity": descriptor.maturity, **asdict(claim)})

    for row in routing_rows:
        claim = routing_admission.claim_metadata(row)
        name = row["feature_id"]
        error = _permission_error(
            name, row["registry_maturity"], claim, policy, explicit
        )
        if error:
            errors.append(error)
        selected.append({
            "kind": "routing_selector",
            "name": name,
            "edge_id": row["edge_id"],
            "row_identity": row["row_identity"],
            "maturity": row["registry_maturity"],
            **asdict(claim),
        })
    if routing_binding is not None:
        selected.append({
            "kind": "routing_selector_manifest",
            "name": routing_admission.OPTION_NAME,
            **routing_binding,
        })

    for name, spec in OPTIONS.items():
        if not _option_is_active(name, spec, options):
            continue
        claim = OPTION_CLAIMS.get(name)
        policy_name = "option:%s" % name
        error = _permission_error(policy_name, spec.maturity, claim, policy, explicit)
        if error:
            errors.append(error)
        selected.append({"kind": "option", "name": name, "value": options.raw(name),
                         "maturity": spec.maturity, **asdict(claim)})

    if include_constants:
        for name, spec in CONSTANTS.items():
            claim = CONSTANT_CLAIMS.get(name)
            policy_name = "constant:%s" % name
            error = _permission_error(policy_name, spec.maturity, claim, policy, explicit)
            if error:
                errors.append(error)
            selected.append({"kind": "constant", "name": name,
                             "maturity": spec.maturity, **asdict(claim)})

    if errors:
        raise ClaimPolicyError("claim policy rejected emission:\n- " + "\n- ".join(errors))
    return PolicyDecision(policy, tuple(selected), explicit)


def write_sidecar(path, decision, routed_path, output_path, extra=None):
    """Write the mandatory hash binding for an experimental-strict image."""
    registry_bytes = json.dumps(manifest(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload = {
        "schema": 1,
        "kind": "agamemnon-claim-policy-sidecar",
        **decision.to_dict(),
        "bindings": {
            "routed_sha256": hashlib.sha256(Path(routed_path).read_bytes()).hexdigest(),
            "registry_manifest_sha256": hashlib.sha256(registry_bytes).hexdigest(),
            "output_sha256": hashlib.sha256(Path(output_path).read_bytes()).hexdigest(),
            "output_bytes": Path(output_path).stat().st_size,
        },
    }
    if extra:
        payload["bindings"].update(extra)
    with Path(path).open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload
