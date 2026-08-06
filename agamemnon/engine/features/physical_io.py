"""Physical package-I/O selector loading, preparation, and emission."""

from __future__ import annotations

import collections
import csv
import os
import re
from dataclasses import dataclass, field

from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


BITSTREAM_FILES = (
    "pips_io.csv",
    "physical_iob_L48.csv",
    "physical_iob_edges_L48.csv",
    "iomux_hop_vendor.csv",
    "padfeed_L48_top.csv",
    "padfeed_L48_left.csv",
    "pad_input_L48.csv",
)

ARCHITECTURE_FILES = (
    "io_pads.csv",
    "io_pads_AGRV2KL48.csv",
    "pad_input_route_L48.csv",
    "padout_L48_left_corridors.csv",
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
        chipdb_files=BITSTREAM_FILES + ARCHITECTURE_FILES,
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
        ),
        phase=EmissionPhase.IO,
        evidence=(
            "qualification/io_evidence.jsonl",
            "qualification/left_edge_output_evidence.jsonl",
        ),
        maturity="release",
        architecture=(
            "Physical pad BELs and qualified perimeter corridors remain in "
            "arch.py until the A-arch migration."
        ),
        bitstream=(
            "Emit qualified left/top ring-pad IOMUX selectors, dynamic-OE "
            "selectors, pad-feed codewords, and perimeter-input enables."
        ),
    )

    def add_architecture(self, context):
        return None

    def prepare(self, module, chipdb_root, selector_cells, archival_legacy):
        from agamemnon.engine import io_emit

        state = PhysicalIoState()
        state.io_cells = io_emit.CELLS

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

    def clear_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.clears:
            if byte < len(context.image):
                context.image[byte] &= (~mask) & 0xFF
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "IO")
                count += 1
        return count

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "IO")
                count += 1
        return count


FEATURE = PhysicalIoFeature()
