"""Typed registry for AGRV2K engine switches and silicon-derived constants.

The architecture generator is executed by nextpnr with ``ctx`` and ``Loc``
injected as globals, while bitgen also runs as a standalone program.  Keeping
configuration here gives both entry points one definition of defaults, types,
scope, and evidence without importing either large engine body.

Boolean switches intentionally retain the historical *presence* semantics:
an unset or empty variable is false and every non-empty value (including
``"0"``) is true.  Changing that behavior would silently alter old campaign
replays.
"""

from __future__ import annotations

from collections import namedtuple
from dataclasses import asdict, dataclass
import hashlib
import json
import os


Option = namedtuple("Option", "default kind scope maturity evidence description")
Constant = namedtuple("Constant", "value maturity evidence description")


@dataclass(frozen=True)
class ClaimMetadata:
    """The independent evidence axis attached to one registered surface."""

    evidence_tier: str
    claim_domain: str
    claim_scope: str
    policy_version: str
    approval_state: str
    approved_by: str | None
    review_date: str | None
    individual_only: bool
    emits: bool
    evidence_refs: tuple[str, ...]
    retained_negative_refs: tuple[str, ...] = ()
    conflict_count: int = 0
    unknown_count: int = 0
    negative_conflict: bool = False
    statistical_trials: int | None = None
    statistical_failures: int | None = None
    statistical_images: int | None = None
    statistical_contexts: int | None = None
    statistical_sram_cycles: int | None = None
    individual_oracle: str | None = None


POLICY_VERSION = "D0-v1"
EVIDENCE_TIERS = {
    "decoded", "differentially_validated", "statistically_silicon_validated",
    "individually_qualified",
}


def _flag(scope, maturity, evidence, description):
    return Option(None, "flag", scope, maturity, evidence, description)


def _value(default, kind, scope, maturity, evidence, description):
    return Option(default, kind, scope, maturity, evidence, description)


