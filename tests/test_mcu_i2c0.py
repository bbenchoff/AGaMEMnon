import csv
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from agamemnon.engine.features.mcu_gpio import FEATURE as MCU_GPIO_FEATURE
from agamemnon.engine.features.routing import mcu_entry_first_hops


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
EVIDENCE = "vendor-i2c0-eight-seed-exact-simultaneous-route-composition"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_i2c0_six_lane_composition_is_exact_and_l48_only():
    paths = rows("mcu_i2c0_l48_paths.csv")
    cfg = rows("mcu_i2c0_l48_pip_cfg.csv")
    assert len(paths) == 48
    assert len(cfg) == 38

    expected = {
        "i2c0_scl_data": ("X12Y5_BufMUX09", "X19Y13_IOMUX01"),
        "i2c0_scl_oe": ("X11Y5_BufMUX05", "X19Y13_IOMUX05"),
        "i2c0_scl_input": ("X19Y13_InputMUX02", "X0Y5_SinkMUXPseudo137"),
        "i2c0_sda_data": ("X12Y5_BufMUX10", "X20Y13_IOMUX02"),
        "i2c0_sda_oe": ("X11Y5_BufMUX06", "X20Y13_IOMUX06"),
        "i2c0_sda_input": ("X20Y13_InputMUX04", "X0Y5_SinkMUXPseudo138"),
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
    for row in cfg:
        clears = [int(value) for value in row["clear_selectors"].split(";") if value]
        sets = [int(value) for value in row["set_selectors"].split(";") if value]
        assert set(sets) <= set(clears)
        if row["cell_table"] == "fabric":
            assert len(clears) == 10
            assert clears == list(range(clears[0], clears[0] + 10))
            assert len(sets) == 2
        else:
            assert row["cell_table"] == "mcu"
            if row["cfg_group"].startswith("BBMUX"):
                assert clears == list(range(9))
                assert len(sets) == 2
            else:
                assert clears == [0]
                assert sets in ([], [0])

    first_hops = mcu_entry_first_hops(CHIPDB)
    for signal in ("i2c0_scl_data", "i2c0_scl_oe",
                   "i2c0_sda_data", "i2c0_sda_oe"):
        lane = by_signal[signal]
        assert first_hops[lane[0]["src_wire"]] == frozenset({lane[0]["dst_wire"]})


def test_i2c0_physical_open_drain_terminals_are_exact():
    oepads = {row["pin"]: row for row in rows("physical_oepad_L48.csv")}
    expected_oe = {
        "PIN_15": ("19", "13", "1", "28", "5", "20", "36;40"),
        "PIN_11": ("20", "13", "2", "8", "6", "0", "0;4"),
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
        ("19", "13", "1", "28", "RMUX92", "19", "9"):
            ("25,27", "2612,2495", "64,1"),
        ("19", "13", "5", "20", "RMUX62", "19", "9"):
            ("25,27", "2612,2496", "32,8"),
        ("20", "13", "2", "8", "RMUX55", "20", "9"):
            ("0,4", "404,520", "8,16"),
        ("20", "13", "6", "0", "RMUX25", "20", "9"):
            ("0,4", "404,520", "4,2"),
    }
    for key, codeword in required.items():
        assert indexed[key] == codeword

    pad_inputs = {
        (row["verified_pin"], row["pad_x"], row["pad_y"], row["inputmux"],
         row["dst_x"], row["dst_y"], row["dst_rmux"]): row
        for row in rows("pad_input_L48.csv")
    }
    scl = pad_inputs[("PIN_15", "19", "13", "2", "19", "9", "20")]
    sda = pad_inputs[("PIN_11", "20", "13", "4", "20", "9", "26")]
    assert (scl["cfg"], scl["set_cells"], scl["clear_cells"]) == (
        "CFG_RMUX3[26,29]", "89:4", ""
    )
    assert (sda["cfg"], sda["set_cells"], sda["clear_cells"]) == (
        "CFG_RMUX4[26,29]", "84:16;85:2;85:64", "85:32"
    )


def test_i2c0_prepare_claims_both_characterized_input_edges():
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
            "scl_input": {"type": "MCU_I2C0_SCL_INPUT"},
            "sda_input": {"type": "MCU_I2C0_SDA_INPUT"},
        }
    }
    MCU_GPIO_FEATURE.prepare(module, {}, physical_io_state=physical)
    assert physical.pad_input_used == {
        (scl_key, ((89, 4),), ()),
        (sda_key, ((84, 16), (85, 2), (85, 64)), ((85, 32),)),
    }


def test_i2c0_typed_ports_and_atomic_lock_are_public():
    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    packer = (ROOT / "agamemnon/engine/uarch/agrv2k/agrv2k.cc").read_text(encoding="utf-8")
    modules = (
        "MCU_I2C0_SCL_DATA", "MCU_I2C0_SCL_OE", "MCU_I2C0_SCL_INPUT",
        "MCU_I2C0_SDA_DATA", "MCU_I2C0_SDA_OE", "MCU_I2C0_SDA_INPUT",
    )
    for bit, module in enumerate(modules, 280):
        assert f'{bit}: "{module}"' in arch
        assert f"module {module}" in prims
    assert '"mcu_i2c0_l48_paths.csv"' in gpio
    assert '"mcu_i2c0_l48_pip_cfg.csv"' in gpio
    assert "lock_i2c_corridors(ctx)" in packer
    assert '"MCU_I2C0_"' in packer
    for suffix in ("SCL_DATA", "SCL_OE", "SCL_INPUT",
                   "SDA_DATA", "SDA_OE", "SDA_INPUT"):
        assert f'"{suffix}"' in packer
    for bel in ("X19Y13_IOB1", "X20Y13_IOB2"):
        assert f'"{bel}"' in packer
