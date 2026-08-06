"""Core LUT/FF preparation, baseline clearing, and bitstream emission."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agamemnon.engine import physmap

from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


@dataclass
class CoreLogicState:
    lut_sets: list = field(default_factory=list)
    register_sets: list = field(default_factory=list)
    slices: list = field(default_factory=list)
    clocked_tiles: set = field(default_factory=set)
    left_vendor_slices: set = field(default_factory=set)
    selector_cells: dict = field(default_factory=dict)


class CoreLogicFeature:
    descriptor = FeatureDescriptor(
        feature_id="core_logic",
        options=(
            "AGAMEMNON_VENDOR_OUT_ALL",
            "AGAMEMNON_VENDOR_OUT_SLICE",
            "AGAMEMNON_LEFT_PAD_OUT",
            "AGAMEMNON_DIRECT_D",
        ),
        chipdb_files=(),
        writable_regions=(
            WritableRegion("algorithmic_slice_init", "agamemnon/engine/physmap.py"),
            WritableRegion("selector_family", "pips_full.csv", "byte", "mask"),
        ),
        phase=EmissionPhase.LOGIC,
        evidence=(
            "qualification/pack_reproduction_evidence.jsonl",
            "qualification/routing_evidence.jsonl",
        ),
        maturity="release",
        architecture="LogicTile slice BEL construction remains in arch.py until A-arch.",
        bitstream=(
            "Clear every placed slice LUT and OMUX field, emit complemented LUT INIT "
            "bits, and select registered or qualified alternate OMUX presentation."
        ),
    )

    def add_architecture(self, context):
        return None

    def prepare(self, module, selector_cells, options, constants):
        state = CoreLogicState(selector_cells=selector_cells)
        vendor_out_all = options.enabled("AGAMEMNON_VENDOR_OUT_ALL")
        vendor_out_raw = options.raw("AGAMEMNON_VENDOR_OUT_SLICE")
        vendor_out = (
            options.coordinates("AGAMEMNON_VENDOR_OUT_SLICE")
            if vendor_out_raw else None
        )
        state.left_vendor_slices = (
            set(constants["left_vendor_slices"].value)
            if options.enabled("AGAMEMNON_LEFT_PAD_OUT") else set()
        )
        legacy_direct_d_sites = (
            {(14, 11, 4), (14, 11, 5), (14, 11, 6), (14, 11, 7)}
            if options.enabled("AGAMEMNON_DIRECT_D") else set()
        )

        for cell in module["cells"].values():
            cell_type = cell.get("type")
            if cell_type not in ("GENERIC_SLICE", "AGRV2K_DUAL_LUT_CONST"):
                continue
            bel = cell["attributes"]["NEXTPNR_BEL"]
            match = re.match(r"X(\d+)Y(\d+)_(?:DUAL_)?SLICE(\d+)", bel)
            x, y, z = (int(match.group(index)) for index in (1, 2, 3))
            direct_d_site = (x, y, z) in legacy_direct_d_sites
            if cell_type == "AGRV2K_DUAL_LUT_CONST":
                value = int(cell.get("parameters", {}).get("VALUE", "0"), 2)
                init = 0xFFFF if value else 0
                bit = selector_cells.get((x, y, "CFG_OMUX%d" % z, 0))
                if bit:
                    state.register_sets.append(bit)
            else:
                init = int(cell["parameters"]["INIT"], 2)

            state.slices.append((x, y, z))
            bram_selection = cell.get("attributes", {}).get("AGRV2K_OMUX_SEL")
            bram_selection = (
                int(str(bram_selection), 2) if bram_selection is not None else None
            )
            if int(cell["parameters"].get("FF_USED", "0"), 2):
                selections = (
                    (0, 1)
                    if (vendor_out_all or vendor_out == (x, y, z) or
                        (x, y, z) in state.left_vendor_slices or direct_d_site)
                    else ((bram_selection,) if bram_selection is not None else (2,))
                )
                for selection in selections:
                    bit = selector_cells.get((x, y, "CFG_OMUX%d" % z, selection))
                    if bit:
                        state.register_sets.append(bit)
                state.clocked_tiles.add((x, y))
            elif (vendor_out_all or (x, y, z) in state.left_vendor_slices or
                  direct_d_site):
                bit = selector_cells.get((x, y, "CFG_OMUX%d" % z, 0))
                if bit:
                    state.register_sets.append(bit)
            elif bram_selection is not None:
                bit = selector_cells.get(
                    (x, y, "CFG_OMUX%d" % z, bram_selection)
                )
                if bit:
                    state.register_sets.append(bit)

            for init_index in range(16):
                byte, mask = physmap.init_bit_pos(x, y, z, init_index)
                if not ((init >> init_index) & 1):
                    state.lut_sets.append((byte, mask))

        print("slices placed:", state.slices, "; LUT-init bits:", len(state.lut_sets))
        return state

    def clear_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for x, y, z in context.state.slices:
            for init_index in range(16):
                byte, mask = physmap.init_bit_pos(x, y, z, init_index)
                if byte < len(context.image):
                    context.image[byte] &= (~mask) & 0xFF
                    if context.ownership is not None:
                        context.ownership.touch(byte, mask, "LUT")
                    count += 1
            for selection in range(3):
                bit = context.state.selector_cells.get(
                    (x, y, "CFG_OMUX%d" % z, selection)
                )
                if bit and bit[0] < len(context.image):
                    context.image[bit[0]] &= (~bit[1]) & 0xFF
                    if context.ownership is not None:
                        context.ownership.touch(bit[0], bit[1], "LUT")
                    count += 1
        return count

    def writable_bits(self, state):
        bits = set(state.lut_sets)
        bits.update(state.register_sets)
        for x, y, z in state.slices:
            bits.update(
                physmap.init_bit_pos(x, y, z, init_index)
                for init_index in range(16)
            )
            bits.update(
                bit for selection in range(3)
                if (bit := state.selector_cells.get(
                    (x, y, "CFG_OMUX%d" % z, selection)
                ))
            )
        return bits

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.lut_sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "LUT")
                count += 1
        return count

    def emit_register_modes(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.register_sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "register_mode")
                count += 1
        print("registered slices (CFG_OMUX<z> sel=2 set): %d" %
              len(context.state.register_sets))
        return count


FEATURE = CoreLogicFeature()
