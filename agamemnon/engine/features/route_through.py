"""Fail-closed emission for characterized identity route-through footprints."""

from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .protocol import (
    BitstreamContext,
    EmissionPhase,
    FeatureDescriptor,
    WritableRegion,
)


class RouteThroughPolicyError(ValueError):
    """A requested complete footprint is outside the qualified subset."""


@dataclass
class RouteThroughState:
    writes: list = field(default_factory=list)


def load_footprints(path):
    """Load and validate the extracted exact-site footprint table."""
    footprints = defaultdict(list)
    seen_bytes = set()
    with open(path, newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            site = (int(row["x"]), int(row["y"]), int(row["z"]))
            byte = int(row["byte"])
            if byte in seen_bytes:
                raise RouteThroughPolicyError(
                    "route-through footprint byte %d is owned more than once" % byte
                )
            seen_bytes.add(byte)
            # Neither of these may be defaulted.  A blank `write_mask` became
            # 255, which makes emit_bitstream() overwrite the WHOLE byte with
            # `value` -- clobbering bits owned by routing or core_logic -- and
            # simultaneously turns both mask validators below into no-ops
            # (`value & ~255 == 0` always).  A blank `sparse_policy` became
            # "allow", which switches OFF the fail-closed check in
            # complete_footprint_for_cell(): the site's characterized final edge
            # can then be absent from the route while the router still uses the
            # LUT, and the footprint is simply not emitted.  Note the policy
            # validator at the bottom of this function runs AFTER the default has
            # been substituted, so it can never see the substitution.
            for column in ("write_mask", "sparse_policy"):
                if not (row.get(column) or "").strip():
                    raise RouteThroughPolicyError(
                        "route-through footprint row for X%dY%d slice%d byte %d "
                        "has no `%s`; defaulting it would %s"
                        % (site + (byte, column,
                                   "grant a full-byte write mask that disables both "
                                   "mask validators" if column == "write_mask" else
                                   "downgrade a fail-closed site to permissive"))
                    )
            footprints[site].append({
                "edge": row["source_wire"] + "." + row["dest_wire"],
                "init": int(row["init"]),
                "byte": byte,
                "value": int(row["value"]),
                "write_mask": int(row["write_mask"]),
                "selector_mask": int(row["selector_mask"]),
                "sparse_policy": row["sparse_policy"],
            })

    for site, entries in footprints.items():
        edges = {entry["edge"] for entry in entries}
        if len(edges) != 1:
            raise RouteThroughPolicyError(
                "route-through site X%dY%d slice%d has mixed final edges" % site
            )
        inits = {entry["init"] for entry in entries}
        if len(inits) != 1:
            raise RouteThroughPolicyError(
                "route-through site X%dY%d slice%d has mixed logical INIT values" % site
            )
        policies = {entry["sparse_policy"] for entry in entries}
        if len(policies) != 1 or not policies <= {"allow", "fail_closed"}:
            raise RouteThroughPolicyError(
                "route-through site X%dY%d slice%d has invalid sparse policy" % site
            )
        if len(entries) < 4:
            raise RouteThroughPolicyError(
                "route-through site X%dY%d slice%d has an incomplete footprint" % site
            )
        for entry in entries:
            if entry["value"] & ~entry["write_mask"]:
                raise RouteThroughPolicyError(
                    "route-through site X%dY%d slice%d writes value bits outside its mask" % site
                )
            if entry["selector_mask"] & ~entry["write_mask"]:
                raise RouteThroughPolicyError(
                    "route-through site X%dY%d slice%d owns selector bits outside its mask" % site
                )
    return dict(footprints)


def _enabled_attribute(cell):
    value = cell.get("attributes", {}).get("AGRV2K_ROUTE_THROUGH")
    if value is None:
        return False
    try:
        return bool(int(str(value), 2))
    except ValueError as exc:
        raise RouteThroughPolicyError(
            "AGRV2K_ROUTE_THROUGH must be a binary integer"
        ) from exc


def _site(cell):
    bel = cell.get("attributes", {}).get("NEXTPNR_BEL", "")
    match = re.fullmatch(r"X(\d+)Y(\d+)_(?:DUAL_)?SLICE(\d+)", bel)
    if not match:
        raise RouteThroughPolicyError(
            "route-through cell has no concrete logic-slice placement"
        )
    return tuple(int(group) for group in match.groups())


def complete_footprint_for_cell(cell, routed_nets, footprints):
    """Return the qualified footprint for *cell*, or an empty tuple."""
    requested = _enabled_attribute(cell)
    site = _site(cell)
    footprint = footprints.get(site)
    if requested and not footprint:
        raise RouteThroughPolicyError(
            "no characterized complete route-through footprint for X%dY%d slice%d" % site
        )

    init = int(cell.get("parameters", {}).get("INIT", "0"), 2)
    ff_used = int(cell.get("parameters", {}).get("FF_USED", "0"), 2)
    expected_init = footprint[0]["init"] if footprint else None
    if requested and (ff_used or init != expected_init):
        raise RouteThroughPolicyError(
            "characterized route-through at X%dY%d slice%d requires "
            "combinational INIT=0x%04X" % (site + (expected_init,))
        )

    expected_edge = footprint[0]["edge"] if footprint else None
    input_bits = set(cell.get("connections", {}).get("I", []))
    matching_nets = [
        name for name, bits, route in routed_nets
        if expected_edge and input_bits & bits and expected_edge in route
    ]
    footprint_candidate = bool(
        footprint and footprint[0]["sparse_policy"] == "fail_closed" and
        not ff_used and init == expected_init
    )
    if (requested or footprint_candidate) and not matching_nets:
        raise RouteThroughPolicyError(
            "route-through X%dY%d slice%d lacks characterized final edge %s; "
            "sparse identity emission is unsafe" %
            (site[0], site[1], site[2], expected_edge)
        )

    if footprint and matching_nets and not ff_used and init == expected_init:
        return tuple(footprint)
    return ()


class RouteThroughFeature:
    descriptor = FeatureDescriptor(
        feature_id="route_through",
        options=("AGAMEMNON_BRAM_SITE_READ_PATHS",),
        chipdb_files=(
            "route_through_footprints.csv",
            "bram_control_route_through_footprints.csv",
        ),
        writable_regions=(
            WritableRegion(
                kind="sparse_table",
                source="route_through_footprints.csv",
                byte_field="byte",
                mask_field="write_mask",
            ),
            WritableRegion(
                kind="sparse_table",
                source="bram_control_route_through_footprints.csv",
                byte_field="byte",
                mask_field="write_mask",
            ),
        ),
        phase=EmissionPhase.ROUTING,
        evidence=(
            "qualification/bram_evidence.jsonl",
            "qualification/bram_site_read_evidence.jsonl",
        ),
        maturity="release",
        evidence_tier="individually_qualified",
        architecture=(
            "No Python-arch contribution; the retained uarch placement contract "
            "remains outside this refactor campaign."
        ),
        bitstream=(
            "Apply each qualified LUT-input permutation and final selector as one "
            "exact-site sparse write set."
        ),
    )

    def add_architecture(self, context):
        return None

    def clear_bitstream(self, context):
        return 0

    def prepare(self, module, chipdb_root):
        table = chipdb_root / self.descriptor.chipdb_files[0]
        footprints = load_footprints(table)
        # These seven sites (five control and two address) were extracted from
        # the simultaneous four-array x18 vendor oracle.  They remain opt-in
        # until fresh source builds reproduce the HREADY/HWRITE behavior on
        # silicon; merely observing a route in a vendor image is not a release
        # qualification.
        experimental = {}
        if os.getenv("AGAMEMNON_BRAM_SITE_READ_PATHS") is not None:
            experimental_table = chipdb_root / self.descriptor.chipdb_files[1]
            experimental = load_footprints(experimental_table)
            overlap = set(footprints) & set(experimental)
            if overlap:
                raise RouteThroughPolicyError(
                    "experimental BRAM-control route-through sites overlap release sites: %s"
                    % sorted(overlap)
                )
            footprints.update(experimental)
        routed_nets = [
            (name, set(net.get("bits", [])), net.get("attributes", {}).get("ROUTING", ""))
            for name, net in module.get("netnames", {}).items()
        ]
        writes = []
        explicit_sites = set()
        for cell in module.get("cells", {}).values():
            if cell.get("type") not in ("GENERIC_SLICE", "AGRV2K_DUAL_LUT_CONST"):
                continue
            complete = complete_footprint_for_cell(cell, routed_nets, footprints)
            if complete:
                explicit_sites.add(_site(cell))
                writes.extend(complete)

        # Router-inserted transparent slices have no netlist cell to visit.
        # The four-site x18 oracle contains two such AddressA paths.  Admit an
        # implicit footprint only when the routed net contains both the exact
        # characterized final input edge and the following physical slice
        # ingress.  This is deliberately limited to the opt-in table; the
        # release table still requires an explicit attributed cell.
        for site, footprint in experimental.items():
            if site in explicit_sites:
                continue
            x, y, z = site
            edge = footprint[0]["edge"]
            destination = edge.split(".", 1)[1]
            slice_ingress = "%s.X%dY%d_alta_slice%02d" % (
                destination, x, y, z,
            )
            matches = [
                name for name, _bits, route in routed_nets
                if edge in route and slice_ingress in route
            ]
            if len(matches) > 1:
                raise RouteThroughPolicyError(
                    "implicit route-through X%dY%d slice%d is used by multiple nets: %s"
                    % (site + (sorted(matches),))
                )
            if matches:
                writes.extend(footprint)
        return RouteThroughState(writes=writes)

    def emit_bitstream(self, context: BitstreamContext) -> int:
        writes = context.state.writes

        for entry in writes:
            byte = entry["byte"]
            write_mask = entry["write_mask"]
            context.image[byte] = (
                (context.image[byte] & (~write_mask & 0xFF)) |
                (entry["value"] & write_mask)
            )
            if context.ownership is not None:
                context.ownership.touch(byte, write_mask, "LUT")
                if entry["selector_mask"]:
                    context.ownership.touch(byte, entry["selector_mask"], "PIP")
        return len(writes)

    def writable_bits(self, state):
        return {(entry["byte"], entry["write_mask"]) for entry in state.writes}


FEATURE = RouteThroughFeature()
