import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon import cli
from agamemnon.engine import clock_resources
from agamemnon.engine.features.clock_validate import (
    ClockValidationError,
    validate_clock_intent,
    validate_routed_clock,
)


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
QUALIFICATION = ROOT / "qualification"


def _options(artifact=None):
    environment = {} if artifact is None else artifact.get("environment", {})
    return {
        "AGAMEMNON_NGCLK": "1",
        "AGAMEMNON_CLK_SEAM": "5",
        "AGAMEMNON_SYSCLK": environment.get("AGAMEMNON_SYSCLK", "10"),
        "AGAMEMNON_HSE": environment.get("AGAMEMNON_HSE", "8"),
    }


def _hse_module(route=None, source_type="GENERIC_IOB", source_bel="CLKIN"):
    if route is None:
        route = (
            "X1Y1_ClkMUX03;GCLK0.X1Y1_ClkMUX03;1;"
            "GCLK0;X14Y13_InputMUX01.GCLK0;1;"
            "X14Y13_InputMUX01;;1"
        )
    return {
        "attributes": _typed_metadata(),
        "cells": {
            "arbitrary_source_name": {
                "type": source_type,
                "attributes": {"NEXTPNR_BEL": source_bel},
                "port_directions": {"O": "output"},
                "connections": {"O": [7]},
            },
            "arbitrary_ff_name": {
                "type": "GENERIC_SLICE",
                "parameters": {"FF_USED": "1"},
                "attributes": {"NEXTPNR_BEL": "X1Y1_SLICE3"},
                "port_directions": {"CLK": "input"},
                "connections": {"CLK": [7]},
            },
        },
        "netnames": {
            "renaming_has_no_authority": {
                "bits": [7], "attributes": {"ROUTING": route},
            },
        },
    }


def _typed_metadata(*, profile="HSE_PLL_CLKIN_V1", source_class="HSE_PLL",
                    owner="renaming_has_no_authority"):
    return {
        "AGAMEMNON_CLOCK_SCHEMA": "00000000000000000000000000000001",
        "AGAMEMNON_CLOCK_CLASS": "GCLK0",
        "AGAMEMNON_CLOCK_SOURCE_CATALOG_SHA256": (
            clock_resources.EXPECTED_SOURCE_CATALOG_SHA256
        ),
        "AGAMEMNON_CLOCK_TOPOLOGY_SHA256": (
            clock_resources.EXPECTED_TOPOLOGY_SHA256
        ),
        "AGAMEMNON_CLOCK_SOURCE_CLASS": source_class,
        "AGAMEMNON_CLOCK_SOURCE_PROFILE": profile,
        "AGAMEMNON_CLOCK_OWNER_NET": owner,
    }


def _document(module):
    return {"modules": {"top": module}}


def test_source_catalog_is_exact_self_contained_authority():
    catalog = clock_resources.load_source_catalog(CHIPDB)
    assert catalog.digest == clock_resources.EXPECTED_SOURCE_CATALOG_SHA256
    assert [profile.profile for profile in catalog.profiles] == [
        "HSE_PLL_CLKIN_V1", "MCU_BUS_DEFAULT_V1", "MCU_SYS_UNSUPPORTED_V1",
    ]
    hse, bus, system = catalog.profiles
    assert hse.root_wire == "X14Y13_InputMUX01"
    assert hse.entry_edge == ("X14Y13_InputMUX01", "GCLK0")
    assert bus.root_wire == "GCLK0" and bus.entry_edge is None
    assert bus.evidence.endswith("#bus-clock-lfsr16-mtime-rate-20260803")
    assert system.admitted is False
    assert system.evidence == "qualification/pack_regression.json#no-MCU_SYS_CLOCK-source"


def test_retained_corpus_has_no_mcu_sys_source():
    pack = json.loads((QUALIFICATION / "pack_regression.json").read_text(encoding="utf-8"))
    found = []
    for artifact in pack["artifacts"]:
        document = json.loads((ROOT / artifact["routed"]).read_text(encoding="utf-8"))
        for cell in document["modules"]["top"].get("cells", {}).values():
            if cell.get("type") == "MCU_SYS_CLOCK":
                found.append(artifact["routed"])
    assert found == []