# maturity is one of: release, archival, experimental, diagnostic.
OPTIONS = {
    "AGAMEMNON_STRICT_POLICY": _value("release-strict", "policy", "bitgen", "diagnostic", "docs/ENGINE_CONFIGURATION.md", "Select release-strict, experimental-strict, or research-unsafe claim-policy enforcement."),
    "AGAMEMNON_EXPERIMENTAL_FEATURES": _value("", "csv", "bitgen", "diagnostic", "docs/ENGINE_CONFIGURATION.md", "Comma-separated feature IDs explicitly admitted to one experimental-strict build."),
    "AGAMEMNON_POLICY_SIDECAR": _value(None, "path", "bitgen", "diagnostic", "docs/ENGINE_CONFIGURATION.md", "Override the path for the hash-bound claim-policy sidecar."),
    "AGAMEMNON_RESEARCH_UNSAFE": _flag("both", "diagnostic", "agamemnon/chipdb/research_knowledge_manifest.json", "Explicitly select the non-release recovered-knowledge profile and mandatory provenance sidecar."),
    "AGAMEMNON_DATA": _value(None, "path", "both", "release", "docs/ARCHITECTURE.md", "Override the packaged chip database."),
    "AGAMEMNON_DEVICE": _value("AGRV2KL48", "text", "arch", "release", "agamemnon/engine/device.py", "Select the package legality model."),
    "AGAMEMNON_PHYSICAL_IO": _flag("both", "release", "qualification/io_evidence.jsonl", "Enable physical package I/O routing and emission."),
    "AGAMEMNON_HW_CARRY": _flag("arch", "release", "qualification/carry_evidence.jsonl", "Expose the qualified dedicated-carry corridors."),
    "AGAMEMNON_CLEAN_SEL_GATE": _flag("both", "release", "agamemnon/chipdb/sel_edge_pairs.agdb", "Require exact conflict-free selector encodings."),
    "AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT": _flag("both", "experimental", "agamemnon/chipdb/routing_selector_admission.json", "Enable explicitly reviewed row-tiered routing selector encodings without changing the release table."),
    "AGAMEMNON_STRICT_GATE": _flag("arch", "release", "qualification/routing_evidence.jsonl", "Restrict routing to position-qualified edges."),
    "AGAMEMNON_CONDUCTION_GATE": _flag("arch", "release", "agamemnon/chipdb/master_conduction.csv", "Restrict routing to electrically conducting edges."),
    "AGAMEMNON_XBAR_CONDUCT": _flag("arch", "release", "agamemnon/chipdb/ff2_conduction.csv", "Prune dead intra-tile crossbar edges."),
    "AGAMEMNON_LEDPADS": _flag("arch", "release", "qualification/io_evidence.jsonl", "Expose physical pad BELs and the HSE clock input."),
    "AGAMEMNON_PADFEED_TOP": _flag("arch", "release", "agamemnon/chipdb/padfeed_L48_top.csv", "Expose qualified top-edge pad feeders."),
    "AGAMEMNON_HARDEN_PADFEED": _flag("arch", "release", "agamemnon/chipdb/padfeed_L48_top.csv", "Reject non-qualified alternatives into a pad feeder."),
    "AGAMEMNON_LEFT_PAD_OUT": _flag("both", "release", "qualification/left_edge_output_evidence.jsonl", "Enable the qualified left-edge output presentation."),
    "AGAMEMNON_DIRECT_D": _flag("both", "release", "qualification/mcu_bus_clock_evidence.jsonl", "Enable the qualified four-site direct-D presentation."),
    "AGAMEMNON_DIRECT_D_COMB_F2": _value(None, "xyz", "arch", "experimental", "qualification/mcu_ahb_register_bank_evidence.jsonl", "Use one hash-recorded default F2 combinational presentation inside the direct-D site pool."),
    "AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT": _flag("both", "experimental", "qualification/mcu_bus_clock_x15y8_s12_gpio_dff.v", "Expose the exact X15Y8 slice12 direct-D footprint for bounded silicon qualification."),
    "AGAMEMNON_BRAM_PORTB_EXIT": _flag("both", "release", "qualification/bram_evidence.jsonl", "Enable the qualified BRAM Port-B exit corridor."),
    "AGAMEMNON_BRAM_PORTB_MCU_EXIT": _flag("arch", "experimental", "agamemnon/chipdb/bram_portb_corridors.csv", "Enable the BRAM-to-MCU experimental corridor."),
    "AGAMEMNON_NO_BRAM_WL": _flag("arch", "archival", "agamemnon/chipdb/bram_wl.csv", "Disable the qualified BRAM final-hop whitelist."),
    "AGAMEMNON_BRAM_APPROACH": _flag("arch", "experimental", "agamemnon/chipdb/bram_approach.csv", "Enable the narrow BRAM approach whitelist."),
    "AGAMEMNON_X9_FULL_ADDRESS": _flag("arch", "experimental", "agamemnon/chipdb/bram_x9_haddr_paths.csv", "Expose the vendor-observed but not yet silicon-qualified x9 HADDR[6:11] ingress continuation."),
    "AGAMEMNON_BRAM_HSE_INPUT": _flag("bitgen", "experimental", "qualification/bram_evidence.jsonl", "Force the BRAM HSE input-enable footprint outside automatic x9 mode; diagnostic override only."),
    "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG": _flag("bitgen", "experimental", "agamemnon/chipdb/bram_config_admission.json", "Enable B4-admitted BRAM configuration encodings without claiming release behavior."),
    "AGAMEMNON_X9_Q5_ALT_EXPERIMENT": _flag("both", "experimental", "qualification/bram_evidence.jsonl", "Expose the retained negative alternate q5/RMUX75 corridor for bounded causal-direction experiments."),
    "AGAMEMNON_PIPELINED_APPLY_EXPERIMENT": _flag("arch", "experimental", "qualification/mcu_ahb_register_bank_evidence.jsonl", "Expose retained candidate apply-stage paths for bounded pipelined register-bank experiments."),
    "AGAMEMNON_SCRATCH3_EXPERIMENT": _flag("arch", "experimental", "qualification/mcu_ahb_register_bank_evidence.jsonl", "Expose the scratch3 internal candidate path set for bounded register-bank experiments."),
    "AGAMEMNON_BRAM_ALL_EDGES": _flag("arch", "archival", "agamemnon/chipdb/bram_resolver.json", "Expose BRAM pips the bit generator cannot necessarily emit."),
    "AGAMEMNON_VENDOR_OUT_SLICE": _value(None, "xyz", "both", "experimental", "qualification/left_pad_vendor_tff.v", "Use vendor-faithful F/Q OMUX presentation for one slice."),
    "AGAMEMNON_DUAL_LUT_CONST": _value(None, "xyz", "both", "experimental", "qualification/mcu_slave_ahb_request_payload_route_evidence.jsonl", "Expose the vendor-observed OMUX0/OMUX2 constant dual-output source."),
    "AGAMEMNON_VENDOR_OUT_ALL": _flag("both", "experimental", "qualification/left_pad_vendor_tff.v", "Use vendor-faithful F/Q OMUX presentation globally."),
    "AGAMEMNON_NGCLK": _value("1", "int", "arch", "experimental", "agamemnon/chipdb/clk0_spine.json", "Number of global clock spines exposed to nextpnr."),
    "AGAMEMNON_CLK_SEAM": _value("5", "int", "bitgen", "release", "qualification/clock_divider_probe.v", "Clock seam selector used by qualified clocked tiles."),
    "AGAMEMNON_SYSCLK": _value("10", "int", "bitgen", "release", "qualification/timing_evidence.jsonl", "Requested supported fabric clock in MHz."),
    "AGAMEMNON_HSE": _value("8", "int", "bitgen", "release", "docs/HARDWARE_VALIDATION.md", "External crystal frequency in MHz."),
    "AGAMEMNON_BASELINE": _value(None, "path", "bitgen", "release", "docs/STATUS.md", "Override the packaged default configuration baseline."),
    "AGAMEMNON_NOSPINE": _flag("bitgen", "experimental", "agamemnon/chipdb/clk0_spine.json", "Inherit the global clock spine from the baseline."),
    "AGAMEMNON_NO_SEAM": _flag("bitgen", "experimental", "qualification/clock_divider_probe.v", "Suppress per-tile clock seam configuration."),
    "AGAMEMNON_NO_CLKGEN": _flag("bitgen", "experimental", "qualification/clock_divider_probe.v", "Suppress the open clock-generation preamble."),
    "AGAMEMNON_MCU_XY": _value("10,5", "xy", "arch", "release", "agamemnon/chipdb/pips_mcuedge.csv", "Physical MCU/fabric crossing coordinate."),
    "AGAMEMNON_MCU_ENTRY": _flag("arch", "experimental", "agamemnon/chipdb/pips_mcuedge.csv", "Force the historical MCU-entry chain."),
    "AGAMEMNON_MESH_TEMPLATE": _flag("bitgen", "experimental", "agamemnon/engine/mesh_template.py", "Enable the decoded mesh-template selector fallback."),
    "AGAMEMNON_ALLOW_UNMAPPED": _flag("bitgen", "archival", "docs/ARCHITECTURE.md", "Permit archival/predictive selector replay."),
    "AGAMEMNON_TRUE_TOPO": _flag("arch", "experimental", "agamemnon/chipdb/rrg_edges_full.csv", "Use the recovered true-topology graph."),
    "AGAMEMNON_OBSERVED_ONLY": _flag("arch", "experimental", "agamemnon/chipdb/pip_usage.csv", "Expose only corpus-observed edges."),
    "AGAMEMNON_TRUSTED": _flag("arch", "experimental", "agamemnon/chipdb/master_conduction.csv", "Use the legacy trusted-edge set."),
    "AGAMEMNON_EDGE_BLACKLIST": _value("", "text", "arch", "experimental", "agamemnon/chipdb/dead_edges_silicon.csv", "Add campaign-local edges to the dead-edge blacklist."),
    "AGAMEMNON_NO_EXIT_WL": _flag("arch", "archival", "agamemnon/chipdb/exit_feeder_whitelist.csv", "Disable exit-feeder restrictions."),
    "AGAMEMNON_SOFT_PREFER": _flag("arch", "experimental", "qualification/routing_evidence.jsonl", "Prefer conducting edges without gating alternatives."),
    "AGAMEMNON_SOFT_PENALTY": _value("30", "float", "arch", "experimental", "qualification/routing_evidence.jsonl", "Nanosecond cost for an unqualified soft-preference edge."),
    "AGAMEMNON_SPAN_DELAY": _flag("arch", "experimental", "agamemnon/chipdb/wire_timing_worst.json", "Add geometric span cost to trusted edges."),
    "AGAMEMNON_SPAN_STEP": _value("0.1", "float", "arch", "experimental", "agamemnon/chipdb/wire_timing_worst.json", "Nanosecond cost per Manhattan routing step."),
    "AGAMEMNON_WIRE_TIMING_MARGIN": _value("1.0", "float", "arch", "release", "agamemnon/chipdb/wire_timing_worst.json", "Multiplier on conservative wire delays."),
    "AGAMEMNON_CLEAN_SEL_PREFER": _flag("arch", "experimental", "agamemnon/chipdb/sel_edge_pairs.agdb", "Prefer exact encodings without gating alternatives."),
    "AGAMEMNON_CLEAN_SEL_PENALTY": _value("30", "float", "arch", "experimental", "agamemnon/chipdb/sel_edge_pairs.agdb", "Nanosecond cost for a selector without exact evidence."),
    "AGAMEMNON_XBAR_FULL": _flag("arch", "experimental", "agamemnon/chipdb/rrg_rmux_imux_full.csv", "Expose the completed inferred intra-tile crossbar."),
    "AGAMEMNON_FBRESTRICT": _flag("arch", "experimental", "agamemnon/chipdb/ff_feedback_map.csv", "Enable the partial feedback-edge sample."),
    "AGAMEMNON_FB_OFFSET3": _flag("arch", "experimental", "agamemnon/chipdb/ff_feedback_map.csv", "Restrict OMUX feedback to offset-three IMUX targets."),
    "AGAMEMNON_NO_INTRA_RMUX": _flag("arch", "experimental", "qualification/routing_evidence.jsonl", "Drop intra-tile RMUX-to-RMUX edges."),
    "AGAMEMNON_OBS_IMUX": _flag("arch", "experimental", "agamemnon/chipdb/pip_usage.csv", "Restrict IMUX input edges to corpus observations."),
    "AGAMEMNON_NO_FFBRIDGE": _flag("arch", "experimental", "qualification/routing_evidence.jsonl", "Disable the qualified FF bridge."),
    "AGAMEMNON_PADFEED_ONLY": _value(None, "xyz", "arch", "diagnostic", "agamemnon/chipdb/padfeed_L48_top.csv", "Expose one pad feeder for an isolation campaign."),
    "AGAMEMNON_PROBE": _flag("arch", "diagnostic", "agamemnon/engine/arch.py", "Print nextpnr Python API probes."),
    "AGAMEMNON_DEBUG": _flag("bitgen", "diagnostic", "agamemnon/engine/bitgen.py", "Print selector-resolution diagnostics."),
    "AGAMEMNON_OWNERSHIP_TRACE": _value(None, "path", "bitgen", "diagnostic", "docs/ARCHITECTURE.md", "Write the optional last-writer report; declared ownership enforcement is always active."),
}


