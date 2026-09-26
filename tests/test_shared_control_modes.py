"""Typed shared-control protocol and strict-emitter boundary."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agamemnon.engine.features.core_logic import FEATURE as CORE_LOGIC_FEATURE
from agamemnon.engine.features.shared_control import (
    ASYNC_CLEAR_ADMIT_OPTION,
    ASYNC_CLEAR_NET_ATTRIBUTE,
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
    """Build a synthetic routed ``GENERIC_SLICE``.

    ``control="bound"`` means the POST-PACKING lifted shape: for
    ASYNC_CLEAR_POS_ZERO that is the ``AGRV2K_ASYNC_CLEAR_NET`` attribute (no
    ARST port -- a packed slice never carries one, see
    ``agamemnon/engine/features/shared_control.py``'s module docstring).  Use
    ``extra_ports`` to inject an actual control PORT (e.g. a stray ``ARST`` on
    a ``NONE``-mode cell, or a second port alongside a bound async net) --
    that is a genuinely different, still-malformed shape.
    """
    attrs = {
        "NEXTPNR_BEL": "X14Y8_SLICE0",
        "AGRV2K_REGISTER_INPUT_MODE": (
            "LUT_FEEDTHROUGH_I0" if ff_used else "NONE"
        ),
    }
    if mode is not None:
        attrs[SHARED_CONTROL_MODE_ATTRIBUTE] = mode
    if mode == "ASYNC_CLEAR_POS_ZERO" and control == "bound":
        attrs[ASYNC_CLEAR_NET_ATTRIBUTE] = "reset"
    elif control not in ("missing", "bound"):
        raise ValueError(control)
    connections = {
        "I": [3, "x", "x", "x"],
        "CLK": [2] if ff_used else [],
        "Q": [4] if ff_used else [],
        "F": [],
    }
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
    """Unset AGRV2K_SHARED_CONTROL_ASYNC_CLEAR: still refused, by default."""
    requirement = validate_module_shared_controls(
        _slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound")
    )["state"]
    assert requirement.active
    assert requirement.polarity == "POSITIVE"
    assert requirement.clear_value == 0
    assert requirement.async_clear_net == "reset"
    assert not requirement.legacy_derived


def test_async_clear_becomes_inactive_once_admitted(monkeypatch):
    monkeypatch.setenv(ASYNC_CLEAR_ADMIT_OPTION, "1")
    requirement = validate_module_shared_controls(
        _slice(mode="ASYNC_CLEAR_POS_ZERO", control="bound")
    )["state"]
    assert not requirement.active
    assert requirement.async_clear_net == "reset"


@pytest.mark.parametrize(
    "module, reason",
    [
        (_slice(mode="ASYNC_CLEAR_POS_ZERO"),
         "requires a AGRV2K_ASYNC_CLEAR_NET"),
        (_slice(mode="NONE", extra_ports=("ARST",)),
         "inactive attribute disagrees"),
        (_slice(mode=None, extra_ports=("ARST",)),
         "inactive attribute disagrees"),
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
        validate_module_shared_controls(_slice(mode=token))


@pytest.mark.parametrize("port", [
    "R", "ARST", "ASET", "SET", "CE", "EN", "SRST", "SCLR", "SLOAD", "ALOAD",
])
def test_unsupported_and_combined_control_ports_fail_closed(port):
    with pytest.raises(SystemExit, match="must carry no control port"):
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


def test_frontend_guard_runs_before_dfflegalize_and_tags_final_cells():
    source = SYNTH.read_text(encoding="utf-8")
    lower = source.index("yosys dffunmap")
    guard = source.index("_shared_control_unsupported")
    stamp = source.index("AGRV2K_SHARED_CONTROL_MODE")
    legalize = source.index("yosys dfflegalize")
    assert lower < guard < legalize < stamp
    assert "t:\\$_DFFE_NN_ t:\\$_DFFE_NP_" in source
    assert "t:\\$_SDFF_* t:\\$_SDFFE_* t:\\$_SDFFCE_*" in source
    assert "yosys dffunmap t:\\$_DFFE_*" not in source
    assert "t:\\$_DFF_P_ t:\\$_DFF_PP0_" in source
    assert "-cell \\$_DFF_PP0_ 0" in source
    assert "yosys dffunmap -srst-only" in source
    assert "yosys opt -full -nosdff" in source
    assert "AGRV2K_SHARED_CONTROL_MINCE" in source
    assert "-mince $_shared_control_mince" in source
