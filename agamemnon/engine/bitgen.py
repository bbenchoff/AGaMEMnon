"""Phase-driven AGRV2K routed-JSON to bitstream driver."""

from __future__ import annotations

import collections
import hashlib
import json
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from agamemnon.engine import lzw_codec as L
from agamemnon.engine import special_routes
from agamemnon.engine.bit_ownership import BitOwnershipTrace
from agamemnon.engine.claim_policy import ClaimPolicyError, evaluate_policy, write_sidecar
from agamemnon.engine.features.bram import FEATURE as BRAM_FEATURE
from agamemnon.engine.features.carry import FEATURE as CARRY_FEATURE
from agamemnon.engine.features.clocks import FEATURE as CLOCK_FEATURE
from agamemnon.engine.features.core_logic import FEATURE as CORE_LOGIC_FEATURE
from agamemnon.engine.features.mcu_ahb import FEATURE as MCU_AHB_FEATURE
from agamemnon.engine.features.mcu_gpio import FEATURE as MCU_GPIO_FEATURE
from agamemnon.engine.features.physical_io import FEATURE as PHYSICAL_IO_FEATURE
from agamemnon.engine.features.protocol import BitstreamContext, EmissionPhase
from agamemnon.engine.features.route_through import (
    FEATURE as ROUTE_THROUGH_FEATURE,
    RouteThroughPolicyError,
)
from agamemnon.engine.features.routing import FEATURE as ROUTING_FEATURE
from agamemnon.engine.registry import CONSTANTS, options_from
from agamemnon.engine.selector_injectivity import enforce as enforce_selector_injectivity
from agamemnon.engine.silicon_negatives import (
    refuse_known_silicon_negative_design,
    refuse_known_silicon_negative_image,
)


CHIPDB_ROOT = Path(__file__).resolve().parent.parent / "chipdb"

# The order is part of the byte-exact format contract. Some feature phases have
# multiple passes (for example logic register modes and IO pad inputs), but no
# pass is implicit in main() anymore.
EMISSION_PHASES = (
    EmissionPhase.CLEAR_BASELINE,
    EmissionPhase.ROUTING,
    EmissionPhase.MCU_EDGES,
    EmissionPhase.LOGIC,
    EmissionPhase.CLOCKS,
    EmissionPhase.IO,
    EmissionPhase.BRAM,
    EmissionPhase.PREAMBLE,
    EmissionPhase.INTEGRITY,
)


