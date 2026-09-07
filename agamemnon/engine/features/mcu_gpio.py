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
    "mcu_uart0_tx_l48_pip_cfg.csv",
    "mcu_uart1_tx_l48_pip_cfg.csv",
    "mcu_uart2_tx_l48_pip_cfg.csv",
    "mcu_spi0_tx_l48_pip_cfg.csv",
    "mcu_spi0_rx_l48_pip_cfg.csv",
    "mcu_spi1_tx_l48_pip_cfg.csv",
    "mcu_spi1_rx_l48_pip_cfg.csv",
    "mcu_i2c0_l48_pip_cfg.csv",
    "mcu_i2c1_l48_pip_cfg.csv",
)

PATH_FILES = (
    "mcu_gpio5_loop_paths.csv",
    "mcu_gpio5_loop_l48_paths.csv",
    "mcu_gpio5_lane0_l48_paths.csv",
    "mcu_uart0_tx_l48_paths.csv",
    "mcu_uart1_tx_l48_paths.csv",
    "mcu_uart2_tx_l48_paths.csv",
    "mcu_spi0_tx_l48_paths.csv",
    "mcu_spi0_rx_l48_paths.csv",
    "mcu_spi1_tx_l48_paths.csv",
    "mcu_spi1_rx_l48_paths.csv",
    "mcu_i2c0_l48_paths.csv",
    "mcu_i2c1_l48_paths.csv",
)


@dataclass
class McuGpioState:
    sets: list = field(default_factory=list)