CONSTANTS = {
    "lut_inputs": Constant(4, "release", "docs/ARCHITECTURE.md", "AGRV2K logic-element LUT width."),
    "mcu_edge_xy": Constant((10, 5), "release", "agamemnon/chipdb/pips_mcuedge.csv", "Qualified MCU/fabric crossing."),
    "clock_seam_selector": Constant(5, "release", "qualification/clock_divider_probe.v", "Silicon-positive SeamMUX selector."),
    "left_vendor_slices": Constant(((14, 11, 4), (14, 11, 5)), "release", "qualification/left_edge_output_evidence.jsonl", "Qualified left-edge output slices."),
    "bram_portb_qsel": Constant((((14, 10, 0), 0), ((14, 10, 4), 0), ((14, 10, 15), 0)), "release", "qualification/bram_evidence.jsonl", "Qualified Port-B alternate OMUX presentations."),
    "raw_image_bytes": Constant(99936, "release", "docs/BITSTREAM_FORMAT.md", "Uncompressed configuration payload size."),
    "crc_payload_bytes": Constant(99932, "release", "docs/BITSTREAM_FORMAT.md", "Configuration bytes covered before the CRC field."),
    "crc_polynomial": Constant(0x04C11DB7, "release", "docs/BITSTREAM_FORMAT.md", "CRC-32/BZIP2 polynomial."),
    "hse_input_bit": Constant((71737, 0x04), "release", "qualification/clock_divider_probe.v", "Qualified HSE input-enable bit."),
    "l48_id_scratch8_image_sha256": Constant(
        "4cd1551d1202c9768554b75deddcace93291e8444b6d6c82f9762936a7dc737b",
        "release",
        "qualification/mcu_ahb_register_bank_evidence.jsonl",
        "Exact silicon-qualified L48 immutable-ID/writable-scratch profile image.",
    ),
    "l48_serv_blinky_image_sha256": Constant(
        "fe7ecca298dc5bd929a12c3bf63c90a8323180a93016defa977de59580aa3d5a",
        "release",
        "qualification/pack_regression.json",
        "Exact release-strict replay image for the retained L48 SERV blinky route.",
    ),
}


