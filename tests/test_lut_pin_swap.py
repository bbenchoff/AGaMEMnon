"""Router-chosen LUT input pins (AGAMEMNON_LUT_PIN_SWAP, off by default).

Structural checks always run.  The compiled checks run the isolated agrv2k
nextpnr on a small hand-built netlist and need AGAMEMNON_UARCH_NEXTPNR plus a
matching generated devdb (AGAMEMNON_UARCH_DEVDB).
"""

import itertools
import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
DEFAULT_DEVDB = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
FIXED_BEL = "X16Y8_SLICE0"


def permute_init(init, perm):
    """Truth table over physical inputs; perm[l] is the physical input of logical l."""
    out = 0
    for physical_row in range(16):
        logical_row = sum(1 << l for l in range(4) if physical_row >> perm[l] & 1)
        if init >> logical_row & 1:
            out |= 1 << physical_row
    return out


# ---------------------------------------------------------------- structural

def _source():
    return UARCH.read_text(encoding="utf-8")


def test_option_is_off_unless_exactly_one():
    source = _source()
    body = source.split("static bool lut_pin_swap_enabled()", 1)[1].split("\n}\n", 1)[0]
    assert 'std::getenv("AGAMEMNON_LUT_PIN_SWAP")' in body
    assert 'value == nullptr || std::string(value) == "0"' in body
    assert 'std::string(value) == "1"' in body
    assert "log_error" in body


def test_hooks_run_after_every_pre_route_reservation_and_before_post_route_audits():
    source = _source()
    pre = source.split("    void preRoute() override", 1)[1].split("    bool checkPipAvail(PipId pip)", 1)[0]
    assert pre.rstrip().endswith("setup_lut_pin_swap();\n    }") or \
        pre.index("setup_lut_pin_swap();") > pre.index("reserve_required_routes(true);")
    assert pre.index("setup_lut_pin_swap();") > pre.index("lock_global_clock_tree(")
    post = source.split("    void postRoute() override", 1)[1].split("\n    }\n", 1)[0]
    assert post.strip().startswith("{\n        finish_lut_pin_swap();")
    assert post.index("finish_lut_pin_swap();") < post.index("audit_carry_routes(")


def test_pseudo_pips_are_gated_only_by_their_own_table_when_active():
    source = _source()
    avail = source.split("    bool checkPipAvail(PipId pip) const override", 1)[1].split("\n    }\n", 1)[0]
    assert avail.strip().startswith("{\n        if (is_lut_swap_pip(pip))\n            return lut_swap_pip_ok(pip);")
    helper = source.split("    bool is_lut_swap_pip(PipId pip) const", 1)[1].split("\n    }\n", 1)[0]
    assert "lut_swap_active &&" in helper


def test_freeze_rules_cover_afexe_and_packer_owned_shapes():
    source = _source()
    cell = source.split("static std::string lut_swap_cell_freeze_reason(", 1)[1].split("\n}\n", 1)[0]
    # af.exe: self-loop freezes A-D; carry/Cout freezes C/D (whole cell here);
    # BypassEn/FeedbackMux freezes C (register-input modes here); fixed never swaps.
    assert '"LUT self-loop"' in cell and "net == f || net == q" in cell
    assert 'port_has_net(ctx, cell, "CIN") || port_has_net(ctx, cell, "COUT")' in cell
    assert "RegisterInputMode::NONE && input.mode != RegisterInputMode::LUT_COMPUTE_TO_FF" in cell
    assert "cell->belStrength >= STRENGTH_USER" in cell
    for attr in ('"BEL"', '"AGRV2K_IO_PINPACKED"', '"AGRV2K_MCU_PINPACKED"', '"AGRV2K_BRAM_PINPACKED"',
                 '"AGRV2K_ROUTE_THROUGH"', '"agamemnon_local_qin_feedback"',
                 '"agamemnon_registered_pad_input"', '"AGRV2K_CARRY_"', '"agamemnon_direct_d_"'):
        assert attr in cell, attr
    assert "native_endpoint_requirement" in cell and "mcu_endpoint_requirement" in cell
    assert "init_depends_on(init_value, input_index)" in cell
    pin = source.split("static std::string lut_swap_pin_freeze_reason(", 1)[1].split("\n}\n", 1)[0]
    assert '"net repeats on another input of the same LUT"' in pin
    assert '"hard-block driver "' in pin and '"constant net"' in pin
    setup = source.split("    void setup_lut_pin_swap()", 1)[1].split("\n    }\n\n", 1)[0]
    assert '"pre-routed sink"' in setup and "carry_d_default_high_wires" in setup


