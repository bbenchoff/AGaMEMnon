"""Clock-distribution selectors, preamble profiles, and HSE enable emission."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from agamemnon.engine.registry import CONSTANTS

from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


@dataclass
class ClockState:
    sets: list = field(default_factory=list)
    clocked_tiles: set = field(default_factory=set)
    registered: bool = False
    bram_x9_hse_input: bool = False
    bram_hse_input: bool = False


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
        architecture=(
            "Global sources, spines, and tile clock pips remain in arch.py until A-arch."
        ),
        bitstream=(
            "Emit the qualified spine, tile clock/seam/async selectors, generated "
            "PLL or idle preamble, and HSE input enable."
        ),
    )

    def add_architecture(self, context):
        return None

    def prepare(self, clocked_tiles, registered_sets, bram_cells,
                selector_cells, chipdb_root, options):
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
            clocked_tiles=set(clocked_tiles),
            registered=bool(registered_sets) and not os.environ.get("AGAMEMNON_NO_CLKGEN"),
        )
        seam_selection = options.integer("AGAMEMNON_CLK_SEAM")
        for x, y in sorted(state.clocked_tiles):
            key = "%d,%d" % (x, y)
            if key in clksel0:
                state.sets.append(tuple(clksel0[key]))
            seam = selector_cells.get((x, y, "CFG_SEAMMUX", seam_selection))
            if seam and not os.environ.get("AGAMEMNON_NO_SEAM"):
                state.sets.append(seam)
            if key in asyncmux3:
                state.sets.append(tuple(asyncmux3[key]))
        state.bram_x9_hse_input = any(
            width == 8 for _x, _y, width, _width_b, _mode in bram_cells
        )
        state.bram_hse_input = state.bram_x9_hse_input or bool(
            bram_cells and options.enabled("AGAMEMNON_BRAM_HSE_INPUT")
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
            context.ownership.touch_bytes(
                0,
                preamble.PREAMBLE_LENGTH,
                "clock" if context.state.registered else "default",
            )
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
                      ("x9" if context.state.bram_x9_hse_input else "forced"))
        return count


FEATURE = ClockFeature()
