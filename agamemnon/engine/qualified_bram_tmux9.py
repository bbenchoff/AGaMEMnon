"""Exact routed branches for the qualified X13Y4 TMUX09 write source.

This is a source-to-route profile, not a routed-checkpoint replay.  Placement
and routing first run normally; the measured reset, hard-output, and three
source/observer trees are then replaced atomically with their silicon-qualified
branches before strict bitgen.  The BRAM feature independently verifies the
resulting structure and routes before admitting the two scoped TMUX/KMUX
codewords, and the CLI requires the exact final raw and compressed hashes.
"""

from __future__ import annotations

import json
from pathlib import Path


PROFILES = frozenset({
    "bram-tmux9-i0-d1-we0", "bram-tmux9-i0-d1-we1",
    "bram-tmux9-i1-d0-we0", "bram-tmux9-i1-d0-we1",
})

# The hard BRAM output tree is represented in nextpnr's sink-rooted ordering,
# unlike the three ordinary fabric-driver trees below.  It is part of the
# measured simultaneous solution and must remain fixed as h1-h3 are replaced.
H0_ROUTE = (
    "X14Y4_RMUX20;X13Y4_BufMUX01.X14Y4_RMUX20;1;"
    "X10Y4_RMUX74;X14Y4_RMUX20.X10Y4_RMUX74;1;"
    "X14Y4_RMUX02;X10Y4_RMUX74.X14Y4_RMUX02;1;"
    "X14Y8_RMUX19;X14Y4_RMUX02.X14Y8_RMUX19;1;"
    "X14Y12_RMUX79;X14Y8_RMUX19.X14Y12_RMUX79;1;"
    "X13Y12_BBMUXE02;X14Y12_RMUX79.X13Y12_BBMUXE02;1;"
    "X0Y5_SinkMUXPseudo02;X13Y12_BBMUXE02.X0Y5_SinkMUXPseudo02;1;"
    "X13Y4_BufMUX01;;1"
)
RESET_LOW_ROUTE = (
    "X14Y5_RMUX80;X13Y5_BufMUX19.X14Y5_RMUX80;1;"
    "X14Y3_RMUX33;X14Y5_RMUX80.X14Y3_RMUX33;1;"
    "X12Y3_RMUX39;X14Y3_RMUX33.X12Y3_RMUX39;1;"
    "X12Y4_RMUX68;X12Y3_RMUX39.X12Y4_RMUX68;1;"
    "X14Y4_RMUX91;X12Y4_RMUX68.X14Y4_RMUX91;1;"
    "X15Y4_RMUX79;X14Y4_RMUX91.X15Y4_RMUX79;1;"
    "X13Y4_RMUX40;X15Y4_RMUX79.X13Y4_RMUX40;1;"
    "X13Y4_IMUX32;X13Y4_RMUX40.X13Y4_IMUX32;1;"
    "X13Y4_TileAsyncMUX00;X13Y4_IMUX32.X13Y4_TileAsyncMUX00;1;"
    "X13Y5_BufMUX19;;1"
)
RESET_HIGH_ROUTE = (
    "X14Y5_RMUX80;X13Y5_BufMUX19.X14Y5_RMUX80;1;"
    "X14Y3_RMUX33;X14Y5_RMUX80.X14Y3_RMUX33;1;"
    "X11Y3_RMUX39;X14Y3_RMUX33.X11Y3_RMUX39;1;"
    "X11Y4_RMUX68;X11Y3_RMUX39.X11Y4_RMUX68;1;"
    "X12Y4_RMUX91;X11Y4_RMUX68.X12Y4_RMUX91;1;"
    "X14Y4_RMUX79;X12Y4_RMUX91.X14Y4_RMUX79;1;"
    "X13Y4_RMUX40;X14Y4_RMUX79.X13Y4_RMUX40;1;"
    "X13Y4_IMUX32;X13Y4_RMUX40.X13Y4_IMUX32;1;"
    "X13Y4_TileAsyncMUX00;X13Y4_IMUX32.X13Y4_TileAsyncMUX00;1;"
    "X13Y5_BufMUX19;;1"
)

