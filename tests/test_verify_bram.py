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


def test_carry_slice_unconnected_c_input_is_by_construction():
    doc = _slice_document(0x3cc0, [2, "0", 900, "0"])
    cell = doc["modules"]["top"]["cells"]["lut"]
    cell["connections"]["CIN"] = ["0"]
    cell["connections"]["COUT"] = [5]
    doc["modules"]["top"]["netnames"]["cout"] = {"bits": [5]}
    reads, _ = sim_routed(None, cycles=1, document=doc)   # must not raise
    assert len(reads) == 1


def test_carry_seed_unconnected_c_and_d_inputs_are_by_construction():
    # the packer's $CARRY_SEED: INIT 0x00AA, COUT only, I[1..3] unconnected
    doc = _slice_document(0x00AA, [2, 900, 901, 902])
    cell = doc["modules"]["top"]["cells"]["lut"]
    cell["connections"]["COUT"] = [5]
    doc["modules"]["top"]["netnames"]["cout"] = {"bits": [5]}
    reads, _ = sim_routed(None, cycles=1, document=doc)   # must not raise
    assert len(reads) == 1


def test_cli_verify_accepts_a_stimulus_file_and_trace(tmp_path, capsys):
    import argparse
    from agamemnon import cli
    routed = tmp_path / "wr.json"
    routed.write_text(json.dumps(_document(0)), encoding="utf-8")
    stim = tmp_path / "stim.json"
    stim.write_text(json.dumps({"schema": 1, "events": [[0, {"mcu_din": 1, "mcu_we": 1}], [1, {"mcu_we": 0}]]}),
                    encoding="utf-8")
    args = argparse.Namespace(input=str(routed), observed=None, cycles=6, stimulus=str(stim), trace="q0,din")
    with pytest.raises(SystemExit) as exc:
        cli.cmd_verify(args)
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "with stimulus" in out
    assert "read sequence (value x cycles): 0x2 1x4" in out
    assert "trace @0" in out and "din=1" in out


def test_malformed_stimulus_file_is_refused(tmp_path):
    from agamemnon.engine.verify_netlist import load_stimulus
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": 1, "events": [[0, 1]]}), encoding="utf-8")
    with pytest.raises(ValueError, match="malformed event"):
        load_stimulus(str(bad))
