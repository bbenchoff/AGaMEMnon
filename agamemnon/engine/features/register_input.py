"""Strict routed-netlist protocol for physical register input paths.

The C++ packer writes ``AGRV2K_REGISTER_INPUT_MODE`` on newly packed slices.
Retained routed artifacts that predate the attribute are accepted only when
their complete physical shape determines one unambiguous mode.  This module is
the final fail-closed check before core-logic bit emission.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


REGISTER_INPUT_MODE_ATTRIBUTE = "AGRV2K_REGISTER_INPUT_MODE"
REGISTER_INPUT_MODE_TOKENS = (
    "NONE",
    "LUT_COMPUTE_TO_FF",
    "LUT_FEEDTHROUGH_I0",
    "REGISTERED_PAD_I3",
    "DIRECT_D_I3",
    "CARRY_SUM_TO_FF",
    "UNKNOWN",
    "MALFORMED",
)


@dataclass(frozen=True)
class RegisterInputRequirement:
    mode: str
    legacy_derived: bool


def _parse_binary_parameter(cell, name):
    try:
        raw = cell["parameters"][name]
        return int(str(raw), 2)
    except (KeyError, TypeError, ValueError):
        raise SystemExit("register input: missing or malformed %s parameter" % name)


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
    # nextpnr's JSON writer fills unused members of grouped GENERIC_SLICE
    # ports with fresh numeric placeholders.  Such a placeholder is unnamed,
    # is not a top port, and occurs exactly once.  A real routed bit is named,
    # externally visible, or joins at least two cell endpoints.
    return named | {bit for bit, count in counts.items() if count > 1}


def _port_bit(cell, port, live_bits):
    connections = cell.get("connections", {})
    if port.startswith("I[") and port.endswith("]"):
        index = int(port[2:-1])
        if port in connections:
            bits = connections.get(port, [])
            bit = bits[0] if bits else None
        else:
            bits = connections.get("I", [])
            bit = bits[index] if index < len(bits) else None
    else:
        bits = connections.get(port, [])
        bit = bits[0] if bits else None
    if bit in ("0", "1"):
        return bit
    return bit if isinstance(bit, int) and bit in live_bits else None


def _init_depends_on(init, input_index):
    for row in range(16):
        if row & (1 << input_index):
            continue
        if ((init >> row) & 1) != ((init >> (row | (1 << input_index))) & 1):
            return True
    return False


def _reject(cell_name, mode, reason):
    raise SystemExit(
        "register input: cell %r mode %s is malformed: %s" %
        (cell_name, mode, reason)
    )


def requirement_for_cell(cell_name, cell, live_bits):
    """Return and validate one GENERIC_SLICE register-input requirement."""

    ff_used = _parse_binary_parameter(cell, "FF_USED")
    if ff_used not in (0, 1):
        _reject(cell_name, "MALFORMED", "FF_USED is neither 0 nor 1")
    init = _parse_binary_parameter(cell, "INIT") & 0xFFFF
    attrs = cell.get("attributes", {})
    tagged_pad = "agamemnon_registered_pad_input" in attrs
    tagged_direct = "agamemnon_direct_d_feedback" in attrs
    connections = cell.get("connections", {})
    carry_shape = "CIN" in connections or "COUT" in connections
    if int(tagged_pad) + int(tagged_direct) + int(carry_shape) > 1:
        _reject(
            cell_name, "MALFORMED",
            "conflicting registered-pad, direct-D, and carry shapes",
        )

    explicit = attrs.get(REGISTER_INPUT_MODE_ATTRIBUTE)
    legacy = explicit is None
    if explicit is not None:
        mode = str(explicit)
        if mode not in REGISTER_INPUT_MODE_TOKENS:
            _reject(cell_name, "UNKNOWN", "unknown protocol token %r" % mode)
        if mode in ("UNKNOWN", "MALFORMED"):
            _reject(cell_name, mode, "explicit fail-closed protocol state")
    elif ff_used == 0:
        mode = "NONE"
    elif tagged_pad:
        mode = "REGISTERED_PAD_I3"
    elif tagged_direct:
        mode = "DIRECT_D_I3"
    elif carry_shape:
        mode = "CARRY_SUM_TO_FF"
    else:
        i_ports = [_port_bit(cell, "I[%d]" % index, live_bits) for index in range(4)]
        q_bit = _port_bit(cell, "Q", live_bits)
        mode = (
            "DIRECT_D_I3"
            if i_ports[3] is not None and i_ports[3] == q_bit and
            _init_depends_on(init, 3)
            else "LUT_FEEDTHROUGH_I0"
            if init == 0xAAAA and i_ports[0] is not None and
            all(bit is None for bit in i_ports[1:])
            else "LUT_COMPUTE_TO_FF"
        )

    clk = _port_bit(cell, "CLK", live_bits)
    q = _port_bit(cell, "Q", live_bits)
    f = _port_bit(cell, "F", live_bits)
    inputs = [_port_bit(cell, "I[%d]" % index, live_bits) for index in range(4)]

    if mode == "NONE":
        if ff_used != 0:
            _reject(cell_name, mode, "requires FF_USED=0")
        if tagged_pad or tagged_direct:
            _reject(cell_name, mode, "special registered tag requires an active FF mode")
        return RegisterInputRequirement(mode, legacy)

    if ff_used != 1:
        _reject(cell_name, mode, "requires FF_USED=1")
    if clk is None or q is None:
        _reject(cell_name, mode, "requires connected CLK/Q")
    if f is not None and mode not in ("DIRECT_D_I3", "LUT_COMPUTE_TO_FF"):
        _reject(cell_name, mode, "requires unused F")

    if mode == "LUT_FEEDTHROUGH_I0":
        if init != 0xAAAA:
            _reject(cell_name, mode, "requires INIT=0xAAAA")
        if inputs[0] is None or any(bit is not None for bit in inputs[1:]):
            _reject(cell_name, mode, "requires the data net on I[0] only")
        if tagged_pad or tagged_direct or carry_shape:
            _reject(cell_name, mode, "cannot inherit I3, direct-D, or carry support")
    elif mode == "REGISTERED_PAD_I3":
        if not tagged_pad or tagged_direct or carry_shape:
            _reject(
                cell_name, mode,
                "requires only the existing agamemnon_registered_pad_input tag",
            )
        if init != 0xFF00:
            _reject(cell_name, mode, "requires the qualified I[3] identity INIT=0xFF00")
        if inputs[3] is None or any(bit is not None for bit in inputs[:3]):
            _reject(cell_name, mode, "requires the registered pad data net on I[3] only")
    elif mode == "DIRECT_D_I3":
        if (not tagged_direct and not legacy) or tagged_pad or carry_shape:
            _reject(
                cell_name, mode,
                "requires the existing direct-D tag or an exact legacy own-Q/I[3] shape",
            )
        if inputs[3] is None or inputs[3] != q:
            _reject(cell_name, mode, "requires own-Q feedback on I[3]")
        if not _init_depends_on(init, 3):
            _reject(cell_name, mode, "INIT does not depend on tagged I[3]")
    elif mode == "CARRY_SUM_TO_FF":
        if not carry_shape or tagged_pad or tagged_direct:
            _reject(cell_name, mode, "requires only the dedicated carry resource shape")
        if inputs[3] is None:
            _reject(cell_name, mode, "requires the carry I[3] sum selector")
    elif mode == "LUT_COMPUTE_TO_FF":
        if tagged_pad or tagged_direct or carry_shape:
            _reject(cell_name, mode, "cannot inherit I3, direct-D, or carry support")
        for index in range(4):
            if _init_depends_on(init, index) and inputs[index] is None:
                _reject(cell_name, mode, "INIT depends on unconnected I[%d]" % index)
    else:  # Defensive: the explicit token check above should make this unreachable.
        _reject(cell_name, mode, "unsupported protocol state")
    return RegisterInputRequirement(mode, legacy)


def validate_module_register_inputs(module):
    """Validate every slice before any core-logic bit is claimed or emitted."""

    live_bits = _all_connection_bits(module)
    requirements = {}
    for cell_name, cell in module.get("cells", {}).items():
        if cell.get("type") != "GENERIC_SLICE":
            continue
        requirements[cell_name] = requirement_for_cell(cell_name, cell, live_bits)
    return requirements
