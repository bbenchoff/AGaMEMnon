import json


def _slice(init, connections, ff_used):
    return {
        "type": "GENERIC_SLICE",
        "parameters": {"INIT": format(init, "016b"), "FF_USED": "1" if ff_used else "0"},
        "attributes": {},
        "connections": connections,
    }


def test_routed_verifier_models_seeded_dedicated_carry(tmp_path):
    """A seeded two-bit ripple must visit 00, 01, 10, and 11."""
    cells = {
        "$CARRY_SEED": _slice(0x0000, {"I": [], "COUT": [10]}, False),
        "bit0": _slice(0xC3FC, {"I": ["0", 30, "0", "1"], "CIN": [10],
                                       "COUT": [11], "Q": [30]}, True),
        "bit1": _slice(0x3CC0, {"I": ["0", 31, "0", "1"], "CIN": [11],
                                       "COUT": [12], "Q": [31]}, True),
        "mcu_h0": {"type": "MCU_DOUT", "parameters": {},
                   "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT10"},
                   "connections": {"DOUT": [30]}},
        "mcu_h1": {"type": "MCU_DOUT", "parameters": {},
                   "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT11"},
                   "connections": {"DOUT": [31]}},
    }
    design = {"modules": {"top": {"cells": cells, "netnames": {
        "carry0": {"bits": [10]}, "carry1": {"bits": [11]},
        "carry2": {"bits": [12]}, "q0": {"bits": [30]}, "q1": {"bits": [31]},
    }}}}
    routed = tmp_path / "carry.json"
    routed.write_text(json.dumps(design))

    from agamemnon.engine.verify_netlist import sim_routed

    reads, bind = sim_routed(str(routed), cycles=8)
    assert set(reads) == {0, 1, 2, 3}
    assert bind == {"mcu_h0": (0, 0), "mcu_h1": (1, 1)}


def test_routed_verifier_models_two_independent_carry_chains(tmp_path):
    cells = {
        "seed_a": _slice(0x0000, {"I": [], "COUT": [10]}, False),
        "a0": _slice(0xC3FC, {"I": ["0", 30, "0", "1"], "CIN": [10],
                                 "COUT": [11], "Q": [30]}, True),
        "a1": _slice(0x3CC0, {"I": ["0", 31, "0", "1"], "CIN": [11],
                                 "COUT": [12], "Q": [31]}, True),
        "seed_b": _slice(0x0000, {"I": [], "COUT": [20]}, False),
        "b0": _slice(0xC3FC, {"I": ["0", 40, "0", "1"], "CIN": [20],
                                 "COUT": [21], "Q": [40]}, True),
        "b1": _slice(0x3CC0, {"I": ["0", 41, "0", "1"], "CIN": [21],
                                 "COUT": [22], "Q": [41]}, True),
    }
    for bit, net in enumerate((30, 31, 40, 41)):
        cells["mcu_h%d" % bit] = {
            "type": "MCU_DOUT", "parameters": {},
            "attributes": {"NEXTPNR_BEL": "X10Y5_MCU_DOUT%d" % (10 + bit)},
            "connections": {"DOUT": [net]},
        }
    design = {"modules": {"top": {"cells": cells, "netnames": {
        "carry_a0": {"bits": [10]}, "carry_a1": {"bits": [11]},
        "carry_a2": {"bits": [12]},
        "carry_b0": {"bits": [20]}, "carry_b1": {"bits": [21]},
        "carry_b2": {"bits": [22]},
        "a0": {"bits": [30]}, "a1": {"bits": [31]},
        "b0": {"bits": [40]}, "b1": {"bits": [41]},
    }}}}
    routed = tmp_path / "dual-carry.json"
    routed.write_text(json.dumps(design))

    from agamemnon.engine.verify_netlist import sim_routed

    reads, bind = sim_routed(str(routed), cycles=8)
    # Both disjoint state spaces advance and are visible in separate AHB lanes.
    assert set(value & 0x3 for value in reads) == {0, 1, 2, 3}
    assert set((value >> 2) & 0x3 for value in reads) == {0, 1, 2, 3}
    assert all(declared == physical for declared, physical in bind.values())
