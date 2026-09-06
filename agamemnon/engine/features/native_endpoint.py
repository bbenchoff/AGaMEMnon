"""Strict routed-netlist protocol for native fixed-I/O endpoint placement.

The C++ packer leaves ordinary output-pad drivers and direct combinational
input-pad consumers to nextpnr's native placer, recording why that is legal
with ``AGRV2K_NATIVE_ENDPOINT_MODE``.  This module is the independent
image-emission boundary: a hand-edited routed JSON cannot use the marker to
turn a non-I/O composition into an admitted one.  Legacy images without the
attribute remain unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .physical_io import (
    qualified_input_endpoint_bels,
    qualified_output_endpoint_bels,
)


NATIVE_ENDPOINT_MODE_ATTRIBUTE = "AGRV2K_NATIVE_ENDPOINT_MODE"
NATIVE_ENDPOINT_MODE_TOKENS = (
    "NONE",
    "IOB_OUTPUT",
    "IOB_INPUT",
    "UNKNOWN",
    "MALFORMED",
)

_SLICE_BEL = re.compile(r"X\d+Y\d+_SLICE\d+")

_GENERIC_SLICE_PORT_DIRECTIONS = {
    "I": "input",
    "CLK": "input",
    "CIN": "input",
    "F": "output",
    "Q": "output",
    "COUT": "output",
}


@dataclass(frozen=True)
class NativeEndpointRequirement:
    mode: str
    fixed_endpoints: tuple[str, ...]
    legacy_absent: bool

    @property
    def active(self):
        return self.mode in ("IOB_OUTPUT", "IOB_INPUT")


def _reject(cell_name, mode, reason):
    raise SystemExit(
        "native endpoint: cell %r mode %s is malformed: %s" %
        (cell_name, mode, reason)
    )


def _bits(cell, port):
    value = cell.get("connections", {}).get(port, [])
    if not isinstance(value, list):
        return ()
    return tuple(bit for bit in value if isinstance(bit, int))


def _parameter_int(cell, name):
    value = cell.get("parameters", {}).get(name)
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"[01]+", value):
            return int(value, 2)
        return int(value, 0)
    except ValueError:
        return None


def _is_async_controller_input(module, name, port, input_bit):
    cell = module['cells'][name]
    if (cell.get('type') != 'AGRV2K_ASYNCCTRL' or port != 'DIN' or
            set(cell.get('connections', {})) != {'DIN', 'DOUT'} or
            cell.get('port_directions') != {'DIN': 'input', 'DOUT': 'output'} or
            _parameter_int(cell, 'MODE') != 2 or _bits(cell, 'DIN') != (input_bit,)):
        return False
    bel = re.fullmatch(r'X(\d+)Y(\d+)_ASYNCCTRL([01])',
                       cell.get('attributes', {}).get('NEXTPNR_BEL', ''))
    output = _bits(cell, 'DOUT')
    if bel is None or len(output) != 1 or output == (input_bit,):
        return False
    x, y, index = map(int, bel.groups())
    used = False
    for other_name, other in module['cells'].items():
        if other_name == name:
            continue
        for sink_port in other.get('connections', {}):
            if output[0] not in _bits(other, sink_port):
                continue
            target = re.fullmatch(r'X(\d+)Y(\d+)_SLICE(\d+)',
                                  other.get('attributes', {}).get('NEXTPNR_BEL', ''))
            if (other.get('type') != 'GENERIC_SLICE' or sink_port != 'ARST' or
                    other.get('port_directions', {}).get(sink_port) != 'input' or
                    _bits(other, sink_port) != output or target is None or
                    tuple(map(int, target.groups()[:2])) != (x, y) or
                    int(target.group(3)) not in range(16) or _parameter_int(other, 'FF_USED') != 1 or
                    other.get('attributes', {}).get('AGRV2K_SHARED_CONTROL_MODE') != 'ASYNC_CLEAR_POS_ZERO' or
                    _attribute_int(other, 'AGRV2K_ASYNC_CONTROLLER_INDEX') != index):
                return False
            used = True
    return used


def _attribute_int(cell, name):
    value = cell.get("attributes", {}).get(name)
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r"[01]+", value):
            return int(value, 2)
        return int(value, 0)
    except ValueError:
        return None


def _live_bits(module, cell_name, cell, port):
    """Return connected bits, excluding nextpnr's anonymous x placeholders."""

    candidates = _bits(cell, port)
    if not candidates:
        return ()
    named = set()
    for net in module.get("netnames", {}).values():
        named.update(bit for bit in net.get("bits", []) if isinstance(bit, int))
    for module_port in module.get("ports", {}).values():
        named.update(
            bit for bit in module_port.get("bits", []) if isinstance(bit, int)
        )
    occurrences = {}
    for other_name, other in module.get("cells", {}).items():
        for other_port in other.get("connections", {}):
            for bit in _bits(other, other_port):
                occurrences[bit] = occurrences.get(bit, 0) + 1
    return tuple(
        bit for bit in candidates
        if bit in named or occurrences.get(bit, 0) > 1
    )


