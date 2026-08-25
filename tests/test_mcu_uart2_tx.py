import csv
from pathlib import Path

from agamemnon.engine.features.routing import mcu_entry_first_hops


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"


def rows(name):
    with (CHIPDB / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_uart2_tx_boundary_is_exact_typed_and_l48_only():
    paths = rows("mcu_uart2_tx_l48_paths.csv")
    cfg = rows("mcu_uart2_tx_l48_pip_cfg.csv")
    padfeed = rows("padfeed_L48_top.csv")
    oepad = rows("physical_uart2_oe_L48.csv")
    assert len(paths) == 20
    assert len(cfg) == 16
    assert {row["signal"] for row in paths} == {"uart2_txd_data", "uart2_txd_oe"}
    data = [row for row in paths if row["signal"] == "uart2_txd_data"]
    enable = [row for row in paths if row["signal"] == "uart2_txd_oe"]
    assert data[0]["src_wire"] == "X5Y5_BufMUX06"
    assert data[0]["dst_wire"] == "X5Y5_InputMUX07"
    assert [(row["src_wire"], row["dst_wire"]) for row in data][-2:] == [
        ("X20Y9_RMUX92", "X20Y13_RMUX28"),
        ("X20Y13_RMUX28", "X20Y13_IOMUX01"),
    ]
    assert enable[0]["src_wire"] == "X4Y5_BufMUX02"
    assert enable[0]["dst_wire"] == "X4Y5_InputMUX02"
    assert [(row["src_wire"], row["dst_wire"]) for row in enable][-2:] == [
        ("X20Y9_RMUX85", "X20Y13_RMUX16"),
        ("X20Y13_RMUX16", "X20Y13_IOMUX05"),
    ]
    assert cfg[0]["set_selectors"] == ""
    assert cfg[1]["set_selectors"] == "33;39"
    exact_feed = {
        (row["padfeed_rmux"], row["src_res"], row["src_x"], row["src_y"]): row
        for row in padfeed
        if row["padtile_x"] == "20" and row["padtile_y"] == "13"
        and row["iomux_z"] == "1"
    }
    assert exact_feed[("28", "RMUX92", "20", "9")]["codeword_sels"] == "25,27"
    assert exact_feed[("16", "RMUX85", "20", "9")]["codeword_sels"] == "0,4"
    assert oepad == [{
        "pin": "PIN_10", "x": "20", "y": "13", "z": "1",
        "data_iomux": "1", "data_rmux": "28",
        "oe_iomux": "5", "oe_rmux": "16",
        "cfg_x": "19", "cfg_y": "13", "oe_cfg": "CFG_IOMUX0",
        "oe_sels": "35;40", "clear_scope": "full_field",
        "companion_sets": "CFG_IOMUX1:27;CFG_IOMUX2:13",
        "companion_clears": "CFG_IOMUX3:6;CFG_IOMUX3:34",
        "qualification": "vendor-uart2-eight-seed-route-pico-silicon-20260824",
    }]

    arch = (ROOT / "agamemnon/engine/features/mcu_ahb.py").read_text(encoding="utf-8")
    gpio = (ROOT / "agamemnon/engine/features/mcu_gpio.py").read_text(encoding="utf-8")
    prims = (ROOT / "agamemnon/synth/prims.v").read_text(encoding="utf-8")
    packer = (ROOT / "agamemnon/engine/uarch/agrv2k/agrv2k.cc").read_text(
        encoding="utf-8"
    )
    assert '294: "MCU_UART2_TXD_DATA"' in arch
    assert '295: "MCU_UART2_TXD_OE"' in arch
    assert '"mcu_uart2_tx_l48_paths.csv"' in gpio
    assert '"mcu_uart2_tx_l48_pip_cfg.csv"' in gpio
    for module in ("MCU_UART2_TXD_DATA", "MCU_UART2_TXD_OE"):
        assert f"module {module}" in prims
    assert 'candidate->type == ctx->id(prefix + "TXD_DATA")' in packer
    assert 'candidate->type == ctx->id(prefix + "TXD_OE")' in packer
    assert 'const std::string filename = "mcu_uart" + index + "_tx_l48_paths.csv"' in packer
    assert "mixed UART controller typed composition is not characterized" in packer

    first_hops = mcu_entry_first_hops(CHIPDB)
    assert first_hops["X5Y5_BufMUX06"] == frozenset({"X5Y5_InputMUX07"})
    assert first_hops["X4Y5_BufMUX02"] == frozenset({"X4Y5_InputMUX02"})
