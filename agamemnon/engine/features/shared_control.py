"""Typed, fail-closed protocol for slice-shared register controls.

The asynchronous-clear oracle remains preserved but physically fenced.  One
separate, default-off synchronous-clear vehicle is admitted only at
``X14Y12_SLICE0`` and only through the twice-repeated vendor ingress route.
That narrow desk surface exists to build a silicon A/B candidate; it is not an
all-site shared-control claim.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


SHARED_CONTROL_MODE_ATTRIBUTE = "AGRV2K_SHARED_CONTROL_MODE"
SHARED_CONTROL_MODE_TOKENS = (
    "NONE",
    "ASYNC_CLEAR_POS_ZERO",
    "SYNC_CLEAR_POS_ZERO",
    "UNKNOWN",
    "MALFORMED",
)
SHARED_CONTROL_PORT_TOKENS = (
    "ARST", "R", "ASET", "SET", "CE", "EN", "SRST", "SCLR", "SLOAD",
    "ALOAD",
)

NATIVE_SYNC_CLEAR_OPTION = "AGAMEMNON_NATIVE_SYNC_CLEAR_X14Y12_S0"
NATIVE_SYNC_CLEAR_SITE = (14, 12, 0)
NATIVE_SYNC_CLEAR_BEL = "X14Y12_SLICE0"
NATIVE_SYNC_CLEAR_ROUTE_EDGES = frozenset({
    ("X15Y12_RMUX90", "X14Y12_CtrlMUX03"),
    ("X14Y12_CtrlMUX03", "X14Y12_TileSyncMUX00"),
})
NATIVE_SYNC_CLEAR_ROUTE_TERMINAL = "X14Y12_TileSyncMUX00"

# Two same-site vendor arms (seeds 7109 and 7121) use this exact ingress
# selector.  The independently four-seed-stable native mode bit is [5].
NATIVE_SYNC_CLEAR_TILESYNC_CLEAR = tuple(
    "CFG_TILESYNCMUX[%d]" % index for index in range(6)
)
NATIVE_SYNC_CLEAR_TILESYNC_SET = (
    "CFG_TILESYNCMUX[1]", "CFG_TILESYNCMUX[5]",
)
NATIVE_SYNC_CLEAR_CTRLMUX_CLEAR = tuple(
    "CFG_CTRLMUX[%d]" % index for index in range(24, 48)
)
NATIVE_SYNC_CLEAR_CTRLMUX_SET = (
    "CFG_CTRLMUX[42]", "CFG_CTRLMUX[47]",
)


@dataclass(frozen=True)
class SharedControlRequirement:
    mode: str
    polarity: str
    clear_value: int | None
    control_bit: int | None
    legacy_derived: bool

    @property
    def active(self):
        return self.mode != "NONE"

    @property
    def synchronous(self):
        return self.mode == "SYNC_CLEAR_POS_ZERO"


def _all_connection_bits(module):
    counts = Counter()
    for cell in module.get("cells", {}).values():
        for bits in cell.get("connections", {}).values():
            if isinstance(bits, list):
                counts.update(bit for bit in bits if isinstance(bit, int))
    named = set()
    for net in module.get("netnames", {}).values():
        named.update(bit for bit in net.get("bits", []) if isinstance(bit, int))
    for port in module.get("ports", {}).values():
        named.update(bit for bit in port.get("bits", []) if isinstance(bit, int))
    return named | {bit for bit, count in counts.items() if count > 1}


def _bound_port_bit(cell, port, live_bits):
    bits = cell.get("connections", {}).get(port, [])
    bit = bits[0] if isinstance(bits, list) and len(bits) == 1 else None
    return bit if isinstance(bit, int) and bit in live_bits else None


def _ff_used(cell):
    try:
        return int(str(cell["parameters"]["FF_USED"]), 2)
    except (KeyError, TypeError, ValueError):
        raise SystemExit("shared control: missing or malformed FF_USED parameter")


def _reject(cell_name, mode, reason):
    raise SystemExit(
        "shared control: cell %r mode %s is malformed: %s" %
        (cell_name, mode, reason)
    )


def requirement_for_cell(cell_name, cell, live_bits):
    """Normalize and validate one routed ``GENERIC_SLICE`` control shape."""

    attrs = cell.get("attributes", {})
    connections = cell.get("connections", {})
    explicit = attrs.get(SHARED_CONTROL_MODE_ATTRIBUTE)
    legacy = explicit is None
    mode = "NONE" if explicit is None else str(explicit)
    if mode not in SHARED_CONTROL_MODE_TOKENS:
        _reject(cell_name, "UNKNOWN", "unknown protocol token %r" % mode)
    if mode in ("UNKNOWN", "MALFORMED"):
        _reject(cell_name, mode, "explicit fail-closed protocol state")

    present_controls = [
        name for name in SHARED_CONTROL_PORT_TOKENS if name in connections
    ]
    if mode == "NONE":
        if present_controls:
            _reject(
                cell_name, mode,
                "inactive attribute disagrees with present control port(s): %s" %
                ", ".join(present_controls),
            )
        return SharedControlRequirement("NONE", "NONE", None, None, legacy)

    expected_port = {
        "ASYNC_CLEAR_POS_ZERO": "ARST",
        "SYNC_CLEAR_POS_ZERO": "SCLR",
    }.get(mode)
    if expected_port is None:
        _reject(cell_name, mode, "unsupported active protocol mode")
    extra_ports = [name for name in present_controls if name != expected_port]
    if extra_ports:
        _reject(
            cell_name, mode,
            "unsupported or combined control port(s): %s" %
            ", ".join(extra_ports),
        )
    if _ff_used(cell) != 1:
        _reject(cell_name, mode, "requires FF_USED=1")
    if expected_port not in connections:
        _reject(cell_name, mode, "requires an %s control port" % expected_port)
    control_bit = _bound_port_bit(cell, expected_port, live_bits)
    if control_bit is None:
        _reject(
            cell_name, mode,
            "%s control port has no bound net or is not scalar" % expected_port,
        )
    return SharedControlRequirement(mode, "POSITIVE", 0, control_bit, legacy)


def validate_module_shared_controls(module):
    """Validate and return every routed slice's normalized control mode."""

    live_bits = _all_connection_bits(module)
    requirements = {}
    for cell_name, cell in module.get("cells", {}).items():
        if cell.get("type") != "GENERIC_SLICE":
            continue
        requirements[cell_name] = requirement_for_cell(cell_name, cell, live_bits)
    return requirements


