"""Physical package-I/O selector loading, preparation, and emission."""

from __future__ import annotations

import collections
import csv
import os
import re
from dataclasses import dataclass, field

from .mcu_ahb import exact_wire
from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


BITSTREAM_FILES = (
    "pips_io.csv",
    "physical_iob_L48.csv",
    "physical_iob_edges_L48.csv",
    "iomux_hop_vendor.csv",
    "padfeed_L48_top.csv",
    "padfeed_L48_left.csv",
    "pad_input_L48.csv",
    # Reference measurement, not a writable region: the fifteen af.exe slot-set
    # oracles on IOTILE (19,13) against a no-pad control from the same flow.
    # io_emit.index_config() reproduces every row exactly, which is what turns
    # the pad CFG_IOMUX config from a six-of-fifteen lookup table into a rule.
    "pad_iomux_slotset_L48.csv",
    # Measured per-pad electrical config bits (CFG_PULL_UP / CFG_OPEN_DRAIN).
    # These sit in the regenerated preamble region, so they are applied in the
    # preamble phase, after preamble.apply() rewrites [0:164].
    "io_pad_electrical_L48.csv",
)

# Complete vendor-routed four-link L48 corridors: the four independent
# left-edge dynamic-OE trunks and the paired link-input reduction corridors.
# The rows are consumed three ways: the architecture graph gains the exact
# OE hops, the C++ packer locks every hop before general placement, and the
# exact route mapper emits each configurable hop's selector codeword.
CORRIDOR_FILES = (
    "pad_oe_L48_left_corridors.csv",
    "pad_input_L48_left_corridors.csv",
)

ARCHITECTURE_FILES = (
    "io_pads.csv",
    "io_pads_AGRV2KL48.csv",
    "pad_input_route_L48.csv",
    "padout_L48_left_corridors.csv",
    "iomux_term_vendor.csv",
)

PACKAGE_FILES = (
    "bondmap_L100.csv",
    "bondmap_L48.csv",
    "bondmap_L64.csv",
    "bondmap_Q32.csv",
)


@dataclass
class PhysicalIoState:
    sets: list = field(default_factory=list)
    clears: list = field(default_factory=list)
    pips: set = field(default_factory=set)
    physical_oe_pip: dict = field(default_factory=dict)
    physical_fixed_pip: set = field(default_factory=set)
    iomux_hop: dict = field(default_factory=dict)
    padfeed_exact: dict = field(default_factory=dict)
    left_pad_companion: dict = field(default_factory=dict)
    pad_input_edge: dict = field(default_factory=dict)
    io_pad_hops: set = field(default_factory=set)
    io_cells: dict = field(default_factory=dict)
    pad_input_used: set = field(default_factory=set)
    electrical_used: list = field(default_factory=list)


def parse_wire(wire):
    match = re.match(r"X(\d+)Y(\d+)_([A-Za-z]+)(\d+)", wire)
    if not match:
        return None
    return (
        int(match.group(1)), int(match.group(2)),
        match.group(3), int(match.group(4)),
    )


def _resource(resource):
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", resource)
    return match.group(1), int(match.group(2))


def _cells(text):
    return [
        (int(part.split(":")[0]), int(part.split(":")[1]))
        for part in (text or "").split(";") if part
    ]