def test_rename_invariant_hse_route_closes_to_typed_result():
    result = validate_routed_clock(_hse_module(), CHIPDB, _options())
    assert result.owner_bit == 7
    assert result.source_profile == "HSE_PLL_CLKIN_V1"
    assert result.source_class == "HSE_PLL"
    assert result.clocked_tiles == frozenset({(1, 1)})
    assert result.active_slice_leaves == frozenset({"X1Y1_ClkMUX03"})
    assert result.bram_edges == frozenset()
    assert result.quarantined_extra_leaves == frozenset()
    assert result.quarantined_bitstream_sha256 is None
    assert result.catalog_sha256 == clock_resources.EXPECTED_SOURCE_CATALOG_SHA256
    assert result.topology_sha256 == clock_resources.EXPECTED_TOPOLOGY_SHA256


def test_complete_typed_metadata_is_bound_to_route_derived_identity():
    module = _hse_module()
    module["attributes"] = _typed_metadata()
    result = validate_routed_clock(module, CHIPDB, _options())
    assert result.source_profile == "HSE_PLL_CLKIN_V1"

    for key, value in (
        ("AGAMEMNON_CLOCK_SOURCE_PROFILE", "MCU_BUS_DEFAULT_V1"),
        ("AGAMEMNON_CLOCK_SOURCE_CLASS", "MCU_BUS"),
        ("AGAMEMNON_CLOCK_OWNER_NET", "not_an_owner_alias"),
        ("AGAMEMNON_CLOCK_TOPOLOGY_SHA256", "0" * 64),
    ):
        changed = copy.deepcopy(module)
        changed["attributes"][key] = value
        with pytest.raises(ClockValidationError, match="metadata"):
            validate_routed_clock(changed, CHIPDB, _options())

    partial = _hse_module()
    partial["attributes"] = {"AGAMEMNON_CLOCK_CLASS": "GCLK0"}
    with pytest.raises(ClockValidationError, match="missing or has extra"):
        validate_routed_clock(partial, CHIPDB, _options())

    absent = _hse_module()
    absent.pop("attributes")
    with pytest.raises(ClockValidationError, match="absent outside an exact legacy"):
        validate_routed_clock(
            absent, CHIPDB, _options(), routed_sha256="0" * 64
        )


def test_pre_nextpnr_intent_allows_unplaced_but_rejects_explicit_wrong_bels():
    module = _hse_module(route="")
    del module["cells"]["arbitrary_source_name"]["attributes"]
    del module["cells"]["arbitrary_ff_name"]["attributes"]
    result = validate_clock_intent(module, CHIPDB, _options())
    assert result.owner_bit == 7
    assert result.source_profile == "HSE_PLL_CLKIN_V1"
    assert result.active_slice_leaves == frozenset()
    assert result.clocked_tiles == frozenset()

    wrong_source = copy.deepcopy(module)
    wrong_source["cells"]["arbitrary_source_name"]["attributes"] = {
        "NEXTPNR_BEL": "X0Y0_IOB0"
    }
    with pytest.raises(ClockValidationError, match="typed source driver"):
        validate_clock_intent(wrong_source, CHIPDB, _options())

    wrong_slice = copy.deepcopy(module)
    wrong_slice["cells"]["arbitrary_ff_name"]["attributes"] = {
        "NEXTPNR_BEL": "X0Y0_IOB0"
    }
    with pytest.raises(ClockValidationError, match="not placed at a slice BEL"):
        validate_clock_intent(wrong_slice, CHIPDB, _options())


@pytest.mark.parametrize("bad", [None, True, "", "x", "2", 2])
def test_malformed_or_non_boolean_ff_used_rejects(bad):
    module = _hse_module()
    if bad is None:
        del module["cells"]["arbitrary_ff_name"]["parameters"]["FF_USED"]
    else:
        module["cells"]["arbitrary_ff_name"]["parameters"]["FF_USED"] = bad
    with pytest.raises(ClockValidationError, match="FF_USED"):
        validate_routed_clock(module, CHIPDB, _options())


def test_unsupported_source_and_noninteger_protected_alias_fail_closed():
    unsupported = _hse_module(source_type="MCU_SYS_CLOCK",
                              source_bel="X10Y5_MCU_SYS_CLOCK")
    unsupported["cells"]["arbitrary_source_name"]["port_directions"] = {"CLK": "output"}
    unsupported["cells"]["arbitrary_source_name"]["connections"] = {"CLK": [7]}
    unsupported["netnames"]["renaming_has_no_authority"]["attributes"]["ROUTING"] = (
        "X1Y1_ClkMUX03;GCLK0.X1Y1_ClkMUX03;1;GCLK0;;1"
    )
    with pytest.raises(ClockValidationError, match="classified but unsupported"):
        validate_routed_clock(unsupported, CHIPDB, _options())

    malformed = _hse_module()
    malformed["netnames"]["renaming_has_no_authority"]["bits"] = ["0"]
    with pytest.raises(ClockValidationError, match="without one integer alias"):
        validate_routed_clock(malformed, CHIPDB, _options())


