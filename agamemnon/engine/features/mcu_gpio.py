"""MCU GPIO5 corridor metadata and coherent inactive-terminal emission."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field

from .mcu_ahb import exact_wire
from .protocol import BitstreamContext, EmissionPhase, FeatureDescriptor, WritableRegion


CFG_FILES = (
    "mcu_gpio5_loop_pip_cfg.csv",
    "mcu_gpio5_loop_l48_pip_cfg.csv",
    "mcu_gpio5_lane0_l48_pip_cfg.csv",
)

PATH_FILES = (
    "mcu_gpio5_loop_paths.csv",
    "mcu_gpio5_loop_l48_paths.csv",
    "mcu_gpio5_lane0_l48_paths.csv",
)


@dataclass
class McuGpioState:
    sets: list = field(default_factory=list)


class McuGpioFeature:
    descriptor = FeatureDescriptor(
        feature_id="mcu_gpio",
        options=(),
        chipdb_files=CFG_FILES + PATH_FILES,
        writable_regions=tuple(
            WritableRegion("selector_table", filename) for filename in CFG_FILES
        ),
        phase=EmissionPhase.MCU_EDGES,
        evidence=("qualification/mcu_gpio5_route_evidence.jsonl",),
        maturity="release",
        architecture="GPIO5 typed corridors remain in arch.py until A-arch.",
        bitstream=(
            "Load exact GPIO5 corridor fields and emit the qualified coherent "
            "inactive BBMUXS terminal defaults."
        ),
    )

    def add_architecture(self, context):
        return None

    def load_exact_pip_fields(self, chipdb_root):
        fields = {}
        for filename in CFG_FILES:
            path = chipdb_root / filename
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    key = exact_wire(row["src_wire"]) + exact_wire(row["dst_wire"])
                    value = (
                        row["cell_table"],
                        row["cfg_group"],
                        tuple(int(item) for item in row["clear_selectors"].split(";") if item),
                        tuple(int(item) for item in row["set_selectors"].split(";") if item),
                    )
                    if key in fields and fields[key] != value:
                        raise SystemExit("conflicting exact MCU GPIO codeword for %s" % (key,))
                    fields[key] = value
        return fields

    def prepare(self, module, mcu_cells):
        state = McuGpioState()
        source_types = {
            "MCU_GPIO5_OUT_DATA0", "MCU_GPIO5_OUT_EN0",
            "MCU_GPIO5_OUT_DATA1", "MCU_GPIO5_OUT_EN1",
        }
        if any(cell.get("type") in source_types for cell in module.get("cells", {}).values()):
            for mux in (0, 1, 3, 4, 5, 6, 7):
                bit = mcu_cells.get((9, 5, "BBMUXS%d" % mux, 8))
                if bit is None:
                    raise SystemExit(
                        "missing characterized GPIO5 inactive-terminal default "
                        "BBMUXS%d[8]" % mux
                    )
                state.sets.append(bit)
            print("GPIO5 L48 boundary: selected 7 characterized inactive BBMUXS terminal defaults")
        return state

    def clear_bitstream(self, context):
        return 0

    def emit_bitstream(self, context: BitstreamContext) -> int:
        count = 0
        for byte, mask in context.state.sets:
            if byte < len(context.image):
                context.image[byte] |= mask
                if context.ownership is not None:
                    context.ownership.touch(byte, mask, "PIP")
                count += 1
        return count


FEATURE = McuGpioFeature()
