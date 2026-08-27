import csv
import hashlib
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon.engine import special_routes as sr


CHIPDB = Path(__file__).parents[1] / "agamemnon" / "chipdb"
PHYSICAL_DEVDB = (Path(__file__).parents[1] / "agamemnon" / "engine" /
                  "uarch" / "agrv2k" / "devdb_tiered_pcf")


def _attrs(lane):
    return {
        "NEXTPNR_BEL": lane.source_bel,
        sr.TOKEN_CLASS: sr.CLASS,
        sr.TOKEN_LANE: str(lane.index),
        sr.TOKEN_DIGEST: sr.load_catalog(CHIPDB).digest,
    }


def _route(lane, *, partial=False, root=None, departure=False):
    edges = lane.edges[:-1] if partial else lane.edges
    triples = [root if root is not None else lane.edges[0].src, "", "1"]
    for edge in edges:
        triples += [edge.dst, edge.src + "." + edge.dst, "5"]
    if departure:
        triples += ["X15Y11_RMUX99", lane.edges[0].src + ".X15Y11_RMUX99", "1"]
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
            sr.MODULE_PROFILE: sr.PROFILE,
            sr.MODULE_ENABLED: "1",
            sr.TOKEN_DIGEST: catalog.digest,
        },
        "cells": cells, "netnames": nets,
    }}}


def _write(tmp_path, document, name="route.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


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


def test_owner_departure_to_ordinary_wire_is_allowed(tmp_path):
    path = _write(tmp_path, _document((0,), departure=True))
    assert sr.validate_routed_json(path, "post-nextpnr", CHIPDB)["active_lanes"] == (0,)


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


def test_owner_departure_must_pass_the_ordinary_static_pip_gate(tmp_path):
    document = _document((2,))
    route = document["modules"]["top"]["netnames"]["lane2"]["attributes"]["ROUTING"]
    route += ";X14Y11_OMUX19;X14Y11_OMUX20.X14Y11_OMUX19;1"
    document["modules"]["top"]["netnames"]["lane2"]["attributes"]["ROUTING"] = route
    path = _write(tmp_path, document)
    assert sr.validate_routed_json(
        path, "post-nextpnr", CHIPDB, environ={}
    )["active_lanes"] == (2,)
    with pytest.raises(sr.SpecialRouteError, match="statically unavailable PIP"):
        sr.validate_routed_json(
            path,
            "post-nextpnr",
            CHIPDB,
            environ={"AGRV2K_NO_FBBRIDGE": "1"},
        )


def test_owner_departure_into_inactive_catalog_lane_fails(tmp_path):
    document = _document((0,))
    catalog = sr.load_catalog(CHIPDB)
    route = document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"]
    route += ";%s;%s.%s;1" % (
        catalog.lanes[1].edges[0].dst,
        catalog.lanes[0].edges[0].src,
        catalog.lanes[1].edges[0].dst,
    )
    document["modules"]["top"]["netnames"]["lane0"]["attributes"]["ROUTING"] = route
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="touches active lane|lane 0 route touches"):
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
    assert sr.validate_routed_json(path, "bitgen", CHIPDB)["active_lanes"] == ()

    forged = _document((0,), tokens=False)
    forged["modules"]["top"]["attributes"] = {"top": 1}
    path = _write(tmp_path, forged, "marker-removed.json")
    with pytest.raises(sr.SpecialRouteError, match="lacks authenticated physical-top marker"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


def test_disabled_emitted_generic_marker_is_inert(tmp_path):
    generic = _document((2,), partial=2, tokens=False)
    attrs = generic["modules"]["top"]["attributes"]
    attrs[sr.MODULE_ENABLED] = "0"
    path = _write(tmp_path, generic)
    assert sr.validate_routed_json(path, "bitgen", CHIPDB)["active_lanes"] == ()


def test_disabled_marker_cannot_hide_a_complete_physical_lane(tmp_path):
    document = _document((0,), tokens=False)
    document["modules"]["top"]["attributes"][sr.MODULE_ENABLED] = "0"
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="disabled.*complete physical lane"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


def test_malformed_enabled_marker_is_not_coerced_to_disabled(tmp_path):
    document = _document((0,))
    document["modules"]["top"]["attributes"][sr.MODULE_ENABLED] = "false"
    path = _write(tmp_path, document)
    with pytest.raises(sr.SpecialRouteError, match="malformed enabled state"):
        sr.validate_routed_json(path, "bitgen", CHIPDB)


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
    with pytest.raises(sr.SpecialRouteError, match="touches active lane"):
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
    with pytest.raises(sr.SpecialRouteError, match="sink I is not an input"):
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


def test_owner_q_may_share_its_net_with_a_local_input_user(tmp_path):
    document = _document((0,))
    driver = document["modules"]["top"]["cells"]["driver0"]
    driver["port_directions"]["A"] = "input"
    driver["connections"]["A"] = [100]
    path = _write(tmp_path, document)
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
        "0979d59eb4c2c0f6c23fc63d198128250e49ed379a9d836061d07b87d8cc8e35"
    )
    with graph_path.open(newline="", encoding="utf-8") as stream:
        graph = {(row["src"], row["dst"]) for row in csv.DictReader(stream)}
    assert len(graph) == 326481
    touching = sorted(
        edge for edge in graph
        if (edge[0] in catalog.wires or edge[1] in catalog.wires) and
        edge not in catalog.edges
    )
    canonical = "".join("%s,%s\n" % edge for edge in touching).encode("utf-8")
    assert len(touching) == 957
    assert hashlib.sha256(canonical).hexdigest() == (
        "fb274b131e751fec71bdc8ba9abbb55c0f3c177d81f27edce39c9cbe43b9fd47"
    )
    incoming = [edge for edge in touching if edge[1] in catalog.wires]
    outgoing = [edge for edge in touching if edge[0] in catalog.wires]
    internal = [edge for edge in touching
                if edge[0] in catalog.wires and edge[1] in catalog.wires]
    assert (len(incoming), len(outgoing), len(internal)) == (295, 672, 10)

    # The census above binds the exact current physical graph.  Avoid 7,656
    # redundant catalog reads while still exercising the public validator for
    # every owner and foreign-net role against every noncatalog touching PIP.
    monkeypatch.setattr(sr, "load_catalog", lambda _root=None: catalog)
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
            should_accept = src in lane.wires and dst not in catalog.wires
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


