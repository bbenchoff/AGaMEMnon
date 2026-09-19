"""A registered driver of BRAM AddressA[4] gets an identity-LUT buffer.

The pin's qualified source slot (X14Y4_SLICE0) is one of three slices whose F
and Q outputs present on different wires, and only the F wire reaches the pin
in the admitted graph, so a flip-flop can never be seated there.  bram_rom_kat
and bram_fifo_kat (``addr <= addr + 1``) failed every placement attempt with
"no gated-graph slice output reaches dynamic BRAM pin AddressA[4]" until the
pre-pass inserted the buffer (2026-09-19).
"""
import copy

from agamemnon.engine.bram_pin_buffer import buffer_registered_drivers


def _design(addr4_driver_type):
    cells = {
        "addr_ff": {
            "type": "DFF" if addr4_driver_type == "DFF" else "LUT",
            "parameters": {},
            "attributes": {},
            "port_directions": {"D": "input", "Q": "output", "I": "input"},
            "connections": {"D": [10], "I": [10, "0", "0", "0"], "Q": [20]},
        },
        "incr": {
            "type": "LUT",
            "parameters": {"INIT": "0101010101010101"},
            "attributes": {},
            "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": [20, "0", "0", "0"], "Q": [30]},
        },
        "rom": {
            "type": "ALTA_BRAM9K",
            "parameters": {"PORTA_WIDTH": "01000"},
            "attributes": {},
            "port_directions": {"AddressA": "input", "DataOutA": "output"},
            "connections": {"AddressA": ["0", "0", "0", 30, 20, 31, "0", "0", "0", "0", "0", "0", "0"],
                            "DataOutA": [40, 41, 42, 43, 44, 45, 46, 47, 48]},
        },
    }
    return {"modules": {"top": {"attributes": {"top": "1"}, "cells": cells, "netnames": {}}}}


def test_registered_addr4_driver_is_buffered_and_keeps_its_other_readers():
    design = _design("DFF")
    added, examined = buffer_registered_drivers(design)
    assert (added, examined) == (1, 1)
    cells = design["modules"]["top"]["cells"]
    buf = cells["$bram_pin_buf$1"]
    assert buf["type"] == "LUT"
    assert buf["parameters"]["INIT"] == "1010101010101010"
    assert buf["connections"]["I"] == [20, "0", "0", "0"]
    new_bit = buf["connections"]["Q"][0]
    assert cells["rom"]["connections"]["AddressA"][4] == new_bit
    # the register still feeds the increment logic and the other address bits are untouched
    assert cells["incr"]["connections"]["I"][0] == 20
    assert cells["rom"]["connections"]["AddressA"][3] == 30
    assert cells["rom"]["connections"]["AddressA"][5] == 31
    assert buf["attributes"]["agamemnon_bram_pin_buffer"] == "AddressA[4]"


def test_lut_driven_addr4_is_byte_identical():
    design = _design("LUT")
    before = copy.deepcopy(design)
    assert buffer_registered_drivers(design) == (0, 1)
    assert design == before


def test_constant_or_absent_addr4_is_ignored():
    design = _design("DFF")
    design["modules"]["top"]["cells"]["rom"]["connections"]["AddressA"][4] = "0"
    assert buffer_registered_drivers(design) == (0, 0)