H1_COMMON = (
    ("X14Y8_OMUX08", "X14Y8_OMUX06"),
    ("X14Y8_OMUX06", "X15Y8_RMUX02"),
    ("X15Y8_RMUX02", "X15Y12_RMUX03"),
    ("X15Y12_RMUX03", "X14Y12_RMUX20"),
    ("X14Y12_RMUX20", "X13Y12_BBMUXE03"),
    ("X13Y12_BBMUXE03", "X0Y5_SinkMUXPseudo03"),
    ("X14Y8_OMUX06", "X15Y8_RMUX21"),
    ("X15Y8_RMUX21", "X15Y4_RMUX86"),
    ("X15Y4_RMUX86", "X11Y4_RMUX66"),
    ("X11Y4_RMUX66", "X10Y4_IMUX03"),
    ("X14Y8_OMUX08", "X14Y8_RMUX09"),
    ("X14Y8_RMUX09", "X14Y12_RMUX29"),
    ("X14Y12_RMUX29", "X14Y12_IMUX01"),
)
H1_WEA = (
    ("X15Y4_RMUX86", "X13Y4_TMUX09"),
    ("X13Y4_TMUX09", "X13Y4_KMUX03"),
)
H2 = (
    ("X10Y4_OMUX02", "X10Y4_RMUX08"),
    ("X10Y4_RMUX08", "X14Y4_RMUX32"),
    ("X14Y4_RMUX32", "X14Y8_RMUX32"),
    ("X14Y8_RMUX32", "X14Y12_RMUX32"),
    ("X14Y12_RMUX32", "X14Y12_RMUX34"),
    ("X14Y12_RMUX34", "X14Y12_IMUX00"),
    ("X14Y8_RMUX32", "X14Y12_RMUX26"),
    ("X14Y12_RMUX26", "X13Y12_BBMUXE04"),
    ("X13Y12_BBMUXE04", "X0Y5_SinkMUXPseudo04"),
    ("X10Y4_OMUX02", "X10Y4_RMUX15"),
    ("X10Y4_RMUX15", "X14Y4_RMUX69"),
    ("X14Y4_RMUX69", "X14Y8_RMUX77"),
    ("X14Y8_RMUX77", "X14Y8_IMUX11"),
)
H3 = (
    ("X14Y12_OMUX02", "X14Y12_RMUX13"),
    ("X14Y12_RMUX13", "X13Y12_BBMUXE05"),
    ("X13Y12_BBMUXE05", "X0Y5_SinkMUXPseudo05"),
)


def is_high(profile: str) -> bool:
    if profile not in PROFILES:
        raise ValueError("unknown qualified TMUX09 source profile %r" % profile)
    return profile.endswith("we1")


def _route(root: str, edges) -> str:
    fields = [root + ";;5"]
    fields.extend("%s;%s.%s;5" % (dst, src, dst) for src, dst in edges)
    return ";".join(fields)


def expected_routes(profile: str) -> dict[str, str]:
    high = is_high(profile)
    return {
        "resetn": RESET_HIGH_ROUTE if high else RESET_LOW_ROUTE,
        "h0": H0_ROUTE,
        "h1": _route("X14Y8_OMUX08", H1_COMMON + (H1_WEA if high else ())),
        "h2": _route("X10Y4_OMUX02", H2),
        "h3": _route("X14Y12_OMUX02", H3),
    }


def routes_match(module: dict, profile: str) -> bool:
    netnames = module.get("netnames", {})
    return all(
        netnames.get(name, {}).get("attributes", {}).get("ROUTING") == route
        for name, route in expected_routes(profile).items()
    )


def prepare_route_reservations(path, profile: str) -> None:
    """Carry the required trees into native routing before other nets compete."""
    source = Path(path)
    document = json.loads(source.read_text(encoding="utf-8"))
    modules = document.get("modules", {})
    if "top" not in modules:
        raise ValueError("qualified TMUX09 reservations require a top module")
    nets = modules["top"].get("netnames", {})
    routes = expected_routes(profile)
    missing = sorted(set(routes) - set(nets))
    if missing:
        raise ValueError("qualified TMUX09 reservations lost nets: " + ", ".join(missing))
    for name, route in routes.items():
        nets[name].setdefault("attributes", {})["AGAMEMNON_REQUIRED_ROUTE"] = route
    source.write_text(json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8")


def _route_wires(route: str) -> set[str]:
    """Return every named wire consumed by a nextpnr ROUTING tree."""
    fields = route.split(";")
    wires = {fields[0]} if fields and fields[0] else set()
    for offset in range(3, len(fields), 3):
        if offset + 1 >= len(fields):
            break
        destination, pip = fields[offset:offset + 2]
        if destination:
            wires.add(destination)
        if "." in pip:
            source, pip_destination = pip.split(".", 1)
            wires.update((source, pip_destination))
    return wires


def canonicalize_routed_file(path, profile: str) -> None:
    """Replace the three qualified trees after proving they are unoccupied."""
    routed = Path(path)
    document = json.loads(routed.read_text(encoding="utf-8"))
    modules = document.get("modules", {})
    if set(modules) != {"top"}:
        raise ValueError("qualified TMUX09 source build requires one top module")
    module = modules["top"]
    netnames = module.get("netnames", {})
    missing = sorted(set(expected_routes(profile)) - set(netnames))
    if missing:
        raise ValueError(
            "qualified TMUX09 source build lost routed net(s): %s" %
            ", ".join(missing)
        )
    replacement = expected_routes(profile)
    qualified_wires = set().union(*map(_route_wires, replacement.values()))
    conflicts = []
    for name, net in netnames.items():
        if name in replacement:
            continue
        route = net.get("attributes", {}).get("ROUTING")
        if not route:
            continue
        overlap = sorted(qualified_wires & _route_wires(route))
        if overlap:
            conflicts.append("%s: %s" % (name, ", ".join(overlap)))
    if conflicts:
        raise ValueError(
            "qualified TMUX09 tree collides with routed net(s): %s" %
            "; ".join(conflicts)
        )
    for name, route in replacement.items():
        netnames[name].setdefault("attributes", {})["ROUTING"] = route
    routed.write_text(
        json.dumps(document, separators=(",", ":")) + "\n", encoding="utf-8"
    )
