"""Dedicated-carry slice selectors and byte-exact bitstream emission."""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field

from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


@dataclass
class CarryState:
    fields: dict = field(default_factory=dict)
    sets: list = field(default_factory=list)
    clears: list = field(default_factory=list)


class CarryFeature:
    descriptor = FeatureDescriptor(
        feature_id="carry",
        options=("AGAMEMNON_HW_CARRY",),
        chipdb_files=("slice_cfg.csv",),
        writable_regions=(WritableRegion(
            kind="selector_table",
            source="slice_cfg.csv",
            byte_field="byte",
            mask_field="mask",
        ),),
        phase=EmissionPhase.LOGIC,
        evidence=("qualification/carry_evidence.jsonl",),
        maturity="release",
        evidence_tier="individually_qualified",
        architecture=(
            "Construct synthetic Cin/Cout wires and qualified fixed carry seams."
        ),
        bitstream=(
            "Clear mutually exclusive slice controls, then select dedicated Cin "
            "mode and explicitly requested bypass/carry controls."
        ),
    )

    def add_architecture(self, context):
        if not os.environ.get("AGAMEMNON_HW_CARRY"):
            return 0
        ctx, Loc = context.ctx, context.loc
        slice_bels = context.shared["slice_bels"]
        delay = ctx.getDelayFromNS(0.05)
        wire_count = pip_count = 0
        for (tile_x, tile_y), bels in slice_bels.items():
            for z in sorted(bels):
                carry_in = "X%dY%d_CARRYIN%02d" % (tile_x, tile_y, z)
                carry_out = "X%dY%d_CARRYOUT%02d" % (tile_x, tile_y, z)
                ctx.addWire(name=carry_in, type="CARRY", x=tile_x, y=tile_y)
                ctx.addWire(name=carry_out, type="CARRY", x=tile_x, y=tile_y)
                ctx.addBelInput(bel=bels[z], name="CIN", wire=carry_in)
                ctx.addBelOutput(bel=bels[z], name="COUT", wire=carry_out)
                wire_count += 2
            for z in sorted(bels):
                if z + 1 not in bels:
                    continue
                source = "X%dY%d_CARRYOUT%02d" % (tile_x, tile_y, z)
                destination = "X%dY%d_CARRYIN%02d" % (tile_x, tile_y, z + 1)
                ctx.addPip(
                    name="%s.%s" % (source, destination), type="CARRY",
                    srcWire=source, dstWire=destination, delay=delay,
                    loc=Loc(tile_x, tile_y, 0),
                )
                pip_count += 1
        for source_x, source_y, dest_x, dest_y in (
            (20, 12, 20, 11), (20, 11, 20, 12), (20, 12, 20, 10),
        ):
            source = "X%dY%d_CARRYOUT15" % (source_x, source_y)
            destination = "X%dY%d_CARRYIN00" % (dest_x, dest_y)
            if (
                (source_x, source_y) in slice_bels
                and 15 in slice_bels[(source_x, source_y)]
                and (dest_x, dest_y) in slice_bels
                and 0 in slice_bels[(dest_x, dest_y)]
            ):
                ctx.addPip(
                    name="%s.%s" % (source, destination), type="CARRY_SEAM",
                    srcWire=source, dstWire=destination,
                    delay=ctx.getDelayFromNS(0.10),
                    loc=Loc(source_x, source_y, 0),
                )
                pip_count += 1
        print("AGRV2K arch: HW-CARRY on: %d synthetic carry wires + %d "
              "qualified COUT->CIN pips" % (wire_count, pip_count))
        return wire_count + pip_count

    def load_slice_config(self, chipdb_root):
        fields = {}
        path = chipdb_root / self.descriptor.chipdb_files[0]
        if path.exists():
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    fields[(int(row["x"]), int(row["y"]), row["feature"])] = (
                        int(row["byte"]), int(row["mask"])
                    )
            print("loaded %d LE-internal slice-config bits (slice_cfg.csv)" % len(fields))
        return fields

    def prepare(self, module, fields):
        state = CarryState(fields=fields)
        for cell in module.get("cells", {}).values():
            if cell.get("type") not in ("GENERIC_SLICE", "AGRV2K_DUAL_LUT_CONST"):
                continue
            bel = cell["attributes"]["NEXTPNR_BEL"]
            match = re.match(r"X(\d+)Y(\d+)_(?:DUAL_)?SLICE(\d+)", bel)
            x, y, z = (int(group) for group in match.groups())
            connections = cell.get("connections", {})
            has_cin = bool(connections.get("CIN"))
            has_cout = bool(connections.get("COUT"))

            normal_carry_crl = cell.get("attributes", {}).get("AGRV2K_CARRY_CRL")
            if normal_carry_crl is not None and int(str(normal_carry_crl), 2):
                if has_cin or has_cout:
                    raise SystemExit(
                        "AGRV2K_CARRY_CRL is only valid on a plain non-carry slice"
                    )
                bit = fields.get((x, y, "CFG_CARRY_CRL[%d]" % z))
                if not bit:
                    raise SystemExit("missing CFG_CARRY_CRL[%d] at X%dY%d" % (z, x, y))
                state.sets.append(bit)

            if has_cin or has_cout:
                for feature in (
                    "CFG_LUTCMUX[%d]" % (2 * z),
                    "CFG_LUTCMUX[%d]" % (2 * z + 1),
                    "CFG_BYPASSEN[%d]" % z,
                    "CFG_CARRY_CRL[%d]" % z,
                ):
                    bit = fields.get((x, y, feature))
                    if bit:
                        state.clears.append(bit)
                bit = fields.get((x, y, "CFG_LUTCMUX[%d]" % (2 * z + 1)))
                if bit:
                    state.sets.append(bit)

            if has_cin:
                bypass = cell.get("parameters", {}).get("BYPASSEN")
                if bypass is not None and int(str(bypass), 2):
                    bit = fields.get((x, y, "CFG_BYPASSEN[%d]" % z))
                    if bit:
                        state.sets.append(bit)
        return state

    def clear_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.clears:
            if byte < len(context.image):
                context.image[byte] &= (~mask) & 0xFF
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "LUT")
                count += 1
        return count

    def writable_bits(self, state):
        return set(state.clears) | set(state.sets)

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "LUT")
                count += 1
        return count


FEATURE = CarryFeature()