def test_fabricated_direct_bram_tap_rejects():
    module = _hse_module(
        "X1Y1_ClkMUX03;GCLK0.X1Y1_ClkMUX03;1;"
        "X13Y4_TileClkMUX01;GCLK0.X13Y4_TileClkMUX01;1;"
        "GCLK0;X14Y13_InputMUX01.GCLK0;1;X14Y13_InputMUX01;;1"
    )
    module["cells"]["memory"] = {
        "type": "ALTA_BRAM9K",
        "attributes": {"NEXTPNR_BEL": "X13Y4_BRAM"},
        "port_directions": {"Clk0": "input"},
        "connections": {"Clk0": [7]},
    }
    with pytest.raises(ClockValidationError, match="foreign or wrong-class"):
        validate_routed_clock(module, CHIPDB, _options())


@pytest.mark.parametrize(
    ("directions", "connections", "diagnostic"),
    [
        ({}, {}, "has no declared clock port"),
        ({"Clk0": "input"}, {}, "has no bound clock"),
        ({"Clk0": "input"}, {"Clk0": ["x"]}, "has no bound clock"),
        ({"Clk0": "input"}, {"Clk0": ["0"]}, "has no bound clock"),
        ({"Clk0": "input"}, {"Clk0": ["1"]}, "has no bound clock"),
        ({"Clk0": "input"}, {"Clk0": [7, 8]}, "exactly one integer"),
        ({"Clk0": "output"}, {"Clk0": [7]}, "must be an input"),
        ({}, {"Clk0": [7]}, "must be an input"),
    ],
)
def test_declared_malformed_or_unbound_bram_clock_port_rejects(
        directions, connections, diagnostic):
    module = _hse_module()
    module["cells"]["memory"] = {
        "type": "ALTA_BRAM9K",
        "attributes": {"NEXTPNR_BEL": "X13Y4_BRAM"},
        "port_directions": directions,
        "connections": connections,
    }
    with pytest.raises(ClockValidationError, match=diagnostic):
        validate_routed_clock(module, CHIPDB, _options())


def test_clocked_bram_requires_exact_type_and_site():
    route = (
        "X1Y1_ClkMUX03;GCLK0.X1Y1_ClkMUX03;1;"
        "X13Y0_BufMUX05;GCLK0.X13Y0_BufMUX05;1;"
        "X13Y4_SeamMUX01;X13Y0_BufMUX05.X13Y4_SeamMUX01;1;"
        "X13Y4_TileClkMUX01;X13Y4_SeamMUX01.X13Y4_TileClkMUX01;1;"
        "GCLK0;X14Y13_InputMUX01.GCLK0;1;X14Y13_InputMUX01;;1"
    )
    module = _hse_module(route)
    module["cells"]["memory"] = {
        "type": "ALTA_BRAM9K", "attributes": {"NEXTPNR_BEL": "X12Y4_BRAM"},
        "port_directions": {"Clk0": "input"}, "connections": {"Clk0": [7]},
    }
    with pytest.raises(ClockValidationError, match="X13Y4_BRAM"):
        validate_routed_clock(module, CHIPDB, _options())
    module["cells"]["memory"]["attributes"]["NEXTPNR_BEL"] = "X13Y4_BRAM"
    module["cells"]["memory"]["type"] = "BRAM9K"
    with pytest.raises(ClockValidationError, match="exact ALTA_BRAM9K"):
        validate_routed_clock(module, CHIPDB, _options())
    module["cells"]["memory"]["type"] = "ALTA_BRAM9K"
    result = validate_routed_clock(module, CHIPDB, _options())
    assert result.bram_edges == (
        frozenset({clock_resources.BRAM_ROOT_EDGE}) |
        clock_resources.BRAM_BRANCH_EDGES
    )