INDIVIDUALLY_QUALIFIED_OPTIONS = {
    "AGAMEMNON_DATA", "AGAMEMNON_DEVICE", "AGAMEMNON_PHYSICAL_IO",
    "AGAMEMNON_HW_CARRY", "AGAMEMNON_CLEAN_SEL_GATE",
    "AGAMEMNON_STRICT_GATE", "AGAMEMNON_CONDUCTION_GATE",
    "AGAMEMNON_XBAR_CONDUCT", "AGAMEMNON_LEDPADS",
    "AGAMEMNON_PADFEED_TOP", "AGAMEMNON_HARDEN_PADFEED",
    "AGAMEMNON_LEFT_PAD_OUT", "AGAMEMNON_DIRECT_D",
    "AGAMEMNON_BRAM_PORTB_EXIT", "AGAMEMNON_CLK_SEAM",
    "AGAMEMNON_SYSCLK", "AGAMEMNON_HSE", "AGAMEMNON_BASELINE",
    "AGAMEMNON_MCU_XY", "AGAMEMNON_WIRE_TIMING_MARGIN",
}
DIFFERENTIALLY_VALIDATED_OPTIONS = {
    "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG",
    "AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT",
}
OPTION_EVIDENCE_TIERS = {
    name: (
        "individually_qualified" if name in INDIVIDUALLY_QUALIFIED_OPTIONS else
        "differentially_validated" if name in DIFFERENTIALLY_VALIDATED_OPTIONS else
        "decoded"
    )
    for name in OPTIONS
}
CONSTANT_EVIDENCE_TIERS = {name: "individually_qualified" for name in CONSTANTS}