def _parse_route(name, value):
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(
            "shared control: active signal route %r has no textual ROUTING attribute" %
            name
        )
    parts = value.split(";")
    if len(parts) % 3:
        raise SystemExit(
            "shared control: route %r is not canonical wire/PIP/strength triples" %
            name
        )
    edges = set()
    wires = set()
    for wire, pip, strength in zip(parts[0::3], parts[1::3], parts[2::3]):
        if not wire or strength not in set("0123456"):
            raise SystemExit("shared control: route %r contains a malformed triple" % name)
        wires.add(wire)
        if not pip:
            continue
        if pip.count(".") != 1:
            raise SystemExit("shared control: route %r has malformed PIP %r" % (name, pip))
        source, destination = pip.split(".")
        if destination != wire or (source, destination) in edges:
            raise SystemExit("shared control: route %r has inconsistent PIP %r" % (name, pip))
        edges.add((source, destination))
        wires.add(source)
    return edges, wires


def validate_native_sync_clear_route(module, cell_name, requirement):
    """Require the exact desk-qualified X14Y12 control-ingress composition."""

    carriers = []
    for name, net in module.get("netnames", {}).items():
        bits = net.get("bits", [])
        attributes = net.get("attributes", {})
        if requirement.control_bit in bits and "ROUTING" in attributes:
            if bits != [requirement.control_bit]:
                raise SystemExit(
                    "shared control: route carrier %r for %r is not scalar" %
                    (name, cell_name)
                )
            carriers.append((name, attributes["ROUTING"]))
    if not carriers:
        raise SystemExit(
            "shared control: synchronous clear on %r has no ROUTING carrier" %
            cell_name
        )
    if len({route for _name, route in carriers}) != 1:
        raise SystemExit(
            "shared control: synchronous-clear aliases on %r disagree about ROUTING" %
            cell_name
        )
    edges, wires = _parse_route(carriers[0][0], carriers[0][1])
    missing = NATIVE_SYNC_CLEAR_ROUTE_EDGES - edges
    control_edges = {
        edge for edge in edges
        if any(token in endpoint for endpoint in edge
               for token in ("CtrlMUX", "TileSyncMUX"))
    }
    if missing or control_edges != NATIVE_SYNC_CLEAR_ROUTE_EDGES:
        raise SystemExit(
            "shared control: synchronous clear on %r does not use the exact "
            "X15Y12_RMUX90 -> X14Y12_CtrlMUX03 -> "
            "X14Y12_TileSyncMUX00 ingress" % cell_name
        )
    if NATIVE_SYNC_CLEAR_ROUTE_TERMINAL not in wires:
        raise SystemExit(
            "shared control: synchronous clear on %r does not terminate at %s" %
            (cell_name, NATIVE_SYNC_CLEAR_ROUTE_TERMINAL)
        )
    return edges
