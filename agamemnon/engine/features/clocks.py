"""Clock-distribution selectors, preamble profiles, and HSE enable emission."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from agamemnon.engine.registry import CONSTANTS

from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


VP_AGM_007_CLOCK_TILES = frozenset({
    (1, 1), (12, 4), (14, 5), (20, 1), (20, 12),
})


def refuse_silicon_negative_clock_reach(clocked_tiles, options):
    """Fence the exact VP-AGM-007 far-site constellation and clock profile."""
    if (
        options.integer("AGAMEMNON_SYSCLK") == 100
        and options.integer("AGAMEMNON_HSE") == 8
        and VP_AGM_007_CLOCK_TILES <= set(clocked_tiles)
    ):
        sites = ", ".join("X%dY%d" % site for site in sorted(
            VP_AGM_007_CLOCK_TILES
        ))
        raise SystemExit(
            "VP-AGM-007: refusing the retained silicon-negative 100MHz/8MHz "
            "five-tile clock-reach constellation (%s); changed routes remain "
            "unqualified" % sites
        )


@dataclass
class ClockState:
    sets: list = field(default_factory=list)
    clocked_tiles: set = field(default_factory=set)
    registered: bool = False
    bram_x9_hse_input: bool = False
    bram_site_read_hse_input: bool = False
    bram_hse_input: bool = False
    ownership_exclusions: dict = field(default_factory=dict)
    owner_bit: int | None = None
    source_profile: str | None = None
    source_class: str | None = None
    active_slice_leaves: frozenset = frozenset()
    bram_edges: frozenset = frozenset()
    quarantined_extra_leaves: frozenset = frozenset()
    quarantined_bitstream_sha256: str | None = None
    catalog_sha256: str | None = None
    topology_sha256: str | None = None


class ClockFeature:
    descriptor = FeatureDescriptor(
        feature_id="clocks",
        options=(
            "AGAMEMNON_NGCLK",
            "AGAMEMNON_CLK_SEAM",
            "AGAMEMNON_SYSCLK",
            "AGAMEMNON_HSE",
            "AGAMEMNON_NOSPINE",
            "AGAMEMNON_NO_SEAM",
            "AGAMEMNON_NO_CLKGEN",
        ),
        chipdb_files=(
            "clock_source_profiles_l48.csv",
            "clock_legacy_extra_leaves.json",
            # Retained evidence for the one composite VP-AGM-007 quarantine.
            # N5.7A no longer loads this CSV as placement legality.
            "clock_reach_silicon_negative.csv",
            "clk0_spine.json",
            "logictile_clksel0.json",
            "logictile_asyncmux3.json",
        ),
        writable_regions=(
            WritableRegion("sparse_json", "clk0_spine.json"),
            WritableRegion("coordinate_json", "logictile_clksel0.json"),
            WritableRegion("coordinate_json", "logictile_asyncmux3.json"),
            WritableRegion("preamble_profile", "agamemnon/engine/preamble.py"),
        ),
        phase=EmissionPhase.CLOCKS,
        evidence=(
            "qualification/clock_divider_probe.v",
            "qualification/timing_evidence.jsonl",
        ),
        maturity="release",
        evidence_tier="individually_qualified",
        architecture=(
            "Construct global sources, clock nets, slice taps, and the BRAM clock feed."
        ),
        bitstream=(
            "Emit the qualified spine, tile clock/seam/async selectors, generated "
            "PLL or idle preamble, and HSE input enable."
        ),
    )

    def add_architecture(self, context):
        ctx, Loc, options = context.ctx, context.loc, context.options
        shared = context.shared
        wire_name, wires = shared["wire_name"], shared["wires"]
        inputs, clock_wires = shared["io_inputs"], shared["clock_wires"]
        global_count = options.integer("AGAMEMNON_NGCLK")
        for index in range(global_count):
            # N5.7A exposes exactly one admitted whole-device spine.  Keep the
            # index in the type so a future GCLK1 cannot silently inherit the
            # GCLK0 ownership contract merely because it shares a spelling
            # convention.
            ctx.addWire(
                name="GCLK%d" % index,
                type="GCLK%d_SPINE" % index,
                x=0,
                y=0,
            )
        if global_count:
            for clock_type, z in (("MCU_SYS_CLOCK", 118), ("MCU_BUS_CLOCK", 119)):
                bel = "X10Y5_%s" % clock_type
                ctx.addBel(
                    name=bel, type=clock_type, loc=Loc(10, 5, z),
                    gb=True, hidden=False,
                )
                ctx.addBelOutput(bel=bel, name="CLK", wire="GCLK0")
        delay = ctx.getDelayFromNS(0.05)
        pip_count = 0
        for (x, y), resource in inputs:
            source = wire_name(x, y, resource)
            for index in range(global_count):
                ctx.addPip(
                    name="%s.GCLK%d" % (source, index),
                    type="GCLK%d_ENTRY" % index,
                    srcWire=source, dstWire="GCLK%d" % index, delay=delay,
                    loc=Loc(0, 0, 0),
                )
                pip_count += 1
        for clock_wire in clock_wires:
            for index in range(global_count):
                ctx.addPip(
                    name="GCLK%d.%s" % (index, clock_wire),
                    type="GCLK%d_SLICE_LEAF" % index,
                    srcWire="GCLK%d" % index, dstWire=clock_wire,
                    delay=delay, loc=Loc(0, 0, 0),
                )
                pip_count += 1
        bram_feed = wire_name(13, 0, "BufMUX05")
        if bram_feed in wires:
            for index in range(global_count):
                ctx.addPip(
                    name="GCLK%d.%s" % (index, bram_feed),
                    type="GCLK%d_BRAM_ROOT" % index,
                    srcWire="GCLK%d" % index, dstWire=bram_feed,
                    delay=delay, loc=Loc(13, 0, 0),
                )
                pip_count += 1
            print("AGRV2K arch: added BRAM clock feed "
                  "(GCLK -> ClkdisTILE(13,0) BufMUX05)")
        print("AGRV2K arch: added %d global-clock nets + %d clock pips" %
              (global_count, pip_count))
        return global_count + pip_count

    def prepare(self, clocked_tiles, registered_sets, bram_cells,
                selector_cells, chipdb_root, options, validated_clock):
        # Placement is useful only as a cross-check.  The routed validator is
        # the authority for the one admitted owner, source, tree, and selector
        # footprint; emission must never derive a clock plan from placement
        # alone.
        placed_clocked_tiles = set(clocked_tiles)
        clocked_tiles = set(validated_clock.clocked_tiles)
        if placed_clocked_tiles != clocked_tiles:
            raise SystemExit(
                "clocks: routed active-leaf tiles disagree with core-logic "
                "placement (%s versus %s)" %
                (sorted(clocked_tiles), sorted(placed_clocked_tiles))
            )
        refuse_silicon_negative_clock_reach(clocked_tiles, options)
        spine = [
            tuple(bit) for bit in json.loads(
                (chipdb_root / "clk0_spine.json").read_text(encoding="utf-8")
            )
        ]
        clksel0 = json.loads(
            (chipdb_root / "logictile_clksel0.json").read_text(encoding="utf-8")
        )
        asyncmux3 = json.loads(
            (chipdb_root / "logictile_asyncmux3.json").read_text(encoding="utf-8")
        )
        state = ClockState(
            sets=[] if os.environ.get("AGAMEMNON_NOSPINE") else list(spine),
            clocked_tiles=clocked_tiles,
            registered=(
                bool(validated_clock.active_slice_leaves)
                and not options.enabled("AGAMEMNON_NO_CLKGEN")
            ),
            owner_bit=validated_clock.owner_bit,
            source_profile=validated_clock.source_profile,
            source_class=validated_clock.source_class,
            active_slice_leaves=validated_clock.active_slice_leaves,
            bram_edges=validated_clock.bram_edges,
            quarantined_extra_leaves=validated_clock.quarantined_extra_leaves,
            quarantined_bitstream_sha256=(
                validated_clock.quarantined_bitstream_sha256
            ),
            catalog_sha256=validated_clock.catalog_sha256,
            topology_sha256=validated_clock.topology_sha256,
        )
        seam_selection = options.integer("AGAMEMNON_CLK_SEAM")
        # A clocked tile with no entry in these tables used to be skipped in
        # silence: its FFs were placed, its slices presented, its data routed,
        # and the tile clock select was simply never programmed -- so the design
        # config-accepted (FCB 0x000f0002) and the registers never advanced.
        # Both tables are complete for all 132 placeable LogicTiles (and a slice
        # BEL exists nowhere else), so failing closed costs nothing and pins that
        # completeness claim instead of trusting it.
        for x, y in sorted(state.clocked_tiles):
            key = "%d,%d" % (x, y)
            for table, name in ((clksel0, "logictile_clksel0.json"),
                                (asyncmux3, "logictile_asyncmux3.json")):
                if key not in table:
                    raise SystemExit(
                        "clocks: %s has no entry for clocked LogicTile X%sY%s; "
                        "refusing to emit a clocked design whose tile clock "
                        "select would be left unprogrammed" % (name, x, y)
                    )
            state.sets.append(tuple(clksel0[key]))
            if not os.environ.get("AGAMEMNON_NO_SEAM"):
                seam = selector_cells.get((x, y, "CFG_SEAMMUX", seam_selection))
                if not seam:
                    raise SystemExit(
                        "clocks: pips_full.csv has no CFG_SEAMMUX sel %d cell at "
                        "clocked LogicTile X%sY%s (AGAMEMNON_CLK_SEAM=%d); "
                        "refusing to emit a clocked tile with no seam selection"
                        % (seam_selection, x, y, seam_selection)
                    )
                state.sets.append(seam)
            state.sets.append(tuple(asyncmux3[key]))
        state.bram_x9_hse_input = any(
            width == 8 for _x, _y, width, _width_b, _mode in bram_cells
        )
        state.bram_site_read_hse_input = bool(
            bram_cells and options.enabled("AGAMEMNON_BRAM_SITE_READ_PATHS")
        )
        state.bram_hse_input = (
            state.bram_x9_hse_input or state.bram_site_read_hse_input or bool(
                bram_cells and options.enabled("AGAMEMNON_BRAM_HSE_INPUT")
            )
        )
        print("clock bits: %d (spine + %d clocked-tile seam/select/async)" %
              (len(state.sets), len(state.clocked_tiles)))
        return state

    def clear_bitstream(self, context):
        return 0

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "clock")
                count += 1
        return count

    def writable_bits(self, state):
        bits = set(state.sets)
        if state.registered or state.bram_hse_input:
            bits.add(tuple(CONSTANTS["hse_input_bit"].value))
        return bits

    def exclude_ownership(self, state, bits):
        for byte, mask in bits:
            state.ownership_exclusions[byte] = (
                state.ownership_exclusions.get(byte, 0) | mask
            )

    def writable_byte_ranges(self):
        from agamemnon.engine import preamble

        return ((0, preamble.PREAMBLE_LENGTH),)

    def emit_global(self, context: BitstreamContext) -> int:
        from agamemnon.engine import preamble

        sysclk = context.options.integer("AGAMEMNON_SYSCLK")
        hse = context.options.integer("AGAMEMNON_HSE")
        preamble.apply(
            context.image,
            clocked=context.state.registered,
            sysclk=sysclk,
            hse=hse,
        )
        if context.ownership is not None:
            context.ownership.clearing().touch_bytes(
                0,
                preamble.PREAMBLE_LENGTH,
                "default",
            )
            if context.state.registered:
                for byte, (idle, emitted) in enumerate(zip(
                        preamble.IDLE_PROFILE,
                        context.image[:preamble.PREAMBLE_LENGTH])):
                    changed = idle ^ emitted
                    changed &= ~context.state.ownership_exclusions.get(byte, 0)
                    if changed:
                        context.ownership.touch(byte, changed, "clock")
        print("generated OPEN preamble profile %s" % (
            "PLL SYSCLK=%d HSE=%d" % (sysclk, hse)
            if context.state.registered else "idle"
        ))

        count = preamble.PREAMBLE_LENGTH
        if context.state.registered or context.state.bram_hse_input:
            byte, mask = CONSTANTS["hse_input_bit"].value
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "clock")
                count += 1
            if context.state.registered:
                print("emitted OPEN %dMHz clock (gen preamble + HSE input CFG_IOMUX11[9]@(22,4))" %
                      sysclk)
            elif context.state.bram_hse_input:
                print("emitted %s BRAM HSE input CFG_IOMUX11[9]@(22,4)" %
                      ("x9" if context.state.bram_x9_hse_input else
                       "site-read" if context.state.bram_site_read_hse_input else
                       "forced"))
        return count


FEATURE = ClockFeature()
