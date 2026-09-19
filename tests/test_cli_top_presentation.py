"""The build presents the synthesized top module as modules['top'].

Every stage after synthesis reads the exact ``modules['top']`` key.  Yosys keeps
the user's module name, so a design whose top module is not literally named
``top`` (the shipped serv_blinky example, most user RTL) used to be refused with
"typed special routes require exact modules['top']" before place-and-route.
"""
import json
from pathlib import Path

from agamemnon import cli

TOP_MARK = "00000000000000000000000000000001"


def _write(path, modules):
    path.write_text(json.dumps({"creator": "test", "modules": modules}), encoding="utf-8")
    return path


def _module(cells=None, top=None):
    module = {"attributes": {}, "ports": {}, "cells": cells or {}, "netnames": {}}
    if top is not None:
        module["attributes"]["top"] = top
    return module


def test_marked_top_module_is_presented_under_the_exact_key(tmp_path):
    cells = {"$auto$blinky$1": {"type": "LUT", "parameters": {"INIT": "0110"}}}
    path = _write(tmp_path / "synth.json", {"blinky": _module(cells, TOP_MARK)})
    assert cli._present_top_module(path) == "blinky"
    design = json.loads(path.read_text(encoding="utf-8"))
    assert list(design["modules"]) == ["top"]
    assert design["modules"]["top"]["cells"] == cells
    assert design["modules"]["top"]["attributes"]["top"] == TOP_MARK
    # Idempotent: a second pass reports the exact key and rewrites nothing.
    before = path.read_bytes()
    assert cli._present_top_module(path) == "top"
    assert path.read_bytes() == before


def test_design_already_named_top_is_left_byte_identical(tmp_path):
    path = _write(tmp_path / "synth.json", {"top": _module({}, TOP_MARK)})
    before = path.read_bytes()
    assert cli._present_top_module(path, "top") == "top"
    assert path.read_bytes() == before


def test_requested_top_wins_over_a_marker_and_other_modules_are_kept(tmp_path):
    modules = {
        "helper": _module({"h": {"type": "LUT"}}),
        "serv_blinky": _module({"c": {"type": "DFF"}}, "1"),
    }
    path = _write(tmp_path / "synth.json", modules)
    assert cli._present_top_module(path, "serv_blinky") == "serv_blinky"
    design = json.loads(path.read_text(encoding="utf-8"))
    assert list(design["modules"]) == ["top", "helper"]
    assert design["modules"]["top"]["cells"] == {"c": {"type": "DFF"}}
    assert design["modules"]["helper"]["cells"] == {"h": {"type": "LUT"}}


def test_sole_unmarked_module_is_presented(tmp_path):
    path = _write(tmp_path / "synth.json", {"lonely": _module()})
    assert cli._present_top_module(path) == "lonely"
    design = json.loads(path.read_text(encoding="utf-8"))
    assert list(design["modules"]) == ["top"]
    assert design["modules"]["top"]["attributes"]["top"] == TOP_MARK


def test_ambiguous_tops_are_left_for_the_exact_downstream_refusal(tmp_path):
    modules = {"a": _module({}, TOP_MARK), "b": _module({}, TOP_MARK)}
    path = _write(tmp_path / "synth.json", modules)
    before = path.read_bytes()
    assert cli._present_top_module(path) is None
    assert path.read_bytes() == before
    unmarked = {"a": _module(), "b": _module()}
    path = _write(tmp_path / "synth2.json", unmarked)
    assert cli._present_top_module(path) is None


def test_build_path_wires_the_presentation_before_the_first_top_consumer():
    src = Path(cli.__file__).read_text(encoding="utf-8")
    call = src.index("_presented_top = _present_top_module(synth_json, top)")
    guard = src.index("_mem_leftover_sidecar = synth_json + \".leftover_mem.json\"")
    nextpnr = src.index('npr += ["--top", top]')
    assert call < guard < nextpnr
    assert 'top = "top"' in src[call:guard]