@pytest.mark.parametrize("constant", ["0", "1"])
@pytest.mark.parametrize("inactive_port", ["Clk0", "Clk1"])
def test_constant_bram_clock_is_not_a_dynamic_owner(constant, inactive_port):
    module = _hse_module()
    active_port = "Clk1" if inactive_port == "Clk0" else "Clk0"
    module["cells"]["memory"] = {
        "type": "ALTA_BRAM9K",
        "port_directions": {"Clk0": "input", "Clk1": "input"},
        "connections": {active_port: [7], inactive_port: [constant]},
    }
    result = validate_clock_intent(module, CHIPDB, _options())
    assert result.owner_bit == 7
    assert result.bram_edges

    # A second dynamic clock must still fail whole-device owner validation.
    module["cells"]["memory"]["connections"][inactive_port] = [8]
    with pytest.raises(ClockValidationError, match="more than one"):
        validate_clock_intent(module, CHIPDB, _options())


@pytest.mark.parametrize("malformed", [["0", "0"], ["z"], [True], "0"])
def test_malformed_second_bram_clock_still_rejects(malformed):
    module = _hse_module()
    module["cells"]["memory"] = {
        "type": "ALTA_BRAM9K",
        "port_directions": {"Clk0": "input", "Clk1": "input"},
        "connections": {"Clk0": [7], "Clk1": malformed},
    }
    with pytest.raises(ClockValidationError, match="exactly one integer"):
        validate_clock_intent(module, CHIPDB, _options())


def test_wrong_entry_foreign_net_and_wrong_resource_class_reject():
    wrong_entry = _hse_module(
        "X1Y1_ClkMUX03;GCLK0.X1Y1_ClkMUX03;5;"
        "GCLK0;X14Y13_InputMUX04.GCLK0;5;X14Y13_InputMUX04;;5"
    )
    with pytest.raises(ClockValidationError, match="foreign or wrong-class"):
        validate_routed_clock(wrong_entry, CHIPDB, _options())

    wrong_class = _hse_module(
        "X1Y1_ClkMUX03;GCLK0.X1Y1_ClkMUX03;5;"
        "X13Y0_BufMUX05;GCLK0.X13Y0_BufMUX05;5;"
        "GCLK0;X14Y13_InputMUX01.GCLK0;5;X14Y13_InputMUX01;;5"
    )
    with pytest.raises(ClockValidationError, match="foreign or wrong-class"):
        validate_routed_clock(wrong_class, CHIPDB, _options())

    foreign = _hse_module()
    foreign["netnames"]["foreign_clock_claim"] = {
        "bits": [8],
        "attributes": {
            "ROUTING": "X1Y1_ClkMUX04;GCLK0.X1Y1_ClkMUX04;5;GCLK0;;5",
        },
    }
    with pytest.raises(ClockValidationError, match="foreign signal alias"):
        validate_routed_clock(foreign, CHIPDB, _options())


def test_internal_or_wrong_package_clock_source_rejects():
    internal = _hse_module(source_type="AG32_FA", source_bel="X1Y1_SLICE1")
    internal["cells"]["arbitrary_source_name"]["port_directions"] = {"SUM": "output"}
    internal["cells"]["arbitrary_source_name"]["connections"] = {"SUM": [7]}
    with pytest.raises(ClockValidationError, match="typed source driver"):
        validate_routed_clock(internal, CHIPDB, _options())

    wrong_package = _hse_module(source_bel="PIN_16")
    with pytest.raises(ClockValidationError, match="typed source driver"):
        validate_routed_clock(wrong_package, CHIPDB, _options())


def test_direct_pack_and_bitgen_reject_incomplete_tree_before_emission(
        tmp_path, monkeypatch):
    from agamemnon.engine import bitgen

    module = _hse_module(
        "GCLK0;X14Y13_InputMUX01.GCLK0;5;X14Y13_InputMUX01;;5"
    )
    routed = tmp_path / "partial-clock.json"
    routed.write_text(json.dumps(_document(module), sort_keys=True), encoding="utf-8")

    launched = []
    monkeypatch.setattr(cli, "_run_child", lambda *args, **kwargs: launched.append(args))
    with pytest.raises(SystemExit) as direct:
        cli.cmd_pack(SimpleNamespace(
            input=str(routed), output=str(tmp_path / "direct.bin"), baseline=None,
            research_unsafe=False, qualified_checkpoint=None,
        ))
    assert direct.value.code == 2
    assert launched == []

    stale = tmp_path / "stale.bin"
    stale.write_bytes(b"stale")
    with pytest.raises(SystemExit, match="incomplete"):
        bitgen.build(routed, stale, environ={})
    assert not stale.exists()


