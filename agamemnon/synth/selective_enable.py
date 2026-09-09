"""Exact, pre-qin fallback for selected native clock-enable groups.

The caller archives one synthesized JSON document, calls
:func:`stamp_enable_groups`, and later calls :func:`lower_selected_enable_groups`
on a fresh copy of that same document.  Selection is by the JSON integer bit on
``DFFE.EN``; it is never inferred from a signal name or a resynthesized design.

This module deliberately operates before qin/packing.  A selected DFFE becomes
an ordinary DFF whose D input is a packable LUT implementing ``EN ? D : Q``.
The pre-existing D expression is preserved verbatim, which retains reset value
and reset/enable priority already established by the synthesis frontend.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping


ENABLE_GROUP_ATTRIBUTE = "AGRV2K_ENABLE_GROUP_ID"
NATIVE_ENABLE_ATTRIBUTES = frozenset((
    ENABLE_GROUP_ATTRIBUTE,
    "AGRV2K_SHARED_CONTROL_MODE",
    "AGRV2K_CLOCK_ENABLE_NET",
))


class SelectiveEnableError(ValueError):
    """The archived synthesized JSON cannot be selected without guessing."""


def _scalar_integer_port(cell_name: str, cell: Mapping[str, Any], port: str) -> int:
    bits = cell.get("connections", {}).get(port)
    if not isinstance(bits, list) or len(bits) != 1 or isinstance(bits[0], bool) or not isinstance(bits[0], int):
        raise SelectiveEnableError(
            "DFFE %r requires exactly one integer bit on %s" % (cell_name, port)
        )
    return bits[0]


def _scalar_data_port(cell_name: str, cell: Mapping[str, Any], port: str) -> int | str:
    """Return a scalar data pin, allowing the JSON constants ``0`` and ``1``.

    Yosys legitimately leaves a DFFE's D input tied to a constant (for example
    a sticky flag).  Those cells remain candidates when their enable is a real
    synthesized bit.  CLK and Q deliberately retain the stricter signal-bit
    check: a constant clock or driven Q is not a native-enable candidate.
    """
    bits = cell.get("connections", {}).get(port)
    if (not isinstance(bits, list) or len(bits) != 1 or
            isinstance(bits[0], bool) or
            not (isinstance(bits[0], int) or bits[0] in ("0", "1"))):
        raise SelectiveEnableError(
            "DFFE %r requires exactly one integer bit or constant on %s" % (cell_name, port)
        )
    return bits[0]


def enable_group_id(module_name: str, enable_bit: int) -> str:
    """Stable group ID for one archived module and one exact synthesized bit."""
    if not isinstance(module_name, str) or not module_name:
        raise SelectiveEnableError("module name must be a non-empty string")
    if isinstance(enable_bit, bool) or not isinstance(enable_bit, int):
        raise SelectiveEnableError("enable bit must be an integer")
    return sha256((module_name + "\x00" + str(enable_bit)).encode("utf-8")).hexdigest()[:16]


def stamp_enable_groups(document: Mapping[str, Any]) -> dict[str, int]:
    """Stamp every DFFE with its deterministic pre-qin enable-group identifier.

    The document is modified in place and the return value maps group ID to the
    number of DFFEs in that group.  Existing conflicting stamps are rejected:
    this must be run against the archived synthesized snapshot, not a partially
    transformed or resynthesized netlist.
    """
    modules = document.get("modules")
    if not isinstance(modules, dict):
        raise SelectiveEnableError("JSON document has no modules object")
    counts: dict[str, int] = {}
    for module_name in sorted(modules):
        module = modules[module_name]
        cells = module.get("cells", {})
        if not isinstance(cells, dict):
            raise SelectiveEnableError("module %r has no cells object" % module_name)
        for cell_name in sorted(cells):
            cell = cells[cell_name]
            if cell.get("type") != "DFFE":
                continue
            # A constant EN is already trivially reducible (or was retained by
            # a prior pass) and cannot identify an infeasible placement group.
            # Leave it untouched; never manufacture a synthetic broad group.
            en_bits = cell.get("connections", {}).get("EN")
            if en_bits == ["0"] or en_bits == ["1"]:
                continue
            enable_bit = _scalar_integer_port(cell_name, cell, "EN")
            # Validate all four primitive pins before trusting a group key.
            _scalar_integer_port(cell_name, cell, "CLK")
            _scalar_data_port(cell_name, cell, "D")
            _scalar_integer_port(cell_name, cell, "Q")
            group_id = enable_group_id(module_name, enable_bit)
            attrs = cell.setdefault("attributes", {})
            if not isinstance(attrs, dict):
                raise SelectiveEnableError("DFFE %r has non-object attributes" % cell_name)
            previous = attrs.get(ENABLE_GROUP_ATTRIBUTE)
            if previous is not None and str(previous) != group_id:
                raise SelectiveEnableError(
                    "DFFE %r has conflicting %s" % (cell_name, ENABLE_GROUP_ATTRIBUTE)
                )
            attrs[ENABLE_GROUP_ATTRIBUTE] = group_id
            counts[group_id] = counts.get(group_id, 0) + 1
    return counts


def _selected_bits(reset_enable_mapping: Mapping[str, Any]) -> dict[str, set[int]]:
    if not isinstance(reset_enable_mapping, Mapping):
        raise SelectiveEnableError("reset_enable_mapping must map module names to enable-bit mappings")
    selected: dict[str, set[int]] = {}
    for module_name, bit_mapping in reset_enable_mapping.items():
        if not isinstance(module_name, str) or not module_name:
            raise SelectiveEnableError("reset_enable_mapping has an invalid module name")
        if not isinstance(bit_mapping, Mapping):
            raise SelectiveEnableError("reset_enable_mapping[%r] must be a mapping" % module_name)
        bits: set[int] = set()
        for bit in bit_mapping:
            if isinstance(bit, bool) or not isinstance(bit, int):
                raise SelectiveEnableError(
                    "reset_enable_mapping[%r] has non-integer enable bit %r" % (module_name, bit)
                )
            bits.add(bit)
        if bits:
            selected[module_name] = bits
    return selected


def _used_integer_bits(module: Mapping[str, Any]) -> set[int]:
    used: set[int] = set()
    for cell in module.get("cells", {}).values():
        for bits in cell.get("connections", {}).values():
            if isinstance(bits, list):
                used.update(bit for bit in bits if isinstance(bit, int) and not isinstance(bit, bool))
    for net in module.get("netnames", {}).values():
        bits = net.get("bits", [])
        if isinstance(bits, list):
            used.update(bit for bit in bits if isinstance(bit, int) and not isinstance(bit, bool))
    for port in module.get("ports", {}).values():
        bits = port.get("bits", [])
        if isinstance(bits, list):
            used.update(bit for bit in bits if isinstance(bit, int) and not isinstance(bit, bool))
    return used


def _unique_name(cells: Mapping[str, Any], stem: str) -> str:
    name = stem
    index = 0
    while name in cells:
        index += 1
        name = "%s$%d" % (stem, index)
    return name


def lower_selected_enable_groups(document: Mapping[str, Any], reset_enable_mapping: Mapping[str, Any]) -> dict[str, int]:
    """Lower selected ``DFFE.EN`` groups to a feedback LUT plus plain DFF.

    ``reset_enable_mapping`` is ``{module_name: {enable_bit: metadata}}``.
    Metadata is intentionally opaque: only the exact integer bit selects a
    group.  Every requested bit must match one or more scalar DFFE.EN ports;
    unmatched bits and malformed selected DFFEs raise instead of falling back
    on a name-based guess.  Returns the number lowered per enable-group ID.
    """
    selected = _selected_bits(reset_enable_mapping)
    modules = document.get("modules")
    if not isinstance(modules, dict):
        raise SelectiveEnableError("JSON document has no modules object")
    unknown_modules = sorted(set(selected) - set(modules))
    if unknown_modules:
        raise SelectiveEnableError("reset_enable_mapping names missing modules: %s" % ", ".join(unknown_modules))

    result: dict[str, int] = {}
    for module_name in sorted(selected):
        module = modules[module_name]
        cells = module.get("cells", {})
        if not isinstance(cells, dict):
            raise SelectiveEnableError("module %r has no cells object" % module_name)
        wanted = selected[module_name]
        matches = {bit: [] for bit in wanted}
        for cell_name in sorted(cells):
            cell = cells[cell_name]
            if cell.get("type") != "DFFE":
                continue
            connections = cell.get("connections", {})
            en_bits = connections.get("EN")
            if isinstance(en_bits, list) and len(en_bits) == 1 and en_bits[0] in wanted:
                enable_bit = _scalar_integer_port(cell_name, cell, "EN")
                _scalar_integer_port(cell_name, cell, "CLK")
                _scalar_data_port(cell_name, cell, "D")
                _scalar_integer_port(cell_name, cell, "Q")
                matches[enable_bit].append(cell_name)
            elif isinstance(en_bits, list) and any(bit in wanted for bit in en_bits):
                raise SelectiveEnableError("selected DFFE %r has ambiguous EN width" % cell_name)
        missing = [str(bit) for bit, names in sorted(matches.items()) if not names]
        if missing:
            raise SelectiveEnableError(
                "reset_enable_mapping[%r] did not match DFFE.EN bit(s): %s" %
                (module_name, ", ".join(missing))
            )

        used_bits = _used_integer_bits(module)
        next_bit = max(used_bits, default=0) + 1
        for enable_bit in sorted(matches):
            group_id = enable_group_id(module_name, enable_bit)
            for cell_name in matches[enable_bit]:
                cell = cells[cell_name]
                old_d = _scalar_data_port(cell_name, cell, "D")
                clk = _scalar_integer_port(cell_name, cell, "CLK")
                q = _scalar_integer_port(cell_name, cell, "Q")
                # EN was validated above.  Allocate monotonically after all
                # original bits; no existing net or port can collide.
                hold_d = next_bit
                next_bit += 1
                attrs = deepcopy(cell.get("attributes", {}))
                for attribute in NATIVE_ENABLE_ATTRIBUTES:
                    attrs.pop(attribute, None)
                cell["type"] = "DFF"
                cell["attributes"] = attrs
                cell["connections"] = {"CLK": [clk], "D": [hold_d], "Q": [q]}
                cell["port_directions"] = {"CLK": "input", "D": "input", "Q": "output"}
                lut_name = _unique_name(cells, cell_name + "$enable_hold")
                # I = {I[3]=0, I[2]=EN, I[1]=old D, I[0]=Q}; INIT=0xCACA
                # implements EN ? old_D : Q.  It is a native frontend LUT,
                # so qin/packing can consume it without a second Yosys pass.
                lut_attrs = {}
                if "src" in attrs:
                    lut_attrs["src"] = attrs["src"]
                cells[lut_name] = {
                    "type": "LUT",
                    "parameters": {"K": "00000000000000000000000000000100",
                                   "INIT": "1100101011001010"},
                    "attributes": lut_attrs,
                    "connections": {"I": [q, old_d, enable_bit, "0"], "Q": [hold_d]},
                    "port_directions": {"I": "input", "Q": "output"},
                }
                result[group_id] = result.get(group_id, 0) + 1
    return result


def _normalize_group_ids(group_ids: Any) -> set[str]:
    if isinstance(group_ids, (str, bytes)):
        raise SelectiveEnableError("group_ids must be an iterable of group-id strings")
    try:
        result = set(group_ids)
    except TypeError as exc:
        raise SelectiveEnableError("group_ids must be iterable") from exc
    if not result:
        raise SelectiveEnableError("group_ids must not be empty")
    for group_id in result:
        if not isinstance(group_id, str) or not re.fullmatch(r"[0-9a-f]{16}", group_id):
            raise SelectiveEnableError("invalid enable group ID %r" % (group_id,))
    return result


def lower_enable_group_ids(document: Mapping[str, Any], group_ids: Any) -> dict[str, int]:
    """Lower groups selected by their stamped stable hexadecimal identifiers.

    This is the in-memory API used by the file adapter.  It validates that each
    selected DFFE's stamp is the hash of *this module* and its scalar EN bit,
    then delegates to the exact-bit lowering primitive.  A requested ID that
    has no matching DFFE is an error: callers must retry from the archived
    post-synthesis/pre-qin snapshot, never from a previous fallback output.
    """
    wanted = _normalize_group_ids(group_ids)
    modules = document.get("modules")
    if not isinstance(modules, dict):
        raise SelectiveEnableError("JSON document has no modules object")
    selected: dict[str, dict[int, str]] = {}
    found: set[str] = set()
    for module_name in sorted(modules):
        cells = modules[module_name].get("cells", {})
        if not isinstance(cells, dict):
            raise SelectiveEnableError("module %r has no cells object" % module_name)
        for cell_name in sorted(cells):
            cell = cells[cell_name]
            if cell.get("type") != "DFFE":
                continue
            attrs = cell.get("attributes", {})
            group_id = attrs.get(ENABLE_GROUP_ATTRIBUTE) if isinstance(attrs, dict) else None
            if group_id not in wanted:
                continue
            enable_bit = _scalar_integer_port(cell_name, cell, "EN")
            expected = enable_group_id(module_name, enable_bit)
            if group_id != expected:
                raise SelectiveEnableError(
                    "DFFE %r has stale or conflicting %s" % (cell_name, ENABLE_GROUP_ATTRIBUTE)
                )
            selected.setdefault(module_name, {})[enable_bit] = {"group_id": group_id}
            found.add(group_id)
    missing = sorted(wanted - found)
    if missing:
        raise SelectiveEnableError("requested enable group(s) not found in archived DFFE snapshot: %s" %
                                   ", ".join(missing))
    # A group is all DFFEs sharing an exact EN bit in one module.  Do not let
    # one missing/stale stamp make the bit-level lowering silently consume a
    # different population than the placement report described.
    for module_name, bit_mapping in selected.items():
        cells = modules[module_name]["cells"]
        for cell_name, cell in cells.items():
            if cell.get("type") != "DFFE":
                continue
            en_bits = cell.get("connections", {}).get("EN")
            if not isinstance(en_bits, list) or len(en_bits) != 1:
                continue
            enable_bit = en_bits[0]
            if enable_bit not in bit_mapping:
                continue
            expected = enable_group_id(module_name, enable_bit)
            attrs = cell.get("attributes", {})
            if not isinstance(attrs, dict) or attrs.get(ENABLE_GROUP_ATTRIBUTE) != expected:
                raise SelectiveEnableError(
                    "DFFE %r is missing or has stale %s for selected EN bit %s" %
                    (cell_name, ENABLE_GROUP_ATTRIBUTE, enable_bit)
                )
    return lower_selected_enable_groups(document, selected)


def lower_infeasible_groups(json_path: str | Path, group_ids: Any,
                            output_path: str | Path | None = None) -> dict[str, int]:
    """File adapter for the CLI retry path.

    ``json_path`` must be the archived post-synthesis/pre-qin snapshot.  When
    ``output_path`` is omitted it overwrites that path atomically; callers that
    retain the archive should provide a distinct retry output path.  Returns
    ``{group_id: lowered_dffe_count}``.
    """
    source = Path(json_path)
    destination = source if output_path is None else Path(output_path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectiveEnableError("cannot read synthesized JSON %s: %s" % (source, exc)) from exc
    result = lower_enable_group_ids(document, group_ids)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                                         prefix=destination.name + ".", suffix=".tmp", delete=False) as out:
            json.dump(document, out, sort_keys=True, separators=(",", ":"))
            out.write("\n")
            temporary = Path(out.name)
        temporary.replace(destination)
    except OSError as exc:
        raise SelectiveEnableError("cannot write selective-enable JSON %s: %s" % (destination, exc)) from exc
    return result