APPROVED_EXPERIMENTAL_CLAIMS = {
    "AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG": {
        "claim_scope": (
            "B4 config-encoding only; AGRV2KL48 X13Y1..Y4; "
            "behavior and silicon not established"
        ),
        "approved_by": "Brian Benchoff",
        "review_date": "2026-08-09",
    },
    "AGAMEMNON_ROUTING_SELECTOR_EXPERIMENT": {
        "claim_scope": (
            "Six individually reviewed AGRV2KL48/L48 RMUX30 rows; exact-edge "
            "composition only; disabled by default and denied under release-strict"
        ),
        "approved_by": "Brian Benchoff",
        "review_date": "2026-08-09",
    },
}


def _claim_for(name, maturity, evidence, *, evidence_tier, domain, emits=True):
    """Backfill the approved V4 scope without creating a new promotion claim."""
    release_approved = maturity == "release" and evidence_tier == "individually_qualified"
    experimental_review = APPROVED_EXPERIMENTAL_CLAIMS.get(name)
    individual_only = domain in {"electrical", "timing", "safety"}
    return ClaimMetadata(
        evidence_tier=evidence_tier,
        claim_domain=domain,
        claim_scope=(
            experimental_review["claim_scope"] if experimental_review else
            "preexisting V4 release scope" if release_approved else
            "inventory only"
        ),
        policy_version=POLICY_VERSION,
        approval_state=(
            "approved" if experimental_review else
            "preexisting_v4" if release_approved else "unapproved"
        ),
        approved_by=(
            experimental_review["approved_by"] if experimental_review else
            "Brian Benchoff" if release_approved else None
        ),
        review_date=(
            experimental_review["review_date"] if experimental_review else
            "2026-08-05" if release_approved else None
        ),
        individual_only=individual_only,
        emits=emits,
        evidence_refs=(evidence,),
    )


