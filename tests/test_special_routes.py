import csv
import hashlib
import itertools
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon.engine import clock_resources
from agamemnon.engine import special_routes as sr


CHIPDB = Path(__file__).parents[1] / "agamemnon" / "chipdb"
PHYSICAL_DEVDB = (Path(__file__).parents[1] / "agamemnon" / "engine" /
                  "uarch" / "agrv2k" / "devdb_strict_pcf")
PHYSICAL_ENV = {
    "AGAMEMNON_DEVICE": sr.DEVICE,
    "AGAMEMNON_PHYSICAL_IO": "1",
    "AGAMEMNON_LEFT_PAD_OUT": "1",
    sr.DEVDB_ENV: str(PHYSICAL_DEVDB),
}


@pytest.fixture(autouse=True)
def _selected_physical_special_route_profile(monkeypatch):
    for key, value in PHYSICAL_ENV.items():
        monkeypatch.setenv(key, value)


def _attrs(lane):
    return {
        "NEXTPNR_BEL": lane.source_bel,
        sr.TOKEN_CLASS: sr.CLASS,
        sr.TOKEN_VERSION: sr.ROUTED_VERSION,
        sr.TOKEN_LANE: str(lane.index),
        sr.TOKEN_DIGEST: sr.load_catalog(CHIPDB).digest,
    }


def _route(lane, *, partial=False, root=None, departure=False):
    edges = lane.edges[:-1] if partial else lane.edges
    triples = [root if root is not None else lane.edges[0].src, "", "1"]
    for edge in edges:
        triples += [edge.dst, edge.src + "." + edge.dst, "5"]
    if departure:
        departures = {
            0: ("X14Y11_OMUX12", "X15Y11_RMUX31"),
            1: ("X14Y11_OMUX15", "X15Y11_RMUX33"),
            2: ("X14Y11_RMUX44", "X14Y10_RMUX75"),
            3: ("X14Y11_OMUX23", "X14Y11_RMUX31"),
        }
        src, dst = departures[lane.index]
        triples += [dst, src + "." + dst, "1"]
    return ";".join(triples)


def _document(active=(0,), *, partial=None, wrong_port=None, root=None,
              departure=False, tokens=True):
    catalog = sr.load_catalog(CHIPDB)
    cells = {}
    nets = {}
    for lane_index in active:
        lane = catalog.lanes[lane_index]
        bit = 100 + lane_index
        attrs = _attrs(lane) if tokens else {"NEXTPNR_BEL": lane.source_bel}
        cells["driver%d" % lane_index] = {
            "type": "GENERIC_SLICE", "attributes": attrs,
            "parameters": {"FF_USED": "0"},
            "port_directions": {"Q": "output", "F": "output", "I": "input"},
            "connections": {"Q" if wrong_port != lane_index else "F": [bit]},
        }
        cells["sink%d" % lane_index] = {
            "type": "GENERIC_IOB", "attributes": {"NEXTPNR_BEL": lane.sink_bel},
            "port_directions": {"I": "input", "PAD": "inout"},
            "connections": {"I": [bit], "PAD": []},
        }
        nets["lane%d" % lane_index] = {
            "bits": [bit], "attributes": {
                "ROUTING": _route(
                    lane, partial=(partial == lane_index),
                    root=root if lane_index == active[0] else None,
                    departure=departure,
                )
            },
        }
    return {"modules": {"top": {
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
        "cells": cells, "netnames": nets,
    }}}


def _document_with_malformed_fabric_consumer_direction(form):
    document = _document((0,))
    observer = {
        "type": "GENERIC_SLICE",
        "attributes": {"NEXTPNR_BEL": "X14Y11_SLICE8"},
        "port_directions": {"A": "input", "F": "output"},
        "connections": {"A": [100], "F": [901]},
    }
    if form == "absent-map":
        del observer["port_directions"]
    elif form == "null-map":
        observer["port_directions"] = None
    elif form == "non-object-map":
        observer["port_directions"] = ["A", "input"]
    elif form == "absent-port":
        del observer["port_directions"]["A"]
    elif form == "null-port":
        observer["port_directions"]["A"] = None
    elif form == "unknown-port":
        observer["port_directions"]["A"] = "sideways"
    elif form == "contradictory-port":
        observer["port_directions"]["A"] = "output"
    else:
        raise AssertionError("unknown malformed-direction fixture %s" % form)
    document["modules"]["top"]["cells"]["malformed_observer"] = observer
    return document


def _pad_only_document_from_retained():
    """Convert the old branched four-lane sample into the qualified pad-only shape."""
    retained = (Path(__file__).parents[1] / "qualification" /
                "pad_uarch_left_edge_outputs_routed.json")
    document = json.loads(retained.read_text(encoding="utf-8"))
    top = document["modules"]["top"]
    catalog = sr.load_catalog(CHIPDB)
    top["attributes"].update({
        sr.MODULE_SCHEMA: sr.SCHEMA,
        sr.TOKEN_CLASS: sr.CLASS,
        sr.TOKEN_VERSION: sr.ROUTED_VERSION,
        sr.MODULE_DEVICE: sr.DEVICE,
        sr.MODULE_PACKAGE: sr.PACKAGE,
        sr.MODULE_PROFILE: sr.PROFILE,
        sr.MODULE_ENABLED: "1",
        sr.TOKEN_DIGEST: catalog.digest,
        "AGAMEMNON_CLOCK_SCHEMA": "00000000000000000000000000000001",
        "AGAMEMNON_CLOCK_CLASS": clock_resources.CLASS,
        "AGAMEMNON_CLOCK_SOURCE_CATALOG_SHA256": (
            clock_resources.EXPECTED_SOURCE_CATALOG_SHA256
        ),
        "AGAMEMNON_CLOCK_TOPOLOGY_SHA256": (
            clock_resources.EXPECTED_TOPOLOGY_SHA256
        ),
        "AGAMEMNON_CLOCK_SOURCE_CLASS": "HSE_PLL",
        "AGAMEMNON_CLOCK_SOURCE_PROFILE": "HSE_PLL_CLKIN_V1",
        "AGAMEMNON_CLOCK_OWNER_NET": "$iopadmap$clk",
    })
    constant_feedbacks = 0
    for lane in catalog.lanes:
        owner = next(
            cell for cell in top["cells"].values()
            if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
        )
        owner.setdefault("attributes", {}).update(_attrs(lane))
        bit = owner["connections"][lane.source_port][0]
        for cell in top["cells"].values():
            attrs = cell.get("attributes") or {}
            if attrs.get("NEXTPNR_BEL") == lane.sink_bel:
                continue
            for port, bits in (cell.get("connections") or {}).items():
                if (cell.get("port_directions") or {}).get(port) not in ("input", "inout"):
                    continue
                if bit in bits:
                    # This is a synthetic pad-only ownership fixture, not the
                    # retained counter's silicon behavior. Define the removed
                    # feedback branch as zero instead of leaving a LUT input
                    # floating. Restrict the rewrite to the four known I[3]
                    # buffers; the original retained checkpoint stays intact.
                    assert cell["type"] == "GENERIC_SLICE" and port == "I"
                    assert len(bits) == 4 and bits[3] == bit and bit not in bits[:3]
                    assert int(cell["parameters"]["FF_USED"], 2) == 0
                    assert int(cell["parameters"]["INIT"], 2) == 0xff00
                    cell["connections"][port] = bits[:3] + ["0"]
                    cell["parameters"]["INIT"] = "0" * 16
                    constant_feedbacks += 1
        routed = [
            net for net in top["netnames"].values()
            if bit in net.get("bits", ()) and "ROUTING" in (net.get("attributes") or {})
        ]
        assert len(routed) == 1
        routed[0]["attributes"]["ROUTING"] = _route(lane)
    assert constant_feedbacks == 4
    return document


def test_pad_only_fixture_has_defined_register_inputs():
    from agamemnon.engine.features.register_input import validate_module_register_inputs

    module = _pad_only_document_from_retained()["modules"]["top"]
    validate_module_register_inputs(module)
    buffers = [cell for name, cell in module["cells"].items()
               if name.startswith("$agamemnon$feedback_buffer$")]
    assert len(buffers) == 4
    assert all(cell["connections"]["I"][3] == "0" and
               int(cell["parameters"]["INIT"], 2) == 0 for cell in buffers)


def _write(tmp_path, document, name="route.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _physical_env(**overrides):
    selected = dict(PHYSICAL_ENV)
    selected.update(overrides)
    return selected


def _stub_physical_devdb(monkeypatch):
    catalog = sr.load_catalog(CHIPDB)
    graph = {
        "%s.%s" % (edge.src, edge.dst): (edge.src, edge.dst)
        for lane in catalog.lanes for edge in lane.edges
    }
    monkeypatch.setattr(
        sr, "_validated_devdb", lambda *_args, **_kwargs: (True, graph, frozenset(range(4))),
    )


def test_catalog_is_complete_disjoint_and_identity_frozen():
    catalog = sr.load_catalog(CHIPDB)
    assert len(catalog.edges) == 36
    assert len(catalog.wires) == 40
    assert [len(lane.edges) for lane in catalog.lanes] == [10, 9, 9, 8]
    assert [
        (lane.pin, lane.source_bel, lane.source_port, lane.sink_bel, lane.sink_port)
        for lane in catalog.lanes
    ] == list(sr.FROZEN_LANES)


def test_self_consistent_catalog_endpoint_edit_still_fails(tmp_path):
    copied = tmp_path / sr.CATALOG_NAME
    text = (CHIPDB / sr.CATALOG_NAME).read_text(encoding="utf-8")
    copied.write_text(text.replace("X14Y11_SLICE4", "X14Y11_SLICE8"), encoding="utf-8")
    with pytest.raises(sr.SpecialRouteError, match="frozen qualified identity"):
        sr.load_catalog(tmp_path)


@pytest.mark.parametrize("row_index", [0, 1])
def test_catalog_requires_exactly_16_fields_in_header_and_rows(tmp_path, row_index):
    path = tmp_path / sr.CATALOG_NAME
    rows = list(csv.reader(
        (CHIPDB / sr.CATALOG_NAME).open(newline="", encoding="utf-8")
    ))
    rows[row_index].append("surplus")
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="wrong columns|exactly 16 fields"):
        sr.load_catalog(tmp_path)


