"""Strict routed-netlist protocol for native fixed-I/O endpoint placement.

The C++ packer leaves ordinary output-pad drivers to nextpnr's native placer
and records why that is legal with ``AGRV2K_NATIVE_ENDPOINT_MODE``.  This
module is the independent image-emission boundary: a hand-edited routed JSON
cannot use the marker to turn a non-I/O composition into an admitted one.
Legacy images without the attribute remain unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .physical_io import qualified_output_endpoint_bels


NATIVE_ENDPOINT_MODE_ATTRIBUTE = "AGRV2K_NATIVE_ENDPOINT_MODE"
NATIVE_ENDPOINT_MODE_TOKENS = (
    "NONE",
    "IOB_OUTPUT",
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
        return self.mode == "IOB_OUTPUT"


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


def _endpoint_shape(module, driver_name, driver, allowed_bels, mode):
    attrs = driver.get("attributes", {})
    driver_bel = attrs.get("NEXTPNR_BEL")
    if not _SLICE_BEL.fullmatch(str(driver_bel)):
        _reject(
            driver_name, mode,
            "requires a valid placed slice NEXTPNR_BEL, got %r" % driver_bel,
        )

    directions = driver.get("port_directions", {})
    output_bits = set()
    for port, direction in directions.items():
        if direction == "output":
            output_bits.update(_bits(driver, port))
    if not output_bits:
        _reject(driver_name, mode, "requires at least one connected output port")

    endpoints = []
    for other_name, other in module.get("cells", {}).items():
        if other_name == driver_name:
            continue
        overlaps = []
        for port in other.get("connections", {}):
            shared = output_bits.intersection(_bits(other, port))
            if shared:
                overlaps.append((port, shared))
        if not overlaps:
            continue

        other_attrs = other.get("attributes", {})
        other_bel = other_attrs.get("NEXTPNR_BEL")
        endpoint_claim = (
            other.get("type") == "GENERIC_IOB" or
            other_bel in allowed_bels
        )
        if not endpoint_claim:
            continue  # ordinary fabric fanout is legal
        if other.get("type") != "GENERIC_IOB":
            _reject(
                driver_name, mode,
                "endpoint-shaped cell %r has type %r, not GENERIC_IOB" %
                (other_name, other.get("type")),
            )
        if len(overlaps) != 1 or overlaps[0][0] != "I":
            _reject(
                driver_name, mode,
                "GENERIC_IOB %r has a malformed mixed endpoint claim on port(s) %s" %
                (other_name, ", ".join(port for port, _ in overlaps)),
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
        if other_bel not in allowed_bels:
            _reject(
                driver_name, mode,
                "GENERIC_IOB %r has malformed or unqualified fixed NEXTPNR_BEL %r" %
                (other_name, other_bel),
            )
        endpoints.append(other_name)
    return tuple(sorted(set(endpoints)))


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
    allowed_bels = qualified_output_endpoint_bels(chipdb_root)
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

        endpoints = _endpoint_shape(module, cell_name, cell, allowed_bels, mode)
        if mode == "NONE":
            if endpoints:
                _reject(
                    cell_name, mode,
                    "inactive attribute disagrees with fixed GENERIC_IOB.I output shape",
                )
        elif not endpoints:
            _reject(
                cell_name, mode,
                "requires one or more genuine fixed GENERIC_IOB.I endpoints",
            )
        requirements[cell_name] = NativeEndpointRequirement(
            mode, endpoints, False,
        )
    return requirements
