"""Fail-closed composition of one routed user event into the public32 W1C core.

The public32 checkpoint remains the authority for the register bank.  A user
overlay is synthesized and routed separately with ``build --internal-ports``;
it must be a pure-fabric design with exactly one scalar output, ``status_set``.
This compositor removes the overlay's temporary output IOB, shares the already
qualified MCU bus clock, rejects every BEL or routing-wire collision, cuts only
the qualification-only HWDATA1 set hook, and routes the user's existing output
driver to the retained clocked W1C ingress.

This is deliberately not a general JSON merger.  It accepts no other top-level
ports, hard blocks, physical I/O, MCU endpoints, or unplaced/unrouted cells.
"""

from __future__ import annotations

import copy
import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path


class StatusOverlayError(ValueError):
    """The overlay cannot be composed without widening the qualified claim."""


PACKAGE = Path(__file__).resolve().parents[1]
DEFAULT_CORE = (
    PACKAGE / "templates" / "mcu-fpga-registers" / "logic" /
    "public32_exact_map_L48_routed.json"
)
DEFAULT_DEVDB = None
DEVDB_MANIFEST = PACKAGE / "engine" / "status_overlay_devdb_manifest.json"
DEVDB_MANIFEST_SHA256 = "7d90f704d4794c1d2d12f1001b0e2e4eb9a337fd0444b846979086826b045d2b"
CORE_SHA256 = "ab76df409898241b0e631ac79926345ac4b4cd0783f0e02898d9f95e6525c574"
EVENT_PORT = "status_set"
PREFIX = "user_status$"
HW_REMOVED = {
    "X14Y10_RMUX31", "X18Y10_RMUX25", "X18Y11_RMUX00",
    "X17Y11_IMUX56",
}
PENDING_REMOVED = {"X17Y11_RMUX77", "X17Y11_IMUX57"}


def route_items(route):
    fields = route.split(";") if route else []
    if fields and len(fields) % 3:
        raise StatusOverlayError("malformed route")
    result = []
    for pos in range(0, len(fields), 3):
        destination, pip, strength = fields[pos:pos + 3]
        if not destination.strip():
            continue
        if not strength or (pip and
                            (pip.count(".") != 1 or
                             pip.split(".", 1)[1] != destination)):
            raise StatusOverlayError("malformed route item")
        result.append((destination, pip, strength))
    return result


def encode_route(items):
    return ";".join(value for item in items for value in item)


def _drop_destinations(net, destinations):
    before = route_items(net.get("attributes", {}).get("ROUTING", ""))
    after = [item for item in before if item[0] not in destinations]
    if {item[0] for item in before} - {item[0] for item in after} != destinations:
        raise StatusOverlayError("qualified set-hook route shape drifted")
    net.setdefault("attributes", {})["ROUTING"] = encode_route(after)


def _load_top(path):
    design = json.loads(Path(path).read_text(encoding="utf-8"))
    top = design.get("modules", {}).get("top")
    if not isinstance(top, dict):
        raise StatusOverlayError("routed JSON requires modules.top")
    return design, top


def _all_int_bits(top):
    result = set()
    for port in top.get("ports", {}).values():
        result.update(bit for bit in port.get("bits", []) if isinstance(bit, int))
    for cell in top.get("cells", {}).values():
        for bits in cell.get("connections", {}).values():
            result.update(bit for bit in bits if isinstance(bit, int))
    for net in top.get("netnames", {}).values():
        result.update(bit for bit in net.get("bits", []) if isinstance(bit, int))
    return result


def _remap_bits(value, bit_map):
    if isinstance(value, list):
        return [_remap_bits(item, bit_map) for item in value]
    if isinstance(value, dict):
        return {key: _remap_bits(item, bit_map) for key, item in value.items()}
    return bit_map.get(value, value) if isinstance(value, int) else value


