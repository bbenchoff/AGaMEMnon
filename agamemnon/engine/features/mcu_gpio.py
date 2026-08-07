"""MCU GPIO5 corridor metadata and coherent inactive-terminal emission."""

from __future__ import annotations

import collections
import csv
import os
import re
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
        evidence_tier="individually_qualified",
        architecture="Construct the qualified GPIO5 typed hard-boundary corridors.",
        bitstream=(
            "Load exact GPIO5 corridor fields and emit the qualified coherent "
            "inactive BBMUXS terminal defaults."
        ),
    )

    def add_architecture(self, context):
        ctx, Loc, DEV = context.ctx, context.loc, context.device
        DATA = str(context.chipdb_root)
        shared = context.shared
        wireset = shared["wires"]
        seen_pip = shared["seen_pips"]
        _wire_delay = shared["wire_delay"]
        bit_entry = shared["bit_entry"]
        bit_exit = shared["bit_exit"]
        n_mpip = shared["mcu_pip_count"]

        # One independently recovered GPIO5 boundary unit. Keep data, output-enable,
        # and return-input as separate typed hard ports so placement cannot silently
        # substitute the older GPIO4 loopback BELs. The table contains only literal
        # consecutive vendor-route nodes; it does not expose the full GPIO matrix.
        _gpio5_path_name = ("mcu_gpio5_loop_l48_paths.csv"
                            if DEV.name == "AGRV2KL48" else "mcu_gpio5_loop_paths.csv")
        _gpio5_path_csv = os.path.join(DATA, _gpio5_path_name)
        _n_gpio5 = 0; _gpio5_skip = 0
        if os.path.exists(_gpio5_path_csv):
            _gpio5_paths = collections.defaultdict(list)
            for _r in csv.DictReader(open(_gpio5_path_csv)):
                _gpio5_paths[_r["signal"]].append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _gpio5_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_gpio5 += 1
            _gpio5_data = _gpio5_paths.get("gpio5_io_out_data", [])
            _gpio5_enable = _gpio5_paths.get("gpio5_io_out_en", [])
            _gpio5_input = _gpio5_paths.get("gpio5_io_in", [])
            if _gpio5_data and _gpio5_data[0]["src_wire"] in wireset:
                bit_entry[259] = _gpio5_data[0]["src_wire"]
            else:
                _gpio5_skip += 1
            if _gpio5_enable and _gpio5_enable[0]["src_wire"] in wireset:
                bit_entry[260] = _gpio5_enable[0]["src_wire"]
            else:
                _gpio5_skip += 1
            if _gpio5_input and _gpio5_input[-1]["dst_wire"] in wireset:
                bit_exit[261] = _gpio5_input[-1]["dst_wire"]
            else:
                _gpio5_skip += 1
            print("AGRV2K arch: loaded %d GPIO5 boundary hop(s) from %s (%d skipped)"
                  % (_n_gpio5, _gpio5_path_name, _gpio5_skip))

        # A second L48-only GPIO5 lane is retained separately so the hard-boundary
        # source identity can be tested without implying a generic GPIO matrix.
        _gpio5_lane0_name = "mcu_gpio5_lane0_l48_paths.csv"
        _gpio5_lane0_csv = os.path.join(DATA, _gpio5_lane0_name)
        _n_gpio5_lane0 = 0; _gpio5_lane0_skip = 0
        if DEV.name == "AGRV2KL48" and os.path.exists(_gpio5_lane0_csv):
            _gpio5_lane0_paths = collections.defaultdict(list)
            for _r in csv.DictReader(open(_gpio5_lane0_csv)):
                _gpio5_lane0_paths[_r["signal"]].append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _gpio5_lane0_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    ctx.addPip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                               delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                               loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0))
                    seen_pip.add(_nm); n_mpip += 1
                _n_gpio5_lane0 += 1
            _gpio5_lane0_data = _gpio5_lane0_paths.get("gpio5_io_out_data", [])
            _gpio5_lane0_enable = _gpio5_lane0_paths.get("gpio5_io_out_en", [])
            if _gpio5_lane0_data and _gpio5_lane0_data[0]["src_wire"] in wireset:
                bit_entry[262] = _gpio5_lane0_data[0]["src_wire"]
            else:
                _gpio5_lane0_skip += 1
            if _gpio5_lane0_enable and _gpio5_lane0_enable[0]["src_wire"] in wireset:
                bit_entry[263] = _gpio5_lane0_enable[0]["src_wire"]
            else:
                _gpio5_lane0_skip += 1
            print("AGRV2K arch: loaded %d GPIO5 lane0 hop(s) from %s (%d skipped)"
                  % (_n_gpio5_lane0, _gpio5_lane0_name, _gpio5_lane0_skip))

        shared["mcu_pip_count"] = n_mpip
        return n_mpip

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

    def writable_bits(self, state):
        return set(state.sets)

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
