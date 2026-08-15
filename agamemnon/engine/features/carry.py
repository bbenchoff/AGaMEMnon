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
        # carry_seam_corpus.csv is reference data, not consumed by emission: the
        # 113 vendor-observed inter-tile seams and the two invariants they obey.
        # It exists so the three hard-coded seam pips below can be checked
        # against the corpus rather than against memory.
        chipdb_files=("slice_cfg.csv", "carry_seam_corpus.csv"),
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
        # NOTE (2026-08-15, carry_seam_corpus.csv): of these three, only
        # (20,12)->(20,11) matches the vendor corpus. Every one of 19,790
        # observed inter-tile crossings goes (x,y)->(x,y-1) via SLICE15->SLICE0;
        # (20,11)->(20,12) is UPWARD and (20,12)->(20,10) SKIPS a tile, and
        # neither shape appears anywhere in 3,842 routed vendor netlists. They
        # are retained because carry_evidence.jsonl records a silicon pass for
        # the 33-stage order that uses them, but that trial's observable was
        # narrow, so treat them as unconfirmed rather than as evidence that the
        # hardware is richer than the vendor placer admits.
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

    @staticmethod
    def _require(fields, x, y, z, feature):
        """Return the slice-config cell for *feature*, or fail closed."""
        bit = fields.get((x, y, feature))
        if not bit:
            raise SystemExit(
                "carry: slice_cfg.csv has no %s cell at X%dY%d slice%d; refusing "
                "to emit a carry slice whose dedicated-Cin controls would be left "
                "at their canvas value (config-accepts, computes without carry)"
                % (feature, x, y, z)
            )
        return bit

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
                # slice_cfg.csv carries all four controls for every slice of all
                # 132 LogicTiles. A silent miss here was the worst kind: the
                # mutually exclusive controls stayed at their canvas value and
                # CFG_LUTCMUX[2z+1] -- the bit that actually selects dedicated
                # Cin instead of pinC -- was never set, so the adder placed,
                # routed, config-accepted, and computed without its carry.
                for feature in (
                    "CFG_LUTCMUX[%d]" % (2 * z),
                    "CFG_LUTCMUX[%d]" % (2 * z + 1),
                    "CFG_BYPASSEN[%d]" % z,
                    "CFG_CARRY_CRL[%d]" % z,
                ):
                    state.clears.append(self._require(fields, x, y, z, feature))
                state.sets.append(
                    self._require(fields, x, y, z, "CFG_LUTCMUX[%d]" % (2 * z + 1))
                )

            if has_cin:
                bypass = cell.get("parameters", {}).get("BYPASSEN")
                if bypass is not None and int(str(bypass), 2):
                    # An explicitly requested mode. Silently dropping it handed
                    # back the default with no indication the request was lost.
                    state.sets.append(
                        self._require(fields, x, y, z, "CFG_BYPASSEN[%d]" % z)
                    )
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
