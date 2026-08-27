"""Typed shared-control protocol and strict-emitter boundary."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agamemnon.engine.features.core_logic import FEATURE as CORE_LOGIC_FEATURE
from agamemnon.engine.features.shared_control import (
    SHARED_CONTROL_MODE_ATTRIBUTE,
    SHARED_CONTROL_MODE_TOKENS,
    SHARED_CONTROL_PORT_TOKENS,
    validate_module_shared_controls,
)
from agamemnon.engine.registry import CONSTANTS, options_from


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
SYNTH = ROOT / "agamemnon" / "synth" / "synth_pads.tcl"


def _slice(*, mode="NONE", control="missing", name="state", extra_ports=(),
           ff_used=1):
    attrs = {
        "NEXTPNR_BEL": "X14Y8_SLICE0",
        "AGRV2K_REGISTER_INPUT_MODE": (
            "LUT_FEEDTHROUGH_I0" if ff_used else "NONE"
        ),
    }
    if mode is not None:
        attrs[SHARED_CONTROL_MODE_ATTRIBUTE] = mode
    connections = {
        "I": [3, "x", "x", "x"],
        "CLK": [2] if ff_used else [],
        "Q": [4] if ff_used else [],
        "F": [],
    }
    if control == "bound":
        connections["ARST"] = [5]
    elif control == "unbound":
        connections["ARST"] = [105]
    elif control != "missing":
        raise ValueError(control)
    for port in extra_ports:
        connections[port] = [6]
    cell = {
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(ff_used, "032b"),
            "INIT": format(0xAAAA if ff_used else 0, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": attrs,
        "connections": connections,
    }
    netnames = {
        "clock": {"bits": [2]}, "data": {"bits": [3]},
        "q": {"bits": [4]},
    }
    if control == "bound":
        netnames["reset"] = {"bits": [5]}
    for port in extra_ports:
        netnames[port.lower()] = {"bits": [6]}
    return {
        "cells": {name: cell}, "netnames": netnames, "ports": {},
    }


def test_cpp_and_python_shared_control_tokens_are_exactly_conformant():
    source = UARCH.read_text(encoding="utf-8")
    table = re.search(
        r"SHARED_CONTROL_MODE_TOKENS\[\]\s*=\s*\{(?P<body>.*?)\};",
        source, re.S,
    )
    assert table
    cpp_tokens = tuple(re.findall(r'"([A-Z0-9_]+)"', table.group("body")))
    assert cpp_tokens == SHARED_CONTROL_MODE_TOKENS
    ports = re.search(
        r"SHARED_CONTROL_PORT_TOKENS\[\]\s*=\s*\{(?P<body>.*?)\};",
        source, re.S,
    )
    assert ports
    cpp_ports = tuple(re.findall(r'"([A-Z0-9_]+)"', ports.group("body")))
    assert cpp_ports == SHARED_CONTROL_PORT_TOKENS


@pytest.mark.parametrize("explicit", ["NONE", None])
def test_none_is_inert_and_legacy_compatible(explicit):
    requirement = validate_module_shared_controls(
        _slice(mode=explicit)
    )["state"]
    assert requirement.mode == "NONE"
    assert requirement.polarity == "NONE"
    assert requirement.clear_value is None
    assert requirement.control_bit is None
    assert requirement.legacy_derived is (explicit is None)


def test_async_clear_requirement_carries_exact_semantics_and_bound_net():
    requirement = validate_module_shared_controls(
        _slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound")
    )["state"]
    assert requirement.active
    assert requirement.polarity == "POSITIVE"
    assert requirement.clear_value == 0
    assert requirement.control_bit == 5
    assert not requirement.legacy_derived


@pytest.mark.parametrize(
    "module, reason",
    [
        (_slice(mode="ASYNC_CLEAR_POS_ZERO"), "requires an ARST"),
        (_slice(mode="ASYNC_CLEAR_POS_ZERO", control="unbound"), "no bound net"),
        (_slice(mode="NONE", control="bound"), "inactive attribute disagrees"),
        (_slice(mode=None, control="bound"), "inactive attribute disagrees"),
        (_slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound", ff_used=0),
         "FF_USED=1"),
    ],
)
def test_attr_port_and_active_shape_mismatch_fail_closed(module, reason):
    with pytest.raises(SystemExit, match=reason):
        validate_module_shared_controls(module)


@pytest.mark.parametrize("token", [
    "UNKNOWN", "MALFORMED", "FORGED", "ASYNC_SET_POS_ONE",
    "ASYNC_CLEAR_POS_ONE", "CLOCK_ENABLE", "SYNC_CLEAR", "SYNC_LOAD",
    "ASYNC_CLEAR_WITH_ENABLE",
])
def test_unknown_or_unsupported_mode_tokens_fail_closed(token):
    with pytest.raises(SystemExit, match="shared control"):
        validate_module_shared_controls(_slice(mode=token, control="bound"))


@pytest.mark.parametrize("port", [
    "R", "ASET", "SET", "CE", "EN", "SRST", "SCLR", "SLOAD", "ALOAD",
])
def test_unsupported_and_combined_control_ports_fail_closed(port):
    with pytest.raises(SystemExit, match="unsupported or combined"):
        validate_module_shared_controls(
            _slice(
                mode="ASYNC_CLEAR_POS_ZERO", control="bound",
                extra_ports=(port,),
            )
        )


class _NoBitClaim(dict):
    def get(self, *args, **kwargs):
        raise AssertionError("selector lookup occurred before shared-control rejection")


@pytest.mark.parametrize("name", ["state", "renamed_without_control_hint"])
def test_strict_emitter_rejects_active_control_before_any_bit_claim(name):
    with pytest.raises(SystemExit, match="unsupported physically.*before any bit claim"):
        CORE_LOGIC_FEATURE.prepare(
            _slice(
                mode="ASYNC_CLEAR_POS_ZERO", control="bound", name=name,
            ),
            _NoBitClaim(), options_from({}), CONSTANTS,
        )


def test_cpp_rechecks_shared_control_at_all_native_boundaries():
    source = UARCH.read_text(encoding="utf-8")
    assert source.count("shared_control_requirement(ctx, member.first)") == 1
    assert source.count("shared_control_requirement(ctx, cell)") >= 3
    assert source.count(
        "shared_control_cell_admitted(ctx, ci, bel, explain_invalid)"
    ) == 1
    assert source.index("reject_unsupported_shared_control_ingress(ctx)") < source.index(
        "pack_constants(ctx)"
    )
    assert source.index("pre-route DRC rejects shared control") < source.index(
        "Running router2"
    ) if "Running router2" in source else True


def test_frontend_guard_runs_before_dfflegalize_and_preserves_exact_oracle():
    source = SYNTH.read_text(encoding="utf-8")
    guard = source.index("_shared_control_unsupported")
    stamp = source.index("AGRV2K_SHARED_CONTROL_MODE")
    legalize = source.index("yosys dfflegalize")
    assert guard < stamp < legalize
    assert "t:\\$_DFF_P_ t:\\$_DFF_PP0_" in source
    assert "-cell \\$_DFF_PP0_ 0" in source