def _route_owners(top):
    owners = {}
    for name, net in top.get("netnames", {}).items():
        for destination, pip, _strength in route_items(
                net.get("attributes", {}).get("ROUTING", "")):
            for wire in (destination, pip.split(".", 1)[0] if pip else None):
                if not wire:
                    continue
                prior = owners.get(wire)
                if prior is not None and prior != name:
                    raise StatusOverlayError(
                        f"routing wire collision {wire}: {prior} / {name}")
                owners[wire] = name
    return owners


@lru_cache(maxsize=2)
def _shipped_table(name):
    try:
        manifest_raw = DEVDB_MANIFEST.read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest() != DEVDB_MANIFEST_SHA256:
            raise StatusOverlayError("bundled status-overlay manifest hash drifted")
        manifest = json.loads(manifest_raw.decode("utf-8"))
        row = manifest["tables"][name]
        artifact = DEVDB_MANIFEST.parent / row["artifact"]
        compressed = artifact.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != row["artifact_sha256"]:
            raise StatusOverlayError("bundled status-overlay device table hash drifted")
        raw = gzip.decompress(compressed)
        if len(raw) != row["source_bytes"] or \
                hashlib.sha256(raw).hexdigest() != row["source_sha256"]:
            raise StatusOverlayError("bundled status-overlay device table content drifted")
        return tuple(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    except (OSError, KeyError, UnicodeDecodeError, gzip.BadGzipFile,
            json.JSONDecodeError) as exc:
        raise StatusOverlayError(
            "bundled strict status-overlay device database is missing or invalid") from exc


def _devdb_rows(devdb, name):
    if devdb is None:
        return _shipped_table(name)
    try:
        with (Path(devdb) / name).open(newline="", encoding="utf-8") as source:
            return tuple(csv.DictReader(source))
    except OSError as exc:
        raise StatusOverlayError(
            "strict device database is missing; omit --devdb to use the "
            "bundled hash-checked snapshot") from exc


def _belpin_table(devdb):
    try:
        return {(row["bel"], row["pin"]): row["wire"]
                for row in _devdb_rows(devdb, "dev_belpins.csv")}
    except (KeyError, TypeError) as exc:
        raise StatusOverlayError(
            "strict device database has malformed BEL-pin rows") from exc


def _validate_routed_fragment(top, devdb):
    """Prove each connected user sink is present in its routed net tree."""
    belpins = _belpin_table(devdb)
    by_bit = defaultdict(lambda: {"drivers": [], "sinks": []})
    for name, cell in top.get("cells", {}).items():
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if not bel:
            raise StatusOverlayError("unplaced user cell: " + name)
        directions = cell.get("port_directions", {})
        for port, bits in cell.get("connections", {}).items():
            direction = directions.get(port)
            for index, bit in enumerate(bits):
                if not isinstance(bit, int) or direction not in {"input", "output"}:
                    continue
                pin = port + (f"[{index}]" if len(bits) > 1 else "")
                wire = belpins.get((bel, pin))
                if wire is None:
                    raise StatusOverlayError(
                        f"strict device database lacks {bel}.{pin}")
                kind = "drivers" if direction == "output" else "sinks"
                by_bit[bit][kind].append((name, pin, wire))

    named = defaultdict(list)
    for name, net in top.get("netnames", {}).items():
        for bit in net.get("bits", []):
            if isinstance(bit, int):
                named[bit].append((name, net))
    for bit, endpoints in by_bit.items():
        if not endpoints["drivers"] or not endpoints["sinks"]:
            continue
        if len(endpoints["drivers"]) != 1:
            raise StatusOverlayError(f"user net bit {bit} has ambiguous drivers")
        aliases = [(name, net) for name, net in named.get(bit, [])
                   if net.get("attributes", {}).get("ROUTING", "").strip()]
        if len(aliases) != 1:
            raise StatusOverlayError(
                f"connected user net bit {bit} requires exactly one routed alias")
        name, net = aliases[0]
        items = route_items(net["attributes"]["ROUTING"])
        tree = {wire for destination, pip, _strength in items
                for wire in (destination,
                             pip.split(".", 1)[0] if pip else None) if wire}
        required = {endpoints["drivers"][0][2]}
        required.update(endpoint[2] for endpoint in endpoints["sinks"])
        missing = sorted(required - tree)
        if missing:
            raise StatusOverlayError(
                f"user net {name} is not completely routed; missing " +
                ", ".join(missing))


class _Router:
    def __init__(self, top, devdb):
        try:
            self.adj = defaultdict(list)
            for row in _devdb_rows(devdb, "dev_pips.csv"):
                self.adj[row["src"]].append((row["dst"], row["name"]))
            self.belpins = _belpin_table(devdb)
        except (KeyError, TypeError) as exc:
            raise StatusOverlayError(
                "strict device database has malformed routing rows"
            ) from exc
        self.top = top
        self.owners = _route_owners(top)

    def pin(self, cell, port, index=None):
        bel = self.top["cells"][cell]["attributes"].get("NEXTPNR_BEL")
        suffix = f"[{index}]" if index is not None else ""
        try:
            return self.belpins[(bel, port + suffix)]
        except KeyError as exc:
            raise StatusOverlayError(
                f"strict device database lacks {bel}.{port}{suffix}") from exc

    def extend(self, name, sinks):
        net = self.top["netnames"][name]
        items = route_items(net.get("attributes", {}).get("ROUTING", ""))
        tree = set()
        for destination, pip, _strength in items:
            tree.add(destination)
            if pip:
                tree.add(pip.split(".", 1)[0])
        if not tree:
            raise StatusOverlayError("status event has no routed source root")
        for sink in sinks:
            if sink in tree:
                continue
            parent = {}
            queue = deque(sorted(tree))
            seen = set(tree)
            while queue and sink not in seen:
                source = queue.popleft()
                for destination, pip in self.adj.get(source, ()):
                    owner = self.owners.get(destination)
                    if owner is not None and owner != name:
                        continue
                    if destination in seen:
                        continue
                    seen.add(destination)
                    parent[destination] = (source, pip)
                    queue.append(destination)
            if sink not in seen:
                raise StatusOverlayError(
                    f"no strict collision-free route from user status event to {sink}")
            path = []
            node = sink
            while node not in tree:
                source, pip = parent[node]
                path.append((node, pip, "1"))
                node = source
            for destination, pip, strength in reversed(path):
                source = pip.split(".", 1)[0]
                for wire in (source, destination):
                    prior = self.owners.get(wire)
                    if prior is not None and prior != name:
                        raise StatusOverlayError(
                            f"status route acquired occupied wire {wire}")
                    self.owners[wire] = name
                items.append((destination, pip, strength))
                tree.update((source, destination))
        net.setdefault("attributes", {})["ROUTING"] = encode_route(items)


def compose(overlay_path, *, core_path=DEFAULT_CORE, devdb=DEFAULT_DEVDB):
    """Return ``(design, report)`` for one admitted routed user overlay."""
    core_path = Path(core_path)
    raw = core_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CORE_SHA256:
        raise StatusOverlayError("qualified public32 core hash drifted")
    design, core = _load_top(core_path)
    design = copy.deepcopy(design)
    core = design["modules"]["top"]
    _overlay_design, overlay = _load_top(overlay_path)
    overlay = copy.deepcopy(overlay)

    ports = overlay.get("ports", {})
    if set(ports) != {EVENT_PORT} or \
            ports[EVENT_PORT].get("direction") != "output" or \
            len(ports[EVENT_PORT].get("bits", [])) != 1 or \
            not isinstance(ports[EVENT_PORT]["bits"][0], int):
        raise StatusOverlayError(
            "user overlay must have exactly one scalar output named status_set")
    event_bit = ports[EVENT_PORT]["bits"][0]

    clock_cells = [name for name, cell in overlay.get("cells", {}).items()
                   if cell.get("type") == "MCU_BUS_CLOCK"]
    if len(clock_cells) > 1:
        raise StatusOverlayError("user overlay may contain at most one MCU_BUS_CLOCK")
    clock_bit = None
    if clock_cells:
        clock_cell = overlay["cells"][clock_cells[0]]
        bits = clock_cell.get("connections", {}).get("CLK", [])
        if len(bits) != 1 or not isinstance(bits[0], int):
            raise StatusOverlayError("user MCU_BUS_CLOCK output is malformed")
        clock_bit = bits[0]

    event_iobs = []
    for name, cell in overlay.get("cells", {}).items():
        if cell.get("type") != "GENERIC_IOB":
            continue
        if cell.get("connections", {}).get("I") == [event_bit]:
            event_iobs.append(name)
        else:
            raise StatusOverlayError("physical I/O is forbidden in a status overlay")
    if len(event_iobs) > 1:
        raise StatusOverlayError("status overlay has multiple output IOB wrappers")

    allowed = {"GENERIC_SLICE", "GENERIC_IOB", "MCU_BUS_CLOCK"}
    unexpected = sorted({cell.get("type") for cell in overlay.get("cells", {}).values()} - allowed)
    if unexpected:
        raise StatusOverlayError(
            "status overlay contains forbidden hard cell type(s): " + ", ".join(unexpected))

    # Check retained fabric BEL ownership before interpreting its routes.  The
    # temporary IOB and duplicate hard clock are intentionally discarded.
    retained_bels = {}
    for name, cell in overlay.get("cells", {}).items():
        if name in event_iobs or name in clock_cells or name == "$PACKER_GND":
            continue
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if not bel:
            raise StatusOverlayError("unplaced user cell: " + name)
        if bel in retained_bels:
            raise StatusOverlayError(f"duplicate user BEL {bel}")
        retained_bels[bel] = name
    core_bels_preflight = {
        cell.get("attributes", {}).get("NEXTPNR_BEL")
        for cell in core["cells"].values()
    }
    collisions = sorted(set(retained_bels) & core_bels_preflight)
    if collisions:
        raise StatusOverlayError(
            "user overlay occupies qualified-core BEL(s): " + ", ".join(collisions))

    _validate_routed_fragment(overlay, devdb)

    # Strip the temporary public-output wrapper and the duplicate hard clock.
    for name in event_iobs + clock_cells:
        del overlay["cells"][name]
    overlay["ports"] = {}

    # Drop an unused packer ground cell; unlike VCC, it is normally an artifact
    # of unused LUT inputs and has no logical consumer.
    ground = overlay.get("cells", {}).get("$PACKER_GND")
    if ground is not None:
        outputs = ground.get("connections", {}).get("F", [])
        used = {bit for cell in overlay["cells"].values()
                for direction, bits in cell.get("connections", {}).items()
                if direction not in {"F", "Q", "COUT"}
                for bit in bits if isinstance(bit, int)}
        if outputs and not any(bit in used for bit in outputs):
            del overlay["cells"]["$PACKER_GND"]
            overlay.get("netnames", {}).pop("$PACKER_GND_NET", None)

    # Every retained cell must already be placed by the release router.
    overlay_bels = {}
    for name, cell in overlay.get("cells", {}).items():
        bel = cell.get("attributes", {}).get("NEXTPNR_BEL")
        if not bel:
            raise StatusOverlayError("unplaced user cell: " + name)
        if bel in overlay_bels:
            raise StatusOverlayError(f"duplicate user BEL {bel}")
        overlay_bels[bel] = name
    core_bels = {cell.get("attributes", {}).get("NEXTPNR_BEL"): name
                 for name, cell in core["cells"].items()}
    collisions = sorted(set(overlay_bels) & set(core_bels))
    if collisions:
        raise StatusOverlayError(
            "user overlay occupies qualified-core BEL(s): " + ", ".join(collisions))

    routed_by_bit = {}
    for name, net in overlay.get("netnames", {}).items():
        route = route_items(net.get("attributes", {}).get("ROUTING", ""))
        for bit in net.get("bits", []):
            if isinstance(bit, int) and route:
                if bit in routed_by_bit:
                    raise StatusOverlayError("ambiguous routed aliases in user overlay")
                routed_by_bit[bit] = name
    if event_bit not in routed_by_bit:
        raise StatusOverlayError("status_set has no routed user driver")
    event_name = routed_by_bit[event_bit]
    event_roots = [item for item in route_items(
        overlay["netnames"][event_name]["attributes"]["ROUTING"]) if not item[1]]
    if len(event_roots) != 1:
        raise StatusOverlayError("status_set route requires exactly one source root")
    overlay["netnames"][event_name]["attributes"]["ROUTING"] = \
        encode_route(event_roots)

    hclk_bit = core["netnames"]["hclk"]["bits"][0]
    max_bit = max(_all_int_bits(core))
    bit_map = {}
    for bit in sorted(_all_int_bits(overlay)):
        if bit == clock_bit:
            bit_map[bit] = hclk_bit
        else:
            max_bit += 1
            bit_map[bit] = max_bit
    overlay = _remap_bits(overlay, bit_map)
    event_bit = bit_map[event_bit]

    # Merge the overlay clock tree into the qualified GCLK net, then namespace
    # every remaining user object.  GCLK0 is intentionally shared.
    if clock_bit is not None:
        original_clock_names = [name for name, net in _overlay_design["modules"]["top"]
                                .get("netnames", {}).items()
                                if net.get("bits") == [clock_bit]]
        if len(original_clock_names) != 1:
            raise StatusOverlayError("user clock net is ambiguous")
        clock_items = route_items(
            _overlay_design["modules"]["top"]["netnames"][original_clock_names[0]]
            .get("attributes", {}).get("ROUTING", ""))
        roots = [item for item in clock_items if not item[1]]
        if len(roots) != 1 or roots[0][0] != "GCLK0":
            raise StatusOverlayError("user clock is not rooted at qualified GCLK0")
        core_clock = route_items(core["netnames"]["hclk"]["attributes"]["ROUTING"])
        core["netnames"]["hclk"]["attributes"]["ROUTING"] = encode_route(
            core_clock + [item for item in clock_items if item[1]])
        for name in list(overlay.get("netnames", {})):
            if overlay["netnames"][name].get("bits") == [hclk_bit]:
                del overlay["netnames"][name]

    for name, cell in overlay.get("cells", {}).items():
        core["cells"][PREFIX + name] = cell
    merged_event_name = None
    for name, net in overlay.get("netnames", {}).items():
        merged = PREFIX + name
        if net.get("bits") == [event_bit]:
            merged_event_name = merged
        core["netnames"][merged] = net
    if merged_event_name is None:
        raise StatusOverlayError("status_set routed net disappeared during merge")

    _drop_destinations(core["netnames"]["hwdata[1]"], HW_REMOVED)
    _drop_destinations(core["netnames"]["public_status_pending"], PENDING_REMOVED)
    setter = core["cells"]["public_set_event"]
    setter["connections"]["I"] = [event_bit, "0", "0", "0"]
    setter["parameters"]["INIT"] = "1010101010101010"

    router = _Router(core, devdb)
    router.extend(merged_event_name,
                  [router.pin("public_set_event", "I", 0)])
    _route_owners(core)

    report = {
        "schema": 1,
        "core_sha256": CORE_SHA256,
        "overlay_sha256": hashlib.sha256(Path(overlay_path).read_bytes()).hexdigest(),
        "user_cells": len(overlay.get("cells", {})),
        "user_routed_nets": sum(bool(route_items(
            net.get("attributes", {}).get("ROUTING", "")))
            for net in overlay.get("netnames", {}).values()),
        "event_net": merged_event_name,
        "event_sink": router.pin("public_set_event", "I", 0),
        "scope": "one scalar, pure-fabric, separately routed synchronous status event",
    }
    return design, report


def compose_files(overlay_path, output_path, *, core_path=DEFAULT_CORE,
                  devdb=DEFAULT_DEVDB):
    design, report = compose(overlay_path, core_path=core_path, devdb=devdb)
    encoded = (json.dumps(design, indent=2) + "\n").encode("utf-8")
    Path(output_path).write_bytes(encoded)
    report["output_sha256"] = hashlib.sha256(encoded).hexdigest()
    return report
