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


def test_spi1_rx_exact_l48_ingress_is_one_literal_vendor_path():
    paths = rows("mcu_spi1_rx_l48_paths.csv")
    cfg = rows("mcu_spi1_rx_l48_pip_cfg.csv")
    assert len(paths) == 5
    assert len(cfg) == 4
    assert [int(row["step"]) for row in paths] == list(range(5))
    assert paths[0]["src_wire"] == "X18Y13_InputMUX07"
    assert paths[-1]["dst_wire"] == "X0Y5_SinkMUXPseudo114"
    assert all(a["dst_wire"] == b["src_wire"] for a, b in zip(paths, paths[1:]))
    evidence = "vendor-spi1-duplex-eight-seed-endpoint-three-seed-literal-path"
    assert {row["evidence"] for row in paths + cfg} == {evidence}
    assert [(row["cfg_group"], row["set_selectors"]) for row in cfg] == [
        ("CFG_RMUX9", "26;29"),
        ("CFG_RMUX4", "31;38"),
        ("CFG_RMUX3", "26;29"),
        ("BBMUXE5", "2;6"),
    ]
    assert cfg[-1]["observed_runs"].split(";") == [
        "user_7021", "structural_7027", "structural_7047", "structural_7057"
    ]


def test_spi1_rx_reuses_exact_pin17_physical_input_enable():
    paths = rows("mcu_spi1_rx_l48_paths.csv")
    pad = next(row for row in rows("pad_input_L48.csv")
               if row["verified_pin"] == "PIN_17")
    assert paths[0]["src_wire"] == "X18Y13_InputMUX07"
    assert paths[0]["dst_wire"] == "X18Y9_RMUX56"
    assert (int(pad["pad_x"]), int(pad["pad_y"]), int(pad["inputmux"])) == (18, 13, 7)
    assert (int(pad["dst_x"]), int(pad["dst_y"]), int(pad["dst_rmux"])) == (18, 9, 56)
    assert (int(pad["enable_byte"]), int(pad["enable_mask"])) == (92, 64)
    assert pad["set_cells"] == "92:64"


def test_spi1_rx_exact_composition_selects_corrected_physical_enable():
    key = (18, 13, 7, 18, 9, 56)
    physical = SimpleNamespace(
        pad_input_edge={key: ("CFG_RMUX9", [26, 29], [(92, 64)], [])},
        pad_input_used=set(),
    )
    module = {"cells": {"spi_miso": {"type": "MCU_SPI1_MISO_INPUT"}}}
    MCU_GPIO_FEATURE.prepare(module, {}, physical_io_state=physical)
    assert physical.pad_input_used == {(key, ((92,64),), ())}


def test_spi1_rx_typed_sink_is_public_and_l48_only():
    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    assert '279: "MCU_SPI1_MISO_INPUT"' in arch
    assert "module MCU_SPI1_MISO_INPUT (input DOUT)" in prims
    assert '"mcu_spi1_rx_l48_paths.csv"' in gpio
    assert '"mcu_spi1_rx_l48_pip_cfg.csv"' in gpio
    assert 'DEV.name == "AGRV2KL48"' in gpio
