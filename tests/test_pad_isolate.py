"""Output pads whose net fans out get a dedicated identity-LUT driver.

The typed L48 output lanes refuse a pad driver with internal fanout ("only one
pad sink is qualified"), and the board-proven top-edge outputs were presented
through an identity LUT.  A hobbyist's ``assign led = count[11]`` used to fail
at packing on every placement attempt; the CLI now isolates the pad itself.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

from agamemnon.engine import pad_isolate

TOP = "00000000000000000000000000000001"


def _design(cells):
    return {"creator": "test", "modules": {"top": {"attributes": {"top": TOP}, "cells": cells}}}


def _iob_out(bit, pad=90):
    return {"type": "GENERIC_IOB", "port_directions": {"I": "input", "PAD": "output"},
            "connections": {"I": [bit], "PAD": [pad]}}


def _dff(d, q):
    return {"type": "DFF", "port_directions": {"CLK": "input", "D": "input", "Q": "output"},
            "connections": {"CLK": [1], "D": [d], "Q": [q]}}


def _lut(inputs, out):
    return {"type": "LUT", "parameters": {"INIT": "0110100110010110", "K": "00000000000000000000000000000100"},
            "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": inputs, "Q": [out]}}


def test_fanned_out_pad_net_gets_a_dedicated_identity_lut():
    design = _design({
        "count_ff": _dff(d=5, q=7),
        "next_lut": _lut([7, 2, 3, 4], 5),      # the register feeds its own next-state logic
        "led_pad": _iob_out(7),                  # ... and the pad
    })
    added, examined = pad_isolate.isolate(design)
    assert (added, examined) == (1, 1)
    cells = design["modules"]["top"]["cells"]
    buf = cells["$pad_buf$1"]
    assert buf["type"] == "LUT"
    assert buf["parameters"]["INIT"] == "1010101010101010"
    assert buf["attributes"]["agamemnon_pad_buffer"] == "1"
    assert buf["connections"]["I"] == [7, "0", "0", "0"]
    new_bit = buf["connections"]["Q"][0]
    assert new_bit not in (1, 2, 3, 4, 5, 7, 90)
    assert cells["led_pad"]["connections"]["I"] == [new_bit]
    # Internal consumers still see the register directly.
    assert cells["next_lut"]["connections"]["I"] == [7, 2, 3, 4]
    assert cells["count_ff"]["connections"]["Q"] == [7]


def test_register_driving_a_pad_directly_gets_a_buffer_too():
    # ``output reg led``: the FF's clock input is the CLKIN pad, and bitgen's
    # native-endpoint check refuses that composition ("malformed or
    # unqualified fixed input NEXTPNR_BEL 'CLKIN'"); the identity LUT in
    # between is the qualified presentation (acc_probe, every top-edge output).
    design = _design({
        "led_ff": _dff(d=5, q=7),
        "led_pad": _iob_out(7),
    })
    assert pad_isolate.isolate(design) == (1, 1)
    cells = design["modules"]["top"]["cells"]
    assert cells["$pad_buf$1"]["connections"]["I"][0] == 7
    assert cells["led_pad"]["connections"]["I"] == cells["$pad_buf$1"]["connections"]["Q"]
    assert cells["led_ff"]["connections"]["Q"] == [7]


def test_single_sink_lut_driven_pad_and_input_pads_are_untouched():
    design = _design({
        "copy_lut": _lut([5, 2, 3, 4], 7),
        "led_pad": _iob_out(7),                                # already a dedicated LUT driver
        "reset_pad": {"type": "GENERIC_IOB",
                      "port_directions": {"O": "output", "PAD": "input"},
                      "connections": {"O": [11], "PAD": [91]}},
        "sink_a": _lut([11, 2, 3, 4], 12),
        "sink_b": _lut([11, 2, 3, 4], 13),
    })
    before = copy.deepcopy(design)
    assert pad_isolate.isolate(design) == (0, 1)
    assert design == before


def test_every_fanned_out_pad_gets_its_own_buffer_and_the_file_round_trips(tmp_path):
    design = _design({
        "ff": _dff(d=5, q=7),
        "lut": _lut([7, 2, 3, 4], 5),
        "pad_a": _iob_out(7, 90),
        "pad_b": _iob_out(7, 91),               # two pads on the same net: each isolated
        "pad_c": _iob_out(5, 92),               # LUT output also used by the register
        "pad_d": _iob_out(8, 93),               # sole-user LUT driver: left alone
        "solo": _lut([2, 3, 4, "0"], 8),
    })
    path = tmp_path / "synth.json"
    path.write_text(json.dumps(design), encoding="utf-8")
    root = Path(pad_isolate.__file__).parents[2]
    result = subprocess.run([sys.executable, str(root / "agamemnon" / "engine" / "pad_isolate.py"),
                             str(path)], capture_output=True, text=True, cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 output pad(s), inserted 3 dedicated identity LUT driver(s)" in result.stdout
    cells = json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    buffers = {n: c for n, c in cells.items() if c.get("attributes", {}).get("agamemnon_pad_buffer")}
    assert len(buffers) == 3
    driven = {cells[p]["connections"]["I"][0] for p in ("pad_a", "pad_b", "pad_c")}
    assert driven == {b["connections"]["Q"][0] for b in buffers.values()}
    assert cells["pad_d"]["connections"]["I"] == [8]
    # No bit has two drivers afterwards.
    outputs = [bit for c in cells.values() for port, bits in c["connections"].items()
               if c.get("port_directions", {}).get(port) == "output" for bit in bits
               if isinstance(bit, int)]
    assert len(outputs) == len(set(outputs))


def test_build_runs_pad_isolation_after_qin_and_not_for_exact_replays():
    src = (Path(pad_isolate.__file__).parents[1] / "cli.py").read_text(encoding="utf-8")
    qin = src.index('run("qin", [sys.executable, os.path.join(engine, "qin_pack.py"), synth_json])')
    pad = src.index('run("pad-isolate"')
    replay = src.index('run("exact-route-replay"')
    assert qin < pad < replay
    assert "if not qualified_profile:" in src[qin:pad]


def test_two_pads_on_one_lut_net_both_get_buffers():
    """``assign led = dig[0]``: after the first pad is buffered the net still has two readers (the
    sibling pad and the new buffer), so the sibling gets its own buffer as well.  Leaving it on the raw
    net made the bitgen's native endpoint check refuse the first buffer ("malformed mixed input
    endpoint claim on port I", shift_sevenseg 2026-09-19)."""
    design = _design({
        "dig0_lut": _lut([2, 3, 4, 5], 7),
        "dig0_pad": _iob_out(7, pad=90),
        "led_pad": _iob_out(7, pad=91),
    })
    added, examined = pad_isolate.isolate(design)
    assert (added, examined) == (2, 2)
    cells = design["modules"]["top"]["cells"]
    fed = {cells[n]["connections"]["I"][0] for n in ("dig0_pad", "led_pad")}
    bufs = [c for n, c in cells.items() if n.startswith("$pad_buf$")]
    assert len(bufs) == 2 and {b["connections"]["Q"][0] for b in bufs} == fed
    assert all(b["connections"]["I"][0] == 7 for b in bufs)