@pytest.mark.parametrize(
    "old,new",
    [
        ("X15Y8_RMUX80", "X15Y7_RMUX80"),
        ("2026-07-15-l48-pin25-28-simultaneous",
         "2026-07-15-unreviewed-self-consistent-substitution"),
    ],
)
def test_self_consistent_topology_or_evidence_substitution_still_fails(
        tmp_path, old, new):
    copied = tmp_path / sr.CATALOG_NAME
    text = (CHIPDB / sr.CATALOG_NAME).read_text(encoding="utf-8")
    assert old in text
    copied.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(sr.SpecialRouteError, match="exact reviewed topology/evidence authority"):
        sr.load_catalog(tmp_path)


def test_self_consistent_alternate_catalog_cannot_cross_emission_entries(
        tmp_path, monkeypatch):
    from agamemnon import cli
    from agamemnon.engine import bitgen

    custom = tmp_path / "alternate-chipdb"
    custom.mkdir()
    source = (CHIPDB / sr.CATALOG_NAME).read_text(encoding="utf-8")
    alternate = source.replace("X15Y8_RMUX80", "X15Y7_RMUX80")
    (custom / sr.CATALOG_NAME).write_text(alternate, encoding="utf-8")
    with (custom / sr.CATALOG_NAME).open(newline="", encoding="utf-8") as stream:
        rows = tuple(dict(row) for row in csv.DictReader(stream))
    alternate_digest = hashlib.sha256(sr._canonical_bytes(rows)).hexdigest()
    assert alternate_digest != sr.EXPECTED_CATALOG_SHA256

    document = _document((0,))
    top = document["modules"]["top"]
    top["attributes"][sr.TOKEN_DIGEST] = alternate_digest
    top["cells"]["driver0"]["attributes"][sr.TOKEN_DIGEST] = alternate_digest
    top["netnames"]["lane0"]["attributes"]["ROUTING"] = (
        top["netnames"]["lane0"]["attributes"]["ROUTING"].replace(
            "X15Y8_RMUX80", "X15Y7_RMUX80"
        )
    )
    path = _write(tmp_path, document, "self-consistent-alternate.json")
    match = "exact reviewed topology/evidence authority"
    with pytest.raises(sr.SpecialRouteError, match=match):
        sr.validate_routed_json(path, "bitgen", custom)

    monkeypatch.setenv("AGAMEMNON_DATA", str(custom))
    called = []
    monkeypatch.setattr(cli, "_run_child", lambda *args, **kwargs: called.append(args))
    with pytest.raises(SystemExit) as raised:
        cli.cmd_pack(SimpleNamespace(
            input=str(path), output=str(tmp_path / "direct.bin"), baseline=None,
            research_unsafe=False, qualified_checkpoint=None,
        ))
    assert raised.value.code == 2
    assert called == []

    output = tmp_path / "stale.bin"
    output.write_bytes(b"stale")
    with pytest.raises(SystemExit, match=match):
        bitgen.build(path, output, environ={"AGAMEMNON_DATA": str(custom)})
    assert not output.exists()


@pytest.mark.parametrize(
    "active",
    [subset for size in range(1, 5) for subset in itertools.combinations(range(4), size)],
)
@pytest.mark.parametrize("seed", [4, 2, 7])
def test_all_15_nonempty_lane_subsets_close_for_each_route_seed(tmp_path, active, seed):
    # Seed is intentionally a matrix label: route closure must not encode a
    # placement ordering.  Compiled integration separately invokes these seeds.
    path = _write(tmp_path, _document(active), "seed%d-%s.json" % (seed, "".join(map(str, active))))
    result = sr.validate_routed_json(path, "post-nextpnr", CHIPDB)
    assert result["active_lanes"] == active


