"""The board-witnessed BRAM surfaces auto-enable from the typed cell.

Same promotion pattern as the GPIO4 request corridor: no user-facing flag,
the CLI detects the typed ``ALTA_BRAM9K`` cell in the synthesized netlist
and sets the internal option itself.  A design without the cell must report
neither feature (zero blast radius), and the build-side gate must skip
release-strict builds, where the experimental-maturity options would make
the build refuse the CLI's own setting.
"""

import json

from agamemnon.cli import _bram_auto_features


def _netlist(cells):
    return {"modules": {"top": {"cells": cells}}}


def _write(tmp_path, payload):
    path = tmp_path / "synth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_read_ported_bram_reports_reads(tmp_path):
    synth = _write(tmp_path, _netlist({
        "mem": {"type": "ALTA_BRAM9K",
                "connections": {"DataOutA": [2, 3, "x"], "ByteEnA": ["1", "1"]}},
    }))
    assert _bram_auto_features(synth) == {"reads": True, "byteen": False}


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
        assert _bram_auto_features(path) == {"reads": False, "byteen": True}


def test_bramless_design_reports_neither(tmp_path):
    synth = _write(tmp_path, _netlist({
        "ff": {"type": "ALTA_DFF", "connections": {"Q": [4]}},
    }))
    assert _bram_auto_features(synth) == {"reads": False, "byteen": False}


def test_unreadable_netlist_reports_neither(tmp_path):
    bad = tmp_path / "synth.json"
    bad.write_text("not json", encoding="utf-8")
    assert _bram_auto_features(str(bad)) == {"reads": False, "byteen": False}


def test_port_b_read_also_reports_reads(tmp_path):
    synth = _write(tmp_path, _netlist({
        "mem": {"type": "ALTA_BRAM9K", "connections": {"DataOutB": [7]}},
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
    # ByteEn intent is recorded by qin_pack, so the decision must precede
    # the qin step.
    auto = src.index("_bram_auto_features(synth_json)")
    qin = src.index('run("qin"')
    assert auto < qin
