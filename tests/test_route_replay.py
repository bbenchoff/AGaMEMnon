"""Fail-closed structural contract for exact qualified route replay."""

import copy

import pytest

from agamemnon.engine.route_replay import ReplayError, replay


def design(rename=False):
    first = "renamed_a" if rename else "a"
    return {
        "modules": {
            "top": {
                "ports": {},
                "cells": {
                    first: {
                        "type": "GENERIC_SLICE",
                        "parameters": {"K": "0100", "INIT": "1010", "FF_USED": "0"},
                        "attributes": {},
                        "port_directions": {"I": "input", "F": "output"},
                        "connections": {"I": ["0"], "F": [2]},
                    },
                    "b": {
                        "type": "GENERIC_SLICE",
                        "parameters": {"K": "0100", "INIT": "1100", "FF_USED": "0"},
                        "attributes": {},
                        "port_directions": {"I": "input", "F": "output"},
                        "connections": {"I": [2], "F": [3]},
                    },
                },
                "netnames": {
                    "middle": {"bits": [2], "attributes": {}},
                    "result": {"bits": [3], "attributes": {}},
                },
            }
        }
    }


def checkpoint():
    result = design()
    top = result["modules"]["top"]
    for index, cell in enumerate(top["cells"].values()):
        cell["attributes"]["NEXTPNR_BEL"] = "X1Y1_SLICE%d" % index
    top["netnames"]["middle"]["attributes"]["ROUTING"] = "B;A.B;1;A;;1"
    top["netnames"]["result"]["attributes"]["ROUTING"] = "D;C.D;1;C;;1"
    return result


def test_exact_and_uniquely_renamed_source_replay():
    for source in (design(), design(rename=True)):
        routed, cells, nets = replay(source, checkpoint())
        assert (cells, nets) == (2, 2)
        top = routed["modules"]["top"]
        assert {cell["attributes"]["NEXTPNR_BEL"]
                for cell in top["cells"].values()} == {
                    "X1Y1_SLICE0", "X1Y1_SLICE1"}
        assert {net["attributes"]["ROUTING"]
                for net in top["netnames"].values()} == {
                    "B;A.B;1;A;;1", "D;C.D;1;C;;1"}


@pytest.mark.parametrize("mutation", [
    "parameter", "type", "connection", "extra_cell", "missing_cell",
    "missing_bel", "missing_route", "extra_net",
])
def test_every_structural_or_physical_drift_fails_closed(mutation):
    source = design()
    reference = checkpoint()
    if mutation == "parameter":
        source["modules"]["top"]["cells"]["a"]["parameters"]["INIT"] = "1111"
    elif mutation == "type":
        source["modules"]["top"]["cells"]["a"]["type"] = "OTHER"
    elif mutation == "connection":
        source["modules"]["top"]["cells"]["b"]["connections"]["I"] = [3]
    elif mutation == "extra_cell":
        source["modules"]["top"]["cells"]["extra"] = copy.deepcopy(
            source["modules"]["top"]["cells"]["a"])
    elif mutation == "missing_cell":
        del source["modules"]["top"]["cells"]["b"]
    elif mutation == "missing_bel":
        del reference["modules"]["top"]["cells"]["a"]["attributes"]["NEXTPNR_BEL"]
    elif mutation == "missing_route":
        del reference["modules"]["top"]["netnames"]["middle"]["attributes"]["ROUTING"]
    elif mutation == "extra_net":
        source["modules"]["top"]["netnames"]["alias"] = {
            "bits": [2], "attributes": {}}
    with pytest.raises(ReplayError):
        replay(source, reference)


def test_ambiguous_renamed_cell_mapping_fails_closed():
    source = design(rename=True)
    source["modules"]["top"]["cells"]["renamed_a"]["parameters"] = \
        source["modules"]["top"]["cells"]["b"]["parameters"].copy()
    with pytest.raises(ReplayError):
        replay(source, checkpoint())


def test_source_only_physical_attribute_fails_closed():
    source = design()
    source["modules"]["top"]["cells"]["a"]["attributes"][
        "AGRV2K_ROUTE_THROUGH"] = "1"
    with pytest.raises(ReplayError, match="physical attributes"):
        replay(source, checkpoint())


def test_duplicate_bel_and_malformed_route_fail_closed():
    source = design()
    reference = checkpoint()
    reference["modules"]["top"]["cells"]["b"]["attributes"][
        "NEXTPNR_BEL"] = "X1Y1_SLICE0"
    with pytest.raises(ReplayError, match="duplicate BEL"):
        replay(source, reference)

    reference = checkpoint()
    reference["modules"]["top"]["netnames"]["middle"]["attributes"][
        "ROUTING"] = "not;a;triple;shape"
    with pytest.raises(ReplayError, match="malformed"):
        replay(source, reference)