def test_python_reference_permutation():
    # Swap logical 0 onto physical 1 (and back): INIT for f = I0 & ~I1.
    init = sum(1 << r for r in range(16) if (r & 1) and not (r & 2))
    swapped = permute_init(init, [1, 0, 2, 3])
    assert swapped == sum(1 << r for r in range(16) if (r & 2) and not (r & 1))
    for perm in itertools.permutations(range(4)):
        inverse = [perm.index(p) for p in range(4)]
        assert permute_init(permute_init(0xB4E1, perm), inverse) == 0xB4E1
    assert permute_init(0xB4E1, [0, 1, 2, 3]) == 0xB4E1


# ------------------------------------------------------------------ compiled

def _runtime_inputs():
    nextpnr = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    devdb = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", DEFAULT_DEVDB))
    if not nextpnr or not Path(nextpnr).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    if not (devdb / "dev_pips.csv").is_file():
        pytest.skip("set AGAMEMNON_UARCH_DEVDB to the matching generated devdb")
    return Path(nextpnr), devdb


def _slice(init, inputs, output, attrs=None):
    attributes = {"AGRV2K_REGISTER_INPUT_MODE": "NONE"}
    attributes.update(attrs or {})
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {"FF_USED": format(0, "032b"), "INIT": format(init, "016b"), "K": format(4, "032b")},
        "attributes": attributes,
        "port_directions": {"Q": "output", "F": "output", "CLK": "input", "I": "input"},
        "connections": {"Q": [], "F": [output], "CLK": ["x"], "I": list(inputs)},
    }


RING = [10, 11, 12, 13]


def _netlist():
    cells = {"ring%d" % k: _slice(0x5555, [RING[k - 1], "x", "x", "x"], RING[k]) for k in range(4)}
    cells["mix"] = _slice(0xB4E1, RING, 20)
    cells["pair"] = _slice(0x2222, [RING[0], RING[2], "x", "x"], 21)
    cells["loop"] = _slice(0x8888, [22, RING[1], "x", "x"], 22)        # self-loop: frozen
    cells["dup"] = _slice(0x7878, [RING[1], RING[1], RING[2], "x"], 23)  # I0/I1 share a net
    cells["fixed"] = _slice(0x4444, [RING[3], RING[0], "x", "x"], 24, {"BEL": FIXED_BEL})
    nets = {"r%d" % k: bit for k, bit in enumerate(RING)}
    nets.update(mix=20, pair=21, loop=22, dup=23, fixed=24)
    return {
        "creator": "lut pin swap test",
        "modules": {"top": {
            "attributes": {"top": 1}, "ports": {}, "cells": cells,
            "netnames": {name: {"hide_name": 0, "bits": [bit], "attributes": {}} for name, bit in nets.items()},
        }},
    }


