"""Pure-Python closure tests for the bounded N5.6A carry validator."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from agamemnon.engine import bitgen
from agamemnon.engine import special_routes as sr
from agamemnon.engine.features.carry import FEATURE as CARRY_FEATURE
from agamemnon.engine.features.carry_validate import (
    CarryValidationError,
    CarryValidationResult,
    validate_routed_carry,
)
from agamemnon.engine.registry import options_from
from devdb_fixtures import devdb_path


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
PHYSICAL_DEVDB = devdb_path("strict_pcf")
TIERED_DEVDB = devdb_path("tiered")
PHYSICAL_ENV = {
    "AGAMEMNON_DEVICE": sr.DEVICE,
    "AGAMEMNON_PHYSICAL_IO": "1",
    "AGAMEMNON_LEFT_PAD_OUT": "1",
    sr.DEVDB_ENV: str(PHYSICAL_DEVDB),
}


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


def test_terminal_cout_requires_fabric_export():
    module = _module([(15, 1, z) for z in range(5)])
    terminal = module["cells"]["carry_0_member_4"]
    module["cells"]["ordinary_observer"] = {
        "type": "LUT", "port_directions": {"I": "input"},
        "connections": {"I": terminal["connections"]["COUT"]},
    }
    with pytest.raises(CarryValidationError, match="CIN-to-F export slice is required"):
        validate_routed_carry(module)
    # The same consumer on F is an ordinary fabric value, not a carry tap.
    module["cells"]["ordinary_observer"]["connections"]["I"] = terminal["connections"]["F"]
    validate_routed_carry(module)


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


def _integer_bits(module):
    bits = set()
    for cell in (module.get("cells") or {}).values():
        for value in (cell.get("connections") or {}).values():
            bits.update(bit for bit in value
                        if isinstance(bit, int) and not isinstance(bit, bool))
    for net in (module.get("netnames") or {}).values():
        bits.update(bit for bit in (net.get("bits") or [])
                    if isinstance(bit, int) and not isinstance(bit, bool))
    for port in (module.get("ports") or {}).values():
        bits.update(bit for bit in (port.get("bits") or [])
                    if isinstance(bit, int) and not isinstance(bit, bool))
    return bits


def _remap_module_bits(module, first_bit):
    mapping = {
        bit: first_bit + index
        for index, bit in enumerate(sorted(_integer_bits(module)))
    }

    def remap(values):
        return [mapping.get(bit, bit) for bit in values]

    for cell in (module.get("cells") or {}).values():
        for port, values in (cell.get("connections") or {}).items():
            cell["connections"][port] = remap(values)
    for net in (module.get("netnames") or {}).values():
        net["bits"] = remap(net.get("bits") or [])
    for port in (module.get("ports") or {}).values():
        port["bits"] = remap(port.get("bits") or [])


def _mixed_n55_n56_document():
    """Return one imported checkpoint with both independently owned resources."""

    catalog = sr.load_catalog(CHIPDB)
    cells = {}
    netnames = {}
    for lane in catalog.lanes:
        bit = 100 + lane.index
        cells["n55_driver_%d" % lane.index] = {
            "type": "GENERIC_SLICE",
            "attributes": {
                "NEXTPNR_BEL": lane.source_bel,
                sr.TOKEN_CLASS: sr.CLASS,
                sr.TOKEN_VERSION: sr.ROUTED_VERSION,
                sr.TOKEN_LANE: str(lane.index),
                sr.TOKEN_DIGEST: catalog.digest,
            },
            "port_directions": {"Q": "output", "F": "output", "I": "input"},
            "connections": {lane.source_port: [bit]},
        }
        cells["n55_sink_%d" % lane.index] = {
            "type": "GENERIC_IOB",
            "attributes": {"NEXTPNR_BEL": lane.sink_bel},
            "port_directions": {"I": "input", "PAD": "inout"},
            "connections": {"I": [bit], "PAD": []},
        }
        triples = [lane.edges[0].src, "", "1"]
        for edge in lane.edges:
            triples.extend((edge.dst, edge.src + "." + edge.dst, "5"))
        netnames["n55_lane_%d" % lane.index] = {
            "bits": [bit], "attributes": {"ROUTING": ";".join(triples)},
        }
    document = {"modules": {"top": {
        "attributes": {
            "top": 1,
            sr.MODULE_SCHEMA: sr.SCHEMA,
            sr.TOKEN_CLASS: sr.CLASS,
            sr.TOKEN_VERSION: sr.ROUTED_VERSION,
            sr.MODULE_DEVICE: sr.DEVICE,
            sr.MODULE_PACKAGE: sr.PACKAGE,
            sr.MODULE_PROFILE: sr.PROFILE,
            sr.MODULE_ENABLED: "1",
            sr.TOKEN_DIGEST: catalog.digest,
        },
        "cells": cells,
        "netnames": netnames,
        "ports": {},
    }}}
    module = document["modules"]["top"]

    # Use a graph-backed same-tile footprint even for the independent
    # Python composition fixture; X1Y1 carries exact typed CARRY hops.
    carry = _module(_short(x=1, y=1), prefix="mixed_carry")
    for name, net in carry["netnames"].items():
        if not name.startswith("link_"):
            continue
        parts = net["attributes"]["ROUTING"].split(";")
        assert len(parts) == 6 and parts[1] and not parts[4]
        # The independent validator is order-neutral, but nextpnr's imported
        # checkpoint frontend consumes roots before their downhill PIPs.
        net["attributes"]["ROUTING"] = ";".join(parts[3:6] + parts[0:3])
    carry_members = sorted(
        (cell for cell in carry["cells"].values()
         if "COUT" in (cell.get("connections") or {})),
        key=lambda cell: int(cell["attributes"]["NEXTPNR_BEL"].rsplit(
            "SLICE", 1)[1]),
    )
    roles = ("SEED", "FIRST", "INTERIOR", "TAIL")
    assert len(carry_members) == len(roles)
    for position, (cell, role) in enumerate(zip(carry_members, roles)):
        cell["attributes"].update({
            "AGRV2K_CARRY_SCHEMA": _binary(1),
            "AGRV2K_CARRY_PROFILE": "SHORT_LOCAL",
            "AGRV2K_CARRY_CHAIN": _binary(0),
            "AGRV2K_CARRY_POSITION": _binary(position),
            "AGRV2K_CARRY_LENGTH": _binary(len(carry_members)),
            "AGRV2K_CARRY_ROLE": role,
        })
    occupied = {
        (cell.get("attributes") or {}).get("NEXTPNR_BEL")
        for cell in module["cells"].values()
    }
    carry_bels = {
        (cell.get("attributes") or {}).get("NEXTPNR_BEL")
        for cell in carry["cells"].values()
    }
    assert occupied.isdisjoint(carry_bels)
    _remap_module_bits(carry, max(_integer_bits(module), default=1) + 100)

    module["cells"].update({
        "n56_" + name: cell for name, cell in carry["cells"].items()
    })
    module["netnames"].update({
        "n56_" + name: net for name, net in carry["netnames"].items()
    })
    return document


def _write_mixed(tmp_path, name, document):
    path = tmp_path / (name + ".json")
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _run_mixed_compiled(tmp_path, name, document, *extra):
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR for mixed N5.5/N5.6 checks")
    source = _write_mixed(tmp_path, name, document)
    output = tmp_path / (name + "_out.json")
    env = dict(os.environ)
    env.update(PHYSICAL_ENV)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [executable, "--uarch", "agrv2k", "-o",
         "chipdb=" + str(PHYSICAL_DEVDB), "--json", str(source),
         "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=30,
    )
    return result, result.stdout + result.stderr, source, output


def _raw_short_carry_document():
    cells = {}
    netnames = {}
    next_bit = 2
    carry = "0"
    for index in range(4):
        cout, summ = next_bit, next_bit + 1
        next_bit += 2
        name = "compiled_fa_%d" % index
        cells[name] = {
            "hide_name": 0,
            "type": "AG32_FA",
            "parameters": {},
            "attributes": ({"BEL": "X1Y1_SLICE5"} if index == 0 else {}),
            "port_directions": {
                "A": "input", "B": "input", "CIN": "input",
                "COUT": "output", "SUM": "output",
            },
            "connections": {
                "A": ["0"], "B": ["1"], "CIN": [carry],
                "COUT": [cout], "SUM": [summ],
            },
        }
        netnames["compiled_cout_%d" % index] = {
            "hide_name": 0, "bits": [cout], "attributes": {},
        }
        netnames["compiled_sum_%d" % index] = {
            "hide_name": 0, "bits": [summ], "attributes": {},
        }
        carry = cout
    return {"modules": {"top": {
        "attributes": {"top": 1}, "cells": cells,
        "netnames": netnames, "ports": {},
    }}}


def _placed_compiled_carry_module(tmp_path):
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR for mixed N5.5/N5.6 checks")
    if not (TIERED_DEVDB / "dev_pips.csv").is_file():
        pytest.skip("emit the tiered agrv2k devdb for mixed N5.5/N5.6 checks")
    source = _write_mixed(
        tmp_path, "compiled_carry_unpacked", _raw_short_carry_document())
    output = tmp_path / "compiled_carry_placed.json"
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [executable, "--uarch", "agrv2k", "-o",
         "chipdb=" + str(TIERED_DEVDB), "--json", str(source),
         "--write", str(output), "--no-route"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    module = next(iter(json.loads(output.read_text(
        encoding="utf-8"))["modules"].values()))
    for net in module["netnames"].values():
        (net.get("attributes") or {}).pop("ROUTING", None)

    members = sorted(
        (cell for cell in module["cells"].values()
         if "AGRV2K_CARRY_POSITION" in (cell.get("attributes") or {})),
        key=lambda cell: int(cell["attributes"]["AGRV2K_CARRY_POSITION"], 2),
    )
    assert len(members) == 5
    for before, after in zip(members, members[1:]):
        before_bel = before["attributes"]["NEXTPNR_BEL"]
        after_bel = after["attributes"]["NEXTPNR_BEL"]
        before_tile, before_z = before_bel.rsplit("_SLICE", 1)
        after_tile, after_z = after_bel.rsplit("_SLICE", 1)
        assert before_tile == after_tile
        assert int(after_z) == int(before_z) + 1
        source_wire = "%s_CARRYOUT%02d" % (before_tile, int(before_z))
        sink_wire = "%s_CARRYIN%02d" % (after_tile, int(after_z))
        bit = before["connections"]["COUT"][0]
        net = next(net for net in module["netnames"].values()
                   if bit in net.get("bits", ()))
        net.setdefault("attributes", {})["ROUTING"] = (
            "%s;;1;%s;%s.%s;1" %
            (source_wire, sink_wire, source_wire, sink_wire)
        )
    assert validate_routed_carry(module).chains
    return module


def _compiled_mixed_n55_n56_document(tmp_path):
    document = _mixed_n55_n56_document()
    module = next(iter(document["modules"].values()))
    module["cells"] = {
        name: cell for name, cell in module["cells"].items()
        if not name.startswith("n56_")
    }
    module["netnames"] = {
        name: net for name, net in module["netnames"].items()
        if not name.startswith("n56_")
    }
    carry = _placed_compiled_carry_module(tmp_path)
    _remap_module_bits(carry, max(_integer_bits(module), default=1) + 100)
    assert {
        (cell.get("attributes") or {}).get("NEXTPNR_BEL")
        for cell in module["cells"].values()
    }.isdisjoint({
        (cell.get("attributes") or {}).get("NEXTPNR_BEL")
        for cell in carry["cells"].values()
    })
    module["cells"].update({
        "compiled_n56_" + name: cell
        for name, cell in carry["cells"].items()
    })
    module["netnames"].update({
        "compiled_n56_" + name: net
        for name, net in carry["netnames"].items()
    })
    return document


def _special_lane_net(module, lane_index=0):
    lane = sr.load_catalog(CHIPDB).lanes[lane_index]
    driver = next(
        cell for cell in module["cells"].values()
        if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
    )
    bit = driver["connections"][lane.source_port][0]
    return next(net for net in module["netnames"].values()
                if bit in net.get("bits", ()))


def test_mixed_n55_n56_checkpoint_closes_both_independent_validators(tmp_path):
    document = _mixed_n55_n56_document()
    module = next(iter(document["modules"].values()))
    path = _write_mixed(tmp_path, "mixed_validators", document)

    raw_graph = (PHYSICAL_DEVDB / "dev_pips.csv").read_bytes()
    assert hashlib.sha256(raw_graph).hexdigest() == (
        # Five high-address logic additions; physical/carry ownership unchanged.
        "46bea5556598f30010ae30cbc172f81f4eda4f6d8d879c71ceef4c7589816f81"
    )
    assert raw_graph.count(b"\n") - 1 == 248310
    assert sr.validate_routed_json(
        path, "pre-emission", CHIPDB,
        environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
    )["active_lanes"] == (0, 1, 2, 3)
    carry = validate_routed_carry(module)
    assert len(carry.chains) == 1
    assert carry.chains[0].profile == "short-same-tile"
    assert len(carry.protected_edges) == 3


def test_mixed_n55_n56_complete_import_crosses_compiled_import_boundary(tmp_path):
    result, log, _source, output = _run_mixed_compiled(
        tmp_path, "mixed_complete", _compiled_mixed_n55_n56_document(tmp_path),
        "--no-pack", "--no-place", "--no-route",
    )
    assert result.returncode == 0, log
    assert output.is_file()
    assert "typed resource notification rejects" not in log


def test_physical_graph_imports_typed_short_carry_without_active_n55_lane(tmp_path):
    document = _compiled_mixed_n55_n56_document(tmp_path)
    module = next(iter(document["modules"].values()))
    module["cells"] = {
        name: cell for name, cell in module["cells"].items()
        if not name.startswith("n55_")
    }
    module["netnames"] = {
        name: net for name, net in module["netnames"].items()
        if not name.startswith("n55_")
    }
    result, log, _source, output = _run_mixed_compiled(
        tmp_path, "physical_carry_only", document,
        "--no-pack", "--no-place", "--no-route",
    )
    assert result.returncode == 0, log
    assert output.is_file()


def test_mixed_n55_n56_attacks_fail_on_their_own_owner(tmp_path):
    control = _mixed_n55_n56_document()
    module = next(iter(control["modules"].values()))

    partial_carry = deepcopy(control)
    carry_module = next(iter(partial_carry["modules"].values()))
    route = carry_module["netnames"]["n56_link_0_0"]["attributes"]["ROUTING"]
    carry_module["netnames"]["n56_link_0_0"]["attributes"]["ROUTING"] = (
        route.split(";")[0] + ";;1"
    )
    carry_path = _write_mixed(tmp_path, "mixed_partial_carry", partial_carry)
    assert sr.validate_routed_json(
        carry_path, "pre-emission", CHIPDB,
        environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
    )["active_lanes"] == (0, 1, 2, 3)
    with pytest.raises(
            CarryValidationError,
            match="does not contain its exact one-edge route"):
        validate_routed_carry(carry_module)

    partial_lane = deepcopy(control)
    lane_module = next(iter(partial_lane["modules"].values()))
    lane_net = _special_lane_net(lane_module)
    parts = lane_net["attributes"]["ROUTING"].split(";")
    lane_net["attributes"]["ROUTING"] = ";".join(parts[:-3])
    assert validate_routed_carry(lane_module).chains
    lane_path = _write_mixed(tmp_path, "mixed_partial_lane", partial_lane)
    with pytest.raises(sr.SpecialRouteError, match="is incomplete at"):
        sr.validate_routed_json(
            lane_path, "pre-emission", CHIPDB,
            environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
        )

    alias = deepcopy(control)
    alias_module = next(iter(alias["modules"].values()))
    alias_module["netnames"]["n56_literal_alias_attack"] = {
        "bits": ["0"],
        "attributes": {
            "ROUTING": alias_module["netnames"]["n56_link_0_0"][
                "attributes"]["ROUTING"],
        },
    }
    alias_path = _write_mixed(tmp_path, "mixed_alias", alias)
    with pytest.raises(
            sr.SpecialRouteError,
            match="must have a nonempty exact integer signal-bit tuple"):
        sr.validate_routed_json(
            alias_path, "pre-emission", CHIPDB,
            environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
        )
    with pytest.raises(CarryValidationError, match="exactly one integer signal bit"):
        validate_routed_carry(alias_module)
