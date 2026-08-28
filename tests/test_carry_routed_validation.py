"""Pure-Python closure tests for the bounded N5.6A carry validator."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from agamemnon.engine import bitgen
from agamemnon.engine.features.carry import FEATURE as CARRY_FEATURE
from agamemnon.engine.features.carry_validate import (
    CarryValidationError,
    CarryValidationResult,
    validate_routed_carry,
)
from agamemnon.engine.registry import options_from


def _binary(value, width=32):
    return format(value, "0%db" % width)


def _carry_route(before, after):
    src = "X%dY%d_CARRYOUT%02d" % before
    dst = "X%dY%d_CARRYIN%02d" % after
    return "%s;%s.%s;1;%s;;1" % (dst, src, dst, src)


def _qfb_route(site):
    x, y, z = site
    root = "X%dY%d_OMUX%02d" % (x, y, 3 * z + 2)
    feedback = "X%dY%d_OMUX%02d" % (x, y, 3 * z + 1)
    sink = "X%dY%d_IMUX%02d" % (x, y, 4 * z + 1)
    return "%s;;1;%s;%s.%s;1;%s;%s.%s;1" % (
        root, feedback, root, feedback, sink, feedback, sink,
    )


def _legacy_sites(count, profile):
    if profile == 25:
        result = ([(20, 12, z) for z in range(16)] +
                  [(20, 11, z) for z in range(9)])
    else:
        result = ([(20, 11, z) for z in range(16)] +
                  [(20, 12, z) for z in range(16)] +
                  [(20, 10, 0)])
    return result[:count]


def _module(chain_sites, *, feedback=False, registered=False, prefix="carry"):
    """Build one or more packed chains without semantic cell-name tokens."""

    if chain_sites and isinstance(chain_sites[0], tuple):
        chain_sites = [chain_sites]
    cells = {
        "unrelated_constant_driver": {
            "type": "GENERIC_SLICE",
            "parameters": {
                "K": _binary(4), "FF_USED": _binary(0),
                "INIT": _binary(0xFFFF, 16),
            },
            "attributes": {"NEXTPNR_BEL": "X1Y1_SLICE0"},
            "port_directions": {"F": "output", "I": "input"},
            "connections": {"F": [900], "I": ["0", "0", "0", "0"]},
        },
    }
    netnames = {"ordinary_d_source": {"bits": [900]}}
    next_bit = 1000
    for chain_index, sites in enumerate(chain_sites):
        carry_bits = list(range(next_bit, next_bit + len(sites)))
        next_bit += len(sites) + 100
        seed_name = "%s_%d_alpha" % (prefix, chain_index)
        sx, sy, sz = sites[0]
        cells[seed_name] = {
            "type": "GENERIC_SLICE",
            "parameters": {
                "K": _binary(4), "FF_USED": _binary(0),
                "INIT": _binary(0, 16),
            },
            "attributes": {
                "NEXTPNR_BEL": "X%dY%d_SLICE%d" % (sx, sy, sz),
                "AGRV2K_REGISTER_INPUT_MODE": "NONE",
            },
            "port_directions": {
                "COUT": "output", "Q": "output", "F": "output",
                "CLK": "input", "I": "input",
            },
            "connections": {
                "COUT": [carry_bits[0]], "Q": [], "F": [], "CLK": [],
                "I": ["0", "0", "0", "0"],
            },
        }
        for index, site in enumerate(sites[1:], 1):
            x, y, z = site
            name = "%s_%d_member_%d" % (prefix, chain_index, index)
            q_bit = next_bit
            f_bit = next_bit + 1
            clk_bit = next_bit + 2
            next_bit += 3
            own_feedback = feedback
            inputs = [next_bit, q_bit if own_feedback else next_bit + 1,
                      "0", 900]
            next_bit += 2
            cells[name] = {
                "type": "GENERIC_SLICE",
                "parameters": {
                    "K": _binary(4),
                    "FF_USED": _binary(1 if registered else 0),
                    "INIT": _binary(0x96E8, 16),
                },
                "attributes": {
                    "NEXTPNR_BEL": "X%dY%d_SLICE%d" % (x, y, z),
                    "AGRV2K_REGISTER_INPUT_MODE": (
                        "CARRY_SUM_TO_FF" if registered else "NONE"
                    ),
                },
                "port_directions": {
                    "COUT": "output", "CIN": "input", "Q": "output",
                    "F": "output", "CLK": "input", "I": "input",
                },
                "connections": {
                    "COUT": [carry_bits[index]],
                    "CIN": [carry_bits[index - 1]],
                    "Q": [q_bit] if registered else [],
                    "F": [] if registered else [f_bit],
                    "CLK": [clk_bit] if registered else [],
                    "I": inputs,
                },
            }
            if feedback:
                netnames["feedback_%d_%d" % (chain_index, index)] = {
                    "bits": [q_bit],
                    "attributes": {"ROUTING": _qfb_route(site)},
                }
        for index, (before, after) in enumerate(zip(sites, sites[1:])):
            netnames["link_%d_%d" % (chain_index, index)] = {
                "bits": [carry_bits[index]],
                "attributes": {"ROUTING": _carry_route(before, after)},
            }
        netnames["tail_%d" % chain_index] = {"bits": [carry_bits[-1]]}
    return {"cells": cells, "netnames": netnames, "ports": {}}


def _short(start_z=4, members=3, x=7, y=8):
    return [(x, y, z) for z in range(start_z, start_z + members + 1)]


def test_accepts_renamed_translated_short_chain_and_reports_roles():
    module = _module(_short(), prefix="names_have_no_authority")
    result = validate_routed_carry(module)
    assert len(result.chains) == 1
    chain = result.chains[0]
    assert chain.profile == "short-same-tile"
    assert [(site.x, site.y, site.z) for site in chain.sites] == _short()
    assert chain.roles == ("SEED", "FIRST", "INTERIOR", "TAIL")
    assert chain.capture_cells == ()
    assert chain.q_feedback_cells == ()
    assert len(result.protected_edges) == 3


def test_accepts_independent_disjoint_short_chains_with_one_shared_d_source():
    module = _module([_short(0, 2, 2, 3), _short(8, 2, 9, 10)])
    result = validate_routed_carry(module)
    assert sorted(len(chain.sites) for chain in result.chains) == [3, 3]
    assert {chain.profile for chain in result.chains} == {"short-same-tile"}


@pytest.mark.parametrize("profile,count", [(25, 25), (33, 33)])
def test_accepts_exact_retained_legacy_profile_prefix(profile, count):
    result = validate_routed_carry(_module(_legacy_sites(count, profile)))
    assert len(result.chains[0].sites) == count
    assert result.chains[0].profile == "legacy-%d" % profile


@pytest.mark.parametrize("sites,profile", [
    ([(10, 4, 14), (10, 4, 15), (10, 3, 0)],
     "retained-seam-x10y4-down"),
    ([(15, 2, 14), (15, 2, 15), (15, 1, 0)],
     "retained-seam-x15y2-down"),
])
def test_accepts_only_exact_release_strict_legacy_seam_footprints(sites, profile):
    result = validate_routed_carry(_module(sites))
    assert result.chains[0].profile == profile

    neighboring = [(x + 1, y, z) for x, y, z in sites]
    with pytest.raises(CarryValidationError, match="crosses a tile"):
        validate_routed_carry(_module(neighboring))


@pytest.mark.parametrize(
    "mutation, reason",
    [
        (lambda sites: sites.__setitem__(2, (7, 9, 6)), "crosses a tile"),
        (lambda sites: sites.__setitem__(2, (7, 8, 8)), "not consecutive"),
        (lambda sites: sites.__setitem__(2, (7, 8, 4)), "duplicate site"),
    ],
)
def test_rejects_short_tile_gap_and_duplicate_placement(mutation, reason):
    sites = _short()
    mutation(sites)
    with pytest.raises(CarryValidationError, match=reason):
        validate_routed_carry(_module(sites))


def test_rejects_mutated_retained_profile_and_multiple_legacy_chains():
    sites = _legacy_sites(25, 25)
    sites[16] = (20, 13, 0)
    with pytest.raises(CarryValidationError, match="exact retained legacy-25"):
        validate_routed_carry(_module(sites))

    two = [_short(0, 5, 2, 3), _short(0, 5, 9, 10)]
    with pytest.raises(CarryValidationError, match="requires one retained legacy"):
        validate_routed_carry(_module(two))


def test_rejects_missing_seed_inserted_logic_branch_and_interior_fanout():
    base = _module(_short(0, 3))
    seed = next(name for name in base["cells"] if name.endswith("alpha"))
    missing = deepcopy(base)
    del missing["cells"][seed]
    with pytest.raises(CarryValidationError, match="lacks one direct carry COUT driver"):
        validate_routed_carry(missing)

    inserted = deepcopy(base)
    first = next(cell for cell in inserted["cells"].values()
                 if "CIN" in cell.get("connections", {}))
    first["connections"]["CIN"] = [900]
    with pytest.raises(CarryValidationError, match="lacks one direct carry COUT driver"):
        validate_routed_carry(inserted)

    branched = deepcopy(base)
    members = [(name, cell) for name, cell in branched["cells"].items()
               if "CIN" in cell.get("connections", {})]
    clone = deepcopy(members[-1][1])
    clone["attributes"]["NEXTPNR_BEL"] = "X7Y8_SLICE10"
    clone["connections"]["CIN"] = members[0][1]["connections"]["CIN"]
    clone["connections"]["COUT"] = [9999]
    branched["cells"]["unrelated_clone"] = clone
    with pytest.raises(CarryValidationError, match="branches to multiple CIN"):
        validate_routed_carry(branched)

    fanout = deepcopy(base)
    first_cout = members[0][1]["connections"]["COUT"][0]
    fanout["cells"]["ordinary_observer"] = {
        "type": "GENERIC_SLICE", "attributes": {},
        "port_directions": {"I": "input"},
        "connections": {"I": [first_cout, "0", "0", "0"]},
    }
    with pytest.raises(CarryValidationError, match="ordinary fanout"):
        validate_routed_carry(fanout)


def test_rejects_missing_extra_and_wrong_internal_routes():
    module = _module(_short())
    first_link = module["netnames"]["link_0_0"]
    del first_link["attributes"]["ROUTING"]
    with pytest.raises(CarryValidationError, match="has no ROUTING"):
        validate_routed_carry(module)

    module = _module(_short())
    first_link = module["netnames"]["link_0_0"]
    first_link["attributes"]["ROUTING"] += ";X7Y8_RMUX01;X7Y8_RMUX00.X7Y8_RMUX01;1"
    with pytest.raises(CarryValidationError, match="exact one-edge route"):
        validate_routed_carry(module)

    module = _module(_short())
    route = module["netnames"]["link_0_0"]["attributes"]["ROUTING"]
    module["netnames"]["link_0_0"]["attributes"]["ROUTING"] = route.replace(
        "CARRYIN05", "CARRYIN15"
    )
    with pytest.raises(CarryValidationError, match="exact one-edge route"):
        validate_routed_carry(module)


def test_registered_own_q_requires_exact_bridge_and_typed_slice_qfb():
    module = _module(_short(4, 2), feedback=True, registered=True)
    result = validate_routed_carry(module)
    assert len(result.chains[0].capture_cells) == 2
    assert len(result.chains[0].q_feedback_cells) == 2
    assert len(result.protected_edges) == 4

    missing = deepcopy(module)
    qnet = missing["netnames"]["feedback_0_1"]
    qnet["attributes"]["ROUTING"] = qnet["attributes"]["ROUTING"].rsplit(";", 3)[0]
    with pytest.raises(CarryValidationError, match="root/bridge/SLICE_QFB"):
        validate_routed_carry(missing)


def test_registered_without_own_q_does_not_claim_qfb():
    result = validate_routed_carry(
        _module(_short(4, 2), feedback=False, registered=True)
    )
    assert result.chains[0].q_feedback_cells == ()


def test_ordinary_slice_may_own_its_exact_local_qfb_resource():
    site = (2, 2, 3)
    module = {
        "cells": {
            "ordinary_registered_feedback": {
                "type": "GENERIC_SLICE",
                "parameters": {"FF_USED": _binary(1)},
                "attributes": {"NEXTPNR_BEL": "X2Y2_SLICE3"},
                "port_directions": {"Q": "output", "I": "input"},
                "connections": {"Q": [42], "I": [50, 42, 51, 52]},
            },
        },
        "netnames": {
            "ordinary_feedback": {
                "bits": [42], "attributes": {"ROUTING": _qfb_route(site)},
            },
        },
        "ports": {},
    }
    result = validate_routed_carry(module)
    assert result.chains == ()
    assert len(result.protected_edges) == 1

    multiple_driver = deepcopy(module)
    multiple_driver["cells"]["foreign_q_driver"] = {
        "type": "GENERIC_SLICE",
        "port_directions": {"Q": "output"},
        "connections": {"Q": [42]},
    }
    with pytest.raises(CarryValidationError, match="one exact Q driver"):
        validate_routed_carry(multiple_driver)


def test_legacy_carry_profile_may_retain_an_ordinary_q_feedback_detour():
    module = _module(_legacy_sites(25, 25), feedback=True, registered=True)
    qnet = module["netnames"]["feedback_0_1"]
    qnet["attributes"]["ROUTING"] = (
        "X20Y12_RMUX01;X20Y12_OMUX05.X20Y12_RMUX01;1;"
        "X20Y12_OMUX05;;1"
    )
    assert validate_routed_carry(module).chains[0].profile == "legacy-25"


def test_dynamic_seed_requires_exact_live_i0_and_external_driver():
    module = _module(_short(4, 2))
    seed_name = next(name for name, cell in module["cells"].items()
                     if "COUT" in cell.get("connections", {}) and
                     "CIN" not in cell.get("connections", {}))
    seed = module["cells"][seed_name]
    seed["parameters"]["INIT"] = _binary(0x00AA, 16)
    seed["connections"]["I"][0] = 777
    module["ports"]["carry_in"] = {"direction": "input", "bits": [777]}
    assert validate_routed_carry(module).chains

    malformed = deepcopy(module)
    malformed["cells"][seed_name]["connections"]["I"][1] = 778
    malformed["ports"]["wrong_extra"] = {"direction": "input", "bits": [778]}
    with pytest.raises(CarryValidationError, match=r"folded/dynamic I\[0\] role"):
        validate_routed_carry(malformed)


def test_rejects_foreign_carry_and_slice_qfb_resource_use():
    module = _module(_short())
    module["netnames"]["foreign_carry"] = {
        "bits": [900],
        "attributes": {
            "ROUTING": (
                "X2Y2_CARRYIN01;X2Y2_CARRYOUT00.X2Y2_CARRYIN01;1;"
                "X2Y2_CARRYOUT00;;1"
            ),
        },
    }
    with pytest.raises(CarryValidationError, match="foreign use of carry PIP"):
        validate_routed_carry(module)

    module = _module(_short())
    module["netnames"]["foreign_qfb"] = {
        "bits": [900], "attributes": {"ROUTING": _qfb_route((2, 2, 3))},
    }
    with pytest.raises(CarryValidationError, match="foreign use of SLICE_QFB"):
        validate_routed_carry(module)


def test_rejects_foreign_bel_occupancy_and_bad_d_source():
    module = _module(_short())
    module["cells"]["foreign_occupant"] = {
        "type": "GENERIC_SLICE",
        "attributes": {"BEL": "X7Y8_SLICE5"},
        "connections": {}, "port_directions": {},
    }
    with pytest.raises(CarryValidationError, match="foreign cell.*occupies"):
        validate_routed_carry(module)

    module = _module(_short())
    module["cells"]["unrelated_constant_driver"]["type"] = "FAKE_CONST"
    with pytest.raises(CarryValidationError, match="ordinary GENERIC_SLICE.F"):
        validate_routed_carry(module)


def test_noncarry_module_is_a_dependency_free_noop():
    result = validate_routed_carry({
        "cells": {"ordinary": {"type": "GENERIC_SLICE", "connections": {}}},
        "netnames": {}, "ports": {},
    })
    assert result.chains == ()
    assert result.protected_edges == frozenset()


def test_exact_legacy_partial_tff_reaches_only_the_existing_emission_refusal():
    fixture = Path(__file__).parent / "fixtures" / "tff_routed.json"
    module = json.loads(fixture.read_text(encoding="utf-8"))["modules"]["top"]
    assert validate_routed_carry(module) == CarryValidationResult((), frozenset())

    changed = deepcopy(module)
    next(iter(changed["cells"].values()))["attributes"]["forged"] = "1"
    with pytest.raises(CarryValidationError, match="foreign use of SLICE_QFB"):
        validate_routed_carry(changed)


def test_cli_checkpoint_boundary_uses_the_same_independent_carry_validator():
    from agamemnon import cli

    document = {"modules": {"top": _module(_short())}}
    assert cli._validate_carry_document(
        document, "post-nextpnr"
    ).chains

    malformed = deepcopy(document)
    malformed["modules"]["top"]["netnames"]["link_0_0"][
        "attributes"].pop("ROUTING")
    with pytest.raises(CarryValidationError, match="has no ROUTING"):
        cli._validate_carry_document(malformed, "pre-emission")


@pytest.mark.parametrize("route, reason", [
    (
        "X2Y2_CARRYIN01;X2Y2_CARRYOUT00.X2Y2_CARRYIN01;1;"
        "X2Y2_CARRYOUT00;;1",
        "foreign use of carry PIP",
    ),
    (_qfb_route((2, 2, 3)), "foreign use of SLICE_QFB"),
])
def test_noncarry_module_cannot_bypass_protected_resource_scan(route, reason):
    module = {
        "cells": {"ordinary": {"type": "GENERIC_SLICE", "connections": {}}},
        "netnames": {"ordinary": {
            "bits": [42], "attributes": {"ROUTING": route},
        }},
        "ports": {},
    }
    with pytest.raises(CarryValidationError, match=reason):
        validate_routed_carry(module)


_MALFORMED_PROTECTED_ROUTE_BITS = (
    pytest.param(["0"], id="literal-zero"),
    pytest.param(["1"], id="literal-one"),
    pytest.param(["x"], id="literal-unknown"),
    pytest.param([], id="empty"),
    pytest.param([42, "0"], id="mixed-integer-and-literal"),
    pytest.param([42, 43], id="multiple-integers"),
    pytest.param("42", id="non-list"),
    pytest.param([True], id="boolean"),
)


def _malformed_protected_alias_module(bits):
    return {
        "cells": {},
        "ports": {},
        "netnames": {
            "forged_protected_alias": {
                "bits": deepcopy(bits),
                "attributes": {
                    "ROUTING": (
                        "X1Y1_OMUX01;;5;X1Y1_IMUX01;"
                        "X1Y1_OMUX01.X1Y1_IMUX01;5"
                    ),
                },
            },
        },
    }


@pytest.mark.parametrize("bits", _MALFORMED_PROTECTED_ROUTE_BITS)
def test_protected_routes_reject_non_scalar_integer_aliases_at_every_boundary(bits):
    module = _malformed_protected_alias_module(bits)
    expected = "ROUTING alias must contain exactly one integer signal bit"

    with pytest.raises(CarryValidationError, match=expected):
        validate_routed_carry(module)

    # CarryFeature is the first emission planner and translates the independent
    # validator's refusal into the process boundary consumed by bitgen.
    before = deepcopy(module)
    with pytest.raises(SystemExit, match=expected):
        CARRY_FEATURE.prepare(module, {})
    assert module == before

    # Exercise the full public bitgen planning boundary.  This is the exact
    # layer that accepted the original literal-["0"] reproducer and produced
    # routing selector sets at the rejected parent commit.
    document = {"modules": {"top": module}}
    with pytest.raises(SystemExit, match=expected):
        bitgen.prepare_design(
            "unused-routed.json", options_from({}), document=document
        )
    assert document["modules"]["top"] == before


@pytest.mark.parametrize("route", (
    "X1Y1_CARRYOUT00;;5",
    (
        "X1Y1_CARRYIN01;X1Y1_CARRYOUT00.X1Y1_CARRYIN01;5;"
        "X1Y1_CARRYOUT00;;5"
    ),
))
def test_literal_alias_cannot_claim_protected_carry_roots_or_edges(route):
    module = _malformed_protected_alias_module(["0"])
    module["netnames"]["forged_protected_alias"]["attributes"]["ROUTING"] = route
    with pytest.raises(CarryValidationError, match="exactly one integer signal bit"):
        validate_routed_carry(module)


def test_literal_alias_with_ordinary_route_remains_outside_carry_ownership():
    module = _malformed_protected_alias_module(["0"])
    module["netnames"]["forged_protected_alias"]["attributes"]["ROUTING"] = (
        "X1Y1_OMUX00;;5;X1Y1_IMUX00;X1Y1_OMUX00.X1Y1_IMUX00;5"
    )
    assert validate_routed_carry(module) == CarryValidationResult((), frozenset())
