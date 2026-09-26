"""Typed, fail-closed protocol for slice-shared register controls.

N4.2 admits a second physical control alongside ``CLOCK_ENABLE_POS``:
``ASYNC_CLEAR_POS_ZERO`` (active-high asynchronous clear to zero), behind
``AGRV2K_SHARED_CONTROL_ASYNC_CLEAR``. The evidence is a board-witnessed
control graph and selector codeword -- CtrlMUX instance 0 driving LogicTile
line 1's CFG_TILEASYNCMUX index 1 -- recovered from two silicon-PASS vendor
images (``clk_rst_high``/``clk_rst_low``) and cross-checked against the
2026-09-03 differential-override sweep; see
``agamemnon.engine.control_encode.FAMILY_SOURCE_COLUMNS``. The strict emitter
validates the complete routed shape and then rejects every still-active
control before any feature bit can be claimed.

Once a mode is admitted its packed-slice shape is the SAME lifted-attribute
shape as ``CLOCK_ENABLE_POS``'s: the packer moves the control port off the
slice (a ``GENERIC_SLICE`` bel has no ARST/EN pin -- the signal terminates on
a tile control line, not a per-slice pin) and leaves only the net's NAME as an
attribute, because a routed net still has to be traceable even though nothing
routes to the slice itself. ``CLOCK_ENABLE_POS`` is validated here in the same
fail-closed way but is NOT "active": see
:attr:`SharedControlRequirement.active`. ``ASYNC_CLEAR_POS_ZERO`` becomes
"not active" the same way, but only while
``AGRV2K_SHARED_CONTROL_ASYNC_CLEAR`` is set -- unlike clock enable, this
module itself (not just the nextpnr ingress gate) still refuses it by default,
so a hand-built or corrupted routed JSON cannot reach bitgen's bit writer
outside the admitted, evidenced case.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass


SHARED_CONTROL_MODE_ATTRIBUTE = "AGRV2K_SHARED_CONTROL_MODE"
CLOCK_ENABLE_NET_ATTRIBUTE = "AGRV2K_CLOCK_ENABLE_NET"
ASYNC_CLEAR_NET_ATTRIBUTE = "AGRV2K_ASYNC_CLEAR_NET"
ASYNC_CLEAR_ADMIT_OPTION = "AGRV2K_SHARED_CONTROL_ASYNC_CLEAR"
SHARED_CONTROL_MODE_TOKENS = (
    "NONE",
    "ASYNC_CLEAR_POS_ZERO",
    "CLOCK_ENABLE_POS",
    "UNKNOWN",
    "MALFORMED",
)
SHARED_CONTROL_PORT_TOKENS = (
    "ARST", "R", "ASET", "SET", "CE", "EN", "SRST", "SCLR", "SLOAD",
    "ALOAD",
)


def _async_clear_admitted():
    # Mirrors agrv2k.cc's shared_control_enable_admitted(): presence, not a
    # specific value, is admission -- the CLI sets "1" or pops the variable
    # entirely, never "0", for the same reason.
    return os.environ.get(ASYNC_CLEAR_ADMIT_OPTION) is not None


@dataclass(frozen=True)
class SharedControlRequirement:
    mode: str
    polarity: str
    clear_value: int | None
    control_bit: int | None
    legacy_derived: bool

    #: Name of the enable net for CLOCK_ENABLE_POS, else ``None``.
    enable_net: str | None = None

    #: Name of the async-clear net for ASYNC_CLEAR_POS_ZERO, else ``None``.
    async_clear_net: str | None = None

    @property
    def active(self):
        """A physical shared control this flow REFUSES.

        ``CLOCK_ENABLE_POS`` is deliberately excluded: it is unconditionally
        admitted, and the refusal in ``core_logic`` reads this property to
        decide what to reject, so folding the enable in here would refuse the
        very thing the feature exists to emit.

        ``ASYNC_CLEAR_POS_ZERO`` is excluded ONLY while
        ``AGRV2K_SHARED_CONTROL_ASYNC_CLEAR`` is set. Unlike clock enable,
        this module keeps its own admission check rather than relying solely
        on nextpnr's ingress gate, so bitgen still refuses a still-unsupported
        async-clear control (e.g. a hand-built routed JSON, or a build with
        the kill switch off) by name, independent of what produced the JSON.
        """
        if self.mode == "CLOCK_ENABLE_POS":
            return False
        if self.mode == "ASYNC_CLEAR_POS_ZERO":
            return not _async_clear_admitted()
        return False


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

    if mode == "ASYNC_CLEAR_POS_ZERO":
        # Same lifted shape as CLOCK_ENABLE_POS (see module docstring): a
        # packed slice has no ARST pin, because the clear does not reach a
        # slice at all -- it terminates on a tile control line, and the
        # slice's own per-slice line selector is left at its cleared (line 1,
        # the one evidenced route) baseline. What survives on the slice is
        # the net's name.
        present = [name for name in SHARED_CONTROL_PORT_TOKENS if name in connections]
        if present:
            _reject(cell_name, mode,
                    "a packed async-clear slice must carry no control port, "
                    "found: %s" % ", ".join(present))
        if _ff_used(cell) != 1:
            _reject(cell_name, mode, "requires FF_USED=1")
        async_net = attrs.get(ASYNC_CLEAR_NET_ATTRIBUTE)
        if not async_net:
            _reject(cell_name, mode,
                    "requires a %s attribute naming the async-clear net"
                    % ASYNC_CLEAR_NET_ATTRIBUTE)
        return SharedControlRequirement(
            "ASYNC_CLEAR_POS_ZERO", "POSITIVE", 0, None, legacy,
            None, str(async_net),
        )

    # mode == "NONE"
    present = [name for name in SHARED_CONTROL_PORT_TOKENS if name in connections]
    if present:
        _reject(
            cell_name, mode,
            "inactive attribute disagrees with present control port(s): %s"
            % ", ".join(present),
        )
    return SharedControlRequirement("NONE", "NONE", None, None, legacy)


def validate_module_shared_controls(module):
    """Validate and return every routed slice's normalized control mode."""

    live_bits = _all_connection_bits(module)
    requirements = {}
    for cell_name, cell in module.get("cells", {}).items():
        if cell.get("type") != "GENERIC_SLICE":
            continue
        requirements[cell_name] = requirement_for_cell(cell_name, cell, live_bits)
    return requirements
