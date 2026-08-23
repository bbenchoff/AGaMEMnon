import csv
from pathlib import Path

from agamemnon.engine.features.routing import mcu_entry_first_hops


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_uart0_tx_boundary_is_exact_typed_and_l48_only():
    paths = rows("mcu_uart0_tx_l48_paths.csv")
    cfg = rows("mcu_uart0_tx_l48_pip_cfg.csv")
    oepad = rows("physical_oepad_L48.csv")
    assert len(paths) == 20
    assert len(cfg) == 6
    assert {row["signal"] for row in paths} == {
        "uart0_txd_data", "uart0_txd_oe"
    }
    assert paths[0]["src_wire"] == "X6Y5_BufMUX05"
    assert paths[1]["dst_wire"] == "X6Y4_RMUX38"
    data = [row for row in paths if row["signal"] == "uart0_txd_data"]
    enable = [row for row in paths if row["signal"] == "uart0_txd_oe"]
    assert [(row["src_wire"], row["dst_wire"]) for row in data][-3:] == [
        ("X20Y5_RMUX55", "X20Y9_RMUX25"),
        ("X20Y9_RMUX25", "X20Y13_RMUX00"),
        ("X20Y13_RMUX00", "X20Y13_IOMUX01"),
    ]
    assert enable[0]["src_wire"] == "X5Y5_BufMUX02"
    assert enable[1]["dst_wire"] == "X5Y4_RMUX15"
    assert [(row["src_wire"], row["dst_wire"]) for row in enable][-3:] == [
        ("X20Y5_RMUX85", "X20Y9_RMUX55"),
        ("X20Y9_RMUX55", "X20Y13_RMUX08"),
        ("X20Y13_RMUX08", "X20Y13_IOMUX05"),
    ]
    assert cfg[0]["set_selectors"] == "0"
    assert cfg[2]["set_selectors"] == ""
    assert cfg[4]["clear_selectors"] == "10;11;12;13;14;15;16;17;18;19"
    assert cfg[4]["set_selectors"] == "12;19"
    assert cfg[5]["set_selectors"] == "12;19"
    assert oepad == [{
        "pin": "PIN_10",
        "x": "20",
        "y": "13",
        "z": "1",
        "data_iomux": "1",
        "data_rmux": "0",
        "oe_iomux": "5",
        "oe_rmux": "8",
        "cfg_x": "19",
        "cfg_y": "13",
        "oe_cfg": "CFG_IOMUX0",
        "oe_sels": "37;39",
        "companion_sets": "CFG_IOMUX1:27;CFG_IOMUX2:13",
        "companion_clears": "CFG_IOMUX3:6;CFG_IOMUX3:34",
        "qualification": "vendor-four-seed-uart-and-pico-silicon-20260823",
    }]

    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(
        encoding="utf-8"
    )
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(
        encoding="utf-8"
    )
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    packer = (ROOT / "agamemnon/engine/uarch/agrv2k/agrv2k.cc").read_text(
        encoding="utf-8"
    )
    assert '264: "MCU_UART0_TXD_DATA"' in arch
    assert '265: "MCU_UART0_TXD_OE"' in arch
    assert 'DEV.name == "AGRV2KL48"' in gpio
    assert '"mcu_uart0_tx_l48_paths.csv"' in gpio
    assert '"mcu_uart0_tx_l48_pip_cfg.csv"' in gpio
    assert 'exact_composition=True' in gpio
    assert 'shared["is_edge_blacklisted_wires"]' in gpio
    for module in ("MCU_UART0_TXD_DATA", "MCU_UART0_TXD_OE"):
        assert f"module {module}" in prims
        assert f'"{module}"' in packer
    assert "lock_uart0_tx_corridors(ctx)" in packer
    assert '"X20Y13_OEPAD1"' in packer
    assert "corridor has %d matching hard-source BELs" in packer
    assert "ctx->bindBel(source_bel, driver, STRENGTH_LOCKED)" in packer

    first_hops = mcu_entry_first_hops(CHIPDB)
    assert first_hops["X6Y5_BufMUX05"] == "X6Y5_InputMUX05"
    assert first_hops["X5Y5_BufMUX02"] == "X5Y5_InputMUX02"
