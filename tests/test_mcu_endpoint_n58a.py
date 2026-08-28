"""N5.8A one-lane typed HWDATA25 admission and routed closure."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from agamemnon.engine.features.mcu_endpoint import (
    INTERFACE_ATTRIBUTE,
    LANE_ATTRIBUTE,
    MODE_ATTRIBUTE,
    VERSION_ATTRIBUTE,
    load_mcu_endpoint_capability,
    validate_module_mcu_endpoints,
)


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
UARCH = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
DEFAULT_DEVDB = UARCH.parent / "devdb_strict"


def _attrs(**overrides):
    attrs = {
        "NEXTPNR_BEL": "X10Y5_MCU_DIN69",
        INTERFACE_ATTRIBUTE: "HWDATA",
        LANE_ATTRIBUTE: format(25, "032b"),
        MODE_ATTRIBUTE: "DIRECT_FABRIC_INPUT",
        VERSION_ATTRIBUTE: format(1, "032b"),
    }
    attrs.update(overrides)
    return attrs


def _route(sink="X14Y9_IMUX33", first="X13Y9_InputMUX06"):
    edges = [
        ("X13Y9_BufMUX07", first),
        (first, "X14Y9_RMUX71"),
        ("X14Y9_RMUX71", sink),
    ]
    triples = [("X13Y9_BufMUX07", "", "1")]
    triples += [(dst, "%s.%s" % (src, dst), "1") for src, dst in edges]
    return ";".join(item for triple in triples for item in triple)


def _module(endpoint_name="renamed_endpoint", route=None, with_sink=True):
    cells = {
        endpoint_name: {
            "type": "MCU_DIN",
            "parameters": {},
            "attributes": _attrs(),
            "port_directions": {"DIN": "output"},
            "connections": {"DIN": [7]},
        },
    }
    if with_sink:
        cells["arbitrary_consumer_name"] = {
            "type": "GENERIC_SLICE",
            "parameters": {"INIT": format(0xCCCC, "016b"), "FF_USED": "0"},
            "attributes": {"NEXTPNR_BEL": "X14Y9_SLICE8"},
            "port_directions": {"I": "input", "F": "output", "Q": "output"},
            "connections": {"I": [0, 7, 0, 0], "F": [9], "Q": []},
        }
    net = {"bits": [7], "attributes": {}}
    if route is not None:
        net["attributes"]["ROUTING"] = route
    return {"cells": cells, "netnames": {"semantic_signal": net}, "ports": {}}


def test_capability_is_exactly_one_hash_bound_cross_checked_hwdata25_row():
    capability = load_mcu_endpoint_capability(CHIPDB)
    assert capability.interface == "HWDATA"
    assert capability.lane == 25
    assert capability.hard_pin == "MCU_DIN69"
    assert capability.hard_bel == "X10Y5_MCU_DIN69"
    assert capability.first_hop == (
        "X13Y9_BufMUX07", "X13Y9_InputMUX06",
    )
    assert capability.selector_owner == "mcu"
    assert capability.selector_field == "InputMUX6"
    assert capability.selector_selection == 0


def test_capability_manifest_rejects_byte_drift(tmp_path):
    for name in (
        "mcu_endpoint_capabilities.csv",
        "mcu_endpoint_capability_manifest.json",
        "mcu_hwdata_lanes.csv",
        "mcu_ahb32_corridors.csv",
        "mcu_ahb32_pip_cfg.csv",
    ):
        shutil.copyfile(CHIPDB / name, tmp_path / name)
    with (tmp_path / "mcu_endpoint_capabilities.csv").open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(SystemExit, match="manifest does not bind"):
        load_mcu_endpoint_capability(tmp_path)


def test_renamed_exact_endpoint_and_consumer_route_are_accepted():
    requirements = validate_module_mcu_endpoints(
        _module(endpoint_name="names_have_no_authority", route=_route()), CHIPDB,
    )
    requirement = requirements["names_have_no_authority"]
    assert requirement.active
    assert requirement.route_carrier == "semantic_signal"
    assert [(sink.bel, sink.wire) for sink in requirement.sinks] == [
        ("X14Y9_SLICE8", "X14Y9_IMUX33"),
    ]


def test_kept_but_unused_typed_boundary_cell_activates_no_route_authority():
    requirement = validate_module_mcu_endpoints(
        _module(route=None, with_sink=False), CHIPDB,
    )["renamed_endpoint"]
    assert not requirement.active
    assert requirement.route_carrier is None


@pytest.mark.parametrize("missing", [
    INTERFACE_ATTRIBUTE, LANE_ATTRIBUTE, MODE_ATTRIBUTE, VERSION_ATTRIBUTE,
])
def test_partial_intent_metadata_fails_closed(missing):
    module = _module(route=_route())
    del module["cells"]["renamed_endpoint"]["attributes"][missing]
    with pytest.raises(SystemExit, match="partial endpoint intent"):
        validate_module_mcu_endpoints(module, CHIPDB)


@pytest.mark.parametrize("lane", [24, 26])
def test_adjacent_hwdata_lanes_are_explicit_non_generalization_controls(lane):
    module = _module(route=_route())
    module["cells"]["renamed_endpoint"]["attributes"][LANE_ATTRIBUTE] = \
        format(lane, "032b")
    with pytest.raises(SystemExit, match="HWDATA24/26"):
        validate_module_mcu_endpoints(module, CHIPDB)


@pytest.mark.parametrize(
    "mutation, reason",
    [
        (lambda module: module["cells"]["renamed_endpoint"]["attributes"].update(
            {"NEXTPNR_BEL": "X10Y5_MCU_DIN68"}), "exact hard BEL"),
        (lambda module: module["cells"]["renamed_endpoint"].update(
            {"type": "GENERIC_SLICE"}), "requires type MCU_DIN"),
        (lambda module: module["cells"]["renamed_endpoint"].update(
            {"port_directions": {"DIN": "input"}}), "contradicts known MCU_DIN"),
        (lambda module: module["cells"]["arbitrary_consumer_name"].update(
            {"port_directions": None}), "direction metadata is missing"),
        (lambda module: module["cells"]["arbitrary_consumer_name"].update(
            {"port_directions": {"I": "sideways"}}), "direction metadata is unknown"),
        (lambda module: module["cells"]["arbitrary_consumer_name"]["attributes"].update(
            {"NEXTPNR_BEL": "X99Y99_SLICE8"}), "does not reach consumer"),
    ],
)
def test_malformed_type_direction_bel_and_sink_forms_fail_closed(mutation, reason):
    module = _module(route=_route())
    mutation(module)
    with pytest.raises(SystemExit, match=reason):
        validate_module_mcu_endpoints(module, CHIPDB)


def test_wrong_first_hop_fails_even_when_downstream_route_is_encodable():
    module = _module(route=_route(first="X13Y9_InputMUX07"))
    with pytest.raises(SystemExit, match="mandatory first hop"):
        validate_module_mcu_endpoints(module, CHIPDB)


def test_missing_sink_and_disconnected_tree_fail_closed():
    module = _module(route=_route(sink="X14Y9_IMUX32"))
    with pytest.raises(SystemExit, match="does not reach consumer"):
        validate_module_mcu_endpoints(module, CHIPDB)

    module = _module(route=_route() + ";X18Y9_RMUX1;X17Y9_RMUX1.X18Y9_RMUX1;1")
    with pytest.raises(SystemExit, match="disconnected tree"):
        validate_module_mcu_endpoints(module, CHIPDB)


def test_duplicate_endpoint_and_foreign_route_ownership_fail_closed():
    duplicate = _module(route=_route())
    duplicate["cells"]["second_endpoint"] = deepcopy(
        duplicate["cells"]["renamed_endpoint"]
    )
    with pytest.raises(SystemExit, match="duplicate HWDATA25"):
        validate_module_mcu_endpoints(duplicate, CHIPDB)

    collision = _module(route=_route())
    collision["netnames"]["foreign"] = {
        "bits": [8],
        "attributes": {
            "ROUTING": (
                "X15Y9_RMUX1;;1;X14Y9_RMUX71;"
                "X15Y9_RMUX1.X14Y9_RMUX71;1"
            ),
        },
    }
    with pytest.raises(SystemExit, match="foreign route.*collides"):
        validate_module_mcu_endpoints(collision, CHIPDB)


def test_attribute_absent_legacy_module_needs_no_new_capability_table(tmp_path):
    assert validate_module_mcu_endpoints({"cells": {}, "netnames": {}}, tmp_path) == {}


def test_runtime_and_emission_boundaries_consume_the_same_validator():
    cli = (ROOT / "agamemnon" / "cli.py").read_text(encoding="utf-8")
    core = (ROOT / "agamemnon" / "engine" / "features" /
            "core_logic.py").read_text(encoding="utf-8")
    assert '"mcu_endpoint_capabilities.csv"' in cli
    assert '"mcu_endpoint_capability_manifest.json"' in cli
    assert '"mcu_hwdata_lanes.csv"' in cli
    assert "validate_module_mcu_endpoints(module, chipdb_root)" in core
    assert cli.index("_validate_mcu_endpoint_document(\n                post_snapshot") < \
        cli.index("final_snapshot = special_routes.load_validated_routed_json")
    assert cli.index("_validate_mcu_endpoint_document(\n            final_snapshot") < \
        cli.index("_write_confidence_manifest(\n        routed_json=routed_json")


def test_cpp_uses_typed_identity_and_net_aware_route_gate_not_cell_name():
    source = UARCH.read_text(encoding="utf-8")
    assert "McuEndpointRequirement" in source
    assert "mcu_endpoint_pip_legal" in source
    assert "audit_mcu_endpoint_routes" in source
    assert "mcu_endpoint_cell_admitted" in source
    pack_edge = source.split("static void pack_mcu_edge", 1)[1].split(
        "// ---- pack: bind the one logical external clock", 1,
    )[0]
    assert "mcu_endpoint_intent" in pack_edge
    assert "McuEndpointIntent typed_intent" in pack_edge
    assert "typed_intent.present" in pack_edge


def test_hermetic_nextpnr_build_uses_noninteractive_direction_rejection():
    uarch = UARCH.parent
    patch = uarch / "nextpnr-json-direction-failclosed.patch"
    build = (uarch / "build.sh").read_text(encoding="utf-8")
    contents = patch.read_text(encoding="utf-8")
    assert 'log_error("invalid json port direction:' in contents
    assert 'NPNR_ASSERT_FALSE("invalid json port direction")' in contents
    assert 'apply_nextpnr_patch "$HERE/nextpnr-json-direction-failclosed.patch"' \
        in build


def _compiled_tool():
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated N5.8 build")
    return executable


def _compiled_devdb():
    devdb = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", DEFAULT_DEVDB))
    if not (devdb / "dev_pips.csv").is_file():
        pytest.skip("set AGAMEMNON_UARCH_DEVDB to the matching N5.8 devdb")
    return devdb


def _compiled_design(*, lane=25, endpoint_name="semantic_name_not_required",
                     fanout=False):
    endpoint_attrs = _attrs()
    endpoint_attrs.pop("NEXTPNR_BEL")
    endpoint_attrs[LANE_ATTRIBUTE] = format(lane, "032b")
    document = {
        "creator": "N5.8A compiled renamed HWDATA25 fixture",
        "modules": {"top": {
            "attributes": {"top": 1},
            "ports": {},
            "cells": {
                endpoint_name: {
                    "hide_name": 0,
                    "type": "MCU_DIN",
                    "parameters": {},
                    "attributes": endpoint_attrs,
                    "port_directions": {"DIN": "output"},
                    "connections": {"DIN": [7]},
                },
                "ordinary_consumer": {
                    "hide_name": 0,
                    "type": "GENERIC_SLICE",
                    "parameters": {
                        "FF_USED": format(0, "032b"),
                        "INIT": format(0xAAAA, "016b"),
                        "K": format(4, "032b"),
                    },
                    "attributes": {"AGRV2K_REGISTER_INPUT_MODE": "NONE"},
                    "port_directions": {
                        "I": "input", "F": "output", "Q": "output",
                    },
                    "connections": {
                        "I": [7, "x", "x", "x"], "F": [], "Q": [],
                    },
                },
            },
            "netnames": {
                "semantic_signal": {
                    "hide_name": 0, "bits": [7], "attributes": {},
                },
            },
        }},
    }
    if fanout:
        second = deepcopy(
            document["modules"]["top"]["cells"]["ordinary_consumer"]
        )
        second["parameters"]["INIT"] = format(0xCCCC, "016b")
        document["modules"]["top"]["cells"]["second_consumer"] = second
    return document


def _run_compiled(tmp_path, name, design):
    source = tmp_path / (name + ".json")
    output = tmp_path / (name + "_out.json")
    source.write_text(json.dumps(design, sort_keys=True), encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    for variable in (
        "AGRV2K_CONDPLACE", "AGRV2K_DENSE_TILE", "AGRV2K_REPLAY_BELS",
        "AGRV2K_REPLAY_BELS_IN_DB", "AGRV2K_REPLAY_BELS_HARD",
    ):
        env.pop(variable, None)
    result = subprocess.run(
        [_compiled_tool(), "--uarch", "agrv2k", "-o",
         "chipdb=" + str(_compiled_devdb()), "--json", str(source),
         "--write", str(output), "--router", "router2"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=600,
    )
    return result, output


def test_compiled_renamed_endpoint_routes_and_emitted_tree_revalidates(tmp_path):
    result, output = _run_compiled(
        tmp_path, "renamed_positive",
        _compiled_design(endpoint_name="arbitrary_hierarchy_token"),
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    assert "loaded one typed HWDATA25 endpoint" in log
    assert "bound one typed HWDATA25 endpoint by semantic identity" in log
    assert "typed HWDATA25 route audit verified mandatory first hop" in log
    document = json.loads(output.read_text(encoding="utf-8"))
    module = document["modules"]["top"]
    requirements = validate_module_mcu_endpoints(module, _compiled_devdb())
    requirement = requirements["arbitrary_hierarchy_token"]
    assert requirement.active
    assert requirement.capability.first_hop == (
        "X13Y9_BufMUX07", "X13Y9_InputMUX06",
    )
    consumer = module["cells"]["ordinary_consumer"]
    assert "NEXTPNR_BEL" in consumer["attributes"]
    assert "NEXTPNR_CLUSTER" not in consumer["attributes"]


def test_compiled_router2_reaches_every_sink_without_sentinel_clusters(tmp_path):
    result, output = _run_compiled(
        tmp_path, "two_sink_fanout", _compiled_design(fanout=True),
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log
    assert "one root, and 2 sink(s)" in log
    module = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]
    requirement = validate_module_mcu_endpoints(
        module, _compiled_devdb(),
    )["semantic_name_not_required"]
    assert {sink.cell for sink in requirement.sinks} == {
        "ordinary_consumer", "second_consumer",
    }
    for name in ("ordinary_consumer", "second_consumer"):
        attrs = module["cells"][name]["attributes"]
        assert "NEXTPNR_BEL" in attrs
        assert "NEXTPNR_CLUSTER" not in attrs


@pytest.mark.parametrize("lane", [24, 26])
def test_compiled_adjacent_lanes_fail_before_router2(tmp_path, lane):
    result, output = _run_compiled(
        tmp_path, "negative_lane_%d" % lane, _compiled_design(lane=lane),
    )
    log = result.stdout + result.stderr
    assert result.returncode != 0
    assert "HWDATA24/26 and other lanes are not generalized" in log
    assert "Router2" not in log
    assert not output.exists()
