"""Fail-closed D0 maturity/evidence policy for bitstream emission."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from agamemnon.engine.features import FEATURES
from agamemnon.engine.registry import (
    CONSTANTS,
    CONSTANT_CLAIMS,
    ELECTRICAL_OPTIONS,
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


def _default_promotion_ok(claim):
    """Whether a claim is witnessed enough for amendment-gated default promotion.

    Predicted/decoded/unwitnessed material can never satisfy this: it requires a
    differential-or-higher evidence tier, explicit owner approval, and zero
    conflicts, unknowns, or negative contradiction.  Callers pass
    ``default_promotion=True`` only for routing rows returned by the
    amendment-approved default path; this is the defense-in-depth second check so
    a caller bug still cannot promote a lie.
    """
    return (
        isinstance(claim, ClaimMetadata)
        and claim.evidence_tier in {
            "differentially_validated",
            "statistically_silicon_validated",
            "individually_qualified",
        }
        and claim.emits
        and claim.approval_state in {"approved", "preexisting_v4"}
        and bool(claim.approved_by)
        and bool(claim.review_date)
        and not claim.conflict_count
        and not claim.unknown_count
        and not claim.negative_conflict
    )


def _permission_error(name, maturity, claim, policy, explicit, default_promotion=False):
    if not isinstance(claim, ClaimMetadata):
        return "%s: missing claim metadata (fail closed)" % name
    if claim.evidence_tier not in {
        "decoded", "differentially_validated",
        "statistically_silicon_validated", "individually_qualified",
    }:
        return "%s: missing or invalid evidence tier (fail closed)" % name
    # research-unsafe is intentionally an evidence-preserving escape hatch. It
    # may consume decoded, conflicted, or incomplete knowledge, but the policy
    # sidecar must disclose that fact. Silicon-negative routing edges remain a
    # hard architecture blacklist and are never made executable by this branch.
    if policy == "research-unsafe":
        return None
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
    # D0 default-promotion amendment: a witnessed, approved-population
    # differentially_validated (or higher) row is eligible for the default
    # release graph for its exact witnessed encoding scope.  The caller only
    # sets this for routing rows the amendment approval gate has promoted; the
    # helper is the fail-closed second gate that predicted/decoded material can
    # never pass.  Archival emission is already rejected above, so promotion can
    # never enlarge the archival/unmapped surface.
    if default_promotion and _default_promotion_ok(claim):
        return None
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


def _direct_d_sites_error(options, policy):
    """Validate the CLI-derived direct-D narrowing list under strict policy.

    ``AGAMEMNON_DIRECT_D_SITES`` is not an independently qualified feature. It
    is an internal, per-design subset of the four sites already admitted by
    ``AGAMEMNON_DIRECT_D``.  Keeping it registered is necessary so architecture
    and bitgen share the value, but release maturity must not turn an arbitrary
    user-provided BEL into a qualified direct-D presentation.

    Research-unsafe deliberately retains access to recovered sites.  The one
    separately registered experiment may extend the strict pool only when its
    own option is enabled; the normal option loop still applies that
    experiment's evidence and explicit-selection policy.
    """
    raw = options.raw("AGAMEMNON_DIRECT_D_SITES")
    if not raw or policy == "research-unsafe":
        return None
    if not options.enabled("AGAMEMNON_DIRECT_D"):
        return (
            "option:AGAMEMNON_DIRECT_D_SITES: internal narrowing list "
            "requires AGAMEMNON_DIRECT_D=1"
        )
    allowed = {
        "X14Y11_SLICE4", "X14Y11_SLICE5",
        "X14Y11_SLICE6", "X14Y11_SLICE7",
    }
    if options.enabled("AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT"):
        allowed.add("X15Y8_SLICE12")
    tokens = [item.strip() for item in str(raw).split(";")]
    invalid = sorted({
        token for token in tokens
        if not re.fullmatch(r"X\d+Y\d+_SLICE\d+", token) or token not in allowed
    })
    if invalid:
        return (
            "option:AGAMEMNON_DIRECT_D_SITES: strict builds require an exact "
            "subset of X14Y11_SLICE4..7; outside qualified pool: %s"
            % ",".join(invalid)
        )
    return None


def _vendor_out_slice_error(options, policy):
    """Validate the CLI-derived output-pad F/Q presentation under strict policy.

    ``AGAMEMNON_VENDOR_OUT_SLICE`` is a general xyz slice-presentation override
    (also used, unrestricted, by research-unsafe left-pad TFF work); it is not
    itself an independently qualified feature. For release/experimental-strict
    it must be exactly one of the presentations silicon-qualified for a top-edge
    output pad in ``agamemnon/chipdb/pad_output_qualified_L48.csv`` --
    ``cli._qualified_pad_vendor_out`` only ever derives one of these four values
    from a requested PCF's qualified output pads, and never applies this option
    when a build cannot be attributed to that closed pool. Keeping the option
    registered at release maturity (so architecture and bitgen can share the
    value under strict policy at all) must not let an arbitrary ambient/manual
    value pass as a qualified presentation.
    """
    raw = options.raw("AGAMEMNON_VENDOR_OUT_SLICE")
    if not raw or policy == "research-unsafe":
        return None
    allowed = {"14,9,4", "14,9,8", "14,9,10", "14,9,15"}
    if raw not in allowed:
        return (
            "option:AGAMEMNON_VENDOR_OUT_SLICE: strict builds require an exact "
            "pad_output_qualified_L48.csv F/Q presentation; outside qualified "
            "pool: %s" % raw
        )
    return None


def _part_device_error(options):
    """Validate AGAMEMNON_PART names a known family part matching AGAMEMNON_DEVICE.

    AGAMEMNON_PART (agamemnon/engine/family.py) is descriptive family-registry
    data -- flash size, PSRAM, ADC/DAC channel counts -- layered above
    AGAMEMNON_DEVICE, which remains the sole architecture/pin-legality
    selector. This only catches an internal contradiction (a part whose
    package does not match the selected device); it is not a strictness
    question, so it applies under every policy including research-unsafe.
    """
    if "AGAMEMNON_PART" not in options.environ:
        # Not explicitly selected: AGAMEMNON_DEVICE alone remains authoritative
        # (unchanged pre-T25 behavior), so an existing device-only caller is
        # never newly rejected over a part this build never named.
        return None

    from agamemnon.engine import family

    part_name = options.raw("AGAMEMNON_PART")
    try:
        part = family.get_part(part_name)
    except KeyError:
        return "option:AGAMEMNON_PART: unknown AG32 family part %r" % (part_name,)
    device = options.raw("AGAMEMNON_DEVICE")
    if part.device_id != device:
        return (
            "option:AGAMEMNON_PART=%s: package %s does not match "
            "AGAMEMNON_DEVICE=%s" % (part_name, part.device_id, device)
        )
    return None


def evaluate_policy(options, features=FEATURES, include_constants=True):
    policy = options.raw("AGAMEMNON_STRICT_POLICY")
    explicit = tuple(sorted({
        item.strip() for item in options.raw("AGAMEMNON_EXPERIMENTAL_FEATURES").split(",")
        if item.strip()
    }))
    selected = []
    errors = []
    if policy == "research-unsafe" and not options.enabled("AGAMEMNON_RESEARCH_UNSAFE"):
        errors.append(
            "research-unsafe requires AGAMEMNON_RESEARCH_UNSAFE=1; use the explicit CLI flag"
        )
    direct_d_sites_error = _direct_d_sites_error(options, policy)
    if direct_d_sites_error:
        errors.append(direct_d_sites_error)
    vendor_out_slice_error = _vendor_out_slice_error(options, policy)
    if vendor_out_slice_error:
        errors.append(vendor_out_slice_error)
    part_device_error = _part_device_error(options)
    if part_device_error:
        errors.append(part_device_error)

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

    # Per-part legality (T25 / GOAL_AG32_FAMILY_COVERAGE.md): the AG32 family
    # shares one AGRV2K fabric, so a fabric-logic-only build -- one that never
    # activates a physical/pad electrical surface -- is package-independent
    # and build-supported on every package. What stays package-scoped is the
    # physical/electrical claim itself (pad-out, pad-in, OE, weak pull-up,
    # open-drain, ...): those are silicon-qualified on AGRV2KL48 only, and a
    # capability qualified there never auto-transfers to another package by
    # coordinate or pin number. So gate on the exact surface a build actually
    # activates (ELECTRICAL_OPTIONS), not on the device name alone -- fixing
    # the former blanket reject of every non-L48 device regardless of surface.
    device = options.raw("AGAMEMNON_DEVICE")
    if device != "AGRV2KL48" and policy != "research-unsafe":
        # Deliberately options.enabled(), not _option_is_active(): the latter
        # treats every release-maturity option as permanently "active" (it
        # answers "is this in the permanent release surface", not "did this
        # build turn the flag on"), which would make this gate fire on every
        # non-L48 build regardless of whether it touches a pad.
        active_electrical = sorted(
            name for name in ELECTRICAL_OPTIONS if options.enabled(name)
        )
        if active_electrical:
            errors.append(
                "option:AGAMEMNON_DEVICE=%s: strict emission of a physical/"
                "electrical surface (%s) is qualified only for AGRV2KL48; "
                "Q32, L64, and L100 remain recovered, unqualified "
                "post-release package electrical data. A pad-free, "
                "fabric-logic-only build for this device is build-supported "
                "and does not hit this gate." % (device, ", ".join(active_electrical))
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

    # Rows returned without the opt-in experiment flag can only have come from the
    # amendment-approved default-promotion path in routing_admission (it enforces
    # the release-strict + L48 + approved-population gauntlet).  For those rows the
    # amendment makes their exact witnessed routing scope default-eligible.
    experiment_opt_in = options.enabled("AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT")
    for row in routing_rows:
        claim = routing_admission.claim_metadata(row)
        name = row["feature_id"]
        error = _permission_error(
            name, row["registry_maturity"], claim, policy, explicit,
            default_promotion=not experiment_opt_in,
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
    """Write the mandatory hash binding for a non-release policy image."""
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
