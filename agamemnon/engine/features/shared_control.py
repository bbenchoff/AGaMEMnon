"""Typed, fail-closed protocol for slice-shared register controls.

N4.1 preserves one exact frontend oracle, active-high asynchronous clear to
zero, but does not claim a physical control graph or configuration codeword.
The strict emitter validates the complete routed shape and then rejects every
active control before any feature bit can be claimed.

``CLOCK_ENABLE_POS`` is the one admitted physical control, behind
``AGRV2K_SHARED_CONTROL_ENABLE``. It is validated here in the same fail-closed
way but is NOT "active": see :attr:`SharedControlRequirement.active`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


SHARED_CONTROL_MODE_ATTRIBUTE = "AGRV2K_SHARED_CONTROL_MODE"
CLOCK_ENABLE_NET_ATTRIBUTE = "AGRV2K_CLOCK_ENABLE_NET"
SHARED_CONTROL_MODE_TOKENS = (
    "NONE",
    "ASYNC_CLEAR_POS_ZERO",
    "CLOCK_ENABLE_POS",
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

    #: Name of the enable net for CLOCK_ENABLE_POS, else ``None``.
    enable_net: str | None = None

    @property
    def active(self):
        """A physical shared control this flow REFUSES.

        ``CLOCK_ENABLE_POS`` is deliberately excluded. It is admitted, and the
        refusal in ``core_logic`` reads this property to decide what to reject,
        so folding the enable in here would refuse the very thing the feature
        exists to emit.
        """
        return self.mode == "ASYNC_CLEAR_POS_ZERO"


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

    if mode == "CLOCK_ENABLE_POS":
        # A packed slice has NO enable port: the packer lifted EN onto a tile
        # control cell, because the tile line is where the enable physically
        # terminates. What survives on the slice is the net's name.
        present = [name for name in SHARED_CONTROL_PORT_TOKENS if name in connections]
        if present:
            _reject(cell_name, mode,
                    "a packed clock-enable slice must carry no control port, "
                    "found: %s" % ", ".join(present))
        if _ff_used(cell) != 1:
            _reject(cell_name, mode, "requires FF_USED=1")
        enable_net = attrs.get(CLOCK_ENABLE_NET_ATTRIBUTE)
        if not enable_net:
            _reject(cell_name, mode,
                    "requires a %s attribute naming the enable net"
                    % CLOCK_ENABLE_NET_ATTRIBUTE)
        return SharedControlRequirement(
            "CLOCK_ENABLE_POS", "POSITIVE", None, None, legacy, str(enable_net),
        )

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