def _validate_pad_input_identity(
        module, cell_name, cell, input_endpoints, mode):
    """Prove the complete generated identity shape; never trust its marker."""

    if _attribute_int(cell, "AGRV2K_PAD_INPUT_IDENTITY") != 1:
        _reject(cell_name, mode, "pad identity marker is not numeric 1")
    if _parameter_int(cell, "INIT") != 0xAAAA:
        _reject(cell_name, mode, "pad identity requires exact INIT=0xAAAA")
    if _parameter_int(cell, "K") != 4:
        _reject(cell_name, mode, "pad identity requires exact K=4")
    if _parameter_int(cell, "FF_USED") != 0:
        _reject(cell_name, mode, "pad identity requires explicit FF_USED=0")

    connections = cell.get("connections", {})
    directions = cell.get("port_directions", {})
    inputs = connections.get("I", [])
    live_inputs = set(_live_bits(module, cell_name, cell, "I"))
    if (directions.get("I") != "input" or not isinstance(inputs, list) or
            len(inputs) != 4 or inputs[0] not in live_inputs or
            any(bit in live_inputs for bit in inputs[1:])):
        _reject(
            cell_name, mode,
            "pad identity requires only I[0] live and I[1:3] disconnected",
        )
    outputs = connections.get("F", [])
    live_outputs = _live_bits(module, cell_name, cell, "F")
    if (directions.get("F") != "output" or not isinstance(outputs, list) or
            len(outputs) != 1 or live_outputs != (outputs[0],)):
        _reject(cell_name, mode, "pad identity requires one live F output")
    if (_live_bits(module, cell_name, cell, "Q") or
            ("Q" in directions and directions.get("Q") != "output")):
        _reject(cell_name, mode, "pad identity requires Q disconnected")
    if any(port in connections or port in directions for port in ("CIN", "COUT")):
        _reject(cell_name, mode, "pad identity cannot carry dedicated carry ports")
    for port in connections:
        if (port not in ("I", "F") and
                _live_bits(module, cell_name, cell, port)):
            _reject(
                cell_name, mode,
                "pad identity has an unexpected live port %r" % port,
            )

    if len(input_endpoints) != 1:
        _reject(
            cell_name, mode,
            "pad identity requires exactly one fixed GENERIC_IOB.O endpoint",
        )
    endpoint = module.get("cells", {}).get(input_endpoints[0], {})
    if _bits(endpoint, "O") != (inputs[0],):
        _reject(
            cell_name, mode,
            "pad identity fixed GENERIC_IOB.O endpoint must drive I[0]",
        )

    ordinary_consumers = []
    for other_name, other in module.get("cells", {}).items():
        if other_name == cell_name:
            continue
        for port in other.get("connections", {}):
            if outputs[0] not in _bits(other, port):
                continue
            if ((other.get("type") != "GENERIC_SLICE" and
                    not _is_async_controller_input(module, other_name, port, outputs[0])) or
                    other.get("port_directions", {}).get(port) != "input"):
                _reject(
                    cell_name, mode,
                    "pad identity F may drive only ordinary fabric consumers or validated async controller DIN",
                )
            ordinary_consumers.append((other_name, port))
    if not ordinary_consumers:
        _reject(
            cell_name, mode,
            "pad identity F requires at least one ordinary fabric consumer",
        )

    attrs = cell.get("attributes", {})
    for attribute in (
            "agamemnon_pad_sync_stage", "agamemnon_pad_sync_group",
            "agamemnon_direct_d_feedback", "AGRV2K_ROUTE_THROUGH",
            "AGRV2K_IO_PINPACKED", "AGRV2K_BRAM_PINPACKED",
            "AGRV2K_MCU_PINPACKED", "NEXTPNR_CLUSTER"):
        if attribute in attrs:
            _reject(
                cell_name, mode,
                "pad identity cannot carry special attribute %r" % attribute,
            )
    if ("AGRV2K_REGISTER_INPUT_MODE" in attrs and
            attrs.get("AGRV2K_REGISTER_INPUT_MODE") != "NONE"):
        _reject(
            cell_name, mode,
            "pad identity requires AGRV2K_REGISTER_INPUT_MODE=NONE",
        )