_TIMING_OPTIONS = {
    "AGAMEMNON_CLK_SEAM", "AGAMEMNON_SYSCLK", "AGAMEMNON_HSE",
    "AGAMEMNON_NGCLK", "AGAMEMNON_NOSPINE", "AGAMEMNON_NO_SEAM",
    "AGAMEMNON_NO_CLKGEN", "AGAMEMNON_SPAN_DELAY", "AGAMEMNON_SPAN_STEP",
    "AGAMEMNON_WIRE_TIMING_MARGIN",
}
_ELECTRICAL_OPTIONS = {
    "AGAMEMNON_PHYSICAL_IO", "AGAMEMNON_LEDPADS",
    "AGAMEMNON_PADFEED_TOP", "AGAMEMNON_HARDEN_PADFEED",
    "AGAMEMNON_LEFT_PAD_OUT", "AGAMEMNON_BRAM_HSE_INPUT",
}
_NON_EMITTING_OPTIONS = {
    "AGAMEMNON_STRICT_POLICY", "AGAMEMNON_EXPERIMENTAL_FEATURES",
    "AGAMEMNON_POLICY_SIDECAR", "AGAMEMNON_RESEARCH_UNSAFE",
    "AGAMEMNON_PROBE", "AGAMEMNON_DEBUG",
    "AGAMEMNON_OWNERSHIP_TRACE",
}


OPTION_CLAIMS = {
    name: _claim_for(
        name,
        spec.maturity,
        spec.evidence,
        evidence_tier=OPTION_EVIDENCE_TIERS[name],
        domain=("timing" if name in _TIMING_OPTIONS else
                "electrical" if name in _ELECTRICAL_OPTIONS else "configuration"),
        emits=name not in _NON_EMITTING_OPTIONS,
    )
    for name, spec in OPTIONS.items()
}
CONSTANT_CLAIMS = {
    name: _claim_for(
        name,
        spec.maturity,
        spec.evidence,
        evidence_tier=CONSTANT_EVIDENCE_TIERS[name],
        domain="timing" if name in {"clock_seam_selector", "hse_input_bit"}
        else "format" if name.startswith(("raw_", "crc_"))
        else "configuration",
    )
    for name, spec in CONSTANTS.items()
}