def test_physical_profile_requires_complete_graph_and_digest(tmp_path):
    catalog = sr.load_catalog(CHIPDB)
    devdb = tmp_path / "physical"
    profile = {"AGAMEMNON_PHYSICAL_IO": "1", "AGAMEMNON_LEFT_PAD_OUT": "1"}
    _write_dev_graph(
        devdb, catalog.edges,
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1",
    )
    meta = sr.emit_devdb_metadata(devdb, CHIPDB, profile, catalog.edges)
    _bind_dev_meta(devdb, meta)
    assert meta["enabled"] == "1"
    assert sr.validate_devdb(devdb, CHIPDB) is True
    rows = list(csv.reader((devdb / sr.DEV_META_NAME).open(newline="", encoding="utf-8")))
    rows[-1][-1] = "0" * 64
    with (devdb / sr.DEV_META_NAME).open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="catalog_sha256 drift"):
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
    catalog = sr.load_catalog(CHIPDB)
    devdb = tmp_path / "surplus-field-devdb"
    profile = {"AGAMEMNON_PHYSICAL_IO": "1", "AGAMEMNON_LEFT_PAD_OUT": "1"}
    _write_dev_graph(
        devdb, catalog.edges,
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1",
    )
    meta = sr.emit_devdb_metadata(devdb, CHIPDB, profile, catalog.edges)
    _bind_dev_meta(devdb, meta)
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
    catalog = sr.load_catalog(CHIPDB)
    devdb = tmp_path / "malformed-physical"
    profile = {"AGAMEMNON_PHYSICAL_IO": "1", "AGAMEMNON_LEFT_PAD_OUT": "1"}
    _write_dev_graph(devdb, catalog.edges, env)
    meta = sr.emit_devdb_metadata(devdb, CHIPDB, profile, catalog.edges)
    _bind_dev_meta(devdb, meta)
    with pytest.raises(sr.SpecialRouteError, match=match):
        sr.validate_devdb(devdb, CHIPDB)


