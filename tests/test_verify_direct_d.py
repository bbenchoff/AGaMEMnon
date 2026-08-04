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
