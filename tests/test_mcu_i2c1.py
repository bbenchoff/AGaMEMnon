import csv
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from agamemnon.engine.features.mcu_gpio import FEATURE as MCU_GPIO_FEATURE
from agamemnon.engine.features.routing import mcu_entry_first_hops


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
EVIDENCE = "vendor-i2c1-eight-seed-exact-simultaneous-route-composition"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_i2c1_six_lane_composition_is_exact_and_l48_only():
    paths = rows("mcu_i2c1_l48_paths.csv")
    cfg = rows("mcu_i2c1_l48_pip_cfg.csv")
    assert len(paths) == 49
    assert len(cfg) == 39

    expected = {
        "i2c1_scl_data": ("X12Y5_BufMUX11", "X19Y13_IOMUX01"),
        "i2c1_scl_oe": ("X11Y5_BufMUX07", "X19Y13_IOMUX05"),
        "i2c1_scl_input": ("X19Y13_InputMUX02", "X0Y5_SinkMUXPseudo139"),
        "i2c1_sda_data": ("X11Y5_BufMUX00", "X20Y13_IOMUX02"),
        "i2c1_sda_oe": ("X11Y5_BufMUX08", "X20Y13_IOMUX06"),
        "i2c1_sda_input": ("X20Y13_InputMUX04", "X0Y5_SinkMUXPseudo140"),
    }
    by_signal = defaultdict(list)
    for row in paths:
        by_signal[row["signal"]].append(row)
        assert row["evidence"] == EVIDENCE
    assert set(by_signal) == set(expected)
    for signal, lane in by_signal.items():
        lane.sort(key=lambda row: int(row["step"]))
        assert [int(row["step"]) for row in lane] == list(range(len(lane)))
        assert (lane[0]["src_wire"], lane[-1]["dst_wire"]) == expected[signal]
        assert all(a["dst_wire"] == b["src_wire"] for a, b in zip(lane, lane[1:]))

    path_edges = {(row["src_wire"], row["dst_wire"]) for row in paths}
    cfg_edges = {(row["src_wire"], row["dst_wire"]) for row in cfg}
    assert cfg_edges <= path_edges
    assert {row["evidence"] for row in cfg} == {EVIDENCE}
    first_hops = mcu_entry_first_hops(CHIPDB)
    for signal in ("i2c1_scl_data", "i2c1_scl_oe",
                   "i2c1_sda_data", "i2c1_sda_oe"):
        lane = by_signal[signal]
        assert first_hops[lane[0]["src_wire"]] == frozenset({lane[0]["dst_wire"]})


def test_i2c1_physical_open_drain_terminals_are_exact():
    oepads = {row["pin"]: row for row in rows("physical_i2c1_oe_L48.csv")}
    expected_oe = {
        "PIN_15": ("19", "13", "1", "16", "5", "4", "36;39"),
        "PIN_11": ("20", "13", "2", "16", "6", "8", "2;4"),
    }
    for pin, expected in expected_oe.items():
        row = oepads[pin]
        actual = (row["x"], row["y"], row["data_iomux"], row["data_rmux"],
                  row["oe_iomux"], row["oe_rmux"], row["oe_sels"])
        assert actual == expected
        assert row["clear_scope"] == "selector_group"
        assert row["qualification"] == EVIDENCE

    padfeeds = rows("padfeed_L48_top.csv")
    indexed = {
        (row["padtile_x"], row["padtile_y"], row["iomux_z"],
         row["padfeed_rmux"], row["src_res"], row["src_x"], row["src_y"]):
        (row["codeword_sels"], row["codeword_bytes"], row["codeword_masks"])
        for row in padfeeds
    }
    required = {
        ("19", "13", "1", "16", "RMUX85", "19", "9"):
            ("0,4", "408,524", "32,16"),
        ("19", "13", "5", "4", "RMUX75", "19", "9"):
            ("26,28", "2497,2613", "32,32"),
        ("20", "13", "2", "16", "RMUX85", "20", "9"):
            ("0,4", "403,519", "2,1"),
        ("20", "13", "6", "8", "RMUX55", "20", "9"):
            ("0,4", "404,520", "8,16"),
    }
    for key, codeword in required.items():
        assert indexed[key] == codeword


def test_i2c1_prepare_claims_both_characterized_input_edges():
    scl_key = (19, 13, 2, 19, 9, 20)
    sda_key = (20, 13, 4, 20, 9, 26)
    physical = SimpleNamespace(
        pad_input_edge={
            scl_key: ("CFG_RMUX3", [26, 29], [(89, 4)], []),
            sda_key: ("CFG_RMUX4", [26, 29], [(84, 16), (85, 2), (85, 64)], [(85, 32)]),
        },
        pad_input_used=set(),
    )
    module = {
        "cells": {
            "scl_input": {"type": "MCU_I2C1_SCL_INPUT"},
            "sda_input": {"type": "MCU_I2C1_SDA_INPUT"},
        }
    }
    MCU_GPIO_FEATURE.prepare(module, {}, physical_io_state=physical)
    assert physical.pad_input_used == {
        (scl_key, ((89, 4),), ()),
        (sda_key, ((84, 16), (85, 2), (85, 64)), ((85, 32),)),
    }


def test_i2c1_typed_ports_and_atomic_lock_are_public():
    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    packer = (ROOT / "agamemnon/engine/uarch/agrv2k/agrv2k.cc").read_text(encoding="utf-8")
    modules = (
        "MCU_I2C1_SCL_DATA", "MCU_I2C1_SCL_OE", "MCU_I2C1_SCL_INPUT",
        "MCU_I2C1_SDA_DATA", "MCU_I2C1_SDA_OE", "MCU_I2C1_SDA_INPUT",
    )
    for bit, module in enumerate(modules, 286):
        assert f'{bit}: "{module}"' in arch
        assert f"module {module}" in prims
    assert '"MCU_I2C1_"' in packer
    assert '"mcu_i2c1_l48_paths.csv"' in gpio
    assert '"mcu_i2c1_l48_pip_cfg.csv"' in gpio
    assert "lock_i2c_corridors(ctx)" in packer
    assert "mixed I2C0/I2C1 typed composition is not characterized" in packer
