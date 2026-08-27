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


def _endpoint_shapes(
        module, driver_name, driver, output_bels, input_bels, mode):
    attrs = driver.get("attributes", {})
    driver_bel = attrs.get("NEXTPNR_BEL")
    if not _SLICE_BEL.fullmatch(str(driver_bel)):
        _reject(
            driver_name, mode,
            "requires a valid placed slice NEXTPNR_BEL, got %r" % driver_bel,
        )

    directions = driver.get("port_directions", {})
    output_bits = set()
    input_bits = set()
    for port, direction in directions.items():
        if direction == "output":
            output_bits.update(_bits(driver, port))
        elif direction == "input":
            input_bits.update(_bits(driver, port))
    if mode == "IOB_OUTPUT" and not output_bits:
        _reject(driver_name, mode, "requires at least one connected output port")
    if mode == "IOB_INPUT" and not input_bits:
        _reject(driver_name, mode, "requires at least one connected input port")

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
            shared_input = input_bits.intersection(bits)
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
                    "AGRV2K_PAD_INPUT_IDENTITY",
                    "agamemnon_pad_sync_stage",
                    "agamemnon_pad_sync_group",
            )):
                _reject(
                    cell_name, mode,
                    "cannot claim an exact identity or synchronizer root",
                )
            endpoints = input_endpoints
        requirements[cell_name] = NativeEndpointRequirement(
            mode, endpoints, False,
        )
    return requirements