def _endpoint_shapes(
        module, driver_name, driver, output_bels, input_bels, mode):
    attrs = driver.get("attributes", {})
    driver_bel = attrs.get("NEXTPNR_BEL")
    if not _SLICE_BEL.fullmatch(str(driver_bel)):
        _reject(
            driver_name, mode,
            "requires a valid placed slice NEXTPNR_BEL, got %r" % driver_bel,
        )

    directions = driver.get("port_directions")
    if not isinstance(directions, dict):
        _reject(
            driver_name, mode,
            "requires a port_directions object matching known "
            "GENERIC_SLICE semantics",
        )
    output_bits = set()
    input_bits = set()
    for port in driver.get("connections", {}):
        bits = _bits(driver, port)
        if not bits:
            continue
        expected = _GENERIC_SLICE_PORT_DIRECTIONS.get(port)
        if expected is None:
            _reject(
                driver_name, mode,
                "connected unknown GENERIC_SLICE port %r" % port,
            )
        declared = directions.get(port)
        if declared != expected:
            _reject(
                driver_name, mode,
                "connected GENERIC_SLICE port %s requires direction %s, "
                "got %r" % (port, expected, declared),
            )
        if expected == "output":
            output_bits.update(bits)
        else:
            input_bits.update(bits)
    if mode == "IOB_OUTPUT" and not output_bits:
        _reject(driver_name, mode, "requires at least one connected output port")
    if mode == "IOB_INPUT" and not input_bits:
        _reject(driver_name, mode, "requires at least one connected input port")

    # Match nextpnr's net ownership rather than treating every occurrence of a
    # bit on an input port as evidence that an IOB drives the slice.  A legal
    # registered output commonly feeds its Q bit back into a LUT input while
    # driving GENERIC_IOB.I.  That net is still driven by the slice output; the
    # C++ admission check therefore sees the IOB only as an output endpoint.
    # Keep all non-self-driven input bits so a genuine GENERIC_IOB.O endpoint,
    # including every malformed direction/port form below, remains fail-closed.
    input_endpoint_bits = input_bits.difference(output_bits)

    output_endpoints = []
    input_endpoints = []
    for other_name, other in module.get("cells", {}).items():
        if other_name == driver_name:
            continue
        output_overlaps = []
        input_overlaps = []
        for port in other.get("connections", {}):
            bits = _bits(other, port)
            shared_output = output_bits.intersection(bits)
            shared_input = input_endpoint_bits.intersection(bits)
            if shared_output:
                output_overlaps.append((port, shared_output))
            if shared_input:
                input_overlaps.append((port, shared_input))

        other_attrs = other.get("attributes", {})
        other_bel = other_attrs.get("NEXTPNR_BEL")
        output_claim = (
            other.get("type") == "GENERIC_IOB" or
            other_bel in output_bels
        )
        if output_overlaps and output_claim:
            if other.get("type") != "GENERIC_IOB":
                _reject(
                    driver_name, mode,
                    "endpoint-shaped cell %r has type %r, not GENERIC_IOB" %
                    (other_name, other.get("type")),
                )
            if len(output_overlaps) != 1 or output_overlaps[0][0] != "I":
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r has a malformed mixed output endpoint claim "
                    "on port(s) %s" %
                    (other_name, ", ".join(port for port, _ in output_overlaps)),
                )
            if other.get("port_directions", {}).get("I") != "input":
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r port I is not declared input" % other_name,
                )
            if len(_bits(other, "I")) != 1:
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r port I is not one connected net bit" % other_name,
                )
            if other_bel not in output_bels:
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r has malformed or unqualified fixed "
                    "output NEXTPNR_BEL %r" % (other_name, other_bel),
                )
            output_endpoints.append(other_name)

        input_claim = (
            other.get("type") == "GENERIC_IOB" or
            other_bel in input_bels
        )
        if input_overlaps and input_claim:
            if other.get("type") != "GENERIC_IOB":
                _reject(
                    driver_name, mode,
                    "input-endpoint-shaped cell %r has type %r, not GENERIC_IOB" %
                    (other_name, other.get("type")),
                )
            if len(input_overlaps) != 1 or input_overlaps[0][0] != "O":
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r has a malformed mixed input endpoint claim "
                    "on port(s) %s" %
                    (other_name, ", ".join(port for port, _ in input_overlaps)),
                )
            if other.get("port_directions", {}).get("O") != "output":
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r port O is not declared output" % other_name,
                )
            if len(_bits(other, "O")) != 1:
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r port O is not one connected net bit" % other_name,
                )
            if other_bel not in input_bels:
                _reject(
                    driver_name, mode,
                    "GENERIC_IOB %r has malformed or unqualified fixed input "
                    "NEXTPNR_BEL %r" % (other_name, other_bel),
                )
            input_endpoints.append(other_name)
    return (
        tuple(sorted(set(output_endpoints))),
        tuple(sorted(set(input_endpoints))),
    )


