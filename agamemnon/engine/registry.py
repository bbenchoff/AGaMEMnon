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

from collections import namedtuple
import hashlib
import json
import os


Option = namedtuple("Option", "default kind scope maturity evidence description")
Constant = namedtuple("Constant", "value maturity evidence description")


def _flag(scope, maturity, evidence, description):
    return Option(None, "flag", scope, maturity, evidence, description)


def _value(default, kind, scope, maturity, evidence, description):
    return Option(default, kind, scope, maturity, evidence, description)


# maturity is one of: release, archival, experimental, diagnostic.
OPTIONS = {
    "AGAMEMNON_DATA": _value(None, "path", "both", "release", "docs/ARCHITECTURE.md", "Override the packaged chip database."),
    "AGAMEMNON_DEVICE": _value("AGRV2KL48", "text", "arch", "release", "agamemnon/engine/device.py", "Select the package legality model."),
    "AGAMEMNON_PHYSICAL_IO": _flag("both", "release", "qualification/io_evidence.jsonl", "Enable physical package I/O routing and emission."),
    "AGAMEMNON_HW_CARRY": _flag("arch", "release", "qualification/carry_evidence.jsonl", "Expose the qualified dedicated-carry corridors."),
    "AGAMEMNON_CLEAN_SEL_GATE": _flag("both", "release", "agamemnon/chipdb/sel_edge_pairs.agdb", "Require exact conflict-free selector encodings."),
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
    "AGAMEMNON_DIRECT_D_X15Y8_S12_TEMPLATE": _flag("bitgen", "experimental", "qualification/mcu_bus_clock_direct_d_x15y8_s12_i1_template.v", "Use the decoded template selector instead of the conflicting corpus attribution for the X15Y8 slice12 IMUX49 discriminator."),
    "AGAMEMNON_DIRECT_D_X15Y8_S12_MODE": _flag("bitgen", "experimental", "qualification/mcu_bus_clock_x15y8_s12_nonlocal_tff.v", "Add the candidate slice12 LUTCMUX mode bit for one coupled nonlocal-feedback discriminator."),
    "AGAMEMNON_BRAM_PORTB_EXIT": _flag("both", "release", "qualification/bram_evidence.jsonl", "Enable the qualified BRAM Port-B exit corridor."),
    "AGAMEMNON_BRAM_PORTB_MCU_EXIT": _flag("arch", "experimental", "agamemnon/chipdb/bram_portb_corridors.csv", "Enable the BRAM-to-MCU experimental corridor."),
    "AGAMEMNON_NO_BRAM_WL": _flag("arch", "archival", "agamemnon/chipdb/bram_wl.csv", "Disable the qualified BRAM final-hop whitelist."),
    "AGAMEMNON_BRAM_APPROACH": _flag("arch", "experimental", "agamemnon/chipdb/bram_approach.csv", "Enable the narrow BRAM approach whitelist."),
    "AGAMEMNON_X9_FULL_ADDRESS": _flag("arch", "experimental", "agamemnon/chipdb/bram_x9_haddr_paths.csv", "Expose the vendor-observed but not yet silicon-qualified x9 HADDR[6:11] ingress continuation."),
    "AGAMEMNON_BRAM_HSE_INPUT": _flag("bitgen", "experimental", "qualification/bram_evidence.jsonl", "Force the BRAM HSE input-enable footprint outside automatic x9 mode; diagnostic override only."),
    "AGAMEMNON_X9_Q5_ALT_EXPERIMENT": _flag("both", "experimental", "qualification/bram_evidence.jsonl", "Expose the retained negative alternate q5/RMUX75 corridor for bounded causal-direction experiments."),
    "AGAMEMNON_PIPELINED_APPLY_EXPERIMENT": _flag("arch", "experimental", "qualification/mcu_ahb_register_bank_evidence.jsonl", "Expose retained candidate apply-stage paths for bounded pipelined register-bank experiments."),
    "AGAMEMNON_SCRATCH3_EXPERIMENT": _flag("arch", "experimental", "qualification/mcu_ahb_register_bank_evidence.jsonl", "Expose the scratch3 internal candidate path set for bounded register-bank experiments."),
    "AGAMEMNON_NO_BRAM_APPROACH": _flag("arch", "archival", "agamemnon/chipdb/bram_approach.csv", "Reserved inverse of the approach experiment."),
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
    "AGAMEMNON_NO_FBRESTRICT": _flag("arch", "archival", "agamemnon/chipdb/ff_feedback_map.csv", "Reserved inverse of the feedback experiment."),
    "AGAMEMNON_FB_OFFSET3": _flag("arch", "experimental", "agamemnon/chipdb/ff_feedback_map.csv", "Restrict OMUX feedback to offset-three IMUX targets."),
    "AGAMEMNON_NO_INTRA_RMUX": _flag("arch", "experimental", "qualification/routing_evidence.jsonl", "Drop intra-tile RMUX-to-RMUX edges."),
    "AGAMEMNON_OBS_IMUX": _flag("arch", "experimental", "agamemnon/chipdb/pip_usage.csv", "Restrict IMUX input edges to corpus observations."),
    "AGAMEMNON_NO_FFBRIDGE": _flag("arch", "experimental", "qualification/routing_evidence.jsonl", "Disable the qualified FF bridge."),
    "AGAMEMNON_NO_QINFB": _flag("arch", "experimental", "agamemnon/chipdb/slice_cfg.csv", "Disable Qin feedback modeling."),
    "AGAMEMNON_PADFEED_ONLY": _value(None, "xyz", "arch", "diagnostic", "agamemnon/chipdb/padfeed_L48_top.csv", "Expose one pad feeder for an isolation campaign."),
    "AGAMEMNON_PROBE": _flag("arch", "diagnostic", "agamemnon/engine/arch.py", "Print nextpnr Python API probes."),
    "AGAMEMNON_DEBUG": _flag("bitgen", "diagnostic", "agamemnon/engine/bitgen_seq.py", "Print selector-resolution diagnostics."),
    "AGAMEMNON_OWNERSHIP_TRACE": _value(None, "path", "bitgen", "diagnostic", "docs/ARCHITECTURE.md", "Write a side-channel last-writer map without changing emitted configuration bytes."),
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
}


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
            options.append({
                "name": name,
                "default": spec.default,
                "kind": spec.kind,
                "scope": spec.scope,
                "maturity": spec.maturity,
                "evidence": spec.evidence,
                "description": spec.description,
            })

    constants = []
    for name, spec in sorted(CONSTANTS.items()):
        constants.append({
            "name": name,
            "value": spec.value,
            "maturity": spec.maturity,
            "evidence": spec.evidence,
            "description": spec.description,
        })

    return {"options": options, "constants": constants}