def mark_spi_miso_pad_input(module, physical_io_state):
    """Delegate the shared PIN17 enable to its sole physical-I/O owner.

    SPI0 and SPI1 retain distinct sink routes. Physical-I/O preparation and
    exact-route ownership remain mandatory; a typed sink alone is insufficient.
    """
    types = {"MCU_SPI0_MISO_INPUT", "MCU_SPI1_MISO_INPUT"}
    if not any(cell.get("type") in types for cell in module.get("cells", {}).values()):
        return
    if physical_io_state is None:
        raise SystemExit("SPI MISO input requires prepared physical_io state")
    pad_key = (18, 13, 7, 18, 9, 56)
    pad_input = physical_io_state.pad_input_edge.get(pad_key)
    if pad_input is None:
        raise SystemExit("SPI MISO input has no characterized PIN17 pad codeword")
    _cfg, _selectors, set_bits, clear_bits = pad_input
    physical_io_state.pad_input_used.add((pad_key, tuple(set_bits), tuple(clear_bits)))
    print("SPI MISO input: selected characterized PIN17 pad-input codeword")


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
        _blacklisted_wires = shared["is_blacklisted_wires"]
        _edge_blacklisted_wires = shared["is_edge_blacklisted_wires"]

        # Both GPIO5 loaders below are keyed by whole wire names, and the
        # part-keyed `is_blacklisted` predicate does not accept those, so they
        # added their pips without ever consulting the ban -- a blacklisted
        # GPIO5 boundary hop stayed routable and the build looked like it had
        # obeyed. One gate for both, so the next loader added here inherits it.
        _ban_skipped = []

        def _add_pip(name, type, srcWire, dstWire, delay, loc,
                     exact_composition=False):
            denied = (_edge_blacklisted_wires(srcWire, dstWire)
                      if exact_composition
                      else _blacklisted_wires(srcWire, dstWire))
            if denied:
                _ban_skipped.append(name)
                return False
            ctx.addPip(name=name, type=type, srcWire=srcWire, dstWire=dstWire,
                       delay=delay, loc=loc)
            return True

        # One independently recovered GPIO5 boundary unit. Keep data, output-enable,
        # and return-input as separate typed hard ports so placement cannot silently
        # substitute the older GPIO4 loopback BELs. The table contains only literal
        # consecutive vendor-route nodes; it does not expose the full GPIO matrix.
        _gpio5_path_name = ("mcu_gpio5_loop_l48_paths.csv"
                            if DEV.name == "AGRV2KL48" else "mcu_gpio5_loop_paths.csv")
        _gpio5_path_csv = os.path.join(DATA, _gpio5_path_name)
        _n_gpio5 = 0; _gpio5_skip = 0
        if not os.path.exists(_gpio5_path_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_gpio5_path_name, DEV.name)
            )
        else:
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
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0)):
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
        if DEV.name == "AGRV2KL48" and not os.path.exists(_gpio5_lane0_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_gpio5_lane0_name, DEV.name)
            )
        if DEV.name == "AGRV2KL48":
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
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0)):
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

        # Each characterized UART transmitter is a separate two-root hard
        # boundary even when both controllers use the same qualified PIN_10
        # fixture. Load only the retained complete composition for that
        # controller; no generic UART/GPIO crossbar is implied.
        _uart_specs = (
            ("UART0", "mcu_uart0_tx_l48_paths.csv",
             (("uart0_txd_data", 264), ("uart0_txd_oe", 265))),
            ("UART1", "mcu_uart1_tx_l48_paths.csv",
             (("uart1_txd_data", 292), ("uart1_txd_oe", 293))),
            ("UART2", "mcu_uart2_tx_l48_paths.csv",
             (("uart2_txd_data", 294), ("uart2_txd_oe", 295))),
        )
        if DEV.name == "AGRV2KL48":
            for _uart_controller, _uart_name, _uart_lanes in _uart_specs:
                _uart_csv = os.path.join(DATA, _uart_name)
                if not os.path.exists(_uart_csv):
                    raise ValueError(
                        "mcu_gpio requires chipdb/%s for device %s" %
                        (_uart_name, DEV.name)
                    )
                _n_uart = 0; _uart_skip = 0
                _uart_paths = collections.defaultdict(list)
                for _r in csv.DictReader(open(_uart_csv)):
                    _uart_paths[_r["signal"]].append(_r)
                    _src = _r["src_wire"]; _dst = _r["dst_wire"]
                    _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                    if _src not in wireset or _dst not in wireset or not _dm:
                        _uart_skip += 1
                        continue
                    _nm = "%s.%s" % (_src, _dst)
                    if _nm not in seen_pip:
                        if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src,
                                    dstWire=_dst,
                                    delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                    loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0),
                                    exact_composition=True):
                            seen_pip.add(_nm); n_mpip += 1
                    _n_uart += 1
                for _signal, _bit in _uart_lanes:
                    _path = _uart_paths.get(_signal, [])
                    if _path and _path[0]["src_wire"] in wireset:
                        bit_entry[_bit] = _path[0]["src_wire"]
                    else:
                        _uart_skip += 1
                print("AGRV2K arch: loaded %d %s TX boundary hop(s) from %s (%d skipped)"
                      % (_n_uart, _uart_controller, _uart_name, _uart_skip))

        # SPI0 master TX is a simultaneous six-lane hard-peripheral
        # composition: data and output-enable for SCK, CSN and MOSI.  Keep the
        # six typed roots distinct and retain the one complete structural-6907
        # vendor route in which all six coexist.
        _spi_name = "mcu_spi0_tx_l48_paths.csv"
        _spi_csv = os.path.join(DATA, _spi_name)
        _n_spi = 0; _spi_skip = 0
        if DEV.name == "AGRV2KL48" and not os.path.exists(_spi_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_spi_name, DEV.name)
            )
        if DEV.name == "AGRV2KL48":
            _spi_paths = collections.defaultdict(list)
            for _r in csv.DictReader(open(_spi_csv)):
                _spi_paths[_r["signal"]].append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _spi_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0),
                                exact_composition=True):
                        seen_pip.add(_nm); n_mpip += 1
                _n_spi += 1
            _spi_lanes = (
                ("spi0_sck_data", 266), ("spi0_sck_oe", 267),
                ("spi0_csn_data", 268), ("spi0_csn_oe", 269),
                ("spi0_mosi_data", 270), ("spi0_mosi_oe", 271),
            )
            for _signal, _bit in _spi_lanes:
                _path = _spi_paths.get(_signal, [])
                if _path and _path[0]["src_wire"] in wireset:
                    bit_entry[_bit] = _path[0]["src_wire"]
                else:
                    _spi_skip += 1
            print("AGRV2K arch: loaded %d SPI0 TX boundary hop(s) from %s (%d skipped)"
                  % (_n_spi, _spi_name, _spi_skip))

        # SPI1 uses a different six-root hard-boundary composition even though
        # the qualified L48 pad triplet is the same as SPI0.  Keep the typed
        # identities and exact structural-6987 simultaneous route independent.
        _spi1_name = "mcu_spi1_tx_l48_paths.csv"
        _spi1_csv = os.path.join(DATA, _spi1_name)
        _n_spi1 = 0; _spi1_skip = 0
        if DEV.name == "AGRV2KL48" and not os.path.exists(_spi1_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_spi1_name, DEV.name)
            )
        if DEV.name == "AGRV2KL48":
            _spi1_paths = collections.defaultdict(list)
            for _r in csv.DictReader(open(_spi1_csv)):
                _spi1_paths[_r["signal"]].append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _spi1_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0),
                                exact_composition=True):
                        seen_pip.add(_nm); n_mpip += 1
                _n_spi1 += 1
            _spi1_lanes = (
                ("spi1_sck_data", 273), ("spi1_sck_oe", 274),
                ("spi1_csn_data", 275), ("spi1_csn_oe", 276),
                ("spi1_mosi_data", 277), ("spi1_mosi_oe", 278),
            )
            for _signal, _bit in _spi1_lanes:
                _path = _spi1_paths.get(_signal, [])
                if _path and _path[0]["src_wire"] in wireset:
                    bit_entry[_bit] = _path[0]["src_wire"]
                else:
                    _spi1_skip += 1
            print("AGRV2K arch: loaded %d SPI1 TX boundary hop(s) from %s (%d skipped)"
                  % (_n_spi1, _spi1_name, _spi1_skip))

        # SPI0 MISO is a physical-pad-to-hard-peripheral sink.  Five of eight
        # fresh vendor seeds independently selected this exact complete path;
        # all five images carry the same four configurable codewords.  Expose
        # only that literal path and keep the other observed alternatives out
        # of the release graph until they have their own qualification.
        _spi_rx_name = "mcu_spi0_rx_l48_paths.csv"
        _spi_rx_csv = os.path.join(DATA, _spi_rx_name)
        _n_spi_rx = 0; _spi_rx_skip = 0
        if DEV.name == "AGRV2KL48" and not os.path.exists(_spi_rx_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_spi_rx_name, DEV.name)
            )
        if DEV.name == "AGRV2KL48":
            _spi_rx_path = []
            for _r in csv.DictReader(open(_spi_rx_csv)):
                if _r["signal"] != "spi0_miso_input":
                    continue
                _spi_rx_path.append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _spi_rx_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0),
                                exact_composition=True):
                        seen_pip.add(_nm); n_mpip += 1
                _n_spi_rx += 1
            if _spi_rx_path and _spi_rx_path[-1]["dst_wire"] in wireset:
                bit_exit[272] = _spi_rx_path[-1]["dst_wire"]
            else:
                _spi_rx_skip += 1
            print("AGRV2K arch: loaded %d SPI0 RX boundary hop(s) from %s (%d skipped)"
                  % (_n_spi_rx, _spi_rx_name, _spi_rx_skip))

        # SPI1 MISO shares the qualified PIN17 ingress prefix with SPI0 but
        # terminates at a different hard sink.  Three of eight fresh vendor
        # images selected this complete literal route and all eight agree on
        # BBMUXE05 -> SinkMUXPseudo114.  Keep its type and terminal independent.
        _spi1_rx_name = "mcu_spi1_rx_l48_paths.csv"
        _spi1_rx_csv = os.path.join(DATA, _spi1_rx_name)
        _n_spi1_rx = 0; _spi1_rx_skip = 0
        if DEV.name == "AGRV2KL48" and not os.path.exists(_spi1_rx_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_spi1_rx_name, DEV.name)
            )
        if DEV.name == "AGRV2KL48":
            _spi1_rx_path = []
            for _r in csv.DictReader(open(_spi1_rx_csv)):
                if _r["signal"] != "spi1_miso_input":
                    continue
                _spi1_rx_path.append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _spi1_rx_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0),
                                exact_composition=True):
                        seen_pip.add(_nm); n_mpip += 1
                _n_spi1_rx += 1
            if _spi1_rx_path and _spi1_rx_path[-1]["dst_wire"] in wireset:
                bit_exit[279] = _spi1_rx_path[-1]["dst_wire"]
            else:
                _spi1_rx_skip += 1
            print("AGRV2K arch: loaded %d SPI1 RX boundary hop(s) from %s (%d skipped)"
                  % (_n_spi1_rx, _spi1_rx_name, _spi1_rx_skip))

        # I2C0 is one simultaneous open-drain composition: SCL and SDA each
        # carry independent hard data, output-enable, and return-input lanes.
        # The checked-in route is the exact six-lane user-7061 vendor witness;
        # admitting the lanes together preserves both bidirectional pad loops.
        _i2c_name = "mcu_i2c0_l48_paths.csv"
        _i2c_csv = os.path.join(DATA, _i2c_name)
        _n_i2c = 0; _i2c_skip = 0
        if DEV.name == "AGRV2KL48" and not os.path.exists(_i2c_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_i2c_name, DEV.name)
            )
        if DEV.name == "AGRV2KL48":
            _i2c_paths = collections.defaultdict(list)
            for _r in csv.DictReader(open(_i2c_csv)):
                _i2c_paths[_r["signal"]].append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _i2c_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0),
                                exact_composition=True):
                        seen_pip.add(_nm); n_mpip += 1
                _n_i2c += 1
            _i2c_lanes = (
                ("i2c0_scl_data", 280, "entry"),
                ("i2c0_scl_oe", 281, "entry"),
                ("i2c0_scl_input", 282, "exit"),
                ("i2c0_sda_data", 283, "entry"),
                ("i2c0_sda_oe", 284, "entry"),
                ("i2c0_sda_input", 285, "exit"),
            )
            for _signal, _bit, _direction in _i2c_lanes:
                _path = _i2c_paths.get(_signal, [])
                if _direction == "entry" and _path and _path[0]["src_wire"] in wireset:
                    bit_entry[_bit] = _path[0]["src_wire"]
                elif _direction == "exit" and _path and _path[-1]["dst_wire"] in wireset:
                    bit_exit[_bit] = _path[-1]["dst_wire"]
                else:
                    _i2c_skip += 1
            print("AGRV2K arch: loaded %d I2C0 bidirectional boundary hop(s) from %s (%d skipped)"
                  % (_n_i2c, _i2c_name, _i2c_skip))

        # I2C1 is a distinct hard controller on GPIO3[6:7].  Its six typed
        # roots use an independently recovered simultaneous route even though
        # the qualified package fixture terminates on the same two pads.
        _i2c1_name = "mcu_i2c1_l48_paths.csv"
        _i2c1_csv = os.path.join(DATA, _i2c1_name)
        _n_i2c1 = 0; _i2c1_skip = 0
        if DEV.name == "AGRV2KL48" and not os.path.exists(_i2c1_csv):
            raise ValueError(
                "mcu_gpio requires chipdb/%s for device %s" %
                (_i2c1_name, DEV.name)
            )
        if DEV.name == "AGRV2KL48":
            _i2c1_paths = collections.defaultdict(list)
            for _r in csv.DictReader(open(_i2c1_csv)):
                _i2c1_paths[_r["signal"]].append(_r)
                _src = _r["src_wire"]; _dst = _r["dst_wire"]
                _dm = re.match(r"X(\d+)Y(\d+)_", _dst)
                if _src not in wireset or _dst not in wireset or not _dm:
                    _i2c1_skip += 1
                    continue
                _nm = "%s.%s" % (_src, _dst)
                if _nm not in seen_pip:
                    if _add_pip(name=_nm, type="MCUEDGE", srcWire=_src, dstWire=_dst,
                                delay=_wire_delay(_src.rsplit("_", 1)[-1]),
                                loc=Loc(int(_dm.group(1)), int(_dm.group(2)), 0),
                                exact_composition=True):
                        seen_pip.add(_nm); n_mpip += 1
                _n_i2c1 += 1
            _i2c1_lanes = (
                ("i2c1_scl_data", 286, "entry"),
                ("i2c1_scl_oe", 287, "entry"),
                ("i2c1_scl_input", 288, "exit"),
                ("i2c1_sda_data", 289, "entry"),
                ("i2c1_sda_oe", 290, "entry"),
                ("i2c1_sda_input", 291, "exit"),
            )
            for _signal, _bit, _direction in _i2c1_lanes:
                _path = _i2c1_paths.get(_signal, [])
                if _direction == "entry" and _path and _path[0]["src_wire"] in wireset:
                    bit_entry[_bit] = _path[0]["src_wire"]
                elif _direction == "exit" and _path and _path[-1]["dst_wire"] in wireset:
                    bit_exit[_bit] = _path[-1]["dst_wire"]
                else:
                    _i2c1_skip += 1
            print("AGRV2K arch: loaded %d I2C1 bidirectional boundary hop(s) from %s (%d skipped)"
                  % (_n_i2c1, _i2c1_name, _i2c1_skip))

        if _ban_skipped:
            print("AGRV2K arch: edge blacklist removed %d GPIO5 boundary hop(s): %s"
                  % (len(_ban_skipped), sorted(_ban_skipped)))
        shared["mcu_pip_count"] = n_mpip
        return n_mpip

    def load_exact_pip_fields(self, chipdb_root):
        fields = {}
        for filename in CFG_FILES:
            path = chipdb_root / filename
            if not path.exists():
                raise ValueError(
                    "mcu_gpio requires chipdb/%s; refusing to continue with "
                    "missing release routing metadata" % filename
                )
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

    def prepare(self, module, mcu_cells, physical_io_state=None):
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

        # Both exact receive corridors consume the InputMUX edge before the
        # generic recognizer can mark its enable. File byte 100 is payload 92;
        # the old SPI1 exception was based on comparing the wrong coordinate.
        mark_spi_miso_pad_input(module, physical_io_state)

        # Exact I2C input corridors consume their perimeter InputMUX edges
        # before the generic physical-input recognizer sees them.  Mark each
        # characterized electrical codeword explicitly when its typed sink is
        # present; physical_io remains the sole owner of the actual bits.
        _i2c_inputs = {
            "MCU_I2C0_SCL_INPUT": (19, 13, 2, 19, 9, 20),
            "MCU_I2C0_SDA_INPUT": (20, 13, 4, 20, 9, 26),
            "MCU_I2C1_SCL_INPUT": (19, 13, 2, 19, 9, 20),
            "MCU_I2C1_SDA_INPUT": (20, 13, 4, 20, 9, 26),
        }
        _present_i2c = {
            cell.get("type") for cell in module.get("cells", {}).values()
            if cell.get("type") in _i2c_inputs
        }
        if _present_i2c and physical_io_state is None:
            raise SystemExit("typed I2C input requires prepared physical_io state")
        for _cell_type in sorted(_present_i2c):
            _pad_key = _i2c_inputs[_cell_type]
            _pad_input = physical_io_state.pad_input_edge.get(_pad_key)
            if _pad_input is None:
                raise SystemExit(
                    "%s has no characterized physical pad codeword" % _cell_type
                )
            _cfg, _selectors, set_bits, clear_bits = _pad_input
            physical_io_state.pad_input_used.add(
                (_pad_key, tuple(set_bits), tuple(clear_bits))
            )
        if _present_i2c:
            print("typed I2C input: selected %d characterized pad-input codeword(s)"
                  % len(_present_i2c))
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