def test_owner_departure_to_ordinary_wire_is_rejected(tmp_path):
    path = _write(tmp_path, _document((0,), departure=True))
    with pytest.raises(sr.SpecialRouteError, match="unsupported non-catalog departure"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_owner_departure_must_exist_in_the_selected_devdb_graph(tmp_path):
    document = _document((0,))
    net = document["modules"]["top"]["netnames"]["lane0"]
    net["attributes"]["ROUTING"] += (
        ";X15Y11_RMUX99;X14Y11_OMUX12.X15Y11_RMUX99;1"
    )
    path = _write(tmp_path, document, "graph-absent-departure.json")
    with pytest.raises(sr.SpecialRouteError, match="absent from selected devdb graph"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_active_route_requires_an_explicit_selected_devdb(tmp_path):
    path = _write(tmp_path, _document((0,)))
    environ = {
        "AGAMEMNON_DEVICE": sr.DEVICE,
        "AGAMEMNON_PHYSICAL_IO": "1",
        "AGAMEMNON_LEFT_PAD_OUT": "1",
    }
    with pytest.raises(sr.SpecialRouteError, match="require the selected uarch devdb"):
        sr.validate_routed_json(
            path, "post-nextpnr", CHIPDB, environ=environ, devdb=None,
        )


def test_active_route_uses_the_same_graph_snapshot_that_was_validated(
        tmp_path, monkeypatch):
    path = _write(tmp_path, _document((0,)))
    real_load = sr._devdb_pips
    snapshots = []

    def counted_load(devdb):
        loaded = real_load(devdb)
        snapshots.append(loaded)
        return loaded

    monkeypatch.setattr(sr, "_devdb_pips", counted_load)
    assert sr.validate_routed_json(
        path, "post-nextpnr", CHIPDB,
        environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
    )["active_lanes"] == (0,)
    assert len(snapshots) == 1


@pytest.mark.parametrize("strength", ["", "+1", "-1", "01", "junk", "7", "999"])
def test_every_serialized_route_triple_requires_a_canonical_strength(
        tmp_path, strength):
    document = _document(())
    document["modules"]["top"]["netnames"]["ordinary"] = {
        "bits": [9000],
        "attributes": {"ROUTING": "X0Y0_WIRE0;;%s" % strength},
    }
    path = _write(tmp_path, document, "bad-strength.json")
    with pytest.raises(sr.SpecialRouteError, match="invalid canonical strength"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


@pytest.mark.parametrize(
    "bits",
    [None, [], ["0"], [True], [1, "2"], "100"],
)
def test_every_routing_carrier_requires_exact_nonempty_integer_signal_bits(
        tmp_path, bits):
    document = _document(())
    carrier = {
        "attributes": {"ROUTING": "X0Y0_WIRE0;;1"},
    }
    if bits is not None:
        carrier["bits"] = bits
    document["modules"]["top"]["netnames"]["malformed"] = carrier
    path = _write(tmp_path, document, "malformed-route-carrier.json")
    with pytest.raises(sr.SpecialRouteError, match="nonempty exact integer signal-bit tuple"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


@pytest.mark.parametrize("route", [None, ["not", "text"], 0, False])
def test_nontext_routing_on_an_ordinary_carrier_fails_before_emission(
        tmp_path, route):
    document = _document(())
    document["modules"]["top"]["netnames"]["malformed"] = {
        "bits": [9000], "attributes": {"ROUTING": route},
    }
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="ROUTING attribute.*text"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


def test_route_alias_grouping_uses_the_exact_ordered_integer_tuple(tmp_path):
    document = _document(())
    document["modules"]["top"]["netnames"].update({
        "forward": {
            "bits": [9000, 9001],
            "attributes": {"ROUTING": "X1Y1_RMUX00;;1"},
        },
        "reverse": {
            "bits": [9001, 9000],
            "attributes": {"ROUTING": "X2Y2_RMUX00;;1"},
        },
    })
    path = _write(tmp_path, document)
    assert sr.validate_routed_json(path, "bitgen", CHIPDB)["active_lanes"] == ()


def test_owner_departure_is_rejected_even_when_the_ordinary_static_gate_allows_it(tmp_path):
    document = _document((2,))
    route = document["modules"]["top"]["netnames"]["lane2"]["attributes"]["ROUTING"]
    route += ";X14Y11_OMUX19;X14Y11_OMUX20.X14Y11_OMUX19;1"
    document["modules"]["top"]["netnames"]["lane2"]["attributes"]["ROUTING"] = route
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="unsupported non-catalog departure"):
        sr.validate_routed_json(
            path, "post-nextpnr", CHIPDB, environ=PHYSICAL_ENV,
            devdb=PHYSICAL_DEVDB,
        )


def test_every_owner_edge_must_be_reachable_from_the_exact_source_root(tmp_path):
    document = _document((0,))
    route = document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"]
    route += ";X20Y1_CARRYIN01;X20Y1_CARRYOUT00.X20Y1_CARRYIN01;1"
    document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"] = route
    path = _write(tmp_path, document, "disconnected-graph-present-owner-pip.json")
    with pytest.raises(sr.SpecialRouteError, match="disconnected from exact source root"):
        sr.validate_routed_json(
            path, "bitgen", CHIPDB,
            environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
        )


def test_owner_departure_into_inactive_catalog_lane_fails(tmp_path):
    document = _document((0,))
    route = document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"]
    route += ";X15Y11_RMUX27;X14Y11_OMUX12.X15Y11_RMUX27;1"
    document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"] = route
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="unsupported non-catalog departure"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_partial_import_fails_closed(tmp_path):
    path = _write(tmp_path, _document((1,), partial=1))
    with pytest.raises(sr.SpecialRouteError, match="incomplete"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_direct_pack_rejects_partial_route_before_starting_emitter(
        tmp_path, monkeypatch):
    from agamemnon import cli

    path = _write(tmp_path, _document((1,), partial=1))
    called = []
    monkeypatch.setattr(cli, "_run_child", lambda *args, **kwargs: called.append(args))
    with pytest.raises(SystemExit) as raised:
        cli.cmd_pack(SimpleNamespace(
            input=str(path), output=str(tmp_path / "out.bin"), baseline=None,
            research_unsafe=False, qualified_checkpoint=None,
        ))
    assert raised.value.code == 2
    assert called == []


def test_bitgen_rejects_partial_route_and_removes_stale_output(tmp_path):
    from agamemnon.engine import bitgen

    path = _write(tmp_path, _document((1,), partial=1))
    output = tmp_path / "stale.bin"
    output.write_bytes(b"stale")
    with pytest.raises(SystemExit, match="lane 1 is incomplete"):
        bitgen.build(path, output)
    assert not output.exists()


def test_decoy_marked_module_cannot_hide_the_emitted_top_from_any_entry(
        tmp_path, monkeypatch):
    from agamemnon import cli
    from agamemnon.engine import bitgen

    document = _document((0,), partial=0)
    document["modules"]["top"]["attributes"]["top"] = 0
    document["modules"]["decoy"] = {
        "attributes": {"top": 1}, "cells": {}, "netnames": {},
    }
    path = _write(tmp_path, document, "decoy-top.json")
    match = "physical top marker conflicts with exact modules\\['top'\\] emission module"
    with pytest.raises(sr.SpecialRouteError, match=match):
        sr.validate_routed_json(path, "bitgen", CHIPDB)

    called = []
    monkeypatch.setattr(cli, "_run_child", lambda *args, **kwargs: called.append(args))
    with pytest.raises(SystemExit) as raised:
        cli.cmd_pack(SimpleNamespace(
            input=str(path), output=str(tmp_path / "direct.bin"), baseline=None,
            research_unsafe=False, qualified_checkpoint=None,
        ))
    assert raised.value.code == 2
    assert called == []

    output = tmp_path / "stale.bin"
    output.write_bytes(b"stale")
    with pytest.raises(SystemExit, match=match):
        bitgen.build(path, output)
    assert not output.exists()


def test_wrong_source_port_fails_even_when_it_shares_source_omux(tmp_path):
    path = _write(tmp_path, _document((2,), wrong_port=2))
    with pytest.raises(sr.SpecialRouteError, match=r"must be driven.*\.Q"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_wrong_or_extra_route_root_fails_closed(tmp_path):
    path = _write(tmp_path, _document((0,), root="X14Y11_OMUX99"))
    with pytest.raises(sr.SpecialRouteError, match="exact source root"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_missing_token_and_digest_fail_closed(tmp_path):
    path = _write(tmp_path, _document((3,), tokens=False))
    with pytest.raises(sr.SpecialRouteError, match="token/digest mismatch"):
        sr.validate_routed_json(path, "direct-pack", CHIPDB)


def test_generic_strict_profile_is_inert_but_physical_marker_cannot_be_removed(tmp_path):
    generic = _document((0,), partial=0, tokens=False)
    generic["modules"]["top"]["attributes"] = {"top": 1}
    path = _write(tmp_path, generic, "generic.json")
    assert sr.validate_routed_json(
        path, "bitgen", CHIPDB, environ={}
    )["active_lanes"] == ()

    forged = _document((0,), tokens=False)
    forged["modules"]["top"]["attributes"] = {"top": 1}
    path = _write(tmp_path, forged, "marker-removed.json")
    with pytest.raises(sr.SpecialRouteError, match="lacks authenticated physical-top marker"):
        sr.validate_routed_json(path, "bitgen", CHIPDB, environ={})


def test_disabled_emitted_generic_marker_is_inert(tmp_path):
    generic = _document((2,), partial=2, tokens=False)
    attrs = generic["modules"]["top"]["attributes"]
    attrs[sr.MODULE_ENABLED] = "0"
    path = _write(tmp_path, generic)
    assert sr.validate_routed_json(
        path, "bitgen", CHIPDB, environ={}
    )["active_lanes"] == ()


def test_disabled_marker_cannot_hide_a_complete_physical_lane(tmp_path):
    document = _document((0,), tokens=False)
    document["modules"]["top"]["attributes"][sr.MODULE_ENABLED] = "0"
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="disabled.*complete physical lane"):
        sr.validate_routed_json(path, "bitgen", CHIPDB, environ={})


def test_malformed_enabled_marker_is_not_coerced_to_disabled(tmp_path):
    document = _document((0,))
    document["modules"]["top"]["attributes"][sr.MODULE_ENABLED] = "false"
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="malformed enabled state"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


@pytest.mark.parametrize(
    "key,value",
    [
        (sr.TOKEN_VERSION, "0"),
        (sr.MODULE_DEVICE, "AGRV2KQ48"),
        (sr.MODULE_PACKAGE, "Q48"),
        (sr.MODULE_PROFILE, "generic"),
    ],
)
def test_routed_marker_binds_version_device_package_and_profile(
        tmp_path, key, value):
    document = _document((0,))
    document["modules"]["top"]["attributes"][key] = value
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="physical-top special-route marker drift"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {
            "AGAMEMNON_DEVICE": "AGRV2KQ48",
            "AGAMEMNON_PHYSICAL_IO": "1",
            "AGAMEMNON_LEFT_PAD_OUT": "1",
        },
    ],
)
def test_active_routed_marker_cannot_cross_the_selected_profile(
        tmp_path, environ):
    path = _write(tmp_path, _document((0,)))
    with pytest.raises(sr.SpecialRouteError, match="does not match selected device/profile"):
        sr.validate_routed_json(
            path, "bitgen", CHIPDB, environ=environ, devdb=PHYSICAL_DEVDB,
        )


def test_aliases_must_have_identical_route(tmp_path):
    document = _document((0,))
    top = document["modules"]["top"]
    top["netnames"]["alias"] = {"bits": [100], "attributes": {"ROUTING": " "}}
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="aliases.*disagree"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


@pytest.mark.parametrize("kind", ["pip", "root"])
def test_duplicate_route_serialization_fails_instead_of_set_collapsing(tmp_path, kind):
    document = _document((0,))
    net = document["modules"]["top"]["netnames"]["lane0"]
    parts = net["attributes"]["ROUTING"].split(";")
    duplicate = parts[:3] if kind == "root" else parts[3:6]
    net["attributes"]["ROUTING"] += ";" + ";".join(duplicate)
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="duplicate"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_foreign_net_touching_active_lane_fails(tmp_path):
    document = _document((0,))
    lane = sr.load_catalog(CHIPDB).lanes[0]
    document["modules"]["top"]["netnames"]["foreign"] = {
        "bits": [999], "attributes": {
            "ROUTING": "%s;;1;%s;%s.%s;1" %
            (lane.edges[0].src, lane.edges[0].dst, lane.edges[0].src, lane.edges[0].dst)
        },
    }
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="foreign net"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_cross_lane_owner_touch_fails(tmp_path):
    document = _document((0, 1))
    lane1 = sr.load_catalog(CHIPDB).lanes[1]
    route = document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"]
    route += ";%s;%s.%s;1" % (lane1.edges[0].dst, lane1.edges[0].src, lane1.edges[0].dst)
    document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"] = route
    path = _write(tmp_path, document)
    with pytest.raises(
            sr.SpecialRouteError,
            match="touches active lane|disconnected from exact source root"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_unique_physical_top_ignores_retained_template_modules(tmp_path):
    document = _document((0,))
    document["modules"]["template"] = {"cells": {}, "netnames": {}}
    path = _write(tmp_path, document)
    assert sr.validate_routed_json(path, "post-nextpnr", CHIPDB)["active_lanes"] == (0,)


def test_source_and_sink_cell_types_and_directions_are_hard(tmp_path):
    document = _document((0,))
    document["modules"]["top"]["cells"]["driver0"]["type"] = "OTHER"
    path = _write(tmp_path, document, "bad-driver.json")
    with pytest.raises(sr.SpecialRouteError, match="lacks its exact"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)
    document = _document((0,))
    document["modules"]["top"]["cells"]["sink0"]["port_directions"]["I"] = "output"
    path = _write(tmp_path, document, "bad-sink.json")
    with pytest.raises(
            sr.SpecialRouteError,
            match="connected port direction metadata contradicts known GENERIC_IOB semantics",
    ):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


@pytest.mark.parametrize("cell_name", ["driver0", "sink0"])
@pytest.mark.parametrize("wrong_surface", ["BEL", "NEXTPNR_BEL"])
def test_bel_and_nextpnr_bel_disagreement_fails_closed(
        tmp_path, cell_name, wrong_surface):
    document = _document((0,))
    attrs = document["modules"]["top"]["cells"][cell_name]["attributes"]
    exact = attrs["NEXTPNR_BEL"]
    attrs.update({"BEL": exact, "NEXTPNR_BEL": exact})
    attrs[wrong_surface] = "X14Y8_SLICE0"
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="conflicting BEL/NEXTPNR_BEL"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_missing_routed_file_is_a_fail_closed_validation_error(tmp_path):
    with pytest.raises(sr.SpecialRouteError, match="cannot read routed design"):
        sr.validate_routed_json(tmp_path / "absent.json", "bitgen", CHIPDB)


def test_duplicate_source_sink_occupancy_and_output_driver_fail(tmp_path):
    document = _document((0,))
    top = document["modules"]["top"]
    top["cells"]["sink-duplicate"] = json.loads(json.dumps(top["cells"]["sink0"]))
    path = _write(tmp_path, document, "duplicate-sink.json")
    with pytest.raises(sr.SpecialRouteError, match="duplicate sink BEL occupancy"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)

    document = _document((0,))
    top = document["modules"]["top"]
    top["cells"]["source-duplicate"] = json.loads(json.dumps(top["cells"]["driver0"]))
    top["cells"]["source-duplicate"]["connections"] = {"Q": [777]}
    path = _write(tmp_path, document, "duplicate-source.json")
    with pytest.raises(sr.SpecialRouteError, match="non-unique source BEL occupancy"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)

    document = _document((0,))
    top = document["modules"]["top"]
    top["cells"]["second-output"] = {
        "type": "OTHER", "attributes": {},
        "port_directions": {"O": "output"}, "connections": {"O": [100]},
    }
    path = _write(tmp_path, document, "duplicate-driver.json")
    with pytest.raises(sr.SpecialRouteError, match="non-unique output driver"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


@pytest.mark.parametrize(
    "cell,port,bits",
    [
        ("driver0", "Q", [100, 777]),
        ("driver0", "Q", [100, "0"]),
        ("driver0", "Q", [True]),
        ("sink0", "I", [100, 100]),
        ("sink0", "I", [100, "1"]),
        ("sink0", "I", [False]),
    ],
)
def test_typed_endpoint_ports_are_exact_scalar_integer_signals(
        tmp_path, cell, port, bits):
    document = _document((0,))
    document["modules"]["top"]["cells"][cell]["connections"][port] = bits
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="exactly one integer signal bit"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


def test_owner_q_with_local_functional_fanout_is_rejected(tmp_path):
    document = _document((0,))
    driver = document["modules"]["top"]["cells"]["driver0"]
    driver["port_directions"]["A"] = "input"
    driver["connections"]["A"] = [100]
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="pad-only; additional fabric users"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


def test_r9_shaped_functional_q_plus_internal_observer_fanout_is_rejected(tmp_path):
    document = _document((0,))
    document["modules"]["top"]["cells"]["internal_state_observer"] = {
        "type": "GENERIC_SLICE",
        "attributes": {"NEXTPNR_BEL": "X14Y11_SLICE8"},
        "port_directions": {"A": "input", "F": "output"},
        "connections": {"A": [100], "F": [901]},
    }
    path = _write(tmp_path, document, "r9-functional-q-fanout.json")
    with pytest.raises(sr.SpecialRouteError, match="pad-only; additional fabric users"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


MALFORMED_CONSUMER_DIRECTIONS = (
    "absent-map",
    "null-map",
    "non-object-map",
    "absent-port",
    "null-port",
    "unknown-port",
    "contradictory-port",
)


@pytest.mark.parametrize("form", MALFORMED_CONSUMER_DIRECTIONS)
@pytest.mark.parametrize(
    "phase", ("pre-nextpnr", "post-nextpnr", "pre-emission", "direct-pack", "bitgen"),
)
def test_malformed_connected_consumer_direction_fails_in_every_validator_phase(
        tmp_path, monkeypatch, form, phase):
    _stub_physical_devdb(monkeypatch)
    path = _write(
        tmp_path, _document_with_malformed_fabric_consumer_direction(form),
        "malformed-consumer-%s-%s.json" % (form, phase),
    )
    with pytest.raises(sr.SpecialRouteError, match="connected port direction metadata"):
        sr.validate_routed_json(path, phase, CHIPDB)


@pytest.mark.parametrize("form", MALFORMED_CONSUMER_DIRECTIONS)
def test_direct_pack_rejects_malformed_connected_consumer_before_child(
        tmp_path, monkeypatch, form):
    from agamemnon import cli

    _stub_physical_devdb(monkeypatch)
    path = _write(
        tmp_path, _document_with_malformed_fabric_consumer_direction(form),
        "direct-pack-malformed-consumer-%s.json" % form,
    )
    called = []
    monkeypatch.setattr(cli, "_run_child", lambda *args, **kwargs: called.append(args))
    with pytest.raises(SystemExit) as raised:
        cli.cmd_pack(SimpleNamespace(
            input=str(path), output=str(tmp_path / (form + ".bin")), baseline=None,
            research_unsafe=False, qualified_checkpoint=None,
        ))
    assert raised.value.code == 2
    assert called == []


@pytest.mark.parametrize("form", MALFORMED_CONSUMER_DIRECTIONS)
def test_bitgen_rejects_malformed_connected_consumer_and_removes_stale_output(
        tmp_path, monkeypatch, form):
    from agamemnon.engine import bitgen

    _stub_physical_devdb(monkeypatch)
    path = _write(
        tmp_path, _document_with_malformed_fabric_consumer_direction(form),
        "bitgen-malformed-consumer-%s.json" % form,
    )
    output = tmp_path / (form + ".bin")
    output.write_bytes(b"stale")
    with pytest.raises(SystemExit, match="connected port direction metadata"):
        bitgen.build(path, output)
    assert not output.exists()


def test_dedicated_pad_only_copy_ff_remains_supported(tmp_path):
    document = _document((0,))
    driver = document["modules"]["top"]["cells"]["driver0"]
    driver["parameters"] = {"FF_USED": "1"}
    driver["port_directions"].update({"CLK": "input", "D": "input"})
    driver["connections"].update({"CLK": [902], "D": [903]})
    path = _write(tmp_path, document, "dedicated-pad-copy-ff.json")
    assert sr.validate_routed_json(path, "bitgen", CHIPDB)["active_lanes"] == (0,)


@pytest.mark.parametrize("missing", [True, False])
def test_exact_sink_without_a_fabric_i_net_remains_inactive(tmp_path, missing):
    document = _document(())
    sink = json.loads(json.dumps(_document((0,))["modules"]["top"]["cells"]["sink0"]))
    if missing:
        del sink["connections"]["I"]
    else:
        sink["connections"]["I"] = []
    document["modules"]["top"]["cells"]["inactive-sink"] = sink
    path = _write(tmp_path, document)
    assert sr.validate_routed_json(path, "bitgen", CHIPDB)["active_lanes"] == ()


def test_current_physical_touching_pip_role_matrix_is_exhaustive(
        tmp_path, monkeypatch):
    catalog = sr.load_catalog(CHIPDB)
    graph_path = PHYSICAL_DEVDB / "dev_pips.csv"
    raw = graph_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        # Qualified HSIZE1 restoration minus two nonportable selector rows.
        "1e74dab38f724c6564dacadc66320c77d6a6110f5dc66ffc8c83bc14468d6c8c"
    )
    with graph_path.open(newline="", encoding="utf-8") as stream:
        graph_rows = tuple(csv.DictReader(stream))
    graph = {(row["src"], row["dst"]) for row in graph_rows}
    graph_by_name = {
        row["name"]: (row["src"], row["dst"]) for row in graph_rows
    }
    assert len(graph) == 248305
    touching = sorted(
        edge for edge in graph
        if (edge[0] in catalog.wires or edge[1] in catalog.wires) and
        edge not in catalog.edges
    )
    canonical = "".join("%s,%s\n" % edge for edge in touching).encode("utf-8")
    assert len(touching) == 770
    assert hashlib.sha256(canonical).hexdigest() == (
        "a5e65f02d218a523340f22f85d844e9568361d8700e78cc794415afcafac2d22"
    )
    incoming = [edge for edge in touching if edge[1] in catalog.wires]
    outgoing = [edge for edge in touching if edge[0] in catalog.wires]
    internal = [edge for edge in touching
                if edge[0] in catalog.wires and edge[1] in catalog.wires]
    assert (len(incoming), len(outgoing), len(internal)) == (269, 511, 10)

    # The census above binds the exact current physical graph.  Avoid 7,656
    # redundant catalog reads while still exercising the public validator for
    # every owner and foreign-net role against every noncatalog touching PIP.
    assert sr.validate_devdb(PHYSICAL_DEVDB, CHIPDB) is True
    monkeypatch.setattr(sr, "load_catalog", lambda _root=None: catalog)
    monkeypatch.setattr(
        sr, "_validated_devdb",
        lambda *_args, **_kwargs: (True, graph_by_name, frozenset(range(4))),
    )
    path = tmp_path / "touching-role.json"
    for lane in catalog.lanes:
        base = _document((lane.index,))
        owner_name = "lane%d" % lane.index
        for src, dst in touching:
            document = json.loads(json.dumps(base))
            route = document["modules"]["top"]["netnames"][owner_name]["attributes"]["ROUTING"]
            route += ";%s;%s.%s;1" % (dst, src, dst)
            document["modules"]["top"]["netnames"][owner_name]["attributes"]["ROUTING"] = route
            path.write_text(json.dumps(document), encoding="utf-8")
            should_accept = False
            try:
                sr.validate_routed_json(path, "bitgen", CHIPDB)
            except sr.SpecialRouteError:
                if should_accept:
                    raise AssertionError(
                        "owner lane %d rejected legal departure %s -> %s" %
                        (lane.index, src, dst)
                    )
            else:
                if not should_accept:
                    raise AssertionError(
                        "owner lane %d accepted illegal touching PIP %s -> %s" %
                        (lane.index, src, dst)
                    )

            document = json.loads(json.dumps(base))
            document["modules"]["top"]["netnames"]["foreign"] = {
                "bits": [9000],
                "attributes": {"ROUTING": "%s;;1;%s;%s.%s;1" %
                               (src, dst, src, dst)},
            }
            path.write_text(json.dumps(document), encoding="utf-8")
            touches_active = src in lane.wires or dst in lane.wires
            try:
                sr.validate_routed_json(path, "bitgen", CHIPDB)
            except sr.SpecialRouteError:
                if not touches_active:
                    raise AssertionError(
                        "foreign net lost inactive ordinary semantics at %s -> %s "
                        "with owner lane %d" % (src, dst, lane.index)
                    )
            else:
                if touches_active:
                    raise AssertionError(
                        "foreign net touched active lane %d at %s -> %s" %
                        (lane.index, src, dst)
                    )


def test_stray_token_cannot_claim_an_inactive_lane(tmp_path):
    document = _document((0,))
    document["modules"]["top"]["cells"]["stray"] = {
        "type": "OTHER",
        "attributes": _attrs(sr.load_catalog(CHIPDB).lanes[1]),
        "port_directions": {},
        "connections": {},
    }
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="does not match reconstructed.*lane 1 owner"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_duplicate_token_claim_cannot_hide_on_a_non_owner(tmp_path):
    document = _document((0,))
    attrs = _attrs(sr.load_catalog(CHIPDB).lanes[0])
    del attrs["NEXTPNR_BEL"]
    document["modules"]["top"]["cells"]["duplicate-claim"] = {
        "type": "OTHER",
        "attributes": attrs,
        "port_directions": {},
        "connections": {},
    }
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="lane 0 has duplicate token claims"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def test_partial_token_on_unrelated_cell_fails(tmp_path):
    document = _document((0,))
    document["modules"]["top"]["cells"]["partial-claim"] = {
        "type": "OTHER",
        "attributes": {sr.TOKEN_LANE: "0"},
        "port_directions": {},
        "connections": {},
    }
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="partial special-route lane token"):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


@pytest.mark.parametrize(
    "key,value,match",
    [
        (sr.TOKEN_CLASS, "OTHER", "wrong special-route token class"),
        (sr.TOKEN_VERSION, "0", "wrong special-route token version"),
        (sr.TOKEN_DIGEST, "0" * 64, "wrong special-route token digest"),
        (sr.TOKEN_LANE, "4", "invalid special-route token lane"),
    ],
)
def test_wrong_token_fields_fail_before_they_can_claim_ownership(
        tmp_path, key, value, match):
    document = _document((0,))
    document["modules"]["top"]["cells"]["driver0"]["attributes"][key] = value
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match=match):
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB)


def _write_dev_graph(path, edges, env):
    path.mkdir()
    with (path / "dev_pips.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("name", "type", "src", "dst", "delay_ns", "x", "y", "z"))
        for index, (src, dst) in enumerate(edges):
            writer.writerow((src + "." + dst, "PIP", src, dst, 0, 0, 0, 0))
    catalog = sr.load_catalog(CHIPDB)
    with (path / "dev_bels.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("name", "type", "x", "y", "z"))
        for lane in catalog.lanes:
            writer.writerow((lane.source_bel, "GENERIC_SLICE", 0, 0, lane.index))
            writer.writerow((lane.sink_bel, "GENERIC_IOB", 0, 0, 300 + lane.index))
    with (path / "dev_belpins.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("bel", "pin", "wire", "dir"))
        for lane in catalog.lanes:
            writer.writerow((lane.source_bel, lane.source_port, lane.edges[0].src, "out"))
            writer.writerow((lane.sink_bel, lane.sink_port, lane.edges[-1].dst, "in"))
    with (path / "dev_meta.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("key", "value"))
        writer.writerow(("agamemnon_env", env))


def _copy_physical_devdb(path):
    path.mkdir()
    for name in (
        "dev_pips.csv", "dev_bels.csv", "dev_belpins.csv", "dev_meta.csv",
        sr.DEV_CATALOG_NAME, sr.DEV_META_NAME,
    ):
        shutil.copyfile(PHYSICAL_DEVDB / name, path / name)
    return path


def _direct_d_profile_devdb(path, sites):
    devdb = _copy_physical_devdb(path)
    metadata = devdb / "dev_meta.csv"
    rows = list(csv.reader(metadata.open(newline="", encoding="utf-8")))
    value = r"\;".join("X14Y11_SLICE%d" % z for z in sites)
    for row in rows[1:]:
        if row[0] == "agamemnon_env":
            row[1] += ";AGAMEMNON_DIRECT_D=1;AGAMEMNON_DIRECT_D_SITES=" + value
    with metadata.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    pins = devdb / "dev_belpins.csv"
    rows = list(csv.reader(pins.open(newline="", encoding="utf-8")))
    selected = sites or (4, 5, 6, 7)
    for row in rows[1:]:
        for z in selected:
            if row[:2] == ["X14Y11_SLICE%d" % z, "Q"]:
                row[2] = "X14Y11_OMUX%02d" % (3*z+1)
    with pins.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    return devdb


@pytest.mark.parametrize("sites", [
    subset for size in range(5) for subset in itertools.combinations(range(4, 8), size)
])
def test_direct_d_profile_validates_exact_endpoints_and_available_lanes(tmp_path, sites):
    devdb = _direct_d_profile_devdb(tmp_path / "profile", sites)
    enabled, _, available = sr._validated_devdb(devdb, CHIPDB)
    selected = sites or (4, 5, 6, 7)
    assert enabled is True
    assert available == frozenset(z - 4 for z in range(4, 8) if z < 6 or z not in selected)


@pytest.mark.parametrize("active", [(), (0,), (1,), (2,), (3,)])
def test_direct_d_profile_rejects_only_incompatible_active_pad_owners(tmp_path, active):
    devdb = _direct_d_profile_devdb(tmp_path / "profile", (4, 5, 6, 7))
    path = _write(tmp_path, _document(active))
    if active and active[0] >= 2:
        with pytest.raises(sr.SpecialRouteError, match="incompatible.*direct-D graph profile"):
            sr.validate_routed_json(path, "post-nextpnr", CHIPDB, environ=PHYSICAL_ENV, devdb=devdb)
    else:
        sr.validate_routed_json(path, "post-nextpnr", CHIPDB, environ=PHYSICAL_ENV, devdb=devdb)


def test_direct_d_profile_still_rejects_unexpected_inactive_endpoint(tmp_path):
    devdb = _direct_d_profile_devdb(tmp_path / "profile", (6,))
    path = devdb / "dev_belpins.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    for row in rows[1:]:
        if row[:2] == ["X14Y11_SLICE6", "Q"]:
            row[2] = "X14Y11_OMUX20"
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="BEL-pin endpoint drift"):
        sr.validate_devdb(devdb, CHIPDB)


def _replace_metadata_value(path, key, value):
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    matches = [row for row in rows[1:] if row and row[0] == key]
    assert len(matches) == 1
    matches[0][1] = str(value)
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)


def _bind_dev_meta(path, meta):
    with (path / "dev_meta.csv").open("a", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("special_route_class", meta["class"]))
        writer.writerow(("special_route_enabled", meta["enabled"]))
        writer.writerow(("special_route_catalog_sha256", meta["catalog_sha256"]))


def test_generic_ledpads_profile_is_explicitly_disabled(tmp_path):
    catalog = sr.load_catalog(CHIPDB)
    devdb = tmp_path / "generic"
    _write_dev_graph(devdb, list(catalog.edges)[:27], "AGAMEMNON_LEDPADS=1")
    meta = sr.emit_devdb_metadata(
        devdb, CHIPDB, {"AGAMEMNON_LEDPADS": "1"}, list(catalog.edges)[:27])
    _bind_dev_meta(devdb, meta)
    assert meta["enabled"] == "0"
    assert sr.validate_devdb(devdb, CHIPDB) is False
    routed = _write(tmp_path, _document((0,)), "active-with-generic-devdb.json")
    with pytest.raises(sr.SpecialRouteError, match="enabled physical-I/O devdb"):
        sr.validate_routed_json(
            routed, "bitgen", CHIPDB,
            environ=PHYSICAL_ENV, devdb=devdb,
        )


def test_physical_profile_requires_complete_graph_and_digest(tmp_path):
    devdb = _copy_physical_devdb(tmp_path / "physical")
    assert sr.validate_devdb(devdb, CHIPDB) is True
    _replace_metadata_value(devdb / sr.DEV_META_NAME, "catalog_sha256", "0" * 64)
    with pytest.raises(sr.SpecialRouteError, match="catalog_sha256 drift"):
        sr.validate_devdb(devdb, CHIPDB)


def test_cold_physical_devdb_rebuild_reaches_final_bitgen_byte_identically(tmp_path):
    """A source-fresh graph, not an inherited cache, closes final emission."""
    from agamemnon.engine import bitgen

    root = Path(__file__).parents[1]
    cold_devdb = tmp_path / "never-created-before-test" / "devdb_strict_pcf"
    assert not cold_devdb.exists()
    command = [
        sys.executable,
        str(root / "agamemnon" / "engine" / "emit_uarch_db.py"),
        "--arch", str(root / "agamemnon" / "engine" / "arch.py"),
        "--data", str(CHIPDB),
        "--out", str(cold_devdb),
    ]
    for item in (
        "AGAMEMNON_CONDUCTION_GATE=1",
        "AGAMEMNON_HW_CARRY=1",
        "AGAMEMNON_LEDPADS=1",
        "AGAMEMNON_STRICT_GATE=1",
        "AGAMEMNON_XBAR_CONDUCT=1",
        "AGAMEMNON_CLEAN_SEL_GATE=1",
        "AGAMEMNON_PHYSICAL_IO=1",
        "AGAMEMNON_PADFEED_TOP=1",
        "AGAMEMNON_HARDEN_PADFEED=1",
        "AGAMEMNON_LEFT_PAD_OUT=1",
    ):
        command.extend(("--env", item))
    emitted = subprocess.run(
        command, cwd=root, text=True, capture_output=True, timeout=90,
    )
    assert emitted.returncode == 0, emitted.stdout + emitted.stderr
    runtime_assets = (
        "clock_reach_silicon_negative.csv",
        "master_conduction.csv", "mcu_ahb32_corridors.csv",
        "mcu_ahb32_pip_cfg.csv",
        "mcu_ahb32_addr_corridors.csv", "mcu_logic_consumer_footprints.csv",
        "mcu_endpoint_capabilities.csv",
        "mcu_endpoint_capability_manifest.json",
        "mcu_hwdata_lanes.csv",
        "mcu_slave_ahb_request_control_independent_paths.csv",
        "mcu_slave_ahb_request_payload_paths.csv",
        "mcu_slave_ahb_haddr2_dynamic_paths.csv",
        "mcu_slave_ahb_haddr29_sram_base_paths.csv",
        "mcu_region_witness.csv", "soft_ripple_region_witness.csv",
        "pad_oe_L48_left_corridors.csv", "pad_input_L48_left_corridors.csv",
        "bram_tmux9_source_paths.csv",
    )
    for name in runtime_assets:
        source = CHIPDB / name
        if source.is_file():
            shutil.copyfile(source, cold_devdb / name)
    assert all((cold_devdb / name).is_file() for name in runtime_assets)

    graph_path = cold_devdb / "dev_pips.csv"
    raw_graph = graph_path.read_bytes()
    assert raw_graph.count(b"\n") - 1 == sr.EXPECTED_PHYSICAL_GRAPH_PIP_COUNT
    assert hashlib.sha256(raw_graph).hexdigest() == sr.EXPECTED_PHYSICAL_GRAPH_SHA256
    with graph_path.open(newline="", encoding="utf-8") as stream:
        rows = tuple(csv.DictReader(stream))
    assert sum(row["type"] == "SLICE_QFB" for row in rows) == 2112
    assert sr.validate_devdb(cold_devdb, CHIPDB) is True

    routed = _write(tmp_path, _pad_only_document_from_retained(), "cold-pad-only.json")
    cold_output = tmp_path / "cold.comp"
    control_output = tmp_path / "control.comp"
    bitgen.build(
        routed,
        cold_output,
        environ=_physical_env(**{sr.DEVDB_ENV: str(cold_devdb)}),
    )
    bitgen.build(routed, control_output, environ=PHYSICAL_ENV)
    assert cold_output.read_bytes() == control_output.read_bytes()


def test_source_fresh_tiered_physical_devdb_matches_pinned_graph(tmp_path):
    root = Path(__file__).parents[1]
    devdb = tmp_path / "never-created-before-test" / "devdb_tiered_pcf"
    assert not devdb.exists()
    command = [
        sys.executable,
        str(root / "agamemnon" / "engine" / "emit_uarch_db.py"),
        "--arch", str(root / "agamemnon" / "engine" / "arch.py"),
        "--data", str(CHIPDB),
        "--out", str(devdb),
    ]
    for item in sr.SOURCE_FRESH_PHYSICAL_ENV + (
            "AGAMEMNON_ROUTING_ADMISSION=tiered",):
        command.extend(("--env", item))
    emitted = subprocess.run(
        command, cwd=root, text=True, capture_output=True, timeout=90,
    )
    assert emitted.returncode == 0, emitted.stdout + emitted.stderr

    graph_path = devdb / "dev_pips.csv"
    raw_graph = graph_path.read_bytes()
    assert raw_graph.count(b"\n") - 1 == sr.EXPECTED_TIERED_PHYSICAL_GRAPH_PIP_COUNT
    assert hashlib.sha256(raw_graph).hexdigest() == sr.EXPECTED_TIERED_PHYSICAL_GRAPH_SHA256
    assert sr.validate_devdb(devdb, CHIPDB) is True

    with graph_path.open("a", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow((
            "FAKE_TILE_OMUX00.FAKE_TILE_RMUX00", "PIP",
            "FAKE_TILE_OMUX00", "FAKE_TILE_RMUX00", 0, 0, 0, 0,
        ))
    digest = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    _replace_metadata_value(
        devdb / sr.DEV_META_NAME, "graph_pip_count",
        sr.EXPECTED_TIERED_PHYSICAL_GRAPH_PIP_COUNT + 1,
    )
    _replace_metadata_value(devdb / sr.DEV_META_NAME, "graph_pips_sha256", digest)
    _replace_metadata_value(
        devdb / "dev_meta.csv", "n_pips",
        sr.EXPECTED_TIERED_PHYSICAL_GRAPH_PIP_COUNT + 1,
    )
    with pytest.raises(sr.SpecialRouteError, match="physical graph identity drift"):
        sr.validate_devdb(devdb, CHIPDB)


def test_exact_retained_observation_fanout_is_hash_bound_and_cross_eol(tmp_path):
    root = Path(__file__).parents[1]
    retained = root / "qualification" / "pad_uarch_left_edge_outputs_routed.json"
    canonical = retained.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    assert hashlib.sha256(canonical).hexdigest() == sr.LEGACY_RETAINED_SHA256

    for name, raw in (
            ("lf.json", canonical),
            ("crlf.json", canonical.replace(b"\n", b"\r\n"))):
        path = tmp_path / name
        path.write_bytes(raw)
        result = sr.validate_routed_json(
            path, "direct-pack", CHIPDB,
            environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
        )
        assert result["active_lanes"] == (0, 1, 2, 3)
        assert result["legacy_retained"] is True


def test_modified_retained_observation_checkpoint_loses_legacy_authority(tmp_path):
    root = Path(__file__).parents[1]
    retained = root / "qualification" / "pad_uarch_left_edge_outputs_routed.json"
    modified = retained.read_bytes().replace(b'"creator":', b'"creator" :', 1)
    assert modified != retained.read_bytes()
    path = tmp_path / "modified.json"
    path.write_bytes(modified)
    with pytest.raises(sr.SpecialRouteError, match="enabled state"):
        sr.validate_routed_json(
            path, "direct-pack", CHIPDB,
            environ=PHYSICAL_ENV, devdb=PHYSICAL_DEVDB,
        )


def test_source_fresh_physical_devdb_refuses_a_nonempty_target(tmp_path):
    target = tmp_path / "nonempty"
    target.mkdir()
    (target / "stale.txt").write_text("stale", encoding="utf-8")
    with pytest.raises(sr.SpecialRouteError, match="not empty"):
        sr.emit_source_fresh_physical_devdb(target, CHIPDB)


def test_physical_profile_rejects_recomputed_arbitrary_extra_pip_authority(tmp_path):
    devdb = _copy_physical_devdb(tmp_path / "extra-pip")
    graph_path = devdb / "dev_pips.csv"
    with graph_path.open("a", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow((
            "FAKE_TILE_OMUX00.FAKE_TILE_RMUX00", "PIP",
            "FAKE_TILE_OMUX00", "FAKE_TILE_RMUX00", 0, 0, 0, 0,
        ))
    digest = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    _replace_metadata_value(
        devdb / sr.DEV_META_NAME, "graph_pip_count",
        sr.EXPECTED_PHYSICAL_GRAPH_PIP_COUNT + 1,
    )
    _replace_metadata_value(
        devdb / sr.DEV_META_NAME, "graph_pips_sha256", digest,
    )
    _replace_metadata_value(
        devdb / "dev_meta.csv", "n_pips",
        sr.EXPECTED_PHYSICAL_GRAPH_PIP_COUNT + 1,
    )
    with pytest.raises(sr.SpecialRouteError, match="physical graph identity drift"):
        sr.validate_devdb(devdb, CHIPDB)


@pytest.mark.parametrize(
    "file_name,row_index,match",
    [
        (sr.DEV_CATALOG_NAME, 0, "wrong columns"),
        (sr.DEV_CATALOG_NAME, 1, "exactly 16 fields"),
        (sr.DEV_META_NAME, 0, "wrong columns"),
        (sr.DEV_META_NAME, 1, "exactly 2 fields"),
        ("dev_meta.csv", 0, "wrong columns"),
        ("dev_meta.csv", 1, "exactly 2 fields"),
    ],
)
def test_python_devdb_validator_rejects_surplus_csv_fields(
        tmp_path, file_name, row_index, match):
    devdb = _copy_physical_devdb(tmp_path / "surplus-field-devdb")
    path = devdb / file_name
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[row_index].append("surplus")
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match=match):
        sr.validate_devdb(devdb, CHIPDB)


@pytest.mark.parametrize(
    "env, match",
    [
        (
            "AGAMEMNON_LEFT_PAD_OUT=11;AGAMEMNON_PHYSICAL_IO=10",
            "profile/cache mismatch",
        ),
        (
            "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1;"
            "AGAMEMNON_PHYSICAL_IO=1",
            "agamemnon_env summary is malformed",
        ),
        ("AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO", "summary is malformed"),
    ],
)
def test_physical_profile_environment_requires_exact_unique_tokens(tmp_path, env, match):
    devdb = _copy_physical_devdb(tmp_path / "malformed-physical")
    _replace_metadata_value(devdb / "dev_meta.csv", "agamemnon_env", env)
    with pytest.raises(sr.SpecialRouteError, match=match):
        sr.validate_devdb(devdb, CHIPDB)


@pytest.mark.parametrize(
    "value",
    [
        "X14Y11_SLICE4",
        "X14Y11_SLICE4;X14Y11_SLICE5;X14Y11_SLICE6;X14Y11_SLICE7",
        "a" + chr(92) + "b",
        "",
    ],
)
def test_env_summary_round_trips_values_containing_the_delimiter(value):
    """A value may contain the record's own separator.

    AGAMEMNON_DIRECT_D_SITES, AGAMEMNON_DIRECT_D_EXTRA_SITES and
    AGAMEMNON_VENDOR_OUT_SLICE are semicolon-separated lists carried inside a
    semicolon-separated record.  Unescaped, a two-site direct-D value turned
    every site after the first into a token with no "=" and the whole record was
    rejected, so no multi-site direct-D build could complete.
    """
    escaped = value.replace(chr(92), chr(92) * 2).replace(";", chr(92) + ";")
    record = "AGAMEMNON_DIRECT_D=1;AGAMEMNON_DIRECT_D_SITES=%s;AGAMEMNON_STRICT_GATE=1" % escaped
    parsed = sr._parse_env_summary(record)
    assert parsed["AGAMEMNON_DIRECT_D_SITES"] == value
    assert parsed["AGAMEMNON_DIRECT_D"] == "1"
    assert parsed["AGAMEMNON_STRICT_GATE"] == "1"


def test_env_summary_still_rejects_a_dangling_escape():
    with pytest.raises(sr.SpecialRouteError, match="dangling escape"):
        sr._parse_env_summary("A=1;B=2" + chr(92))


def test_python_devdb_validator_binds_named_pip_to_actual_endpoints(tmp_path):
    devdb = _copy_physical_devdb(tmp_path / "named-pip-drift")
    path = devdb / "dev_pips.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][0] = "SPOOFED.PIP.NAME"
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="named PIP endpoint drift"):
        sr.validate_devdb(devdb, CHIPDB)


@pytest.mark.parametrize(
    "file_name, identity, column, value",
    [
        ("dev_bels.csv", ("X14Y11_SLICE4",), 1, "OTHER"),
        ("dev_belpins.csv", ("X14Y11_SLICE4", "Q"), 2, "X14Y11_OMUX14"),
        ("dev_belpins.csv", ("X14Y11_SLICE4", "Q"), 3, "in"),
        ("dev_belpins.csv", ("X0Y4_IOB0", "I"), 2, "X0Y4_IOMUX01"),
        ("dev_belpins.csv", ("X0Y4_IOB0", "I"), 3, "out"),
    ],
)
def test_python_devdb_validator_binds_bel_pin_endpoint_identity(
        tmp_path, file_name, identity, column, value):
    devdb = _copy_physical_devdb(tmp_path / "bel-pin-drift")
    path = devdb / file_name
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    row_index = next(
        index for index, row in enumerate(rows[1:], 1)
        if tuple(row[:len(identity)]) == identity
    )
    rows[row_index][column] = value
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="BEL-pin endpoint drift"):
        sr.validate_devdb(devdb, CHIPDB)


def test_python_devdb_validator_rejects_catalog_row_reordering(tmp_path):
    devdb = _copy_physical_devdb(tmp_path / "physical-reordered")
    path = devdb / sr.DEV_CATALOG_NAME
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1], rows[2] = rows[2], rows[1]
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="catalog/cache digest drift"):
        sr.validate_devdb(devdb, CHIPDB)


def test_exact_retained_observation_does_not_bypass_profile_selection(monkeypatch):
    retained = Path(__file__).parents[1] / "qualification" / "pad_uarch_left_edge_outputs_routed.json"
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == sr.LEGACY_RETAINED_SHA256
    monkeypatch.delenv("AGAMEMNON_PHYSICAL_IO")
    monkeypatch.delenv("AGAMEMNON_LEFT_PAD_OUT")
    monkeypatch.delenv(sr.DEVDB_ENV)
    result = sr.validate_routed_json(retained, "bitgen", CHIPDB)
    assert result["active_lanes"] == ()
    assert result["legacy_retained"] is False


@pytest.mark.parametrize(
    "name,digest,active",
    [
        ("serv_blinky_L48_routed.json",
         "2fbb058fdfc8a054917aba6e9d0b3bae5a9164b3bbfe962c4c05b7042493d805", ()),
        ("serv_rv32i_heartbeat_L48_routed.json",
         "e3cec1567e1dbcd6aafb9b734407c13b8c3e469fced23ac84eb62286eecaf576", ()),
        ("serv_rv32i_smoke_L48_routed.json",
         "4ffe1076ce65a9a2e0bbbdcbeb67900c6c6249367b3c4f7da41210fdec4563d2", ()),
    ],
)
def test_authenticated_markerless_retained_routes_are_exact_hash_only(
        tmp_path, name, digest, active):
    retained = Path(__file__).parents[1] / "qualification" / name
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == digest
    result = sr.validate_routed_json(retained, "bitgen", CHIPDB)
    assert result["active_lanes"] == active
    assert result["legacy_retained"] is True

    document = json.loads(retained.read_text(encoding="utf-8"))
    changed = _write(tmp_path, document, name)
    assert changed.name == retained.name
    assert changed.read_bytes() != retained.read_bytes()
    with pytest.raises(
            sr.SpecialRouteError,
            match="lacks authenticated physical-top marker|does not match selected device/profile",
    ):
        sr.validate_routed_json(changed, "bitgen", CHIPDB)


def test_cpp_authority_is_exact_digest_bound_and_static_gate_is_first():
    source = (Path(__file__).parents[1] / "agamemnon" / "engine" / "uarch" /
              "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    digest = sr.load_catalog(CHIPDB).digest
    assert digest == sr.EXPECTED_CATALOG_SHA256
    assert 'static const char *exact_catalog_digest' in source
    assert digest in source
    predicate = source[source.index("bool checkPipAvailForNet("):]
    predicate = predicate[:predicate.index("void notifyPipChange")]
    assert predicate.index("if (!checkPipAvail(pip))") < predicate.index(
        "special_route_pip_legal(pip, net)")
    packer = source[source.index("static void pack_output_pin_drivers"):]
    packer = packer[:packer.index("static void lock_uart_tx_corridors")]
    assert "ctx->bindPip" not in packer


def test_cli_revalidates_once_then_publishes_bound_artifacts_after_products():
    source = (Path(__file__).parents[1] / "agamemnon" / "cli.py").read_text(
        encoding="utf-8"
    )
    tail = source[source.index("if qualified_bram_source:"):]
    canonicalize = tail.index("QBW.canonicalize_routed_file")
    final_validation = tail.index('routed_json, "pre-emission", chipdb_root=data')
    portable = tail.index("_write_portable_routed_json")
    internal_confidence = tail.index("_write_confidence_manifest", portable)
    bitgen = tail.index('log = run(\n        "bitgen"')
    final_confidence = tail.index("_write_confidence_manifest", bitgen)
    assert (canonicalize < final_validation < portable < internal_confidence <
            bitgen < final_confidence)
    assert "routed_sha256=final_snapshot.sha256" in tail


def test_confidence_manifest_is_hash_bound_and_release_strict_removes_stale(
        tmp_path, monkeypatch):
    from agamemnon import cli

    routed = tmp_path / "routed.json"
    raw = json.dumps(_document(())).encode("utf-8")
    routed.write_bytes(raw)
    snapshot = sr.load_validated_routed_json(routed, "pre-emission", CHIPDB)
    output = tmp_path / "image.bin"
    output.write_bytes(b"image")
    stale = Path(str(output) + ".confidence.json")
    stale.write_text("stale", encoding="utf-8")
    assert cli._write_confidence_manifest(
        routed_json=str(routed),
        devdb="unused",
        output=str(output),
        sources=["design.v"],
        device="AGRV2KL48",
        admission="release-strict",
        routed_sha256=snapshot.sha256,
        routed_document=snapshot.document,
    ) is None
    assert not stale.exists()

    from agamemnon.engine import routing_tiers
    monkeypatch.setattr(routing_tiers, "load_sidecar", lambda _path: {"unused": {}})
    monkeypatch.setattr(routing_tiers, "load_sidecar_meta", lambda _path: {})
    path = cli._write_confidence_manifest(
        routed_json=str(routed),
        devdb="devdb-tiered",
        output=str(output),
        sources=["design.v"],
        device="AGRV2KL48",
        admission="tiered",
        routed_sha256=snapshot.sha256,
        routed_document=snapshot.document,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["bindings"] == {
        "routed_sha256": snapshot.sha256,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def test_bitgen_emits_and_binds_one_validated_snapshot_after_path_mutation(
        tmp_path, monkeypatch):
    """Every emitter consumer stays on the bytes validated before a path swap."""
    from agamemnon.engine import bitgen

    raw = (json.dumps(_pad_only_document_from_retained(), sort_keys=True) + "\n").encode("utf-8")
    expected_digest = hashlib.sha256(raw).hexdigest()
    control = tmp_path / "control.json"
    attacked = tmp_path / "attacked.json"
    control.write_bytes(raw)
    attacked.write_bytes(raw)
    control_output = tmp_path / "control.comp"
    attacked_output = tmp_path / "attacked.comp"
    sidecar = tmp_path / "attacked.policy.json"
    bitgen.build(control, control_output, environ=PHYSICAL_ENV)

    real_load = sr.load_validated_routed_json

    def load_then_mutate(path, phase, chipdb_root=None, environ=None, devdb=None):
        snapshot = real_load(
            path, phase, chipdb_root, environ=environ, devdb=devdb,
        )
        if Path(path) == attacked:
            changed = json.loads(attacked.read_bytes())
            lane = sr.load_catalog(CHIPDB).lanes[0]
            forbidden = "%s.%s" % (lane.edges[-1].src, lane.edges[-1].dst)
            removed = False
            for net in changed["modules"]["top"]["netnames"].values():
                route = (net.get("attributes") or {}).get("ROUTING")
                if not route or not route.strip():
                    continue
                parts = route.rstrip(";").split(";")
                triples = [parts[i:i + 3] for i in range(0, len(parts), 3)]
                assert all(len(triple) == 3 for triple in triples)
                kept = [triple for triple in triples if triple[1] != forbidden]
                if len(kept) != len(triples):
                    net["attributes"]["ROUTING"] = ";".join(
                        item for triple in kept for item in triple)
                    removed = True
            assert removed
            attacked.write_text(json.dumps(changed), encoding="utf-8")
        return snapshot

    monkeypatch.setattr(sr, "load_validated_routed_json", load_then_mutate)
    bitgen.build(
        attacked,
        attacked_output,
        environ=_physical_env(
            AGAMEMNON_STRICT_POLICY="experimental-strict",
            AGAMEMNON_POLICY_SIDECAR=str(sidecar),
            AGAMEMNON_VALIDATED_ROUTED_SHA256=expected_digest,
        ),
    )
    assert attacked_output.read_bytes() == control_output.read_bytes()
    binding = json.loads(sidecar.read_text(encoding="utf-8"))["bindings"]
    assert binding["routed_sha256"] == expected_digest
    assert hashlib.sha256(attacked.read_bytes()).hexdigest() != expected_digest


def test_bitgen_rejects_graph_present_disconnected_owner_pip_before_emission(
        tmp_path):
    """Regression for the prior byte-identical disconnected-PIP emission."""
    from agamemnon.engine import bitgen

    control_document = _pad_only_document_from_retained()
    catalog = sr.load_catalog(CHIPDB)
    top = control_document["modules"]["top"]
    top["attributes"].update({
        sr.MODULE_SCHEMA: sr.SCHEMA,
        sr.TOKEN_CLASS: sr.CLASS,
        sr.TOKEN_VERSION: sr.ROUTED_VERSION,
        sr.MODULE_DEVICE: sr.DEVICE,
        sr.MODULE_PACKAGE: sr.PACKAGE,
        sr.MODULE_PROFILE: sr.PROFILE,
        sr.MODULE_ENABLED: "1",
        sr.TOKEN_DIGEST: catalog.digest,
    })
    owner_bits = {}
    for lane in catalog.lanes:
        candidates = [
            cell for cell in top["cells"].values()
            if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
            and lane.source_port in (cell.get("connections") or {})
        ]
        assert len(candidates) == 1
        owner = candidates[0]
        owner["attributes"].update(_attrs(lane))
        owner_bits[lane.index] = owner["connections"][lane.source_port][0]

    attacked_document = json.loads(json.dumps(control_document))
    lane0_net = next(
        net for net in attacked_document["modules"]["top"]["netnames"].values()
        if net.get("bits") == [owner_bits[0]] and
        "ROUTING" in (net.get("attributes") or {})
    )
    route = lane0_net["attributes"]["ROUTING"]
    route += ";X20Y1_CARRYIN01;X20Y1_CARRYOUT00.X20Y1_CARRYIN01;1"
    lane0_net["attributes"]["ROUTING"] = route
    control = _write(tmp_path, control_document, "connected-control.json")
    attacked = _write(tmp_path, attacked_document, "disconnected-attack.json")
    control_output = tmp_path / "connected-control.comp"
    attacked_output = tmp_path / "disconnected-attack.comp"

    bitgen.build(control, control_output, environ=PHYSICAL_ENV)
    assert control_output.is_file()
    with pytest.raises(SystemExit, match="disconnected from exact source root"):
        bitgen.build(attacked, attacked_output, environ=PHYSICAL_ENV)
    assert not attacked_output.exists()


@pytest.mark.parametrize("expected", ["0" * 64, "not-a-sha256"])
def test_bitgen_rejects_parent_snapshot_digest_mismatch_and_removes_stale_output(
        tmp_path, expected):
    from agamemnon.engine import bitgen

    path = _write(tmp_path, _document((0,)))
    output = tmp_path / "stale.comp"
    output.write_bytes(b"stale")
    match = ("snapshot SHA-256 mismatch" if len(expected) == 64
             else "snapshot SHA-256 is malformed")
    with pytest.raises(SystemExit, match=match):
        bitgen.build(
            path,
            output,
            environ=_physical_env(AGAMEMNON_VALIDATED_ROUTED_SHA256=expected),
        )
    assert not output.exists()


def test_direct_release_bitgen_removes_default_and_explicit_stale_policy_sidecars(
        tmp_path):
    from agamemnon.engine import bitgen

    retained = _write(
        tmp_path, _pad_only_document_from_retained(), "release-pad-only.json")
    output = tmp_path / "release.comp"
    default_sidecar = Path(str(output) + ".policy.json")
    explicit_sidecar = tmp_path / "explicit.policy.json"
    default_sidecar.write_text("stale-default", encoding="utf-8")
    explicit_sidecar.write_text("stale-explicit", encoding="utf-8")
    bitgen.build(
        retained,
        output,
        environ=_physical_env(AGAMEMNON_POLICY_SIDECAR=str(explicit_sidecar)),
    )
    assert output.is_file()
    assert not default_sidecar.exists()
    assert not explicit_sidecar.exists()


def test_direct_bitgen_refusal_removes_default_and_explicit_stale_policy_sidecars(
        tmp_path):
    from agamemnon.engine import bitgen

    routed = _write(tmp_path, _document((1,), partial=1), "partial-sidecar.json")
    output = tmp_path / "refused.comp"
    default_sidecar = Path(str(output) + ".policy.json")
    explicit_sidecar = tmp_path / "refused-explicit.policy.json"
    default_sidecar.write_text("stale-default", encoding="utf-8")
    explicit_sidecar.write_text("stale-explicit", encoding="utf-8")
    with pytest.raises(SystemExit, match="lane 1 is incomplete"):
        bitgen.build(
            routed,
            output,
            environ=_physical_env(AGAMEMNON_POLICY_SIDECAR=str(explicit_sidecar)),
        )
    assert not output.exists()
    assert not default_sidecar.exists()
    assert not explicit_sidecar.exists()


def test_bitgen_rejects_ownership_trace_alias_without_overwriting_image(tmp_path):
    from agamemnon.engine import bitgen

    retained = _write(
        tmp_path, _pad_only_document_from_retained(), "trace-alias-pad-only.json")
    output = tmp_path / "trace-alias.comp"
    with pytest.raises(SystemExit, match="emission products alias"):
        bitgen.build(
            retained,
            output,
            environ=_physical_env(AGAMEMNON_OWNERSHIP_TRACE=str(output)),
        )
    assert not output.exists()


def test_bitgen_refusal_removes_stale_ownership_trace(tmp_path):
    from agamemnon.engine import bitgen

    routed = _write(tmp_path, _document((1,), partial=1), "partial-trace.json")
    output = tmp_path / "trace-refused.comp"
    trace = tmp_path / "trace.json"
    trace.write_text("stale-trace", encoding="utf-8")
    with pytest.raises(SystemExit, match="lane 1 is incomplete"):
        bitgen.build(
            routed,
            output,
            environ=_physical_env(AGAMEMNON_OWNERSHIP_TRACE=str(trace)),
        )
    assert not output.exists()
    assert not trace.exists()


def test_mandatory_policy_sidecar_failure_rolls_back_image_and_trace(tmp_path):
    from agamemnon.engine import bitgen

    retained = _write(
        tmp_path, _pad_only_document_from_retained(), "transaction-pad-only.json")
    output = tmp_path / "transaction.comp"
    trace = tmp_path / "transaction.trace.json"
    missing_sidecar = tmp_path / "absent" / "policy.json"
    with pytest.raises(OSError):
        bitgen.build(
            retained,
            output,
            environ=_physical_env(
                AGAMEMNON_STRICT_POLICY="experimental-strict",
                AGAMEMNON_POLICY_SIDECAR=str(missing_sidecar),
                AGAMEMNON_OWNERSHIP_TRACE=str(trace),
            ),
        )
    assert not output.exists()
    assert not trace.exists()
    assert not missing_sidecar.exists()
