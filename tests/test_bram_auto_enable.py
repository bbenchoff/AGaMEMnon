"""The board-witnessed BRAM surfaces auto-enable from the typed cell.

Same promotion pattern as the GPIO4 request corridor: no user-facing flag,
the CLI detects the typed ``ALTA_BRAM9K`` cell in the synthesized netlist
and sets the internal option itself.  A design without the cell must report
neither feature (zero blast radius), and the build-side gate must skip
release-strict builds, where the experimental-maturity options would make
the build refuse the CLI's own setting.

The site-read corridor was witnessed for BRAM *read over the MCU bus*
(hbread10).  A BRAM read only by fabric logic -- the SERV register file --
must not receive it: the profile also skips the exact SERV WeA/ReA witness
reservation in the uarch, which on the shipped serv_blinky collided with the
register-file write corridor on every attempt.
"""

import json

from agamemnon.cli import _bram_auto_features

NONE = {"reads": False, "fabric_reads": False, "byteen": False, "narrow_write": False}


def _netlist(cells):
    return {"modules": {"top": {"cells": cells}}}


def _write(tmp_path, payload):
    path = tmp_path / "synth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _mcu_cell():
    return {"type": "MCU_AHB_HREADY", "connections": {"O": [9]}}


def test_read_ported_bram_over_the_mcu_reports_reads(tmp_path):
    synth = _write(tmp_path, _netlist({
        "mem": {"type": "ALTA_BRAM9K",
                "connections": {"DataOutA": [2, 3, "x"], "ByteEnA": ["1", "1"]}},
        "bus": _mcu_cell(),
    }))
    assert _bram_auto_features(synth) == {
        "reads": True, "fabric_reads": False, "byteen": False, "narrow_write": False}


def test_read_ported_bram_without_an_mcu_boundary_is_a_fabric_read(tmp_path):
    # The SERV register file: read and written by fabric logic only.
    synth = _write(tmp_path, _netlist({
        "rf": {"type": "ALTA_BRAM9K",
               "connections": {"DataOutA": [2, 3], "DataOutB": [5, 6],
                               "DataInA": [7, 8], "WeA": [10]}},
        "lut": {"type": "LUT", "connections": {"I": [2, 3, 5, 6], "F": [11]}},
    }))
    assert _bram_auto_features(synth) == {
        "reads": False, "fabric_reads": True, "byteen": False, "narrow_write": False}


def test_grounded_byteen_lane_reports_byteen():
    # Mirrors qin_pack's own predicate: a ByteEnA bit that is the constant
    # string '0'.  Constant-only DataOut is not a read.
    cells = {"mem": {"type": "ALTA_BRAM9K",
                     "connections": {"DataOutA": ["0", "0"],
                                     "ByteEnA": ["0", "1"]}}}
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "synth.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_netlist(cells), fh)
        assert _bram_auto_features(path) == {
            "reads": False, "fabric_reads": False, "byteen": True, "narrow_write": False}


def test_bramless_design_reports_neither(tmp_path):
    synth = _write(tmp_path, _netlist({
        "ff": {"type": "ALTA_DFF", "connections": {"Q": [4]}},
        "bus": _mcu_cell(),
    }))
    assert _bram_auto_features(synth) == NONE


def test_unreadable_netlist_reports_neither(tmp_path):
    bad = tmp_path / "synth.json"
    bad.write_text("not json", encoding="utf-8")
    assert _bram_auto_features(str(bad)) == NONE


def test_port_b_read_over_the_mcu_also_reports_reads(tmp_path):
    synth = _write(tmp_path, _netlist({
        "mem": {"type": "ALTA_BRAM9K", "connections": {"DataOutB": [7]}},
        "bus": {"type": "MCU_SLAVE_AHB_HRDATA1_4", "connections": {"I": [7]}},
    }))
    assert _bram_auto_features(synth)["reads"] is True


def test_build_gate_skips_release_strict_and_respects_explicit_env():
    # The auto-set block must be gated on non-release-strict --uarch builds
    # and must not override an explicit environment setting.  Assert the
    # source shape rather than running a full build.
    import inspect
    import agamemnon.cli as cli
    src = inspect.getsource(cli._cmd_build_once)
    assert "if a.uarch and not release_strict:" in src
    assert '"AGAMEMNON_BRAM_SITE_READ_PATHS" not in env' in src
    assert '"AGAMEMNON_BRAM_BYTEEN" not in env' in src
    # A fabric-only read is reported, never auto-enabled.
    assert '_bram_auto["fabric_reads"]' in src
    fabric = src.index('_bram_auto["fabric_reads"]')
    assert 'env["AGAMEMNON_BRAM_SITE_READ_PATHS"] = "1"' not in src[fabric:fabric + 400]
    # ByteEn intent is recorded by qin_pack, so the decision must precede
    # the qin step.
    auto = src.index("_bram_auto_features(synth_json)")
    qin = src.index('run("qin"')
    assert auto < qin


def test_narrow_port_a_write_reports_narrow_write(tmp_path):
    # x9/x4/x1 Port-A writes with a dynamic WeA get the packer lane-keep switch
    # (2026-09-25 default narrow-write path); nothing else does.
    for code in ("01000", "01100", "01111"):
        synth = _write(tmp_path, _netlist({
            "mem": {"type": "ALTA_BRAM9K", "parameters": {"PORTA_WIDTH": code},
                    "connections": {"WeA": [10], "DataInA": [7] * 18}}}))
        assert _bram_auto_features(synth)["narrow_write"] is True, code


def test_x2_x18_and_read_only_narrow_brams_do_not_report_narrow_write(tmp_path):
    # x2 is exempt (the SERV register file must pack byte-identically), x18 is not
    # narrow, and a constant WeA is a ROM.
    for code, wea in (("01110", [10]), ("00000", [10]), ("01000", ["0"]), ("01100", [])):
        synth = _write(tmp_path, _netlist({
            "mem": {"type": "ALTA_BRAM9K", "parameters": {"PORTA_WIDTH": code},
                    "connections": {"WeA": wea, "DataInA": [7] * 18}}}))
        assert _bram_auto_features(synth)["narrow_write"] is False, code
