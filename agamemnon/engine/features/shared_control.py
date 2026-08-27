"""Typed, fail-closed protocol for slice-shared register controls.

N4.1 preserves one exact frontend oracle, active-high asynchronous clear to
zero, but does not claim a physical control graph or configuration codeword.
The strict emitter validates the complete routed shape and then rejects every
active control before any feature bit can be claimed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


SHARED_CONTROL_MODE_ATTRIBUTE = "AGRV2K_SHARED_CONTROL_MODE"
SHARED_CONTROL_MODE_TOKENS = (
    "NONE",
    "ASYNC_CLEAR_POS_ZERO",
    "UNKNOWN",
    "MALFORMED",
)
ASYNC_CLEAR_PORT = "ARST"
SHARED_CONTROL_PORT_TOKENS = (
    "ARST", "R", "ASET", "SET", "CE", "EN", "SRST", "SCLR", "SLOAD",
    "ALOAD",
)
UNSUPPORTED_CONTROL_PORTS = tuple(
    port for port in SHARED_CONTROL_PORT_TOKENS if port != ASYNC_CLEAR_PORT
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
    bit = bits[0] if isinstance(bits, list) and bits else None
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

    extra_ports = [name for name in UNSUPPORTED_CONTROL_PORTS if name in connections]
    if extra_ports:
        _reject(
            cell_name, mode,
            "unsupported or combined control port(s): %s" % ", ".join(extra_ports),
        )

    has_async_port = ASYNC_CLEAR_PORT in connections
    async_bit = _bound_port_bit(cell, ASYNC_CLEAR_PORT, live_bits)
    if mode == "NONE":
        if has_async_port:
            _reject(
                cell_name, mode,
                "inactive attribute disagrees with present ARST control port",
            )
        return SharedControlRequirement("NONE", "NONE", None, None, legacy)

    if _ff_used(cell) != 1:
        _reject(cell_name, mode, "requires FF_USED=1")
    if not has_async_port:
        _reject(cell_name, mode, "requires an ARST control port")
    if async_bit is None:
        _reject(cell_name, mode, "ARST control port has no bound net")
    return SharedControlRequirement(
        "ASYNC_CLEAR_POS_ZERO", "POSITIVE", 0, async_bit, legacy,
    )


def validate_module_shared_controls(module):
    """Validate and return every routed slice's normalized control mode."""

    live_bits = _all_connection_bits(module)
    requirements = {}
    for cell_name, cell in module.get("cells", {}).items():
        if cell.get("type") != "GENERIC_SLICE":
            continue
        requirements[cell_name] = requirement_for_cell(cell_name, cell, live_bits)
    return requirements