def test_python_devdb_validator_binds_named_pip_to_actual_endpoints(tmp_path):
    catalog = sr.load_catalog(CHIPDB)
    devdb = tmp_path / "named-pip-drift"
    profile = {"AGAMEMNON_PHYSICAL_IO": "1", "AGAMEMNON_LEFT_PAD_OUT": "1"}
    _write_dev_graph(
        devdb, catalog.edges,
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1",
    )
    meta = sr.emit_devdb_metadata(devdb, CHIPDB, profile, catalog.edges)
    _bind_dev_meta(devdb, meta)
    path = devdb / "dev_pips.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][0] = "SPOOFED.PIP.NAME"
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="named PIP endpoint drift"):
        sr.validate_devdb(devdb, CHIPDB)


@pytest.mark.parametrize(
    "file_name, row_index, column, value",
    [
        ("dev_bels.csv", 1, 1, "OTHER"),
        ("dev_belpins.csv", 1, 2, "X14Y11_OMUX14"),
        ("dev_belpins.csv", 1, 3, "in"),
        ("dev_belpins.csv", 2, 2, "X0Y4_IOMUX01"),
        ("dev_belpins.csv", 2, 3, "out"),
    ],
)
def test_python_devdb_validator_binds_bel_pin_endpoint_identity(
        tmp_path, file_name, row_index, column, value):
    catalog = sr.load_catalog(CHIPDB)
    devdb = tmp_path / "bel-pin-drift"
    profile = {"AGAMEMNON_PHYSICAL_IO": "1", "AGAMEMNON_LEFT_PAD_OUT": "1"}
    _write_dev_graph(
        devdb, catalog.edges,
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1",
    )
    meta = sr.emit_devdb_metadata(devdb, CHIPDB, profile, catalog.edges)
    _bind_dev_meta(devdb, meta)
    path = devdb / file_name
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[row_index][column] = value
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="BEL-pin endpoint drift"):
        sr.validate_devdb(devdb, CHIPDB)


def test_python_devdb_validator_rejects_catalog_row_reordering(tmp_path):
    catalog = sr.load_catalog(CHIPDB)
    devdb = tmp_path / "physical-reordered"
    profile = {"AGAMEMNON_PHYSICAL_IO": "1", "AGAMEMNON_LEFT_PAD_OUT": "1"}
    _write_dev_graph(
        devdb, catalog.edges,
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1",
    )
    meta = sr.emit_devdb_metadata(devdb, CHIPDB, profile, catalog.edges)
    _bind_dev_meta(devdb, meta)
    path = devdb / sr.DEV_CATALOG_NAME
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1], rows[2] = rows[2], rows[1]
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    with pytest.raises(sr.SpecialRouteError, match="catalog/cache digest drift"):
        sr.validate_devdb(devdb, CHIPDB)


def test_exact_predecessor_route_remains_accepted_immutable():
    retained = Path(__file__).parents[1] / "qualification" / "pad_uarch_left_edge_outputs_routed.json"
    result = sr.validate_routed_json(retained, "bitgen", CHIPDB)
    assert result == {
        "active_lanes": (0, 1, 2, 3),
        "catalog_sha256": sr.load_catalog(CHIPDB).digest,
        "legacy_retained": True,
    }