def validate_module_native_endpoints(module, chipdb_root):
    """Validate typed native endpoints before core or physical-I/O bit claims."""

    typed = {
        name: cell for name, cell in module.get("cells", {}).items()
        if NATIVE_ENDPOINT_MODE_ATTRIBUTE in cell.get("attributes", {})
    }
    if not typed:
        return {}  # no table dependency for retained attribute-absent images
    if chipdb_root is None:
        raise SystemExit(
            "native endpoint: chipdb root is required for typed endpoint validation"
        )
    output_bels = qualified_output_endpoint_bels(chipdb_root)
    input_bels = qualified_input_endpoint_bels(chipdb_root)
    requirements = {}
    for cell_name, cell in typed.items():
        attrs = cell.get("attributes", {})
        explicit = attrs.get(NATIVE_ENDPOINT_MODE_ATTRIBUTE)
        mode = str(explicit)
        if mode not in NATIVE_ENDPOINT_MODE_TOKENS:
            _reject(cell_name, "UNKNOWN", "unknown protocol token %r" % mode)
        if mode in ("UNKNOWN", "MALFORMED"):
            _reject(cell_name, mode, "explicit fail-closed protocol state")
        if cell.get("type") != "GENERIC_SLICE":
            _reject(cell_name, mode, "attribute requires a GENERIC_SLICE cell")

        output_endpoints, input_endpoints = _endpoint_shapes(
            module, cell_name, cell, output_bels, input_bels, mode,
        )
        if mode == "NONE":
            if output_endpoints or input_endpoints:
                _reject(
                    cell_name, mode,
                    "inactive attribute disagrees with a fixed GENERIC_IOB endpoint shape",
                )
            endpoints = ()
        elif mode == "IOB_OUTPUT":
            if not output_endpoints:
                _reject(
                    cell_name, mode,
                    "requires one or more genuine fixed GENERIC_IOB.I endpoints",
                )
            endpoints = output_endpoints
        else:
            if not input_endpoints:
                _reject(
                    cell_name, mode,
                    "requires one or more genuine fixed GENERIC_IOB.O endpoints",
                )
            if output_endpoints:
                _reject(
                    cell_name, mode,
                    "cannot also claim a GENERIC_IOB.I output endpoint",
                )
            if _parameter_int(cell, "FF_USED") != 0:
                _reject(cell_name, mode, "requires explicit FF_USED=0")
            if any(name in attrs for name in (
                    "agamemnon_pad_sync_stage",
                    "agamemnon_pad_sync_group",
            )):
                _reject(
                    cell_name, mode,
                    "cannot claim a synchronizer root",
                )
            if "AGRV2K_PAD_INPUT_IDENTITY" in attrs:
                _validate_pad_input_identity(
                    module, cell_name, cell, input_endpoints, mode,
                )
            endpoints = input_endpoints
        requirements[cell_name] = NativeEndpointRequirement(
            mode, endpoints, False,
        )
    return requirements
