"""Compiled and structural coverage for opt-in local constant replication."""

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
DEFAULT_DEVDB = (
    ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
)


def _runtime_inputs():
    nextpnr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    devdb = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", DEFAULT_DEVDB))
    if not nextpnr or not Path(nextpnr).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    if not (devdb / "dev_pips.csv").is_file():
        pytest.skip("set AGAMEMNON_UARCH_DEVDB to the matching generated devdb")
    return Path(nextpnr), devdb


def _slice(output_bit):
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(0, "032b"),
            "INIT": format(0xAAAA, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": {"AGRV2K_REGISTER_INPUT_MODE": "NONE"},
        "port_directions": {
            "Q": "output", "F": "output", "CLK": "input", "I": "input",
        },
        "connections": {
            "Q": [], "F": [output_bit], "CLK": ["x"],
            "I": [2, "x", "x", "x"],
        },
    }


def _netlist():
    cells = {
        "vcc_source": {
            "hide_name": 0,
            "type": "VCC",
            "parameters": {},
            "attributes": {},
            "port_directions": {"Y": "output"},
            "connections": {"Y": [2]},
        },
        "consumer_a": _slice(10),
        "consumer_b": _slice(11),
        "consumer_c": _slice(12),
    }
    return {
        "creator": "local constant replication test",
        "modules": {
            "top": {
                "attributes": {"top": 1},
                "ports": {},
                "cells": cells,
                "netnames": {
                    "vcc": {"hide_name": 0, "bits": [2], "attributes": {}},
                    **{
                        f"out_{index}": {
                            "hide_name": 0, "bits": [bit], "attributes": {},
                        }
                        for index, bit in enumerate((10, 11, 12))
                    },
                },
            }
        },
    }


def _pack(tmp_path, *, enabled):
    nextpnr, devdb = _runtime_inputs()
    source = tmp_path / ("enabled.json" if enabled else "default.json")
    output = tmp_path / ("enabled_packed.json" if enabled else "default_packed.json")
    source.write_text(json.dumps(_netlist(), sort_keys=True), encoding="utf-8")
    env = dict(os.environ)
    env.pop("AGRV2K_LOCAL_CONSTANTS", None)
    if enabled:
        env["AGRV2K_LOCAL_CONSTANTS"] = "1"
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [
            str(nextpnr), "--uarch", "agrv2k", "-o", f"chipdb={devdb}",
            "--json", str(source), "--write", str(output), "--pack-only",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    return json.loads(output.read_text(encoding="utf-8")), log


def _constant_drivers(packed):
    cells = packed["modules"]["top"]["cells"]
    return {
        name: cell for name, cell in cells.items()
        if name == "$PACKER_VCC" or name.startswith("$PACKER_VCC_LOCAL_")
    }


def test_feature_is_explicitly_opt_in_and_after_constant_packing():
    source = UARCH.read_text(encoding="utf-8")
    pack = source.split("static void pack_constants", 1)[1].split(
        "static void pack_inactive_constant_slice_clocks", 1
    )[0]
    assert 'std::getenv("AGRV2K_LOCAL_CONSTANTS") != nullptr' in pack
    assert pack.index('std::getenv("AGRV2K_LOCAL_CONSTANTS")') < pack.index(
        'replicate_local_constants(ctx, ctx->id("$PACKER_GND_NET")'
    )
    assert pack.index('replicate_local_constants(ctx, ctx->id("$PACKER_GND_NET")') < pack.index(
        'replicate_local_constants(ctx, ctx->id("$PACKER_VCC_NET")'
    )


def test_unset_path_keeps_one_shared_constant_driver(tmp_path):
    packed, log = _pack(tmp_path, enabled=False)
    drivers = _constant_drivers(packed)
    assert set(drivers) == {"$PACKER_VCC"}
    assert "AGRV2K_LOCAL_CONSTANTS replicated" not in log
    cells = packed["modules"]["top"]["cells"]
    constant_bits = {cells[name]["connections"]["I"][0] for name in (
        "consumer_a", "consumer_b", "consumer_c",
    )}
    assert constant_bits == {drivers["$PACKER_VCC"]["connections"]["F"][0]}


def test_enabled_path_gives_each_consumer_a_matching_local_driver(tmp_path):
    packed, log = _pack(tmp_path, enabled=True)
    drivers = _constant_drivers(packed)
    assert set(drivers) == {
        "$PACKER_VCC", "$PACKER_VCC_LOCAL_2", "$PACKER_VCC_LOCAL_3",
    }
    assert "AGRV2K_LOCAL_CONSTANTS replicated 2 local drivers off $PACKER_VCC" in log
    assert len({cell["connections"]["F"][0] for cell in drivers.values()}) == 3
    assert len({json.dumps(cell["parameters"], sort_keys=True) for cell in drivers.values()}) == 1
    cells = packed["modules"]["top"]["cells"]
    assert len({cells[name]["connections"]["I"][0] for name in (
        "consumer_a", "consumer_b", "consumer_c",
    )}) == 3