class PhysicalIoFeature:
    descriptor = FeatureDescriptor(
        feature_id="physical_io",
        options=(
            "AGAMEMNON_PHYSICAL_IO",
            "AGAMEMNON_LEDPADS",
            "AGAMEMNON_PADFEED_TOP",
            "AGAMEMNON_HARDEN_PADFEED",
            "AGAMEMNON_LEFT_PAD_OUT",
        ),
        chipdb_files=BITSTREAM_FILES + ARCHITECTURE_FILES + PACKAGE_FILES +
        CORRIDOR_FILES,
        writable_regions=(
            WritableRegion("cell_map", "pips_io.csv", "byte", "mask"),
            WritableRegion(
                "encoded_sparse_table", "padfeed_L48_top.csv",
                "codeword_bytes", "codeword_masks",
            ),
            WritableRegion(
                "encoded_sparse_table", "padfeed_L48_left.csv",
                "codeword_bytes", "codeword_masks",
            ),
            WritableRegion(
                "encoded_sparse_table", "pad_input_L48.csv",
                "enable_byte", "enable_mask",
            ),
            WritableRegion(
                "measured_bit_table", "io_pad_electrical_L48.csv",
                "raw_byte", "bit",
            ),
        ) + tuple(
            WritableRegion("selector_table", filename)
            for filename in CORRIDOR_FILES
        ),
        phase=EmissionPhase.IO,
        evidence=(
            "qualification/io_evidence.jsonl",
            "qualification/left_edge_output_evidence.jsonl",
        ),
        maturity="release",
        evidence_tier="individually_qualified",
        architecture=(
            "Construct generic and package-aware pad BELs plus qualified "
            "perimeter corridors."
        ),
        bitstream=(
            "Emit qualified left/top ring-pad IOMUX selectors, dynamic-OE "
            "selectors, pad-feed codewords, and perimeter-input enables."
        ),
    )

    def add_architecture(self, context):
        ctx, Loc, device = context.ctx, context.loc, context.device
        root, shared = context.chipdb_root, context.shared
        wire_name, wires = shared["wire_name"], shared["wires"]

        input_connections = {}
        output_connections = {}
        with (root / "rrg_edges_full.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            for row in csv.DictReader(stream):
                if row["src_res"].startswith("InputMUX"):
                    input_connections.setdefault(
                        (row["src_x"], row["src_y"]), set()
                    ).add(row["src_res"])
                if row["dst_res"].startswith("IOMUX"):
                    output_connections.setdefault(
                        (row["dst_x"], row["dst_y"]), set()
                    ).add(row["dst_res"])
        inputs = sorted(
            (coordinates, resource)
            for coordinates, resources in input_connections.items()
            for resource in resources
        )
        outputs = sorted(
            (coordinates, resource)
            for coordinates, resources in output_connections.items()
            for resource in resources
        )

        generic_count = 0
        for z in range(min(len(inputs), len(outputs))):
            (input_x, input_y), input_resource = inputs[z]
            (output_x, output_y), output_resource = outputs[z]
            bel = "X%sY%s_IO%d" % (input_x, input_y, z)
            ctx.addBel(
                name=bel, type="GENERIC_IOB",
                loc=Loc(int(input_x), int(input_y), z), gb=False, hidden=False,
            )
            ctx.addBelOutput(
                bel=bel, name="O",
                wire=wire_name(input_x, input_y, input_resource),
            )
            ctx.addBelInput(
                bel=bel, name="I",
                wire=wire_name(output_x, output_y, output_resource),
            )
            generic_count += 1
        print("AGRV2K arch: added %d fully-capable GENERIC_IOB bels "
              "(%d in-conn, %d out-conn)" %
              (generic_count, len(inputs), len(outputs)))

        if os.environ.get("AGAMEMNON_PHYSICAL_IO"):
            default_top_inputmux = {0: 1, 1: 2, 2: 4, 3: 7}
            verified_inputmux = {}
            table = root / "pad_input_L48.csv"
            if table.exists():
                with table.open(newline="", encoding="utf-8") as stream:
                    for row in csv.DictReader(stream):
                        pad = device.bond_map.get(row.get("verified_pin"))
                        if pad is not None:
                            verified_inputmux[tuple(pad[:3])] = int(row["inputmux"])
            input_count = 0
            for _pin, pad in sorted(device.bond_map.items()):
                x, y, z, edge = pad
                if edge != "TOP" or z not in default_top_inputmux:
                    continue
                inputmux = verified_inputmux.get(
                    (x, y, z), default_top_inputmux[z]
                )
                wire = wire_name(x, y, "InputMUX%02d" % inputmux)
                if wire not in wires:
                    continue
                bel = "X%dY%d_IPAD%d" % (x, y, z)
                ctx.addBel(
                    name=bel, type="GENERIC_IOB",
                    loc=Loc(x, y, 200 + z), gb=False, hidden=False,
                )
                ctx.addBelOutput(bel=bel, name="O", wire=wire)
                input_count += 1
            print("AGRV2K arch: added %d physical L48 top-row INPUT pad bels" %
                  input_count)

            bidirectional_count = 0
            table = root / "physical_iob_L48.csv"
            if device.name == "AGRV2KL48" and table.exists():
                with table.open(newline="", encoding="utf-8") as stream:
                    for row in csv.DictReader(stream):
                        x, y, z = int(row["x"]), int(row["y"]), int(row["z"])
                        output_wire = wire_name(
                            x, y, "InputMUX%02d" % int(row["inputmux"])
                        )
                        input_wire = wire_name(
                            x, y, "IOMUX%02d" % int(row["data_iomux"])
                        )
                        enable_wire = wire_name(
                            x, y, "IOMUX%02d" % int(row["oe_iomux"])
                        )
                        if not all(
                            wire in wires
                            for wire in (output_wire, input_wire, enable_wire)
                        ):
                            continue
                        bel = "X%dY%d_IOB%d" % (x, y, z)
                        ctx.addBel(
                            name=bel, type="GENERIC_IOB",
                            loc=Loc(x, y, 300 + z), gb=False, hidden=False,
                        )
                        ctx.addBelOutput(bel=bel, name="O", wire=output_wire)
                        ctx.addBelInput(bel=bel, name="I", wire=input_wire)
                        ctx.addBelInput(bel=bel, name="EN", wire=enable_wire)
                        bidirectional_count += 1
            print("AGRV2K arch: added %d characterized physical L48 BIDIR pad bels" %
                  bidirectional_count)

        if os.environ.get("AGAMEMNON_LEDPADS"):
            pad_count = 0
            with (root / "io_pads.csv").open(
                newline="", encoding="utf-8"
            ) as stream:
                for row in csv.DictReader(stream):
                    x, y, z = row["x"], row["y"], int(row["iomux"])
                    wire = wire_name(x, y, "IOMUX%02d" % z)
                    if wire not in wires:
                        continue
                    bel = "X%sY%s_OPAD%d" % (x, y, z)
                    ctx.addBel(
                        name=bel, type="GENERIC_IOB",
                        loc=Loc(int(x), int(y), 100 + z),
                        gb=False, hidden=False,
                    )
                    ctx.addBelInput(bel=bel, name="I", wire=wire)
                    pad_count += 1
            if inputs:
                (clock_x, clock_y), clock_resource = inputs[0]
                ctx.addBel(
                    name="CLKIN", type="GENERIC_IOB", loc=Loc(1, 4, 220),
                    gb=False, hidden=False,
                )
                ctx.addBelOutput(
                    bel="CLKIN", name="O",
                    wire=wire_name(clock_x, clock_y, clock_resource),
                )
            print("AGRV2K arch: added %d ring-pad OUTPUT bels "
                  "(IOMUX pad wires) + CLKIN" % pad_count)

        shared["io_input_connections"] = input_connections
        shared["io_output_connections"] = output_connections
        shared["io_inputs"] = inputs
        shared["io_outputs"] = outputs
        return generic_count

    def load_exact_pip_fields(self, chipdb_root):
        """Load the exact four-link corridor codewords, keyed like MCU pips.

        Rows without a ``cell_table`` are fixed or independently encoded hops
        retained only for routing continuity; they contribute no selector
        codeword here.
        """
        fields = {}
        for filename in CORRIDOR_FILES:
            path = chipdb_root / filename
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    if not row.get("cell_table"):
                        continue
                    key = exact_wire(row["src_wire"]) + exact_wire(row["dst_wire"])
                    value = (
                        row["cell_table"],
                        row["cfg_group"],
                        tuple(
                            int(item) for item in row["clear_selectors"].split(";")
                            if item
                        ),
                        tuple(
                            int(item) for item in row["set_selectors"].split(";")
                            if item
                        ),
                    )
                    if key in fields and fields[key] != value:
                        raise SystemExit(
                            "conflicting exact package-I/O corridor codeword for %s"
                            % (key,)
                        )
                    fields[key] = value
        return fields

    def uses_node_pinout(self, module):
        """True when the routed design drives a bidirectional/output-enable pad.

        The four-link node build instantiates a combined ``GENERIC_IOB`` whose
        output-enable (``EN``) is fabric-driven.  Its left-edge OE and link-
        input corridors are emitted through the exact hard-boundary set, which
        is keyed by wire-pair, so an ordinary design that merely routes through
        one of those wires would otherwise pick up the corridor selectors.  The
        shipped SERV images (and every other release design) only ever bind a
        plain input (``O``) or plain output (``I``) pad, so gating the corridor
        emission on a driven ``EN`` keeps their byte-exact release image intact.
        """
        for cell in module.get("cells", {}).values():
            if cell.get("type") != "GENERIC_IOB":
                continue
            if cell.get("connections", {}).get("EN"):
                return True
        return False

    def prepare(self, module, chipdb_root, selector_cells, archival_legacy,
                options=None):
        from agamemnon.engine import io_emit

        state = PhysicalIoState()
        state.io_cells = io_emit.CELLS
        self._prepare_electrical(state, chipdb_root, options)

        for filename in ("padfeed_L48_top.csv", "padfeed_L48_left.csv"):
            path = chipdb_root / filename
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    source = row["src_res"]
                    family = source.rstrip("0123456789")
                    index = int(source[len(family):])
                    bytes_ = [int(value) for value in row["codeword_bytes"].split(",") if value]
                    masks = [int(value) for value in row["codeword_masks"].split(",") if value]
                    key = (
                        int(row["padtile_x"]), int(row["padfeed_rmux"]),
                        int(row["src_x"]), int(row["src_y"]), family, index,
                    )
                    state.padfeed_exact[key] = list(zip(bytes_, masks))
                    if filename == "padfeed_L48_left.csv" and row.get("companion_cfg"):
                        state.left_pad_companion[int(row["iomux_z"])] = [
                            (row["companion_cfg"], int(selection))
                            for selection in row.get("companion_sels", "").split(",")
                            if selection
                        ]
        print("loaded %d exact package pad-feed codewords" % len(state.padfeed_exact))

        path = chipdb_root / "physical_iob_L48.csv"
        if path.exists():
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    x, y = int(row["x"]), int(row["y"])
                    key = (
                        x, y, "RMUX", int(row["oe_rmux"]),
                        x, y, "IOMUX", int(row["oe_iomux"]),
                    )
                    state.physical_oe_pip[key] = (
                        int(row["cfg_x"]), int(row["cfg_y"]), row["oe_cfg"],
                        tuple(int(value) for value in row["oe_sels"].split(";") if value),
                    )

        path = chipdb_root / "physical_iob_edges_L48.csv"
        if path.exists():
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    if row.get("cfg"):
                        continue
                    sf, si = _resource(row["src_res"])
                    df, di = _resource(row["dst_res"])
                    state.physical_fixed_pip.add((
                        int(row["src_x"]), int(row["src_y"]), sf, si,
                        int(row["dst_x"]), int(row["dst_y"]), df, di,
                    ))

        path = chipdb_root / "iomux_hop_vendor.csv"
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                rows = csv.DictReader(line for line in stream if not line.lstrip().startswith("#"))
                for row in rows:
                    state.iomux_hop[(
                        int(row["pad_x"]), int(row["pad_y"]),
                        int(row["z"]), int(row["feeder_R"]),
                    )] = (_cells(row.get("set_cells")), _cells(row.get("clear_cells")))

        for net in module.get("netnames", {}).values():
            for token in net.get("attributes", {}).get("ROUTING", "").split(";"):
                if "." in token and "GCLK" not in token:
                    state.pips.add(token)

        left_selectors = {
            (0, 30): (1, 5),
            (1, 6): (8, 11),
            (2, 18): (17, 18),
            (3, 0): (21, 25),
        }
        left_outputs = []
        for token in state.pips:
            source_text, destination_text = token.split(".", 1)
            source, destination = parse_wire(source_text), parse_wire(destination_text)
            if source and destination and source + destination in state.physical_oe_pip:
                continue
            if (source and destination and destination[2] == "IOMUX" and
                    (destination[0], destination[1]) == (0, 4) and source[2] == "RMUX"):
                left_outputs.append((destination[3], source[3]))
                state.io_pad_hops.add((0, 4, destination[3]))

        for z, feeder in left_outputs:
            selections = left_selectors.get((z, feeder))
            if selections is None:
                if os.environ.get("AGAMEMNON_DEBUG"):
                    print("  LED (0,4) z%d<-R%d: NO source-select in LEFT_IOMUX0_SEL table" %
                          (z, feeder))
                continue
            for selection in selections:
                bit = io_emit.CELLS.get((0, 4, "CFG_IOMUX0"), {}).get(selection)
                if bit:
                    state.sets.append(bit)
            for bank in range(4):
                bit = io_emit.CELLS.get(
                    (0, 4, "CFG_IOMUX%d" % bank), {}
                ).get(7 * z + 6)
                if bit:
                    state.clears.append(bit)
            if not archival_legacy:
                for cfg, selection in state.left_pad_companion.get(z, ()):
                    bit = selector_cells.get((0, 4, cfg, selection))
                    if bit:
                        state.sets.append(bit)
        if left_outputs:
            print("IO LED pads (0,4) route-driven z<-R %s -> %d src-sel set + %d enable-clear" %
                  (sorted(left_outputs), len(state.sets), len(state.clears)))

        top_row = collections.defaultdict(list)
        for token in state.pips:
            source_text, destination_text = token.split(".", 1)
            source, destination = parse_wire(source_text), parse_wire(destination_text)
            if not source or not destination:
                continue
            if source + destination in state.physical_oe_pip:
                continue
            if destination[2] == "IOMUX" and destination[1] == 13 and source[2] == "RMUX":
                top_row[(destination[0], destination[1])].append((destination[3], source[3]))
        for (pad_x, pad_y), outputs in top_row.items():
            for (x, y, mux), selections in io_emit.CELLS.items():
                if (x, y) == (pad_x - 1, pad_y) and mux.startswith("CFG_IOMUX"):
                    state.clears += list(selections.values())
            bits = io_emit.emit_bits(pad_x - 1, pad_y, outputs)
            state.sets += list(bits)
            for z, feeder in outputs:
                hop_sets, hop_clears = state.iomux_hop.get(
                    (pad_x, pad_y, z, feeder), ([], [])
                )
                state.sets += hop_sets
                state.clears += hop_clears
                state.io_pad_hops.add((pad_x, pad_y, z))
            if os.environ.get("AGAMEMNON_DEBUG"):
                print("  IO top-row pad tile (%d,%d): outs=%s -> %d CFG_IOMUX bit(s) @N-1(%d,%d)" %
                      (pad_x, pad_y, sorted(outputs), len(bits), pad_x - 1, pad_y))
        if top_row:
            print("IO top-row pads: %s (CFG_IOMUX driver via io_emit; feeder CFG_RMUX from route)" %
                  {"%d,%d" % key: sorted(z for z, _ in value)
                   for key, value in top_row.items()})

        path = chipdb_root / "pad_input_L48.csv"
        if path.exists():
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    match = re.fullmatch(r"(CFG_[A-Z0-9]+)\[([0-9, ]+)\]", row["cfg"])
                    if not match:
                        raise SystemExit("bad pad_input_L48.csv cfg: %r" % row["cfg"])
                    key = (
                        int(row["pad_x"]), int(row["pad_y"]), int(row["inputmux"]),
                        int(row["dst_x"]), int(row["dst_y"]), int(row["dst_rmux"]),
                    )
                    # PIN_HSE is a hard CLKIN source, not an ordinary package
                    # IOB.  Its retained top-edge route needs the exact RMUX
                    # codeword below, while the clock-profile emitter owns the
                    # separate hard-HSE input enable.  A literal '-' records
                    # that deliberate empty pad-enable footprint without
                    # falling back to the legacy byte/mask columns.
                    if (row.get("set_cells") or "").strip() == "-":
                        sets = []
                    else:
                        sets = _cells(row.get("set_cells")) or [
                            (int(row["enable_byte"]), int(row["enable_mask"]))
                        ]
                    state.pad_input_edge[key] = (
                        match.group(1),
                        [int(value) for value in match.group(2).split(",")],
                        sets,
                        _cells(row.get("clear_cells")),
                    )
        return state

    def _prepare_electrical(self, state, chipdb_root, options):
        """Resolve requested per-pad electrical fields against the measured table.

        The pull-up/open-drain bits live inside the regenerated [0:164] preamble
        region (measured 2026-08-14 by per-pad set_config image differentials;
        PIN_16 pull-up and PIN_26 open-drain silicon-witnessed).  Emission is
        fail-closed to the exact (pin, field) rows of io_pad_electrical_L48.csv;
        eleven special-function pad sites produced no image change under the
        vendor mechanism and are deliberately absent.
        """
        if options is None:
            return

        def _pins(value):
            return [pin.strip().upper() for pin in (value or "").split(",") if pin.strip()]

        requests = [(pin, "CFG_PULL_UP")
                    for pin in _pins(options.raw("AGAMEMNON_IO_PULLUP"))]
        requests += [(pin, "CFG_OPEN_DRAIN")
                     for pin in _pins(options.raw("AGAMEMNON_IO_OPEN_DRAIN"))]
        if not requests:
            return
        table = {}
        path = chipdb_root / "io_pad_electrical_L48.csv"
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                table[(row["pin"], row["field"])] = (
                    int(row["raw_byte"]), 1 << int(row["bit"])
                )
        for pin, fieldname in requests:
            if (pin, fieldname) not in table:
                raise SystemExit(
                    "io electrical: %s has no measured %s cell in "
                    "io_pad_electrical_L48.csv (fail closed; the special-"
                    "function pad sites accept no such config)" % (pin, fieldname)
                )
            byte, mask = table[(pin, fieldname)]
            state.electrical_used.append((pin, fieldname, byte, mask))

    def clear_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.clears:
            if byte < len(context.image):
                context.image[byte] &= (~mask) & 0xFF
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "IO")
                count += 1
        return count

    def writable_bits(self, state):
        bits = set(state.clears) | set(state.sets)
        for _key, set_bits, clear_bits in state.pad_input_used:
            bits.update(set_bits)
            bits.update(clear_bits)
        for _pin, _field, byte, mask in state.electrical_used:
            bits.add((byte, mask))
        return bits

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "IO")
                count += 1
        return count

    def emit_pad_electrical(self, context: BitstreamContext) -> int:
        """Apply measured per-pad electrical bits after preamble regeneration."""
        for pin, fieldname, byte, mask in context.state.electrical_used:
            context.image[byte] |= mask
            if context.ownership is not None:
                context.ownership.touch(byte, mask, "IO")
        if context.state.electrical_used:
            print("pad electrical fields: %s" % sorted(
                "%s.%s@%d.%d" % (pin, fieldname, byte, mask.bit_length() - 1)
                for pin, fieldname, byte, mask in context.state.electrical_used
            ))
        return len(context.state.electrical_used)

    def emit_pad_inputs(self, context: BitstreamContext) -> int:
        if not context.state.pad_input_used:
            return 0
        sets = {
            bit for _key, set_bits, _clear_bits in context.state.pad_input_used
            for bit in set_bits
        }
        clears = {
            bit for _key, _set_bits, clear_bits in context.state.pad_input_used
            for bit in clear_bits
        }
        for byte, mask in clears:
            context.image[byte] &= ~mask
            if context.ownership is not None:
                context.ownership.touch(byte, mask, "IO")
        for byte, mask in sets:
            context.image[byte] |= mask
            if context.ownership is not None:
                context.ownership.touch(byte, mask, "IO")
        print("pad-input codeword set=%s clear=%s for route(s): %s" % (
            sorted(sets),
            sorted(clears),
            sorted(key for key, _sets, _clears in context.state.pad_input_used),
        ))
        return len(sets) + len(clears)


FEATURE = PhysicalIoFeature()
