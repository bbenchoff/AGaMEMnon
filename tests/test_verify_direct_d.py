import json

from agamemnon.engine.verify_netlist import sim_routed


def test_registered_slice_exposes_f_while_q_feeds_direct_d(tmp_path):
    routed = tmp_path / "direct_d.json"
    routed.write_text(json.dumps({"modules": {"top": {
        "netnames": {
            "q": {"bits": [2]},
            "observed": {"bits": [3]},
        },
        "cells": {
            "tff": {
                "type": "GENERIC_SLICE",
                "parameters": {"FF_USED": "1", "INIT": "0000000011111111"},
                "attributes": {"NEXTPNR_BEL": "X1Y4_SLICE2"},
                "connections": {"Q": [2], "F": [3], "I": ["0", "0", "0", 2]},
            },
            "mcu_h0": {
                "type": "MCU_DOUT",
                "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT10"},
                "connections": {"DOUT": [3]},
            },
        },
    }}}), encoding="utf-8")

    reads, bind = sim_routed(routed, cycles=6)
    assert reads == [1, 0, 1, 0, 1, 0]
    assert bind == {"mcu_h0": (0, 0)}


def test_one_source_net_can_drive_multiple_mcu_read_lanes(tmp_path):
    routed = tmp_path / "constant_fanout.json"
    routed.write_text(json.dumps({"modules": {"top": {
        "netnames": {"shared_high": {"bits": [2]}},
        "cells": {
            "source": {
                "type": "GENERIC_SLICE",
                "parameters": {"FF_USED": "0", "INIT": "1111111111111111"},
                "attributes": {"NEXTPNR_BEL": "X1Y4_SLICE2"},
                "connections": {"F": [2], "I": ["0", "0", "0", "0"]},
            },
            "mcu_h2": {
                "type": "MCU_DOUT",
                "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT12"},
                "connections": {"DOUT": [2]},
            },
            "mcu_h5": {
                "type": "MCU_DOUT",
                "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT15"},
                "connections": {"DOUT": [2]},
            },
        },
    }}}), encoding="utf-8")

    reads, bind = sim_routed(routed, cycles=2)
    assert reads == [0x24, 0x24]
    assert bind == {"mcu_h2": (2, 2), "mcu_h5": (5, 5)}
