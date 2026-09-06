"""Compiled reset-preserving packing and physical-admission boundaries."""

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
    attrs = {
        "AGRV2K_REGISTER_INPUT_MODE": "LUT_FEEDTHROUGH_I0",
        "AGRV2K_SHARED_CONTROL_MODE": mode,
    }
    if bel:
        attrs.update({
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        })
    connections = {
        "I": [3, "x", "x", "x"], "CLK": [2], "Q": [4], "F": [],
    }
    directions = {"I": "input", "CLK": "input", "Q": "output", "F": "output"}
    if control == "bound":
        connections["ARST"] = [5]
        directions["ARST"] = "input"
    elif control == "unbound":
        connections["ARST"] = ["x"]
        directions["ARST"] = "input"
    elif control != "missing":
        raise ValueError(control)
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
def test_fixed_bel_allocates_active_control_under_renaming(tmp_path, name):
    result, log, output = _run(
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
    assert result.returncode == 0, log
    module = json.loads(output.read_text())["modules"]["top"]
    controllers = [c for c in module["cells"].values() if c["type"] == "AGRV2K_ASYNCCTRL"]
    assert len(controllers) == 1
    assert controllers[0]["connections"]["DIN"] == module["netnames"]["reset"]["bits"]
    assert controllers[0]["connections"]["DOUT"] == module["cells"][name]["connections"]["ARST"]
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


def test_unbound_active_control_places_with_a_controller(tmp_path):
    result, log, output = _run(
        tmp_path, "unbound_active",
        _design(_slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound")),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log
    module = json.loads(output.read_text())["modules"]["top"]
    assert any(c["type"] == "AGRV2K_ASYNCCTRL" for c in module["cells"].values())
    assert "Running router2" not in log


@pytest.mark.parametrize(
    "mode, control, extra_ports, reason",
    [
        ("ASYNC_CLEAR_POS_ZERO", "missing", (), "requires a ARST control port"),
        ("ASYNC_CLEAR_POS_ZERO", "unbound", (), "ARST control port has no bound net"),
        ("NONE", "bound", (), "NONE attribute disagrees"),
        ("FORGED", "bound", (), "unknown AGRV2K_SHARED_CONTROL_MODE"),
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
    "mode, control, reason",
    [
        ("ASYNC_CLEAR_POS_ZERO", "missing", "requires a ARST control port"),
        ("NONE", "bound", "NONE attribute disagrees"),
    ],
)
def test_relative_cluster_rejects_active_or_malformed_member(
        tmp_path, mode, control, reason):
    result, log, _ = _run(
        tmp_path, "cluster",
        _design(_slice(mode=mode, control=control), boundary=True),
        "--pack-only",
    )
    assert result.returncode != 0
    assert "relative cluster rejects" in log
    assert reason in log
    assert "Placing design" not in log


def test_relative_cluster_places_and_allocates_active_member(tmp_path):
    result, log, output = _run(
        tmp_path, "active_cluster",
        _design(_slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound"), boundary=True),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log
    module = json.loads(output.read_text())["modules"]["top"]
    active = module["cells"]["state"]
    controllers = [c for c in module["cells"].values() if c["type"] == "AGRV2K_ASYNCCTRL"]
    assert len(controllers) == 1
    assert active["connections"]["ARST"] == controllers[0]["connections"]["DOUT"]
    assert controllers[0]["connections"]["DIN"] == module["netnames"]["reset"]["bits"]


def test_async_allocation_rejects_occupied_controller_bel(tmp_path):
    design = _design(_slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound", bel="X14Y8_SLICE0"))
    design["modules"]["top"]["cells"]["foreign_controller"] = {
        "type": "AGRV2K_ASYNCCTRL", "hide_name": 0,
        "parameters": {"MODE": format(2, "032b")},
        "attributes": {"NEXTPNR_BEL": "X14Y8_ASYNCCTRL0", "BEL_STRENGTH": format(5, "032b")},
        "port_directions": {"DIN": "input", "DOUT": "output"},
        "connections": {"DIN": [5], "DOUT": [60]},
    }
    result, log, _ = _run(tmp_path, "occupied", design, "--no-route", "--placer", "heap")
    assert result.returncode != 0
    assert "async allocation has missing or occupied controller" in log


def test_physical_input_identity_can_feed_allocated_controller(tmp_path, monkeypatch):
    monkeypatch.setenv('AGRV2K_IO_PINPACK', '1')
    monkeypatch.setenv('AGAMEMNON_DATA', str(ROOT / 'agamemnon/chipdb'))
    design = _design(_slice(mode='ASYNC_CLEAR_POS_ZERO', control='bound', bel='X14Y8_SLICE0'))
    design['modules']['top']['cells']['reset_pad'] = {
        'type': 'GENERIC_IOB', 'hide_name': 0, 'parameters': {},
        'attributes': {'NEXTPNR_BEL': 'X20Y13_IPAD1'},
        'port_directions': {'PAD': 'inout', 'O': 'output'},
        'connections': {'PAD': [], 'O': [5]},
    }
    result, log, output = _run(tmp_path, 'pad_placed', design, '--no-route', '--placer', 'heap')
    assert result.returncode == 0, log
    from agamemnon.engine.features.native_endpoint import validate_module_native_endpoints
    placed = json.loads(output.read_text())['modules']['top']
    validate_module_native_endpoints(placed, ROOT / 'agamemnon/chipdb')
    result, log, _ = _run(tmp_path, 'pad_route_refused', design, '--router', 'router2')
    assert result.returncode != 0
    assert 'pre-route DRC rejects shared control' in log
    assert 'rejects malformed native endpoint' not in log
    assert 'Running router2' not in log


def _raw_async():
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
    return cell


@pytest.mark.parametrize("fused", (False, True))
@pytest.mark.parametrize("name", ("state", "renamed_without_control_hint"))
def test_exact_raw_frontend_packing_preserves_reset(tmp_path, fused, name):
    cell = _raw_async()
    design = _design(cell, name=name)
    if fused:
        cell["connections"]["D"] = [7]
        design["modules"]["top"]["cells"]["logic"] = {
            "type": "LUT", "hide_name": 0,
            "parameters": {"K": format(4, "032b"), "INIT": format(0x5555, "016b")},
            "attributes": {"AGRV2K_SHARED_CONTROL_MODE": "NONE"},
            "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": [3, "x", "x", "x"], "Q": [7]},
        }
    result, log, output = _run(tmp_path, "packed", design, "--pack-only")
    assert result.returncode == 0, log
    module = json.loads(output.read_text())["modules"]["top"]
    registers = [c for c in module["cells"].values()
                 if c["type"] == "GENERIC_SLICE" and int(c["parameters"]["FF_USED"], 2)]
    assert len(registers) == 1
    packed = registers[0]
    assert packed["attributes"]["AGRV2K_SHARED_CONTROL_MODE"] == "ASYNC_CLEAR_POS_ZERO"
    assert packed["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] == (
        "LUT_COMPUTE_TO_FF" if fused else "LUT_FEEDTHROUGH_I0")
    assert int(packed["parameters"]["INIT"], 2) == (0x5555 if fused else 0xAAAA)
    for port, net in (("ARST", "reset"), ("CLK", "clock"), ("Q", "q")):
        assert packed["connections"][port] == module["netnames"][net]["bits"]
    assert packed["port_directions"]["ARST"] == "input"
    assert "R" not in packed["connections"]
    assert not any(c["type"] == "$_DFF_PP0_" for c in module["cells"].values())


@pytest.mark.parametrize("fused", (False, True))
def test_raw_control_places_but_cannot_enter_routing(tmp_path, fused):
    design = _design(_raw_async())
    if fused:
        design["modules"]["top"]["cells"]["state"]["connections"]["D"] = [7]
        design["modules"]["top"]["cells"]["logic"] = {
            "type": "LUT", "hide_name": 0,
            "parameters": {"K": format(4, "032b"), "INIT": format(0x5555, "016b")},
            "attributes": {}, "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": [3, "x", "x", "x"], "Q": [7]},
        }
    result, log, _ = _run(tmp_path, "cannot_route", design, "--router", "router2")
    assert result.returncode != 0
    assert "pre-route DRC rejects shared control" in log
    assert UNSUPPORTED in log
    assert "Running router2" not in log


@pytest.mark.parametrize("requests, controllers, legal", [
    (("a", "a", "a"), 1, True),
    (("a", "ground"), 2, True),
    (("a", "b"), 2, True),
    (("a", "b", "ground"), 0, False),
    (("a", "b", "c"), 0, False),
    (("ground", "ground"), 0, True),
    (("a", "combinational", "b"), 2, True),
])
def test_tile_control_capacity_and_physical_bindings(tmp_path, requests, controllers, legal):
    design = _design(_slice())
    module = design["modules"]["top"]
    del module["cells"]["state"]
    source_bits = {"a": 20, "b": 21, "c": 22}
    for source, bit in source_bits.items():
        module["netnames"]["reset_" + source] = {"bits": [bit], "attributes": {}, "hide_name": 0}
    for index, request in enumerate(requests):
        active = request in source_bits
        cell = _slice(mode="ASYNC_CLEAR_POS_ZERO" if active else "NONE",
                      control="bound" if active else "missing", bel="X14Y8_SLICE%d" % (2*index))
        cell["connections"]["Q"] = [30 + index]
        if active:
            cell["connections"]["ARST"] = [source_bits[request]]
        if request == "combinational":
            cell["parameters"]["FF_USED"] = format(0, "032b")
            cell["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] = "NONE"
            cell["connections"].update(CLK=[], Q=[], F=[30 + index])
        module["cells"]["member%d" % index] = cell
    result, log, output = _run(tmp_path, "capacity", design, "--no-route", "--placer", "heap")
    if not legal:
        assert result.returncode != 0
        assert "including inactive registers; capacity is 2" in log
        assert "Running router2" not in log
        return
    assert result.returncode == 0, log
    placed = json.loads(output.read_text())["modules"]["top"]
    controls = [c for c in placed["cells"].values() if c["type"] == "AGRV2K_ASYNCCTRL"]
    assert len(controls) == controllers
    for index, request in enumerate(requests):
        cell = placed["cells"]["member%d" % index]
        if not controllers or request == "combinational":
            assert "AGRV2K_ASYNC_CONTROLLER_INDEX" not in cell["attributes"]
            continue
        slot = int(cell["attributes"]["AGRV2K_ASYNC_CONTROLLER_INDEX"], 2)
        controller = next(c for c in controls if c["attributes"]["NEXTPNR_BEL"] ==
                          "X14Y8_ASYNCCTRL%d" % slot)
        if request == "ground":
            assert int(controller["parameters"]["MODE"], 2) == 0
            assert controller["connections"]["DIN"] == []
            assert "ARST" not in cell["connections"]
        else:
            assert int(controller["parameters"]["MODE"], 2) == 2
            assert controller["connections"]["DIN"] == placed["netnames"]["reset_" + request]["bits"]
            assert cell["connections"]["ARST"] == controller["connections"]["DOUT"]
            assert controller["connections"]["DIN"] != controller["connections"]["DOUT"]


@pytest.mark.parametrize("mutation", ("missing_clock", "wrong_direction", "extra_port"))
def test_malformed_raw_control_rejects_before_packing(tmp_path, mutation):
    cell = _raw_async()
    if mutation == "missing_clock":
        cell["connections"]["C"] = ["x"]
    elif mutation == "wrong_direction":
        cell["port_directions"]["R"] = "output"
    else:
        cell["connections"]["EXTRA"] = [6]
        cell["port_directions"]["EXTRA"] = "input"
    result, log, _ = _run(tmp_path, mutation, _design(cell), "--pack-only")
    assert result.returncode != 0
    assert "shared-control ingress rejects malformed register" in log
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