def test_direct_pack_and_bitgen_reject_fresh_route_without_typed_metadata(
        tmp_path, monkeypatch):
    from agamemnon.engine import bitgen

    module = _hse_module()
    module.pop("attributes")
    routed = tmp_path / "untyped-complete-clock.json"
    routed.write_text(json.dumps(_document(module), sort_keys=True), encoding="utf-8")

    launched = []
    monkeypatch.setattr(cli, "_run_child", lambda *args, **kwargs: launched.append(args))
    with pytest.raises(SystemExit) as direct:
        cli.cmd_pack(SimpleNamespace(
            input=str(routed), output=str(tmp_path / "direct.bin"), baseline=None,
            research_unsafe=False, qualified_checkpoint=None,
        ))
    assert direct.value.code == 2
    assert launched == []

    stale = tmp_path / "stale.bin"
    stale.write_bytes(b"stale")
    with pytest.raises(SystemExit, match="absent outside an exact legacy"):
        bitgen.build(routed, stale, environ={})
    assert not stale.exists()


def test_exact_quarantine_is_dual_hash_bound_and_corpus_complete():
    pack = json.loads((QUALIFICATION / "pack_regression.json").read_text(encoding="utf-8"))
    results = []
    legacy = None
    clean_legacy = None
    for artifact in pack["artifacts"]:
        path = ROOT / artifact["routed"]
        document = json.loads(path.read_text(encoding="utf-8"))
        result = validate_routed_clock(
            document, CHIPDB, _options(artifact),
            routed_sha256=artifact["routed_sha256"],
        )
        results.append(result)
        if result.quarantined_extra_leaves and legacy is None:
            legacy = (artifact, document)
        if (result.owner_bit is not None and
                not result.quarantined_extra_leaves and clean_legacy is None):
            clean_legacy = (artifact, document)
    quarantined = [result for result in results if result.quarantined_extra_leaves]
    assert len(results) == 58
    assert sum(bool(result.quarantined_bitstream_sha256) for result in results) == 48
    assert len(quarantined) == 15
    assert sum(len(result.quarantined_extra_leaves) for result in quarantined) == 432
    assert all(result.quarantined_bitstream_sha256 for result in quarantined)
    assert sum(bool(result.bram_edges) for result in results) == 3

    packaged = []
    for profile, row in cli.QUALIFIED_ROUTE_PROFILES.items():
        if not row.get("pack_only"):
            continue
        path = ROOT / "agamemnon" / row["package_root"] / row["checkpoint"]
        routed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        result = validate_routed_clock(
            json.loads(path.read_text(encoding="utf-8")), CHIPDB, _options(),
            routed_sha256=routed_sha256,
        )
        assert result.source_profile == "HSE_PLL_CLKIN_V1"
        assert len(result.quarantined_extra_leaves) == 2
        assert result.quarantined_bitstream_sha256 == row["bitstream_sha256"]
        packaged.append(result)
    assert len(packaged) == 4
    assert sum(len(result.quarantined_extra_leaves) for result in packaged) == 8

    artifact, document = legacy
    with pytest.raises(ClockValidationError, match="exact legacy"):
        validate_routed_clock(document, CHIPDB, _options(artifact),
                              routed_sha256="0" * 64)
    changed = copy.deepcopy(document)
    changed["modules"]["top"].setdefault("attributes", {})["unrelated_mutation"] = "1"
    with pytest.raises(ClockValidationError, match="module mismatch"):
        validate_routed_clock(changed, CHIPDB, _options(artifact),
                              routed_sha256=artifact["routed_sha256"])

    clean_artifact, clean_document = clean_legacy
    changed = copy.deepcopy(clean_document)
    changed["modules"]["top"].setdefault("attributes", {})[
        "unrelated_mutation"
    ] = "1"
    with pytest.raises(ClockValidationError, match="module mismatch"):
        validate_routed_clock(
            changed, CHIPDB, _options(clean_artifact),
            routed_sha256=clean_artifact["routed_sha256"],
        )

    quarantine = json.loads(
        (CHIPDB / clock_resources.LEGACY_QUARANTINE_NAME).read_text(encoding="utf-8")
    )
    assert len(quarantine["artifacts"]) == 19
    assert sum(len(quarantine["leaf_sets"][row["leaf_set"]])
               for row in quarantine["artifacts"]) == 440
    pinned = {row["routed_sha256"]: row for row in quarantine["artifacts"]}
    for artifact in pack["artifacts"]:
        row = pinned.get(artifact["routed_sha256"])
        if row is None:
            continue
        assert row["bitstream_sha256"] == artifact["bitstream_sha256"]
        assert hashlib.sha256((ROOT / artifact["routed"]).read_bytes()).hexdigest() == row[
            "routed_sha256"
        ]
