"""Dedicated-carry slice selectors and byte-exact bitstream emission."""

from __future__ import annotations

import csv
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
        architecture=(
            "Synthetic Cin/Cout wires and qualified fixed carry seams remain in "
            "arch.py until the A-arch migration."
        ),
        bitstream=(
            "Clear mutually exclusive slice controls, then select dedicated Cin "
            "mode and explicitly requested bypass/carry controls."
        ),
    )

    def add_architecture(self, context):
        return None

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