@pytest.mark.parametrize(
    "name,digest,active",
    [
        ("pad_uarch_left_edge_outputs_routed.json", sr.LEGACY_RETAINED_SHA256, (0, 1, 2, 3)),
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
    with pytest.raises(sr.SpecialRouteError, match="lacks authenticated physical-top marker"):
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

    retained = (Path(__file__).parents[1] / "qualification" /
                "pad_uarch_left_edge_outputs_routed.json")
    raw = retained.read_bytes()
    expected_digest = hashlib.sha256(raw).hexdigest()
    control = tmp_path / "control.json"
    attacked = tmp_path / "attacked.json"
    control.write_bytes(raw)
    attacked.write_bytes(raw)
    control_output = tmp_path / "control.comp"
    attacked_output = tmp_path / "attacked.comp"
    sidecar = tmp_path / "attacked.policy.json"
    bitgen.build(control, control_output, environ={})

    real_load = sr.load_validated_routed_json

    def load_then_mutate(path, phase, chipdb_root=None, environ=None):
        snapshot = real_load(path, phase, chipdb_root, environ=environ)
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
        environ={
            "AGAMEMNON_STRICT_POLICY": "experimental-strict",
            "AGAMEMNON_POLICY_SIDECAR": str(sidecar),
            "AGAMEMNON_VALIDATED_ROUTED_SHA256": expected_digest,
        },
    )
    assert attacked_output.read_bytes() == control_output.read_bytes()
    binding = json.loads(sidecar.read_text(encoding="utf-8"))["bindings"]
    assert binding["routed_sha256"] == expected_digest
    assert hashlib.sha256(attacked.read_bytes()).hexdigest() != expected_digest


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
            environ={"AGAMEMNON_VALIDATED_ROUTED_SHA256": expected},
        )
    assert not output.exists()


def test_direct_release_bitgen_removes_default_and_explicit_stale_policy_sidecars(
        tmp_path):
    from agamemnon.engine import bitgen

    retained = (Path(__file__).parents[1] / "qualification" /
                "pad_uarch_left_edge_outputs_routed.json")
    output = tmp_path / "release.comp"
    default_sidecar = Path(str(output) + ".policy.json")
    explicit_sidecar = tmp_path / "explicit.policy.json"
    default_sidecar.write_text("stale-default", encoding="utf-8")
    explicit_sidecar.write_text("stale-explicit", encoding="utf-8")
    bitgen.build(
        retained,
        output,
        environ={"AGAMEMNON_POLICY_SIDECAR": str(explicit_sidecar)},
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
            environ={"AGAMEMNON_POLICY_SIDECAR": str(explicit_sidecar)},
        )
    assert not output.exists()
    assert not default_sidecar.exists()
    assert not explicit_sidecar.exists()


def test_bitgen_rejects_ownership_trace_alias_without_overwriting_image(tmp_path):
    from agamemnon.engine import bitgen

    retained = (Path(__file__).parents[1] / "qualification" /
                "pad_uarch_left_edge_outputs_routed.json")
    output = tmp_path / "trace-alias.comp"
    with pytest.raises(SystemExit, match="emission products alias"):
        bitgen.build(
            retained,
            output,
            environ={"AGAMEMNON_OWNERSHIP_TRACE": str(output)},
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
            environ={"AGAMEMNON_OWNERSHIP_TRACE": str(trace)},
        )
    assert not output.exists()
    assert not trace.exists()


def test_mandatory_policy_sidecar_failure_rolls_back_image_and_trace(tmp_path):
    from agamemnon.engine import bitgen

    retained = (Path(__file__).parents[1] / "qualification" /
                "pad_uarch_left_edge_outputs_routed.json")
    output = tmp_path / "transaction.comp"
    trace = tmp_path / "transaction.trace.json"
    missing_sidecar = tmp_path / "absent" / "policy.json"
    with pytest.raises(OSError):
        bitgen.build(
            retained,
            output,
            environ={
                "AGAMEMNON_STRICT_POLICY": "experimental-strict",
                "AGAMEMNON_POLICY_SIDECAR": str(missing_sidecar),
                "AGAMEMNON_OWNERSHIP_TRACE": str(trace),
            },
        )
    assert not output.exists()
    assert not trace.exists()
    assert not missing_sidecar.exists()
