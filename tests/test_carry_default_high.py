"""Experimental carry D defaults must remain undriven through serialization."""
import json
from pathlib import Path
import re

import pytest

from agamemnon.engine.features.carry_validate import CarryValidationError, validate_routed_carry
from agamemnon.engine.features.register_input import validate_module_register_inputs

ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTE = "AGRV2K_CARRY_D_DEFAULT_HIGH"
TOKEN = "IMUX_UNSELECTED_HIGH_V1"


@pytest.fixture
def default_high():
    module = json.loads((ROOT / "qualification/counter8_carry_routed.json").read_text())["modules"]["top"]
    members = {name: cell for name, cell in module["cells"].items() if "CIN" in cell["connections"]}
    terminals = set()
    next_bit = 1 + max(bit for cell in module["cells"].values()
                       for values in cell["connections"].values() for bit in values if isinstance(bit, int))
    for offset, cell in enumerate(members.values()):
        cell["attributes"][ATTRIBUTE] = TOKEN
        cell["connections"]["I"][3] = next_bit + offset
        x, y, z = map(int, re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", cell["attributes"]["NEXTPNR_BEL"]).groups())
        terminals.add("X%dY%d_IMUX%02d" % (x, y, 4 * z + 3))
    for net in module["netnames"].values():
        route = net.get("attributes", {}).get("ROUTING")
        if not route:
            continue
        fields = route.split(";")
        net["attributes"]["ROUTING"] = ";".join(
            item for index in range(0, len(fields), 3) if fields[index] not in terminals
            for item in fields[index:index + 3])
    return module, members, terminals


def test_explicit_undriven_registered_carry_d_is_accepted(default_high):
    module, _, _ = default_high
    assert validate_routed_carry(module).chains
    assert validate_module_register_inputs(module)


@pytest.mark.parametrize("value", ["1", "", "IMUX_UNSELECTED_HIGH_V2"])
def test_unknown_default_high_token_is_refused(default_high, value):
    module, members, _ = default_high
    next(iter(members.values()))["attributes"][ATTRIBUTE] = value
    with pytest.raises(CarryValidationError, match="malformed experimental"):
        validate_routed_carry(module)
    with pytest.raises(SystemExit, match="malformed experimental"):
        validate_module_register_inputs(module)


def test_default_high_cannot_keep_a_live_input(default_high):
    module, members, _ = default_high
    cell = next(iter(members.values()))
    cell["connections"]["I"][3] = cell["connections"]["Q"][0]
    with pytest.raises(CarryValidationError, match="undriven registered"):
        validate_routed_carry(module)
    with pytest.raises(SystemExit, match="malformed experimental"):
        validate_module_register_inputs(module)


def test_default_high_rejects_foreign_route_through_selector(default_high):
    module, _, terminals = default_high
    wire = sorted(terminals)[0]
    module["netnames"]["foreign-d-route"] = {
        "bits": [987654321], "attributes": {"ROUTING": wire + ";X20Y12_RMUX05." + wire + ";1"}}
    with pytest.raises(CarryValidationError, match="route drives"):
        validate_routed_carry(module)


def test_default_high_cannot_be_silently_untagged(default_high):
    module, members, _ = default_high
    del next(iter(members.values()))["attributes"][ATTRIBUTE]
    with pytest.raises(CarryValidationError, match="mixed ordinary"):
        validate_routed_carry(module)
    with pytest.raises(SystemExit, match="sum selector"):
        validate_module_register_inputs(module)


def test_default_high_cannot_be_claimed_by_an_ordinary_slice(default_high):
    module, _, _ = default_high
    cell = next(cell for cell in module["cells"].values()
                if cell["type"] == "GENERIC_SLICE" and "COUT" not in cell["connections"])
    cell["attributes"][ATTRIBUTE] = TOKEN
    with pytest.raises(CarryValidationError, match="malformed experimental"):
        validate_routed_carry(module)
    with pytest.raises(SystemExit, match="malformed experimental"):
        validate_module_register_inputs(module)


@pytest.fixture
def a_feedback(default_high):
    module, members, _ = default_high
    for cell in members.values():
        inputs = cell["connections"]["I"]
        inputs[0], inputs[1] = inputs[1], inputs[0]
        cell["attributes"]["AGRV2K_CARRY_A_Q_FEEDBACK"] = "LOCAL_PRESENTATION_V1"
        init = int(cell["parameters"]["INIT"], 2)
        swapped = sum(((init >> ((row & ~3) | ((row & 1) << 1) | ((row & 2) >> 1))) & 1) << row
                      for row in range(16))
        cell["parameters"]["INIT"] = format(swapped, "016b")
        x, y, z = map(int, re.fullmatch(r"X(\d+)Y(\d+)_SLICE(\d+)", cell["attributes"]["NEXTPNR_BEL"]).groups())
        old, new = ["X%dY%d_IMUX%02d" % (x, y, 4 * z + offset) for offset in (1, 0)]
        for net in module["netnames"].values():
            if net["bits"] != cell["connections"]["Q"]:
                continue
            net["attributes"]["ROUTING"] = net["attributes"]["ROUTING"].replace(old, new)
    return module, members


def test_explicit_a_feedback_requires_its_local_presentation(a_feedback):
    module, members = a_feedback
    result = validate_routed_carry(module)
    assert len(result.chains[0].q_feedback_cells) == len(members)


def test_a_feedback_without_profile_stays_refused(a_feedback):
    module, members = a_feedback
    del next(iter(members.values()))["attributes"]["AGRV2K_CARRY_A_Q_FEEDBACK"]
    with pytest.raises(CarryValidationError, match="outside the typed B"):
        validate_routed_carry(module)


def test_a_feedback_missing_local_edge_is_refused(a_feedback):
    module, members = a_feedback
    q = next(iter(members.values()))["connections"]["Q"]
    for net in module["netnames"].values():
        if net["bits"] == q:
            fields = net["attributes"]["ROUTING"].split(";")
            net["attributes"]["ROUTING"] = ";".join(
                value for index in range(0, len(fields), 3) if "IMUX" not in fields[index]
                for value in fields[index:index + 3])
    with pytest.raises(CarryValidationError, match="exact local presentation"):
        validate_routed_carry(module)


def test_a_feedback_tag_does_not_authorize_b_or_unregistered_feedback(default_high):
    module, members, _ = default_high
    next(iter(members.values()))["attributes"]["AGRV2K_CARRY_A_Q_FEEDBACK"] = "LOCAL_PRESENTATION_V1"
    with pytest.raises(CarryValidationError, match="own Q on I"):
        validate_routed_carry(module)
