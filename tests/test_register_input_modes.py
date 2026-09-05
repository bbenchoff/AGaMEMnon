"""Typed register-feedthrough legality and strict-emitter admission."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from agamemnon.engine.features.core_logic import FEATURE as CORE_LOGIC_FEATURE
from agamemnon.engine.features.register_input import (
    REGISTER_INPUT_MODE_TOKENS,
    validate_module_register_inputs,
)
from agamemnon.engine.registry import CONSTANTS, options_from


ROOT = Path(__file__).resolve().parents[1]
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"


def _cell(mode, base, *, init=0xAAAA, ff_used=1, inputs=(0,), tags=(),
          f_used=False, carry=False, own_q_i3=False):
    q, clk, f = base, base + 1, base + 2
    input_bits = [base + 20 + index for index in range(4)]
    dummy_bits = [base + 100 + index for index in range(4)]
    connected = set(inputs)
    if own_q_i3:
        input_bits[3] = q
        connected.add(3)
    connections = {
        "I": [input_bits[index] if index in connected else dummy_bits[index]
              for index in range(4)],
        "CLK": [clk] if ff_used else [],
        "Q": [q] if ff_used else [],
        "F": [f] if f_used else [],
    }
    if carry:
        connections.update({"CIN": [base + 10], "COUT": [base + 11]})
    attributes = {"AGRV2K_REGISTER_INPUT_MODE": mode}
    attributes.update({tag: "1" for tag in tags})
    cell = {
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(ff_used, "032b"),
            "INIT": format(init, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": attributes,
        "connections": connections,
    }
    live = {q: "q", clk: "clock"}
    if f_used:
        live[f] = "f"
    for index in connected:
        live[input_bits[index]] = "i%d" % index
    if carry:
        live.update({base + 10: "cin", base + 11: "cout"})
    return cell, live


def _module(cells_and_live):
    cells = {}
    netnames = {}
    for name, (cell, live) in cells_and_live.items():
        cells[name] = cell
        for bit, suffix in live.items():
            netnames["%s_%s" % (name, suffix)] = {"bits": [bit]}
    return {"cells": cells, "netnames": netnames, "ports": {}}


def _feedthrough(base=100):
    return _cell("LUT_FEEDTHROUGH_I0", base)


@pytest.mark.parametrize("missing", [None, "cin", "a", "selector"])
def test_combinational_carry_uses_cin_without_ordinary_i2(missing):
    inputs = tuple(i for i in (0, 1, 3)
                   if not (missing == "a" and i == 0) and
                      not (missing == "selector" and i == 3))
    cell, live = _cell("NONE", 100, init=0x96E8, ff_used=0,
                       inputs=inputs, carry=True, f_used=True)
    if missing == "cin":
        cell["connections"]["CIN"] = []
    module = _module({"carry": (cell, live)})
    if missing is None:
        assert validate_module_register_inputs(module)["carry"].mode == "NONE"
    else:
        with pytest.raises(SystemExit, match="INIT depends on unconnected"):
            validate_module_register_inputs(module)


def test_ordinary_combinational_lut_cannot_borrow_carry_exception():
    module = _module({"plain": _cell("NONE", 100, init=0x96E8, ff_used=0,
                                      inputs=(0, 1, 3), f_used=True)})
    with pytest.raises(SystemExit, match=r"unconnected I\[2\]"):
        validate_module_register_inputs(module)


def test_cpp_and_python_protocol_tokens_are_exactly_conformant():
    source = UARCH.read_text(encoding="utf-8")
    table = re.search(
        r"REGISTER_INPUT_MODE_TOKENS\[\]\s*=\s*\{(?P<body>.*?)\};",
        source, re.S,
    )
    assert table
    cpp_tokens = tuple(re.findall(r'"([A-Z0-9_]+)"', table.group("body")))
    assert cpp_tokens == REGISTER_INPUT_MODE_TOKENS


def test_native_direct_d_replay_is_guarded_at_every_bel_surface():
    source = UARCH.read_text(encoding="utf-8")
    hint = source[source.index("static void hint_replay_bels"):
                  source.index("static void pack_replay_bels")]
    replay = source[source.index("static void pack_replay_bels"):
                    source.index("static void pack_route_through_bels")]
    direct = source[source.index("static void pack_direct_d_bels"):
                    source.index("static void pack_condplace")]
    for body in (hint, replay):
        assert "native_direct_d_pool_cell(ctx, ci)" in body
        assert "replay BEL map names native direct-D member" in body
    assert hint.index("native_direct_d_pool_cell(ctx, ci)") < hint.index(
        "ci->attrs[ctx->id(\"BEL\")]")
    assert replay.index("native_direct_d_pool_cell(ctx, ci)") < replay.index(
        "ctx->bindBel")
    assert "native_direct_d_pool_cell(ctx, ci)" in direct
    assert "replay and explicit BEL metadata are forbidden" in direct
    assert direct.index("native_direct_d_pool_cell(ctx, ci)") < direct.index("ctx->bindBel")


def test_typed_raw_dff_shape_is_exact_and_name_invariant():
    for name in ("raw_state", "renamed_without_semantic_hint"):
        requirements = validate_module_register_inputs(
            _module({name: _feedthrough()})
        )
        assert requirements[name].mode == "LUT_FEEDTHROUGH_I0"
        assert not requirements[name].legacy_derived


def test_two_same_clock_feedthroughs_compose():
    left, left_live = _feedthrough(100)
    right, right_live = _feedthrough(1000)
    # Both consume the same physical shared-clock net; their data and Q nets
    # remain independent.
    right["connections"]["CLK"] = left["connections"]["CLK"]
    right_live.pop(1001)
    right_live[101] = "clock"
    requirements = validate_module_register_inputs(
        _module({"left": (left, left_live), "right": (right, right_live)})
    )
    assert {item.mode for item in requirements.values()} == {"LUT_FEEDTHROUGH_I0"}


def test_feedthrough_composes_with_lut_fused_ff_and_carry_adjacency():
    feed = _feedthrough(100)
    lut = _cell("NONE", 1000, ff_used=0, init=0x6996, inputs=(0, 1, 2, 3),
                f_used=True)
    fused = _cell("LUT_COMPUTE_TO_FF", 2000, init=0xCCCC, inputs=(1,))
    carry = _cell("CARRY_SUM_TO_FF", 3000, init=0x96E8,
                  inputs=(0, 1, 3), carry=True)
    requirements = validate_module_register_inputs(_module({
        "feed": feed, "lut": lut, "fused": fused, "carry": carry,
    }))
    assert [requirements[name].mode for name in ("feed", "lut", "fused", "carry")] == [
        "LUT_FEEDTHROUGH_I0", "NONE", "LUT_COMPUTE_TO_FF", "CARRY_SUM_TO_FF",
    ]


@pytest.mark.parametrize("token", ["UNKNOWN", "MALFORMED", "FORGED_MODE"])
def test_unknown_or_forged_mode_fails_closed(token):
    cell, live = _feedthrough()
    cell["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] = token
    with pytest.raises(SystemExit, match="register input"):
        validate_module_register_inputs(_module({"bad": (cell, live)}))


@pytest.mark.parametrize(
    "mutation, reason",
    [
        (lambda cell, live: cell["parameters"].__setitem__("FF_USED", "0"),
         "FF_USED=1"),
        (lambda cell, live: cell["parameters"].__setitem__("INIT", format(0xCCCC, "016b")),
         "INIT=0xAAAA"),
        (lambda cell, live: (
            live.pop(cell["connections"]["I"][0]),
            cell["connections"]["I"].__setitem__(3, 150),
            live.__setitem__(150, "wrong_i3"),
        ), "I\\[0\\] only"),
        (lambda cell, live: (
            cell["connections"]["F"].append(102),
            live.__setitem__(102, "forged_f"),
        ), "unused F"),
    ],
)
def test_feedthrough_metadata_shape_mismatches_fail_closed(mutation, reason):
    cell, live = _feedthrough()
    mutation(cell, live)
    with pytest.raises(SystemExit, match=reason):
        validate_module_register_inputs(_module({"bad": (cell, live)}))


@pytest.mark.parametrize(
    "special",
    ["agamemnon_registered_pad_input", "agamemnon_direct_d_feedback", "carry"],
)
def test_i0_feedthrough_cannot_inherit_i3_direct_or_carry_support(special):
    cell, live = _feedthrough()
    if special == "carry":
        cell["connections"].update({"CIN": [180], "COUT": [181]})
        live.update({180: "cin", 181: "cout"})
    else:
        cell["attributes"][special] = "1"
    with pytest.raises(SystemExit, match="cannot inherit|conflicting"):
        validate_module_register_inputs(_module({"bad": (cell, live)}))


def test_one_bad_member_rejects_the_whole_composition():
    bad, bad_live = _feedthrough(1000)
    bad["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] = "FORGED_MODE"
    with pytest.raises(SystemExit, match="cell 'bad'"):
        validate_module_register_inputs(_module({
            "good": _feedthrough(100), "bad": (bad, bad_live),
        }))


def _direct_module(bel, *, explicit=True, tag=False):
    cell, live = _cell(
        "DIRECT_D_I3", 100, init=0x00FF, inputs=(),
        tags=(("agamemnon_direct_d_feedback",) if tag else ()),
        own_q_i3=True,
    )
    if not explicit:
        cell["attributes"].pop("AGRV2K_REGISTER_INPUT_MODE")
    cell["attributes"]["NEXTPNR_BEL"] = bel
    return _module({"state": (cell, live)})


def _native_direct_module(bels, *, declared=None):
    declared = len(bels) if declared is None else declared
    items = {}
    for index, bel in enumerate(bels):
        cell, live = _cell(
            "DIRECT_D_I3", 100 + 1000 * index, init=0x00FF, inputs=(),
            tags=("agamemnon_direct_d_feedback",), own_q_i3=True,
        )
        cell["attributes"].update({
            "agamemnon_direct_d_origin": "qin-pack-inferred-own-q",
            "AGRV2K_NATIVE_DIRECT_D_POOL": "X14Y11_SLICE4_7_V1",
            "AGRV2K_NATIVE_DIRECT_D_COUNT": str(declared),
            "NEXTPNR_BEL": bel,
        })
        items["state%d" % index] = (cell, live)
    return _module(items)


def test_strict_emitter_direct_d_site_policy_matches_presentation_set():
    selectors = {
        (14, 11, "CFG_OMUX4", selection): (81000 + selection, 1)
        for selection in (0, 1)
    }
    state = CORE_LOGIC_FEATURE.prepare(
        _direct_module("X14Y11_SLICE4"), selectors,
        options_from({"AGAMEMNON_DIRECT_D": "1"}), CONSTANTS,
    )
    assert state.slices == [(14, 11, 4)]
    assert len(state.register_sets) == 2

    with pytest.raises(SystemExit, match="outside _direct_d_sites"):
        CORE_LOGIC_FEATURE.prepare(
            _direct_module("X14Y8_SLICE0"), {},
            options_from({"AGAMEMNON_DIRECT_D": "1"}), CONSTANTS,
        )


@pytest.mark.parametrize("count", [1, 2, 3])
def test_strict_register_input_accepts_distinct_native_direct_d_compositions(count):
    bels = ["X14Y11_SLICE%d" % z for z in range(4, 4 + count)]
    requirements = validate_module_register_inputs(_native_direct_module(bels))
    assert len(requirements) == count
    assert {item.mode for item in requirements.values()} == {"DIRECT_D_I3"}


@pytest.mark.parametrize("count", [1, 2, 3])
def test_strict_native_direct_d_allows_external_f_observation(count):
    bels = ["X14Y11_SLICE%d" % z for z in range(4, 4 + count)]
    module = _native_direct_module(bels)
    f_bits = []
    for index in range(count):
        cell = module["cells"]["state%d" % index]
        f_bit = 102 + 1000 * index
        cell["connections"]["F"] = [f_bit]
        module["netnames"]["state%d_f" % index] = {"bits": [f_bit]}
        f_bits.append(f_bit)
    module["cells"]["observer"] = {
        "type": "HARD_OBSERVER", "attributes": {},
        "port_directions": {"DIN": "input"}, "connections": {"DIN": f_bits},
    }
    requirements = validate_module_register_inputs(module)
    assert sum(item.mode == "DIRECT_D_I3" for item in requirements.values()) == count


@pytest.mark.parametrize("observer_kind", [
    "ordinary", "hard", "hard_missing_direction", "hard_wrong_direction",
])
def test_strict_native_direct_d_rejects_external_registered_q_consumer(
        observer_kind):
    module = _native_direct_module(["X14Y11_SLICE4"])
    if observer_kind.startswith("hard"):
        directions = {"DIN": "input"}
        if observer_kind == "hard_missing_direction":
            directions = {}
        elif observer_kind == "hard_wrong_direction":
            directions = {"DIN": "output"}
        module["cells"]["observer"] = {
            "type": "HARD_OBSERVER", "attributes": {},
            "port_directions": directions, "connections": {"DIN": [100]},
        }
    else:
        observer, _ = _cell("NONE", 5000, ff_used=0, init=0xAAAA, inputs=(0,))
        observer["connections"]["I"][0] = 100
        module["cells"]["observer"] = observer
    with pytest.raises(SystemExit, match="registered Q to be local-only"):
        validate_module_register_inputs(module)


@pytest.mark.parametrize("direction", ["input", "output", "inout", None])
def test_strict_native_direct_d_rejects_registered_q_top_port(direction):
    module = _native_direct_module(["X14Y11_SLICE4"])
    module["ports"]["observed_q"] = {"bits": [100]}
    if direction is not None:
        module["ports"]["observed_q"]["direction"] = direction
    with pytest.raises(SystemExit, match="registered Q to be local-only"):
        validate_module_register_inputs(module)

    module["ports"]["observed_q"]["bits"] = [102]
    module["cells"]["state0"]["connections"]["F"] = [102]
    module["netnames"]["state0_f"] = {"bits": [102]}
    validate_module_register_inputs(module)


def test_strict_emitter_accepts_native_direct_d_composition_with_legacy_parity():
    selectors = {
        (14, 11, "CFG_OMUX%d" % z, selection): (83000 + z * 10 + selection, 1)
        for z in (4, 5) for selection in (0, 1)
    }
    state = CORE_LOGIC_FEATURE.prepare(
        _native_direct_module(["X14Y11_SLICE4", "X14Y11_SLICE5"]),
        selectors, options_from({"AGAMEMNON_DIRECT_D": "1"}), CONSTANTS,
    )
    assert state.slices == [(14, 11, 4), (14, 11, 5)]
    assert len(state.register_sets) == 4


@pytest.mark.parametrize("bels, declared, reason", [
    (["X14Y11_SLICE4", "X14Y11_SLICE4"], 2, "duplicates site"),
    (["X14Y11_SLICE4", "X14Y8_SLICE0"], 2, "outside X14Y11"),
    (["X14Y11_SLICE4", "X14Y11_SLICE5"], 3, "declares 3"),
    (["X14Y11_SLICE4", "X14Y11_SLICE5", "X14Y11_SLICE6", "X14Y11_SLICE7"],
     3, "only exact 1..3"),
])
def test_strict_register_input_rejects_bad_native_direct_d_compositions(
        bels, declared, reason):
    with pytest.raises(SystemExit, match=reason):
        validate_module_register_inputs(_native_direct_module(bels, declared=declared))


def test_direct_d_attribute_and_legacy_tag_precedence_fails_closed():
    explicit = _direct_module("X14Y11_SLICE4", explicit=True, tag=False)
    requirement = validate_module_register_inputs(explicit)["state"]
    assert requirement.mode == "DIRECT_D_I3"
    assert not requirement.legacy_derived

    tagged = _direct_module("X14Y11_SLICE4", explicit=False, tag=True)
    requirement = validate_module_register_inputs(tagged)["state"]
    assert requirement.mode == "DIRECT_D_I3"
    assert requirement.legacy_derived

    stale = _direct_module("X14Y11_SLICE4", explicit=True, tag=True)
    stale["cells"]["state"]["attributes"][
        "AGRV2K_REGISTER_INPUT_MODE"
    ] = "LUT_COMPUTE_TO_FF"
    with pytest.raises(SystemExit, match="cannot inherit I3, direct-D, or carry support"):
        validate_module_register_inputs(stale)


def test_vendor_presentation_cannot_upgrade_legacy_compute_to_direct_d():
    module = _direct_module("X14Y8_SLICE0", explicit=False, tag=False)
    requirement = validate_module_register_inputs(module)["state"]
    assert requirement.mode == "LUT_COMPUTE_TO_FF"
    assert requirement.legacy_derived
    selectors = {
        (14, 8, "CFG_OMUX0", selection): (82000 + selection, 1)
        for selection in (0, 1)
    }
    state = CORE_LOGIC_FEATURE.prepare(
        module, selectors,
        options_from({"AGAMEMNON_VENDOR_OUT_SLICE": "14,8,0"}), CONSTANTS,
    )
    assert state.slices == [(14, 8, 0)]


def test_all_retained_x14y9_own_q_i3_cells_remain_legacy_compute():
    expected = {
        "qualification/pad_pair_pin16_pin13_routed.json",
        "qualification/pad_pair_pin16_pin14_routed.json",
        "qualification/pad_pair_pin18_pin17_routed.json",
        "qualification/pad_pair_pin16_pin19_routed.json",
        "qualification/pad_pair_pin16_pin12_routed.json",
        "qualification/pad_pair_pin10_pin11_routed.json",
        "qualification/pad_uarch_pin10_only_routed.json",
        "qualification/pad_uarch_pin11_only_routed.json",
        "qualification/pad_uarch_pin12_only_routed.json",
        "qualification/pad_uarch_pin13_only_routed.json",
        "qualification/pad_uarch_pin14_only_routed.json",
        "qualification/pad_uarch_pin17_only_routed.json",
        "qualification/pad_uarch_pin19_only_routed.json",
    }
    manifest = json.loads(
        (ROOT / "qualification" / "pack_regression.json").read_text(encoding="utf-8")
    )
    rows = {row["routed"]: row for row in manifest["artifacts"]}
    assert expected <= set(rows)
    witnessed = set()
    for relative in expected:
        assert "AGAMEMNON_DIRECT_D" not in rows[relative]["environment"]
        design = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        module = next(iter(design["modules"].values()))
        requirements = validate_module_register_inputs(module)
        for name, cell in module["cells"].items():
            bel = cell.get("attributes", {}).get("NEXTPNR_BEL", "")
            inputs = cell.get("connections", {}).get("I", [])
            q = cell.get("connections", {}).get("Q", [])
            if bel.startswith("X14Y9_SLICE") and len(inputs) == 4 and q and inputs[3] == q[0]:
                assert requirements[name].mode == "LUT_COMPUTE_TO_FF"
                assert requirements[name].legacy_derived
                witnessed.add(relative)
    assert witnessed == expected


def test_cpp_uses_one_validator_for_placement_cluster_and_preroute_drc():
    source = UARCH.read_text(encoding="utf-8")
    assert source.count("register_input_requirement(ctx, member.first)") == 1
    assert source.count("register_input_bel_valid(ctx, cell, cell->bel, true)") == 1
    assert source.count("register_input_bel_valid(ctx, ci, bel, explain_invalid)") == 1
    assert source.count("fixed_endpoint_pins_reachable(cell, cell->bel, true)") == 1
    assert source.count("dedicated_carry_pins_reachable(cell, cell->bel, true)") == 1
    assert source.index("register_input_bel_valid(ctx, cell, cell->bel, true)") < source.index(
        "Running router2"
    ) if "Running router2" in source else True
    # Capability comes from the actual GENERIC_SLICE resource and pin wires;
    # there is no status-overlay or two-site allowlist in the validator.
    validator = source[source.index("static bool register_input_bel_valid"):source.index(
        "static void make_relative_cluster"
    )]
    assert 'getBelType(bel) != ctx->id("GENERIC_SLICE")' in validator
    assert "getBelPinWire" in validator
    assert "X8Y2" not in validator


def test_native_direct_d_region_is_coarse_exact_and_cannot_overwrite_constraints():
    source = UARCH.read_text(encoding="utf-8")
    validator = source[source.index("static void validate_native_direct_d_pool"):
                       source.index("static void pack_direct_d_bels")]
    assert 'ctx->createRectangularRegion(region, 14, 11, 14, 11)' in validator
    assert 'ctx->region.count(region)' in validator
    assert 'cell->cluster != ClusterId() || cell->region != nullptr' in validator
    assert 'ctx->constrainCellToRegion(cell->name, region)' in validator
    # z membership is not encoded by the coarse Region; it remains a hard
    # per-BEL predicate shared by placement and pre-route DRC.
    assert 'loc.z >= 4 && loc.z <= 7' in source[source.index(
        "static bool native_direct_d_pool_site"):source.index(
        "static int native_direct_d_pool_count")]


def test_qualified_x8y2_status_overlay_is_two_exact_legacy_i0_feedthroughs():
    path = ROOT / "qualification" / "mcu_ahb_status_overlay_pulse_checkpoint.json"
    design = json.loads(path.read_text(encoding="utf-8"))
    module = next(iter(design["modules"].values()))
    requirements = validate_module_register_inputs(module)
    by_bel = {
        cell.get("attributes", {}).get("NEXTPNR_BEL"): name
        for name, cell in module["cells"].items()
    }
    assert set(by_bel) >= {"X8Y2_SLICE0", "X8Y2_SLICE4"}
    for bel in ("X8Y2_SLICE0", "X8Y2_SLICE4"):
        name = by_bel[bel]
        cell = module["cells"][name]
        assert requirements[name].mode == "LUT_FEEDTHROUGH_I0"
        assert requirements[name].legacy_derived
        assert int(cell["parameters"]["FF_USED"], 2) == 1
        assert int(cell["parameters"]["INIT"], 2) == 0xAAAA
        assert cell["connections"]["F"] == []


def test_retained_serial_mux_serv_and_public_artifacts_remain_exact_inputs():
    manifest_path = ROOT / "qualification" / "pack_regression.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selected = {
        "qualification/serial_mux_L48_routed.json",
        "qualification/serv_blinky_L48_routed.json",
        "qualification/serv_rv32i_smoke_L48_routed.json",
        "qualification/mcu_ahb_public32_exact_map_routed.json",
    }
    rows = {row["routed"]: row for row in manifest["artifacts"]}
    assert selected <= set(rows)
    for relative in selected:
        path = ROOT / relative
        canonical = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert hashlib.sha256(canonical).hexdigest() == rows[relative]["routed_sha256"]
        design = json.loads(path.read_text(encoding="utf-8"))
        for module in design["modules"].values():
            validate_module_register_inputs(module)