def _route(tmp_path, tag, swap=None, derange=None):
    nextpnr, devdb = _runtime_inputs()
    source = tmp_path / "design.json"
    source.write_text(json.dumps(_netlist(), sort_keys=True), encoding="utf-8")
    output = tmp_path / ("%s.json" % tag)
    env = dict(os.environ)
    for key in ("AGAMEMNON_LUT_PIN_SWAP", "AGAMEMNON_LUT_PIN_SWAP_TEST_DERANGE"):
        env.pop(key, None)
    if swap is not None:
        env["AGAMEMNON_LUT_PIN_SWAP"] = swap
    if derange is not None:
        env["AGAMEMNON_LUT_PIN_SWAP_TEST_DERANGE"] = derange
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [str(nextpnr), "--uarch", "agrv2k", "-o", "chipdb=%s" % devdb, "--json", str(source),
         "--write", str(output), "--router", "router2", "--placer", "heap", "--seed", "1", "--top", "top", "--ignore-loops"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=600,
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log[-4000:]
    return output.read_bytes(), log


NET_NAMES = {"r0", "r1", "r2", "r3", "mix", "pair", "loop", "dup", "fixed"}


def _cells_and_routes(document):
    """Cells with I connections translated to net names, and wires per net name."""
    module = document["modules"]["top"]
    name_of = {}
    routes = {}
    for name, net in module["netnames"].items():
        if name in NET_NAMES and len(net["bits"]) == 1:
            name_of[net["bits"][0]] = name
            routing = net.get("attributes", {}).get("ROUTING", "")
            routes[name] = set(routing.split(";")[0::3])
    cells = {}
    for cell_name, cell in module["cells"].items():
        if cell["type"] != "GENERIC_SLICE" or cell_name.startswith("$"):
            continue
        cells[cell_name] = dict(
            init=int(cell["parameters"]["INIT"], 2),
            inputs=[name_of.get(bit) for bit in cell["connections"]["I"]],
            bel=cell["attributes"]["NEXTPNR_BEL"],
            attrs=cell["attributes"],
        )
    return cells, routes


def _function(cell):
    """Truth table keyed by the named nets feeding this cell."""
    names = sorted({n for n in cell["inputs"] if n is not None})
    table = {}
    for values in itertools.product((0, 1), repeat=len(names)):
        assign = dict(zip(names, values))
        row = sum(assign[n] << k for k, n in enumerate(cell["inputs"]) if n is not None)
        table[values] = cell["init"] >> row & 1
    return names, table


def _check_pins(cells, routes):
    for name, cell in cells.items():
        x, y, z = map(int, re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", cell["bel"]).groups())
        for k, net in enumerate(cell["inputs"]):
            if net is not None:
                assert "X%dY%d_IMUX%02d" % (x, y, 4 * z + k) in routes[net], (name, k)


def test_unset_and_zero_are_byte_identical_and_add_nothing(tmp_path):
    unset, unset_log = _route(tmp_path, "unset")
    zero, zero_log = _route(tmp_path, "zero", swap="0")
    assert unset == zero
    assert b"LUTPERM" not in unset and b"AGRV2K_LUT_PIN_PERM" not in unset
    assert "LUT pin swap" not in unset_log and "LUT pin swap" not in zero_log


def test_forced_swaps_permute_init_and_land_on_the_physical_input(tmp_path):
    off_bytes, _ = _route(tmp_path, "off")
    on_bytes, log = _route(tmp_path, "derange", swap="1", derange="*")
    assert b"LUTPERM" not in on_bytes
    off_cells, _ = _cells_and_routes(json.loads(off_bytes))
    on_cells, on_routes = _cells_and_routes(json.loads(on_bytes))
    _check_pins(on_cells, on_routes)
    assert "froze 1 slice(s): LUT self-loop" in log
    assert "froze 1 slice(s): user-fixed location" in log
    assert "froze 2 input pin(s): net repeats on another input of the same LUT" in log
    swapped = {n for n, c in on_cells.items() if "AGRV2K_LUT_PIN_PERM" in c["attrs"]}
    assert {"mix", "pair", "dup", "ring0", "ring1", "ring2", "ring3"} <= swapped
    assert not swapped & {"loop", "fixed"}
    for name in ("loop", "fixed"):
        assert on_cells[name]["inputs"] == off_cells[name]["inputs"]
        assert on_cells[name]["init"] == off_cells[name]["init"]
    for name in swapped:
        cell = on_cells[name]
        perm = [int(c) for c in cell["attrs"]["AGRV2K_LUT_PIN_PERM"]]
        pre = int(cell["attrs"]["AGRV2K_LUT_PRESWAP_INIT"], 2)
        assert sorted(perm) == [0, 1, 2, 3]
        assert permute_init(pre, perm) == cell["init"]
        assert pre == off_cells[name]["init"]
        # every swappable connected input moved (derangement); dup keeps I0/I1
        for logical, net in enumerate(off_cells[name]["inputs"]):
            if net is None:
                continue
            frozen = name == "dup" and logical in (0, 1)
            assert (perm[logical] == logical) == frozen, (name, logical, perm)
            assert cell["inputs"][perm[logical]] == net
        assert _function(cell) == _function(off_cells[name]), name


def test_unforced_swap_builds_and_preserves_every_function(tmp_path):
    off_bytes, _ = _route(tmp_path, "off")
    on_bytes, log = _route(tmp_path, "on", swap="1")
    assert "LUT pin swap ON:" in log and "LUT pin swap rewrote" in log
    off_cells, _ = _cells_and_routes(json.loads(off_bytes))
    on_cells, on_routes = _cells_and_routes(json.loads(on_bytes))
    _check_pins(on_cells, on_routes)
    for name in off_cells:
        assert _function(on_cells[name]) == _function(off_cells[name]), name