def verify_research_knowledge_manifest(chipdb_root):
    """Fail closed unless the research inventory binds the current chipdb."""
    root = Path(chipdb_root).resolve()
    path = root / "research_knowledge_manifest.json"
    if not path.exists():
        raise SystemExit("research-unsafe requires research_knowledge_manifest.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("invalid research knowledge manifest: %s" % exc)
    if payload.get("schema") != 1 or payload.get("profile") != "research-unsafe":
        raise SystemExit("invalid research knowledge manifest identity")
    rows = payload.get("datasets")
    if not isinstance(rows, list) or not rows:
        raise SystemExit("research knowledge manifest has no dataset inventory")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise SystemExit("invalid research knowledge dataset row")
        candidate = (root / Path(row["path"]).name).resolve()
        if candidate.parent != root or candidate.name in seen or not candidate.is_file():
            raise SystemExit("research knowledge dataset is absent or unsafe: %s" % row["path"])
        seen.add(candidate.name)
        data = candidate.read_bytes()
        if len(data) != row.get("bytes") or hashlib.sha256(data).hexdigest() != row.get("sha256"):
            raise SystemExit("research knowledge dataset hash mismatch: %s" % row["path"])
    actual = {
        item.name for item in root.iterdir()
        if item.is_file() and item != path and not item.name.startswith(".")
    }
    if seen != actual:
        raise SystemExit("research knowledge manifest does not inventory the complete chipdb")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class PreparedDesign:
    module: dict
    cell_map: dict
    mux_groups: dict
    core_logic: object
    carry: object
    physical_io: object
    routing: object
    bram: object
    mcu_gpio: object
    clocks: object
    route_through: object


@dataclass
class ImageAssembly:
    header: bytes
    image: bytearray
    ownership: BitOwnershipTrace
    contexts: dict
    trace_path: str | None


def prepare_design(routed_path, options, chipdb_root=CHIPDB_ROOT, document=None):
    """Load feature-owned metadata and prepare every active feature state."""
    # Reject retained-bad logical compositions before reading any selector or
    # feature table.  The digest excludes physical attributes, so changing
    # placement or route strings cannot turn the same demonstrated-bad cell
    # graph into a candidate image.
    if document is None:
        with Path(routed_path).open(encoding="utf-8") as stream:
            document = json.load(stream)
    try:
        module = special_routes.physical_top_module(document)
    except special_routes.SpecialRouteError as exc:
        raise SystemExit(str(exc))
    refuse_known_silicon_negative_design(module)

    # Structural guard before a single codeword is read. A selector table whose
    # codeword is not injective inside one destination mux cannot be consulted
    # safely: the word that resolves selects a DIFFERENT input, the FCB accepts
    # the image, and nothing in this flow reports anything. Known-defective
    # rows are enumerated with the refusal that neutralises each one; anything
    # else stops the build here.
    enforce_selector_injectivity(str(chipdb_root))
    cell_map, mux_groups = ROUTING_FEATURE.load_cell_map(chipdb_root)
    BRAM_FEATURE.load_selector_cells(chipdb_root, cell_map)
    routing_tables = ROUTING_FEATURE.load_selector_tables(chipdb_root, options)
    slice_config = CARRY_FEATURE.load_slice_config(chipdb_root)
    mcu_cells = ROUTING_FEATURE.load_mcu_cells(chipdb_root)

    try:
        ROUTING_FEATURE.validate_mux_ownership(module)
    except ValueError as exc:
        raise SystemExit(str(exc))

    # The four-link node build's left-edge corridor selectors (keyed by
    # wire-pair) and its X14Y4 output-enable presentation site would otherwise
    # be inherited by any ordinary design that merely routes through or places
    # at those sites.  Fold/apply them only for a design that actually
    # instantiates a fabric-driven output-enable pad; ordinary designs
    # (including the shipped SERV images) keep their byte-exact release image.
    node_pinout = PHYSICAL_IO_FEATURE.uses_node_pinout(module)
    supplemental_fields = [MCU_GPIO_FEATURE.load_exact_pip_fields(chipdb_root)]
    if node_pinout:
        supplemental_fields.append(
            PHYSICAL_IO_FEATURE.load_exact_pip_fields(chipdb_root)
        )
    mcu_metadata = MCU_AHB_FEATURE.load_routing_metadata(
        chipdb_root, options, tuple(supplemental_fields)
    )

    carry_state = CARRY_FEATURE.prepare(module, slice_config)
    core_logic_state = CORE_LOGIC_FEATURE.prepare(
        module, cell_map, options, CONSTANTS,
        chipdb_root=chipdb_root, node_pinout=node_pinout,
    )
    bram_state = BRAM_FEATURE.prepare(module, chipdb_root, options)
    physical_io_state = PHYSICAL_IO_FEATURE.prepare(
        module, chipdb_root, cell_map, routing_tables.archival_legacy,
        options=options,
    )
    mcu_gpio_state = MCU_GPIO_FEATURE.prepare(
        module, mcu_cells, physical_io_state=physical_io_state
    )
    routing_state = ROUTING_FEATURE.prepare(
        pips=physical_io_state.pips,
        cell=cell_map,
        options=options,
        tables=routing_tables,
        physical_io_state=physical_io_state,
        exact_mcu_pips=mcu_metadata.exact_pips,
        mcu_cells=mcu_cells,
        mcu_exit_pairs=mcu_metadata.exit_pairs,
        bram_feature=BRAM_FEATURE,
        bram_state=bram_state,
        slice_config=slice_config,
        left_vendor_slices=core_logic_state.left_vendor_slices,
    )
    ROUTING_FEATURE.delegate_bits(
        routing_state,
        set(core_logic_state.register_sets) | set(bram_state.sets),
    )
    clock_state = CLOCK_FEATURE.prepare(
        core_logic_state.clocked_tiles,
        core_logic_state.register_sets,
        bram_state.cells,
        cell_map,
        chipdb_root,
        options,
    )
    CLOCK_FEATURE.exclude_ownership(
        clock_state, PHYSICAL_IO_FEATURE.writable_bits(physical_io_state)
    )
    try:
        route_through_state = ROUTE_THROUGH_FEATURE.prepare(module, chipdb_root)
    except RouteThroughPolicyError as exc:
        raise SystemExit(str(exc))
    ROUTING_FEATURE.delegate_bits(
        routing_state,
        ROUTE_THROUGH_FEATURE.writable_bits(route_through_state),
    )

    return PreparedDesign(
        module=module,
        cell_map=cell_map,
        mux_groups=mux_groups,
        core_logic=core_logic_state,
        carry=carry_state,
        physical_io=physical_io_state,
        routing=routing_state,
        bram=bram_state,
        mcu_gpio=mcu_gpio_state,
        clocks=clock_state,
        route_through=route_through_state,
    )


def base_image(options, chipdb_root=CHIPDB_ROOT):
    """Return the design-neutral (header, image) the overlay is painted onto.

    Default (and every release build): synthesize the base from scratch with
    ``default_frame`` -- silicon-qualified (FCB accepts the exact generated
    image; the stale-CRC vendor canvas is rejected) and byte-identical in
    emission to the former canvas default across the whole retained pack
    corpus (``qualification/fabric_base_evidence.jsonl``).  An explicit
    ``AGAMEMNON_BASELINE`` path still selects a decoded baseline file (the
    packaged ``fabric_default.bin`` remains shipped as a decode reference and
    differential anchor; note its trailing CRC is stale, so it is a template,
    not a directly loadable image).  ``AGAMEMNON_FROM_SCRATCH_BASE`` is kept
    for compatibility and forces the from-scratch base even when a baseline
    path is set.
    """
    if options.enabled("AGAMEMNON_FROM_SCRATCH_BASE") or not options.raw("AGAMEMNON_BASELINE"):
        from agamemnon.engine import default_frame

        return default_frame.header(), bytearray(
            default_frame.build(chipdb_root=chipdb_root)
        )
    baseline = Path(options.raw("AGAMEMNON_BASELINE")).read_bytes()
    payload = baseline[8:]
    image = bytearray(
        payload if len(payload) == CONSTANTS["raw_image_bytes"].value
        else L.decode(payload)
    )
    return baseline[:8], image


def assemble_canvas(plan, options, chipdb_root=CHIPDB_ROOT):
    """Load the design-neutral canvas and bind enforcing feature writers."""
    header, image = base_image(options, chipdb_root)
    ownership = BitOwnershipTrace(len(image))
    writers = {
        "core_logic": ownership.bind(
            "core_logic", CORE_LOGIC_FEATURE.writable_bits(plan.core_logic)
        ),
        "carry": ownership.bind("carry", CARRY_FEATURE.writable_bits(plan.carry)),
        "physical_io": ownership.bind(
            "physical_io", PHYSICAL_IO_FEATURE.writable_bits(plan.physical_io)
        ),
        "routing": ownership.bind(
            "routing", ROUTING_FEATURE.writable_bits(plan.routing)
        ),
        "bram": ownership.bind("bram", BRAM_FEATURE.writable_bits(plan.bram)),
        "mcu_gpio": ownership.bind(
            "mcu_gpio", MCU_GPIO_FEATURE.writable_bits(plan.mcu_gpio)
        ),
        "clocks": ownership.bind(
            "clocks",
            CLOCK_FEATURE.writable_bits(plan.clocks),
            CLOCK_FEATURE.writable_byte_ranges(),
        ),
        "route_through": ownership.bind(
            "route_through",
            ROUTE_THROUGH_FEATURE.writable_bits(plan.route_through),
        ),
    }
    contexts = {
        feature_id: BitstreamContext(
            image=image,
            module=plan.module,
            chipdb_root=chipdb_root,
            options=options,
            ownership=writer,
            state=getattr(plan, feature_id),
        )
        for feature_id, writer in writers.items()
    }
    return ImageAssembly(
        header=header,
        image=image,
        ownership=ownership,
        contexts=contexts,
        trace_path=options.raw("AGAMEMNON_OWNERSHIP_TRACE"),
    )


def clear_baseline_phase(plan, assembly):
    """Clear default routing and every active feature's complete owned surface."""
    image = assembly.image
    oracle = {
        key for key, (byte, mask) in plan.cell_map.items()
        if byte < len(image) and image[byte] & mask
    }
    active_by_group = collections.defaultdict(set)
    for x, y, mux, selector in oracle:
        active_by_group[(x, y, mux)].add(selector)
    saturated = {
        key for key, selectors in active_by_group.items()
        if set(plan.mux_groups.get(key, {}))
        and selectors == set(plan.mux_groups.get(key, {}))
    }
    for (x, y, mux, _selector), (byte, mask) in plan.cell_map.items():
        if (
            mux.rstrip("0123456789") in ("CFG_RMUX", "CFG_IMUX")
            and (x, y, mux) not in saturated
            and byte < len(image)
        ):
            image[byte] &= (~mask) & 0xFF
            assembly.ownership.touch(byte, mask, "default")

    clearers = (
        ("core_logic", CORE_LOGIC_FEATURE),
        ("carry", CARRY_FEATURE),
        ("physical_io", PHYSICAL_IO_FEATURE),
        ("routing", ROUTING_FEATURE),
        ("bram", BRAM_FEATURE),
    )
    for feature_id, feature in clearers:
        context = assembly.contexts[feature_id]
        writer = context.ownership
        context.ownership = writer.clearing()
        feature.clear_bitstream(context)
        context.ownership = writer


def emit_feature_phases(assembly):
    """Apply feature passes in the retained byte-exact phase order."""
    contexts = assembly.contexts

    # ROUTING, including exact hard-boundary route fields.
    ROUTING_FEATURE.emit_bitstream(contexts["routing"])

    # MCU_EDGES.
    MCU_GPIO_FEATURE.emit_bitstream(contexts["mcu_gpio"])

    # LOGIC first pass.
    CORE_LOGIC_FEATURE.emit_bitstream(contexts["core_logic"])

    # CLOCKS and IO selectors.
    CLOCK_FEATURE.emit_bitstream(contexts["clocks"])
    PHYSICAL_IO_FEATURE.emit_bitstream(contexts["physical_io"])

    # LOGIC register presentation, BRAM, carry, and identity footprints.
    CORE_LOGIC_FEATURE.emit_register_modes(contexts["core_logic"])
    BRAM_FEATURE.emit_bitstream(contexts["bram"])
    CARRY_FEATURE.emit_bitstream(contexts["carry"])
    try:
        count = ROUTE_THROUGH_FEATURE.emit_bitstream(contexts["route_through"])
    except RouteThroughPolicyError as exc:
        raise SystemExit(str(exc))
    if count:
        print("complete route-through footprint bytes: %d" % count)


def emit_preamble_phase(assembly):
    """Regenerate the global profile, then apply qualified pad-input fields."""
    CLOCK_FEATURE.emit_global(assembly.contexts["clocks"])
    PHYSICAL_IO_FEATURE.emit_pad_inputs(assembly.contexts["physical_io"])
    PHYSICAL_IO_FEATURE.emit_pad_electrical(assembly.contexts["physical_io"])


def crc32_bzip2(data, polynomial):
    value = 0xFFFFFFFF
    for byte in data:
        value ^= byte << 24
        for _ in range(8):
            value = (
                ((value << 1) ^ polynomial) & 0xFFFFFFFF
                if value & 0x80000000 else (value << 1) & 0xFFFFFFFF
            )
    return value ^ 0xFFFFFFFF


def emit_integrity_phase(assembly):
    """Write the silicon-qualified CRC field and return the compressed image."""
    crc_end = CONSTANTS["crc_payload_bytes"].value
    checksum = crc32_bzip2(
        assembly.header + bytes(assembly.image[:crc_end]),
        CONSTANTS["crc_polynomial"].value,
    )
    assembly.image[crc_end:crc_end + 4] = struct.pack(">I", checksum)
    assembly.ownership.touch_bytes(crc_end, crc_end + 4, "integrity")
    return assembly.header + L.encode(bytes(assembly.image))


def write_output(assembly, routed_path, output_path, routed_sha256=None):
    """Finalize, write, and optionally describe the canonical decoded image."""
    output_path = Path(output_path)
    output_path.unlink(missing_ok=True)
    output = emit_integrity_phase(assembly)
    refuse_known_silicon_negative_image(assembly.header, assembly.image)
    output_path.write_bytes(output)
    if assembly.trace_path:
        assembly.ownership.write_json(
            assembly.trace_path,
            bytes(assembly.image),
            source=os.path.normpath(routed_path).replace("\\", "/"),
            output_sha256=hashlib.sha256(
                assembly.header + bytes(assembly.image)
            ).hexdigest(),
            routed_sha256=routed_sha256,
        )
        print("wrote ownership trace %s" % assembly.trace_path)
    print(
        "wrote %s (%d B); re-decodes to %d B raw" %
        (output_path, len(output), len(L.decode(output[8:])))
    )


def _paths_alias(first, second):
    first = Path(first)
    second = Path(second)
    if first.resolve() == second.resolve():
        return True
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def _remove_products(paths, strict=False):
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            if strict:
                raise SystemExit("cannot clear stale emission product %s: %s" %
                                 (path, exc))


def build(routed_path, output_path, environ=None):
    """Build one bitstream through the explicit preparation and emission phases."""
    # A fail-closed preparation error must not leave an older image at the
    # requested path where a caller could mistake it for this build's output.
    # write_output repeats the unlink at the final boundary as defense in
    # depth for direct callers and late emission failures.
    output_path = Path(output_path)
    options = options_from(environ)
    policy_sidecar = (
        options.raw("AGAMEMNON_POLICY_SIDECAR") or
        (str(output_path) + ".policy.json")
    )
    routed_identity = Path(routed_path).resolve()
    output_identity = output_path.resolve()
    sidecar_identity = Path(policy_sidecar).resolve()
    if output_identity == routed_identity:
        raise SystemExit("bitgen output path aliases the routed input")
    if sidecar_identity in {routed_identity, output_identity}:
        raise SystemExit("claim-policy sidecar aliases an emission input or output")
    stale_products = {output_path, Path(str(output_path) + ".policy.json")}
    explicit_sidecar = options.raw("AGAMEMNON_POLICY_SIDECAR")
    if explicit_sidecar:
        stale_products.add(Path(explicit_sidecar))
    trace_path = options.raw("AGAMEMNON_OWNERSHIP_TRACE")
    if trace_path:
        stale_products.add(Path(trace_path))
    for stale in stale_products:
        if _paths_alias(stale, routed_path):
            raise SystemExit("bitgen emission product aliases the routed input")
    active_products = [output_path, Path(policy_sidecar)]
    if trace_path:
        active_products.append(Path(trace_path))
    for index, first in enumerate(active_products):
        for second in active_products[index + 1:]:
            if _paths_alias(first, second):
                raise SystemExit("bitgen emission products alias one another")
    _remove_products(stale_products, strict=True)
    chipdb_root = Path(options.raw("AGAMEMNON_DATA", str(CHIPDB_ROOT)))
    try:
        snapshot = special_routes.load_validated_routed_json(
            routed_path,
            "bitgen",
            chipdb_root=chipdb_root,
            environ=options.environ,
        )
    except special_routes.SpecialRouteError as exc:
        raise SystemExit(str(exc))
    expected_snapshot = options.raw("AGAMEMNON_VALIDATED_ROUTED_SHA256")
    if expected_snapshot is not None:
        expected_snapshot = expected_snapshot.lower()
        if (len(expected_snapshot) != 64 or
                any(char not in "0123456789abcdef" for char in expected_snapshot)):
            raise SystemExit("validated routed snapshot SHA-256 is malformed")
        if snapshot.sha256 != expected_snapshot:
            raise SystemExit(
                "validated routed snapshot SHA-256 mismatch; refusing emission"
            )
    try:
        decision = evaluate_policy(options)
    except ClaimPolicyError as exc:
        raise SystemExit(str(exc))
    plan = prepare_design(
        routed_path,
        options,
        chipdb_root=chipdb_root,
        document=snapshot.document,
    )
    policy_binding = next(
        (item for item in decision.selected
         if item["kind"] == "routing_selector_manifest"),
        None,
    )
    emitted_binding = plan.routing.admission_binding
    if policy_binding is not None:
        policy_binding = {
            key: policy_binding[key]
            for key in (
                "routing_selector_admission_sha256",
                "routing_selector_row_identities",
            )
        }
    if policy_binding != emitted_binding:
        raise SystemExit(
            "routing selector policy/emitter admission binding mismatch; refusing emission"
        )
    assembly = assemble_canvas(plan, options, chipdb_root=chipdb_root)
    clear_baseline_phase(plan, assembly)
    emit_feature_phases(assembly)
    emit_preamble_phase(assembly)
    try:
        write_output(
            assembly,
            routed_path,
            output_path,
            routed_sha256=snapshot.sha256,
        )
        if decision.policy in {"experimental-strict", "research-unsafe"}:
            extra = dict(plan.routing.admission_binding or {})
            extra["routing_provenance_counts"] = plan.routing.provenance_counts
            if decision.policy == "research-unsafe":
                extra["research_knowledge_manifest_sha256"] = (
                    verify_research_knowledge_manifest(chipdb_root)
                )
            write_sidecar(
                policy_sidecar, decision, routed_path, output_path,
                extra=extra, routed_sha256=snapshot.sha256,
            )
            print("wrote claim-policy sidecar %s" % policy_sidecar)
    except BaseException:
        _remove_products(stale_products)
        raise


def main(argv=None, environ=None):
    argv = sys.argv if argv is None else argv
    if len(argv) < 3:
        raise SystemExit("usage: bitgen_seq.py <routed.json> <out.bin>")
    build(argv[1], argv[2], environ=environ)


if __name__ == "__main__":
    main()
