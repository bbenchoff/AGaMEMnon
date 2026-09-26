"""Compiled N4.1 shared-control ingress and native-boundary rejection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
UNSUPPORTED = "unsupported physical shared control ASYNC_CLEAR_POS_ZERO"


def _tool():
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    return executable


def _devdb():
    path = Path(os.environ.get(
        "AGAMEMNON_UARCH_DEVDB",
        ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict",
    ))
    if not (path / "dev_pips.csv").is_file():
        pytest.skip("emit the strict agrv2k devdb before shared-control tests")
    return path


def _clock_source():
    return {
        "hide_name": 0, "type": "MCU_BUS_CLOCK", "parameters": {},
        "attributes": {}, "port_directions": {"CLK": "output"},
        "connections": {"CLK": [2]},
    }


def _slice(*, mode="NONE", control="missing", bel=None, name="state",
           extra_ports=()):
    """Build a compiled-fixture ``GENERIC_SLICE`` cell.

    ``control="bound"`` is the POST-PACKING lifted shape: for
    ASYNC_CLEAR_POS_ZERO that is the ``AGRV2K_ASYNC_CLEAR_NET`` attribute (no
    ARST/R port -- a packed slice never carries one, see agrv2k.cc's
    ``shared_control_requirement``). Use ``extra_ports`` to inject an actual
    control PORT (e.g. a stray ``ARST`` on a ``NONE``-mode cell, or a second
    port alongside a bound async net) -- a genuinely different, still
    malformed shape.
    """
    attrs = {
        "AGRV2K_REGISTER_INPUT_MODE": "LUT_FEEDTHROUGH_I0",
        "AGRV2K_SHARED_CONTROL_MODE": mode,
    }
    if bel:
        attrs.update({
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        })
    if mode == "ASYNC_CLEAR_POS_ZERO" and control == "bound":
        attrs["AGRV2K_ASYNC_CLEAR_NET"] = "reset"
    elif control not in ("missing", "bound"):
        raise ValueError(control)
    connections = {
        "I": [3, "x", "x", "x"], "CLK": [2], "Q": [4], "F": [],
    }
    directions = {"I": "input", "CLK": "input", "Q": "output", "F": "output"}
    for port in extra_ports:
        connections[port] = [6]
        directions[port] = "input"
    return {
        "hide_name": 0, "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(1, "032b"), "INIT": format(0xAAAA, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": attrs,
        "port_directions": directions,
        "connections": connections,
    }


def _design(cell, *, name="state", boundary=False):
    cells = {"typed_clock_source": _clock_source(), name: cell}
    if boundary:
        cells["mcu_h0"] = {
            "hide_name": 0, "type": "MCU_DOUT", "parameters": {},
            "attributes": {}, "port_directions": {"DOUT": "input"},
            "connections": {"DOUT": [4]},
        }
    return {
        "creator": "N4.1 shared-control compiled fixture",
        "modules": {"top": {
            "attributes": {"top": 1}, "ports": {}, "cells": cells,
            "netnames": {
                "clock": {"hide_name": 0, "bits": [2], "attributes": {}},
                "data": {"hide_name": 0, "bits": [3], "attributes": {}},
                "q": {"hide_name": 0, "bits": [4], "attributes": {}},
                "reset": {"hide_name": 0, "bits": [5], "attributes": {}},
                "other_control": {"hide_name": 0, "bits": [6], "attributes": {}},
            },
        }},
    }


def _run(tmp_path, name, design, *extra):
    source = tmp_path / (name + ".json")
    output = tmp_path / (name + "_out.json")
    source.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", "chipdb=%s" % _devdb(),
         "--json", str(source), "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


def test_none_mode_keeps_existing_fixed_slice_behavior(tmp_path):
    result, log, _ = _run(
        tmp_path, "none",
        _design(_slice(mode="NONE", bel="X14Y8_SLICE0")),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log


@pytest.mark.parametrize("name", ["state", "renamed_without_control_hint"])
def test_fixed_bel_rejects_active_control_under_renaming(tmp_path, name):
    result, log, _ = _run(
        tmp_path, "fixed_" + name,
        _design(
            _slice(
                mode="ASYNC_CLEAR_POS_ZERO", control="bound",
                bel="X14Y8_SLICE0", name=name,
            ),
            name=name,
        ),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode != 0
    assert UNSUPPORTED in log
    assert "Running router2" not in log


def test_no_place_preroute_rechecks_fixed_active_control(tmp_path):
    result, log, _ = _run(
        tmp_path, "no_place",
        _design(_slice(
            mode="ASYNC_CLEAR_POS_ZERO", control="bound",
            bel="X14Y8_SLICE0",
        )),
        "--no-place", "--router", "router2",
    )
    assert result.returncode != 0
    assert "pre-route DRC rejects shared control" in log
    assert UNSUPPORTED in log
    assert "Running router2" not in log


def test_unbound_active_control_rejects_before_ordinary_placement(tmp_path):
    result, log, _ = _run(
        tmp_path, "unbound_active",
        _design(_slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound")),
        "--pack-only",
    )
    assert result.returncode != 0
    assert "pre-placement shared-control DRC rejects unbound slice" in log
    assert UNSUPPORTED in log
    assert "Placing design" not in log


@pytest.mark.parametrize(
    "mode, control, extra_ports, reason",
    [
        ("ASYNC_CLEAR_POS_ZERO", "missing", (), "no recorded async-clear net"),
        ("NONE", "missing", ("ARST",), "NONE attribute disagrees"),
        ("FORGED", "missing", (), "unknown AGRV2K_SHARED_CONTROL_MODE"),
        ("ASYNC_CLEAR_POS_ZERO", "bound", ("CE",), "combined control port CE"),
    ],
)
def test_fixed_and_no_place_malformed_attempts_fail_closed(
        tmp_path, mode, control, extra_ports, reason):
    design = _design(_slice(
        mode=mode, control=control, extra_ports=extra_ports,
        bel="X14Y8_SLICE0",
    ))
    for suffix, args in (
        ("heap", ("--no-route", "--placer", "heap")),
        ("no_place", ("--no-place", "--router", "router2")),
    ):
        result, log, _ = _run(tmp_path, suffix, design, *args)
        assert result.returncode != 0
        assert reason in log
        assert "Running router2" not in log


@pytest.mark.parametrize(
    "mode, control, extra_ports, reason",
    [
        ("ASYNC_CLEAR_POS_ZERO", "bound", (), UNSUPPORTED),
        ("ASYNC_CLEAR_POS_ZERO", "missing", (), "no recorded async-clear net"),
        ("NONE", "missing", ("ARST",), "NONE attribute disagrees"),
    ],
)
def test_relative_cluster_rejects_active_or_malformed_member(
        tmp_path, mode, control, extra_ports, reason):
    result, log, _ = _run(
        tmp_path, "cluster",
        _design(_slice(mode=mode, control=control, extra_ports=extra_ports),
                boundary=True),
        "--pack-only",
    )
    assert result.returncode != 0
    assert "relative cluster rejects" in log
    assert reason in log
    assert "Placing design" not in log


def test_exact_raw_frontend_oracle_rejects_at_nextpnr_ingress(tmp_path):
    cell = {
        "hide_name": 0, "type": "$_DFF_PP0_", "parameters": {},
        "attributes": {
            "AGRV2K_SHARED_CONTROL_MODE": "ASYNC_CLEAR_POS_ZERO",
        },
        "port_directions": {
            "C": "input", "D": "input", "Q": "output", "R": "input",
        },
        "connections": {"C": [2], "D": [3], "Q": [4], "R": [5]},
    }
    result, log, _ = _run(
        tmp_path, "raw_oracle", _design(cell), "--pack-only",
    )
    assert result.returncode != 0
    assert "shared-control ingress rejects register" in log
    assert UNSUPPORTED in log
    assert "Packing constants" not in log


@pytest.mark.parametrize("cell_type", [
    "$_DFFE_PP_", "$_SDFF_PP0_", "$_DFF_PP1_", "$_DFF_PN0_",
    "$_ALDFF_PP_",
])
def test_hand_injected_unsupported_frontend_types_fail_closed(tmp_path, cell_type):
    cell = {
        "hide_name": 0, "type": cell_type, "parameters": {}, "attributes": {},
        "port_directions": {"C": "input", "D": "input", "Q": "output"},
        "connections": {"C": [2], "D": [3], "Q": [4]},
    }
    result, log, _ = _run(
        tmp_path, "raw_bad", _design(cell), "--pack-only",
    )
    assert result.returncode != 0
    assert "shared-control ingress rejects unsupported frontend register type" in log
    assert "Packing constants" not in log


# ---------------------------------------------------------------------------
# N4.2: ASYNC_CLEAR_POS_ZERO admitted (AGRV2K_SHARED_CONTROL_ASYNC_CLEAR)
# ---------------------------------------------------------------------------

def _raw_async_clear_cell(name_suffix, *, clock_bit=2, data_bit=3, clear_bit=5,
                          q_bit=None):
    return {
        "hide_name": 0, "type": "$_DFF_PP0_", "parameters": {}, "attributes": {
            "AGRV2K_SHARED_CONTROL_MODE": "ASYNC_CLEAR_POS_ZERO",
        },
        "port_directions": {
            "C": "input", "D": "input", "Q": "output", "R": "input",
        },
        "connections": {
            "C": [clock_bit], "D": [data_bit],
            "Q": [q_bit if q_bit is not None else (100 + name_suffix)],
            "R": [clear_bit],
        },
    }


def _many_cell_design(count):
    cells = {"typed_clock_source": _clock_source()}
    netnames = {
        "clock": {"hide_name": 0, "bits": [2], "attributes": {}},
        "data": {"hide_name": 0, "bits": [3], "attributes": {}},
        "reset": {"hide_name": 0, "bits": [5], "attributes": {}},
    }
    for index in range(count):
        cells["reg_%d" % index] = _raw_async_clear_cell(index)
        netnames["q_%d" % index] = {"hide_name": 0, "bits": [100 + index], "attributes": {}}
    return {
        "creator": "N4.2 async-clear admitted fixture",
        "modules": {"top": {
            "attributes": {"top": 1}, "ports": {}, "cells": cells,
            "netnames": netnames,
        }},
    }


@pytest.fixture
def async_clear_admitted(monkeypatch):
    monkeypatch.setenv("AGRV2K_SHARED_CONTROL_ASYNC_CLEAR", "1")


def test_admitted_async_clear_packs_to_the_lifted_shape(tmp_path, async_clear_admitted):
    """One register: packing succeeds, and the packed slice carries the
    lifted shape shared_control.py's requirement_for_cell expects -- no
    ARST/R port, AGRV2K_ASYNC_CLEAR_NET names the net."""
    result, log, output = _run(
        tmp_path, "one_admitted", _many_cell_design(1), "--pack-only",
    )
    assert result.returncode == 0, log
    routed = json.loads(output.read_text(encoding="utf-8"))
    slices = [c for c in routed["modules"]["top"]["cells"].values()
             if c["type"] == "GENERIC_SLICE"]
    async_slices = [c for c in slices
                    if c["attributes"].get("AGRV2K_SHARED_CONTROL_MODE") == "ASYNC_CLEAR_POS_ZERO"]
    assert len(async_slices) == 1
    slice_cell = async_slices[0]
    assert "ARST" not in slice_cell["connections"]
    assert "R" not in slice_cell["connections"]
    assert slice_cell["attributes"].get("AGRV2K_ASYNC_CLEAR_NET") == "reset"
    controls = [c for c in routed["modules"]["top"]["cells"].values()
               if c["type"] == "AGRV2K_TILE_CONTROL"]
    assert len(controls) == 1
    assert controls[0]["attributes"].get("AGRV2K_ASYNC_CLEAR_NET") == "reset"


def test_admitted_async_clear_without_the_flag_still_refuses(tmp_path):
    """The lifted shape only exists once the packer runs; without the flag,
    is_packable_ff() never recognises $_DFF_PP0_ at all, so the SAME design
    hits the pre-existing raw-frontend ingress refusal, unchanged."""
    result, log, _ = _run(
        tmp_path, "one_unadmitted", _many_cell_design(1), "--pack-only",
    )
    assert result.returncode != 0
    assert "shared-control ingress rejects register" in log
    assert UNSUPPORTED in log


def test_seventeen_registers_on_one_net_split_across_two_tile_controls(
        tmp_path, async_clear_admitted):
    """17 > the packer's 16-slice-per-tile control-set chunk
    (pack_shared_async_clear), so ONE shared async-clear net must produce
    TWO AGRV2K_TILE_CONTROL cells -- the same corpus shape as
    examples/async-clear-reset/clk_rst_multi_tile.v, proven structurally
    here without a full place&route."""
    result, log, output = _run(
        tmp_path, "seventeen", _many_cell_design(17), "--pack-only",
    )
    assert result.returncode == 0, log
    routed = json.loads(output.read_text(encoding="utf-8"))
    cells = routed["modules"]["top"]["cells"].values()
    controls = [c for c in cells if c["type"] == "AGRV2K_TILE_CONTROL"]
    assert len(controls) == 2
    assert all(c["attributes"].get("AGRV2K_ASYNC_CLEAR_NET") == "reset" for c in controls)
    async_slices = [c for c in cells if c["type"] == "GENERIC_SLICE"
                    and c["attributes"].get("AGRV2K_SHARED_CONTROL_MODE") == "ASYNC_CLEAR_POS_ZERO"]
    assert len(async_slices) == 17
