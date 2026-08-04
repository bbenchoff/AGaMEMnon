"""Fail-closed policy for characterized identity route-through footprints.

An identity LUT is not just its truth table on AGRV2K.  At characterized exact
sites, retained vendor artifacts and silicon show that the physical LUT-input
permutation and final IMUX selector must be emitted as one coherent footprint.
The logical identity INIT is site/input specific.  This module keeps
the matching and validation separate from bitgen's byte-writing path so the
policy can be tested without constructing a complete routed design.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict


class RouteThroughPolicyError(ValueError):
    """A requested complete footprint is outside the qualified subset."""


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
            footprints[site].append({
                "edge": row["source_wire"] + "." + row["dest_wire"],
                "init": int(row["init"]),
                "byte": byte,
                "value": int(row["value"]),
                "write_mask": int(row.get("write_mask") or 255),
                "selector_mask": int(row["selector_mask"]),
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
    """Return the qualified footprint for *cell*, or an empty tuple.

    ``routed_nets`` contains ``(name, bit_set, routing_string)`` tuples.  An
    unannotated cell is recognized automatically only when all characterized
    facts match.  An explicitly annotated cell fails closed if any fact does
    not match.
    """
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
    if requested and not matching_nets:
        raise RouteThroughPolicyError(
            "route-through X%dY%d slice%d lacks characterized final edge %s" %
            (site[0], site[1], site[2], expected_edge)
        )

    if footprint and matching_nets and not ff_used and init == expected_init:
        return tuple(footprint)
    return ()
