import json

import pytest

from agamemnon.engine.verify_netlist import sim_routed


def _bram_cell(init_val, **extra):
    params = {"PORTA_WIDTH": "00000", "PORTB_WIDTH": "00000", "PORTA_OUTREG": "0",
              "INIT_VAL": format(init_val, "09216b")}
    params.update(extra)
    return {"type": "ALTA_BRAM9K", "parameters": params,
            "attributes": {"NEXTPNR_BEL": "X13Y4_BRAM"},
            "connections": {
                # word 0 (Address[12:4] = 0), suffix bits hard-defaulted (unconnected)
                "AddressA": ["0"] * 13,
                "DataInA": [10] + ["0"] * 17,
                "WeA": [11], "ReA": ["1"],
                "DataOutA": [20] + [21 + i for i in range(17)],
            }}


def _document(init_val, **extra):
    cell = _bram_cell(init_val, **extra)
    return {"modules": {"top": {
        "netnames": {"din": {"bits": [10]}, "we": {"bits": [11]}, "q0": {"bits": [20]},
                     **{"q%d" % (i + 1): {"bits": [21 + i]} for i in range(17)}},
        "cells": {
            "core_i.memory": cell,
            "mcu_din": {"type": "MCU_DIN", "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DIN40"},
                        "connections": {"DIN": [10]}},
            "mcu_we": {"type": "MCU_DIN", "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DIN41"},
                       "connections": {"DIN": [11]}},
            "mcu_h0": {"type": "MCU_DOUT", "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT10"},
                       "connections": {"DOUT": [20]}},
        },
    }}}


def test_initialised_x18_word_reads_back_without_stimulus():
    # bit 0 of word 0 set: the registered output shows it from the second cycle on
    reads, bind = sim_routed(None, cycles=4, document=_document(1))
    assert reads == [0, 1, 1, 1]
    assert bind == {"mcu_h0": (0, 0)}


def test_write_then_read_follows_the_mcu_stimulus():
    schedule = {0: {"mcu_din": 1, "mcu_we": 1}, 1: {"mcu_we": 0, "mcu_din": 0},
                4: {"mcu_din": 0, "mcu_we": 1}, 5: {"mcu_we": 0}}
    reads, _ = sim_routed(None, cycles=8, document=_document(0),
                          stimulus=lambda cycle, reads: schedule.get(cycle, {}))
    # cycle 0 writes 1: the same-clock read still returns the old word, so the
    # new value is visible from cycle 2; cycle 4 writes 0, visible from cycle 6
    assert reads == [0, 0, 1, 1, 1, 1, 0, 0]


def test_output_register_adds_one_cycle():
    reads, _ = sim_routed(None, cycles=4, document=_document(1, PORTA_OUTREG="1"))
    assert reads == [0, 0, 1, 1]


def test_unmodelled_width_is_refused():
    with pytest.raises(ValueError, match="x18 only"):
        sim_routed(None, cycles=1, document=_document(0, PORTA_WIDTH="01000"))


def test_stimulus_must_name_an_mcu_input():
    with pytest.raises(KeyError):
        sim_routed(None, cycles=1, document=_document(0), stimulus=lambda c, r: {"nope": 1})


def _slice_document(init, inputs):
    return {"modules": {"top": {
        "netnames": {"a": {"bits": [2]}, "out": {"bits": [3]}},
        "cells": {
            "lut": {"type": "GENERIC_SLICE", "parameters": {"FF_USED": "0", "INIT": format(init, "016b")},
                    "attributes": {"NEXTPNR_BEL": "X1Y4_SLICE0"},
                    "connections": {"F": [3], "I": inputs}},
            "src": {"type": "GENERIC_SLICE", "parameters": {"FF_USED": "0", "INIT": "1111111111111111"},
                    "attributes": {"NEXTPNR_BEL": "X1Y4_SLICE1"}, "connections": {"F": [2], "I": []}},
            "mcu_h0": {"type": "MCU_DOUT", "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT10"},
                       "connections": {"DOUT": [3]}},
        },
    }}}


def test_unconnected_lut_input_reads_high_when_cofactored():
    # INIT = I0 (independent of I1..I3); I1 is an unconnected dummy bit (900 names no net)
    reads, _ = sim_routed(None, cycles=2, document=_slice_document(0xAAAA, [2, 900, "0", "0"]))
    assert reads == [1, 1]


def test_unconnected_lut_input_the_init_depends_on_is_refused():
    # INIT = I0 & I1: the unconnected I1 would read 1 on silicon and 0 in a naive sim
    with pytest.raises(ValueError, match="unconnected but INIT"):
        sim_routed(None, cycles=1, document=_slice_document(0x8888, [2, 900, "0", "0"]))