def validate_claim_registry():
    if set(OPTION_CLAIMS) != set(OPTIONS):
        raise ValueError("claim metadata must cover every option exactly")
    if set(CONSTANT_CLAIMS) != set(CONSTANTS):
        raise ValueError("claim metadata must cover every constant exactly")
    if set(OPTION_EVIDENCE_TIERS) != set(OPTIONS):
        raise ValueError("evidence tiers must cover every option exactly")
    if set(CONSTANT_EVIDENCE_TIERS) != set(CONSTANTS):
        raise ValueError("evidence tiers must cover every constant exactly")
    for name, claim in list(OPTION_CLAIMS.items()) + list(CONSTANT_CLAIMS.items()):
        if claim.evidence_tier not in EVIDENCE_TIERS:
            raise ValueError("unsupported evidence tier for %s" % name)
        if not claim.evidence_refs:
            raise ValueError("missing evidence reference for %s" % name)


validate_claim_registry()


class EngineOptions:
    """Validated view over an environment mapping."""

    def __init__(self, environ=None):
        self.environ = os.environ if environ is None else environ

    def raw(self, name, default=None):
        if name not in OPTIONS:
            raise KeyError("unregistered AGRV2K engine option: %s" % name)
        spec = OPTIONS[name]
        fallback = spec.default if default is None else default
        return self.environ.get(name, fallback)

    def enabled(self, name):
        return bool(self.raw(name))

    def integer(self, name):
        return int(self.raw(name))

    def number(self, name):
        return float(self.raw(name))

    def coordinates(self, name):
        value = self.raw(name)
        parts = tuple(int(item) for item in value.split(","))
        expected = 3 if OPTIONS[name].kind == "xyz" else 2
        if len(parts) != expected:
            raise ValueError("%s requires %d comma-separated integers" % (name, expected))
        return parts

    def digest(self, scope="both"):
        selected = {}
        for name, spec in OPTIONS.items():
            if scope == "both" or spec.scope in (scope, "both"):
                selected[name] = self.raw(name)
        data = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()


def options_from(environ=None):
    return EngineOptions(environ)


def manifest(scope="both"):
    """Return a stable, machine-readable snapshot of the registered engine data."""

    options = []
    for name, spec in sorted(OPTIONS.items()):
        if scope == "both" or spec.scope in (scope, "both"):
            row = {
                "name": name,
                "default": spec.default,
                "kind": spec.kind,
                "scope": spec.scope,
                "maturity": spec.maturity,
                "evidence": spec.evidence,
                "description": spec.description,
            }
            row.update(asdict(OPTION_CLAIMS[name]))
            options.append(row)

    constants = []
    for name, spec in sorted(CONSTANTS.items()):
        row = {
            "name": name,
            "value": spec.value,
            "maturity": spec.maturity,
            "evidence": spec.evidence,
            "description": spec.description,
        }
        row.update(asdict(CONSTANT_CLAIMS[name]))
        constants.append(row)

    from agamemnon.engine.features import FEATURES
    features = []
    for feature in sorted(FEATURES, key=lambda item: item.descriptor.feature_id):
        descriptor = feature.descriptor
        features.append({
            "name": descriptor.feature_id,
            "maturity": descriptor.maturity,
            "evidence_tier": descriptor.evidence_tier,
            "evidence_refs": descriptor.evidence,
            "claim_domain": "electrical" if descriptor.feature_id in {"clocks", "physical_io"} else "configuration",
            "claim_scope": "preexisting V4 release scope",
            "policy_version": POLICY_VERSION,
            "approval_state": "preexisting_v4",
            "approved_by": "Brian Benchoff",
            "review_date": "2026-08-05",
            "individual_only": descriptor.feature_id in {"clocks", "physical_io"},
            "emits": True,
            "conflict_count": 0,
            "unknown_count": 0,
            "negative_conflict": False,
        })
    return {"policy_version": POLICY_VERSION, "options": options, "constants": constants, "features": features}
