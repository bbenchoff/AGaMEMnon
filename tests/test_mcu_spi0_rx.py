import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon.engine.features.mcu_gpio import FEATURE as MCU_GPIO_FEATURE


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_spi0_rx_exact_l48_ingress_is_one_literal_vendor_majority_path():
    paths = rows("mcu_spi0_rx_l48_paths.csv")
    cfg = rows("mcu_spi0_rx_l48_pip_cfg.csv")
    assert len(paths) == 5
    assert len(cfg) == 4
    assert [int(row["step"]) for row in paths] == list(range(5))
    assert paths[0]["src_wire"] == "X18Y13_InputMUX07"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo110"
    assert all(a["dst_wire"] == b["src_wire"] for a, b in zip(paths, paths[1:]))
    evidence = "vendor-spi0-duplex-eight-seed-majority-route-five-run-codeword-agreement"
    assert {row["evidence"] for row in paths + cfg} == {evidence}

    assert [(row["cfg_group"], row["set_selectors"]) for row in cfg] == [
        ("CFG_RMUX9", "26;29"),
        ("CFG_RMUX4", "31;38"),
        ("CFG_RMUX3", "26;29"),
        ("BBMUXE1", "2;6"),
    ]
    for row in cfg[:3]:
        clear = [int(item) for item in row["clear_selectors"].split(";")]
        assert len(clear) == 10
        assert clear == list(range(clear[0], clear[0] + 10))
        assert set(map(int, row["set_selectors"].split(";"))) <= set(clear)
        assert row["cell_table"] == "fabric"
    assert cfg[3]["cell_table"] == "mcu"
    assert cfg[3]["clear_selectors"] == "0;1;2;3;4;5;6;7;8"


def test_spi0_rx_pin17_input_enable_is_bound_to_the_exact_perimeter_edge():
    pad = next(row for row in rows("pad_input_L48.csv")
               if row["verified_pin"] == "PIN_17")
    assert (
        int(pad["pad_x"]), int(pad["pad_y"]), int(pad["inputmux"]),
        int(pad["dst_x"]), int(pad["dst_y"]), int(pad["dst_rmux"]),
    ) == (18, 13, 7, 18, 9, 56)
    assert pad["cfg"] == "CFG_RMUX9[26,29]"
    assert pad["set_cells"] == "92:64"
    assert pad["clear_cells"] == ""

    paths = rows("mcu_spi0_rx_l48_paths.csv")
    assert paths[0]["src_wire"] == "X18Y13_InputMUX07"
    assert paths[0]["dst_wire"] == "X18Y9_RMUX56"

    # Eight independent full-duplex references agree on FILE byte 100 bit 6,
    # while all eight otherwise matching TX-only images clear it.  Keeping the
    # cell in the generic pad-input table makes emission depend on using this
    # exact physical ingress rather than merely instantiating the MCU sink.
    # The emitter table indexes payload bytes, excluding the eight-byte header.
    assert (int(pad["enable_byte"]), int(pad["enable_mask"])) == (92, 64)


def test_spi0_rx_exact_composition_is_fail_closed_after_silicon_escape():
    key = (18, 13, 7, 18, 9, 56)
    physical = SimpleNamespace(
        pad_input_edge={
            key: ("CFG_RMUX9", [26, 29], [(92, 64)], []),
        },
        pad_input_used=set(),
    )
    module = {
        "cells": {
            "spi_miso": {"type": "MCU_SPI0_MISO_INPUT"},
        }
    }
    with pytest.raises(SystemExit, match="VP-AGM-008"):
        MCU_GPIO_FEATURE.prepare(module, {}, physical_io_state=physical)
    assert physical.pad_input_used == set()


def test_spi0_rx_typed_sink_is_public_and_l48_only():
    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    assert '272: "MCU_SPI0_MISO_INPUT"' in arch
    assert "module MCU_SPI0_MISO_INPUT (input DOUT)" in prims
    assert '"mcu_spi0_rx_l48_paths.csv"' in gpio
    assert '"mcu_spi0_rx_l48_pip_cfg.csv"' in gpio
    assert 'DEV.name == "AGRV2KL48"' in gpio
