"""Compiled lifecycle coverage for the N5.5 typed L48 left-output pilot."""

from __future__ import annotations

import copy
import csv
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from agamemnon.engine import special_routes as sr
from devdb_fixtures import devdb_path


ROOT = Path(__file__).resolve().parents[1]
DEVDB = devdb_path("strict_pcf")
RETAINED = ROOT / "qualification" / "pad_uarch_left_edge_outputs_routed.json"
CHIPDB = ROOT / "agamemnon" / "chipdb"
PHYSICAL_ENV = {
    "AGAMEMNON_DEVICE": sr.DEVICE,
    "AGAMEMNON_PHYSICAL_IO": "1",
    "AGAMEMNON_LEFT_PAD_OUT": "1",
    sr.DEVDB_ENV: str(DEVDB),
}


def _tool():
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    if not (DEVDB / sr.DEV_META_NAME).is_file():
        pytest.skip("emit the physical-I/O agrv2k devdb before N5.5 compiled tests")
    assert sr.validate_devdb(DEVDB, CHIPDB) is True
    return executable


def _module(document):
    return next(iter(document["modules"].values()))


def _retained_document(active=(0, 1, 2, 3), *, routed=True, authenticated=False):
    document = json.loads(RETAINED.read_text(encoding="utf-8"))
    module = _module(document)
    # The public portable checkpoint intentionally uses negative synthetic
    # top-port IDs. They are not part of the physical routed state and cannot
    # be re-imported by nextpnr's frontend, so compiled import fixtures remove
    # only that portability surface.
    module["ports"] = {}
    catalog = sr.load_catalog(CHIPDB)
    active = tuple(active)
    for name, cell in list(module["cells"].items()):
        bel = (cell.get("attributes") or {}).get("NEXTPNR_BEL")
        if any(bel == lane.sink_bel and lane.index not in active
               for lane in catalog.lanes):
            del module["cells"][name]
    replacement_bit = 900000
    for lane in catalog.lanes:
        if lane.index not in active:
            continue
        driver = next(
            cell for cell in module["cells"].values()
            if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
        )
        bit = driver["connections"][lane.source_port][0]
        for cell in module["cells"].values():
            if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.sink_bel:
                continue
            for port, bits in (cell.get("connections") or {}).items():
                if (cell.get("port_directions") or {}).get(port) not in ("input", "inout"):
                    continue
                if bit in bits:
                    cell["connections"][port] = [
                        replacement_bit if item == bit else item for item in bits
                    ]
                    replacement_bit += 1
        if routed:
            net = _lane_net(document, lane.index)
            triples = [lane.edges[0].src, "", "1"]
            for edge in lane.edges:
                triples.extend((edge.dst, edge.src + "." + edge.dst, "5"))
            net["attributes"]["ROUTING"] = ";".join(triples)
    if not routed:
        for net in module["netnames"].values():
            (net.get("attributes") or {}).pop("ROUTING", None)
    if authenticated:
        module["attributes"].update({
            sr.MODULE_SCHEMA: sr.SCHEMA,
            sr.TOKEN_CLASS: sr.CLASS,
            sr.TOKEN_VERSION: sr.ROUTED_VERSION,
            sr.MODULE_DEVICE: sr.DEVICE,
            sr.MODULE_PACKAGE: sr.PACKAGE,
            sr.MODULE_PROFILE: sr.PROFILE,
            sr.MODULE_ENABLED: "1",
            sr.TOKEN_DIGEST: catalog.digest,
        })
        for lane in catalog.lanes:
            if lane.index not in active:
                continue
            driver = next(
                cell for cell in module["cells"].values()
                if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
            )
            driver["attributes"].update({
                sr.TOKEN_CLASS: sr.CLASS,
                sr.TOKEN_VERSION: sr.ROUTED_VERSION,
                sr.TOKEN_LANE: str(lane.index),
                sr.TOKEN_DIGEST: catalog.digest,
            })
    return document


def _lane_net(document, lane_index):
    module = _module(document)
    lane = sr.load_catalog(CHIPDB).lanes[lane_index]
    driver = next(
        cell for cell in module["cells"].values()
        if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
    )
    bit = driver["connections"][lane.source_port][0]
    return next(
        net for net in module["netnames"].values() if bit in net.get("bits", ())
    )


def _remove_route_edge(document, edge):
    net = _lane_net(document, edge.lane)
    parts = net["attributes"]["ROUTING"].split(";")
    retained = []
    removed = 0
    for index in range(0, len(parts), 3):
        if parts[index + 1] == edge.src + "." + edge.dst:
            removed += 1
        else:
            retained.extend(parts[index:index + 3])
    assert removed == 1
    net["attributes"]["ROUTING"] = ";".join(retained)


def _run(tmp_path, name, document, *extra, devdb=DEVDB):
    source = tmp_path / (name + ".json")
    output = tmp_path / (name + "_out.json")
    source.write_text(json.dumps(document), encoding="utf-8")
    env = dict(os.environ)
    env.update(PHYSICAL_ENV)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", "chipdb=" + str(devdb),
         "--json", str(source), "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


def _validate(path, phase="post-nextpnr"):
    return sr.validate_routed_json(
        path, phase, CHIPDB, environ=PHYSICAL_ENV, devdb=DEVDB,
    )


def test_direct_nextpnr_rejects_graph_valid_catalog_row_drift_at_init(tmp_path):
    mutated = tmp_path / "mutated-devdb"
    shutil.copytree(DEVDB, mutated)
    path = mutated / sr.DEV_CATALOG_NAME
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    changed = 0
    for row in rows[1:]:
        if row[6:7] == ["0"] and row[12:13] == ["2"]:
            assert row[13:15] == ["X15Y11_RMUX44", "X15Y8_RMUX80"]
            row[14] = "X15Y7_RMUX80"
            changed += 1
        if row[6:7] == ["0"] and row[12:13] == ["3"]:
            assert row[13:15] == ["X15Y8_RMUX80", "X15Y4_RMUX26"]
            row[13] = "X15Y7_RMUX80"
            changed += 1
    assert changed == 2
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "catalog_row_drift", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert "actual special-route catalog row drift at lane 0 step 2" in log


def test_direct_nextpnr_rejects_catalog_canonical_row_reordering(tmp_path):
    mutated = tmp_path / "reordered-devdb"
    shutil.copytree(DEVDB, mutated)
    path = mutated / sr.DEV_CATALOG_NAME
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1], rows[2] = rows[2], rows[1]
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "catalog_row_reorder", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert "catalog canonical row-order/digest drift at row 0" in log


@pytest.mark.parametrize(
    "column, value",
    [
        (6, "0junk"),
        (6, "00"),
        (12, "0junk"),
        (12, "+0"),
    ],
)
def test_direct_nextpnr_rejects_noncanonical_catalog_numeric_fields(
        tmp_path, column, value):
    mutated = tmp_path / "noncanonical-numeric-devdb"
    shutil.copytree(DEVDB, mutated)
    path = mutated / sr.DEV_CATALOG_NAME
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[1][column] = value
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "noncanonical_numeric", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert "malformed special-route catalog row" in log


@pytest.mark.parametrize(
    "file_name,row_index,match",
    [
        (sr.DEV_CATALOG_NAME, 0, "malformed dev_special_routes.csv header"),
        (sr.DEV_CATALOG_NAME, 1, "malformed special-route catalog row"),
        (sr.DEV_META_NAME, 0, "malformed dev_special_route_meta.csv header"),
        (sr.DEV_META_NAME, 1, "malformed dev_special_route_meta.csv row"),
        ("dev_meta.csv", 0, "malformed dev_meta.csv header"),
        ("dev_meta.csv", 1, "malformed dev_meta.csv row"),
    ],
)
def test_direct_nextpnr_rejects_surplus_csv_fields(
        tmp_path, file_name, row_index, match):
    mutated = tmp_path / (file_name.replace(".", "-") + "-surplus-devdb")
    shutil.copytree(DEVDB, mutated)
    path = mutated / file_name
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    rows[row_index].append("surplus")
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "surplus_csv_field", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert match in log


def test_direct_nextpnr_rejects_named_pip_with_spoofed_actual_endpoint(tmp_path):
    mutated = tmp_path / "pip-endpoint-drift-devdb"
    shutil.copytree(DEVDB, mutated)
    path = mutated / "dev_pips.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    changed = 0
    for row in rows[1:]:
        if row[0] == "X14Y11_OMUX13.X14Y11_OMUX12":
            assert row[2:4] == ["X14Y11_OMUX13", "X14Y11_OMUX12"]
            row[3] = "X14Y11_OMUX15"
            changed += 1
    assert changed == 1
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "pip_endpoint_drift", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert "named special-route PIP endpoint drift" in log


@pytest.mark.parametrize(
    "bel, pin, replacement, endpoint",
    [
        ("X14Y11_SLICE4", "Q", "X14Y11_OMUX14", "source"),
        ("X0Y4_IOB0", "I", "X0Y4_IOMUX01", "sink"),
    ],
)
def test_direct_nextpnr_rejects_spoofed_bel_pin_endpoint(
        tmp_path, bel, pin, replacement, endpoint):
    mutated = tmp_path / (endpoint + "-belpin-drift-devdb")
    shutil.copytree(DEVDB, mutated)
    path = mutated / "dev_belpins.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    changed = 0
    for row in rows[1:]:
        if row[0:2] == [bel, pin]:
            row[2] = replacement
            changed += 1
    assert changed == 1
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, endpoint + "_belpin_drift", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert "special-route %s BEL-pin endpoint drift" % endpoint in log


@pytest.mark.parametrize(
    "cached_env",
    [
        "AGAMEMNON_LEFT_PAD_OUT=0;AGAMEMNON_PHYSICAL_IO=1",
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=0",
        "AGAMEMNON_LEFT_PAD_OUT=11;AGAMEMNON_PHYSICAL_IO=10",
    ],
)
def test_direct_nextpnr_rejects_enabled_cache_with_wrong_actual_profile(
        tmp_path, cached_env):
    mutated = tmp_path / "profile-mismatched-devdb"
    shutil.copytree(DEVDB, mutated)
    path = mutated / "dev_meta.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    changed = 0
    for row in rows[1:]:
        if row[0] == "agamemnon_env":
            row[1] = cached_env
            changed += 1
    assert changed == 1
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "profile_mismatch", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert "enabled state does not match exact cached profile" in log


@pytest.mark.parametrize(
    "cached_env",
    [
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO",
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1;"
        "AGAMEMNON_PHYSICAL_IO=1",
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1;",
        "AGAMEMNON_LEFT_PAD_OUT=1;AGAMEMNON_PHYSICAL_IO=1;X=value\\",
    ],
)
def test_direct_nextpnr_rejects_malformed_or_duplicate_cached_profile_tokens(
        tmp_path, cached_env):
    mutated = tmp_path / "malformed-profile-devdb"
    shutil.copytree(DEVDB, mutated)
    path = mutated / "dev_meta.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    changed = 0
    for row in rows[1:]:
        if row[0] == "agamemnon_env":
            row[1] = cached_env
            changed += 1
    assert changed == 1
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "malformed_profile", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode != 0
    assert "malformed/duplicate agamemnon_env token" in log


@pytest.mark.parametrize("value", [r"X14Y11_SLICE4\;X14Y11_SLICE5", r"a\\b", r"a\;"])
def test_direct_nextpnr_accepts_escaped_cached_profile_values(tmp_path, value):
    mutated = tmp_path / "escaped-profile-devdb"
    shutil.copytree(DEVDB, mutated)
    path = mutated / "dev_meta.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    for row in rows[1:]:
        if row[0] == "agamemnon_env":
            row[1] += ";ESCAPED_TEST_VALUE=" + value
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    assert sr.validate_devdb(mutated, CHIPDB) is True
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {},
    }}}
    result, log, _ = _run(
        tmp_path, "escaped_profile", empty,
        "--no-pack", "--no-place", "--no-route", devdb=mutated,
    )
    assert result.returncode == 0, log


@pytest.mark.parametrize(
    "active",
    [subset for size in range(1, 5)
     for subset in itertools.combinations(range(4), size)],
)
@pytest.mark.parametrize("seed", [4, 2, 7])
def test_real_router2_closes_all_lane_subsets_across_bounded_seeds(
        tmp_path, active, seed):
    if os.environ.get("AGAMEMNON_TEST_N55_COMPILED_MATRIX") != "1":
        pytest.skip("set AGAMEMNON_TEST_N55_COMPILED_MATRIX=1 for the 45-route gate")
    result, log, output = _run(
        tmp_path, "subset_%s_seed_%d" % ("".join(map(str, active)), seed),
        _retained_document(active, routed=False),
        "--no-pack", "--no-place", "--router", "router2", "--seed", str(seed),
    )
    assert result.returncode == 0, log
    assert "post-route typed L48 left-output audit verified %d active lane(s)" % len(active) in log
    assert _validate(output)["active_lanes"] == active


def test_complete_import_survives_preroute_router_and_postroute_audits(tmp_path):
    result, log, output = _run(
        tmp_path, "complete_import", _retained_document(),
        "--no-pack", "--no-place", "--router", "router2",
    )
    assert result.returncode == 0, log
    assert "pre-route typed L48 left-output audit verified 4 active lane(s)" in log
    assert "post-route typed L48 left-output audit verified 4 active lane(s) with full closure" in log
    assert _validate(output)["active_lanes"] == (0, 1, 2, 3)


@pytest.mark.parametrize(
    "extra, phase",
    [
        (("--pack-only",), "end-pack"),
        (("--no-place", "--no-route"), "end-pack"),
        (("--no-pack", "--no-place", "--router", "router2"), "pre-route"),
    ],
)
def test_partial_import_rejects_at_every_available_aggregate_hook(
        tmp_path, extra, phase):
    document = _retained_document(authenticated=True)
    _remove_route_edge(document, sr.load_catalog(CHIPDB).lanes[0].edges[-1])
    result, log, _ = _run(tmp_path, "partial_" + phase, document, *extra)
    assert result.returncode != 0
    assert "%s typed lane 0 closure is 9/10 PIPs" % phase in log
    assert "Routing complete" not in log


def test_no_pack_no_route_partial_import_is_closed_by_independent_validator(tmp_path):
    document = _retained_document(authenticated=True)
    _remove_route_edge(document, sr.load_catalog(CHIPDB).lanes[0].edges[-1])
    result, log, _ = _run(
        tmp_path, "partial_no_callbacks", document,
        "--no-pack", "--no-place", "--no-route",
    )
    assert result.returncode == 0, log
    source = tmp_path / "partial_no_callbacks.json"
    with pytest.raises(sr.SpecialRouteError, match="lane 0 is incomplete"):
        _validate(source, "bitgen")


def test_wrong_predecessor_is_rejected_during_same_net_import_notification(tmp_path):
    document = _retained_document(authenticated=True)
    lane = sr.load_catalog(CHIPDB).lanes[0]
    edge = lane.edges[1]
    net = _lane_net(document, 0)
    parts = net["attributes"]["ROUTING"].split(";")
    for index in range(0, len(parts), 3):
        if parts[index + 1] == edge.src + "." + edge.dst:
            parts[index + 1] = "X15Y11_OMUX20." + edge.dst
            break
    else:
        raise AssertionError("catalog edge absent from retained route")
    net["attributes"]["ROUTING"] = ";".join(parts)
    result, log, _ = _run(
        tmp_path, "wrong_predecessor", document,
        "--no-pack", "--no-place", "--no-route",
    )
    assert result.returncode != 0
    assert "typed resource notification rejects PIP" in log
    assert "X15Y11_OMUX20.X15Y11_RMUX44" in log


def test_imported_owner_departure_cannot_bypass_static_availability(
        tmp_path, monkeypatch):
    document = _retained_document(authenticated=True)
    net = _lane_net(document, 2)
    net["attributes"]["ROUTING"] += (
        ";X14Y11_OMUX19;X14Y11_OMUX20.X14Y11_OMUX19;1"
    )
    monkeypatch.setenv("AGRV2K_NO_FBBRIDGE", "1")
    result, log, _ = _run(
        tmp_path,
        "statically_dead_owner_departure",
        document,
        "--no-pack",
        "--no-place",
        "--no-route",
    )
    assert result.returncode != 0
    assert "typed resource notification rejects PIP" in log
    assert "X14Y11_OMUX20.X14Y11_OMUX19" in log


def test_graph_present_owner_departure_is_rejected_by_cpp_legality(tmp_path):
    document = _retained_document(authenticated=True)
    net = _lane_net(document, 0)
    net["attributes"]["ROUTING"] += (
        ";X15Y11_RMUX31;X14Y11_OMUX12.X15Y11_RMUX31;1"
    )
    result, log, _ = _run(
        tmp_path, "graph_present_owner_departure", document,
        "--no-pack", "--no-place", "--no-route",
    )
    assert result.returncode != 0
    assert "typed resource notification rejects PIP" in log
    assert "X14Y11_OMUX12.X15Y11_RMUX31" in log


@pytest.mark.parametrize("source,destination", [
    ("X14Y2_RMUX32", "X14Y4_RMUX26"),
    ("X14Y4_RMUX26", "X14Y4_RMUX28"),
])
@pytest.mark.parametrize("net_lane", [0, 2])
def test_bram_corridor_cannot_enter_or_leave_active_pin27(tmp_path, source, destination, net_lane):
    document = _retained_document(authenticated=True)
    net = _lane_net(document, net_lane)
    pip = source + "." + destination
    with (DEVDB / "dev_pips.csv").open(newline="") as stream:
        assert any(row["name"] == pip for row in csv.DictReader(stream))
    net["attributes"]["ROUTING"] += ";" + destination + ";" + pip + ";1"
    result, log, _ = _run(tmp_path, "pin27_corridor", document,
                          "--no-pack", "--no-place", "--no-route")
    assert result.returncode != 0
    assert "typed resource notification rejects PIP" in log
    assert pip in log


@pytest.mark.parametrize("source,destination", [
    ("X14Y2_RMUX32", "X14Y4_RMUX26"),
    ("X14Y4_RMUX26", "X14Y4_RMUX28"),
])
def test_bram_corridor_is_importable_when_pin27_is_inactive(tmp_path, source, destination):
    document = _retained_document(active=(0, 1, 3), authenticated=True)
    # Lane 2's pad is absent, so its former driver is an ordinary net. This
    # isolates resource ownership during import, not end-to-end route closure.
    net = _lane_net(document, 2)
    pip = source + "." + destination
    net["attributes"]["ROUTING"] = source + ";;1;" + destination + ";" + pip + ";1"
    result, log, _ = _run(tmp_path, "inactive_pin27_corridor", document,
                          "--no-pack", "--no-place", "--no-route")
    assert result.returncode == 0, log


@pytest.mark.parametrize("net_lane", [1, 2])
def test_bram_bit8_departure_rejects_active_pin26_owner_and_foreign_net(tmp_path, net_lane):
    document = _retained_document(authenticated=True)
    pip = "X15Y4_RMUX86.X13Y4_RMUX67"
    with (DEVDB / "dev_pips.csv").open(newline="") as stream:
        assert any(row["name"] == pip for row in csv.DictReader(stream))
    _lane_net(document, net_lane)["attributes"]["ROUTING"] += ";X13Y4_RMUX67;" + pip + ";1"
    result, log, _ = _run(tmp_path, "active_pin26_departure", document,
                          "--no-pack", "--no-place", "--no-route")
    assert result.returncode != 0
    assert "typed resource notification rejects PIP" in log and pip in log


def test_bram_bit8_departure_is_importable_with_pin26_inactive(tmp_path):
    document = _retained_document(active=(0, 2, 3), authenticated=True)
    _lane_net(document, 1)["attributes"]["ROUTING"] = (
        "X15Y4_RMUX86;;1;X13Y4_RMUX67;X15Y4_RMUX86.X13Y4_RMUX67;1")
    result, log, _ = _run(tmp_path, "inactive_pin26_departure", document,
                          "--no-pack", "--no-place", "--no-route")
    assert result.returncode == 0, log


def test_r9_shaped_functional_q_plus_internal_fanout_rejects_in_cpp(tmp_path):
    document = _retained_document(authenticated=True)
    module = _module(document)
    lane = sr.load_catalog(CHIPDB).lanes[0]
    driver = next(
        cell for cell in module["cells"].values()
        if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
    )
    bit = driver["connections"][lane.source_port][0]
    module["cells"]["r9_internal_state_observer"] = {
        "type": "GENERIC_SLICE",
        "attributes": {"NEXTPNR_BEL": "X14Y11_SLICE8"},
        "port_directions": {"A": "input", "F": "output"},
        "connections": {"A": [bit], "F": [999001]},
    }
    result, log, _ = _run(
        tmp_path, "r9_functional_q_internal_fanout", document, "--pack-only",
    )
    assert result.returncode != 0
    assert "typed resource notification rejects PIP" in log
    assert "X14Y11_OMUX13.X14Y11_OMUX12" in log


@pytest.mark.parametrize(
    "form,expected",
    (
        ("absent-map", "Failed to get direction for port 'A'"),
        ("null-map", "Failed to get direction for port 'A'"),
        ("non-object-map", "Failed to get direction for port 'A'"),
        ("absent-port", "Failed to get direction for port 'A'"),
        ("null-port", "invalid json port direction"),
        ("unknown-port", "invalid json port direction"),
        ("contradictory-port", "is multiply driven"),
    ),
)
def test_compiled_import_rejects_malformed_connected_consumer_direction(
        tmp_path, form, expected):
    document = _retained_document(authenticated=True)
    module = _module(document)
    lane = sr.load_catalog(CHIPDB).lanes[0]
    driver = next(
        cell for cell in module["cells"].values()
        if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
    )
    bit = driver["connections"][lane.source_port][0]
    observer = {
        "type": "GENERIC_SLICE",
        "attributes": {"NEXTPNR_BEL": "X14Y11_SLICE8"},
        "port_directions": {"A": "input", "F": "output"},
        "connections": {"A": [bit], "F": [999001]},
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
    module["cells"]["malformed_direction_observer"] = observer

    result, log, _ = _run(
        tmp_path, "malformed_direction_%s" % form, document, "--pack-only",
    )
    assert result.returncode != 0
    assert expected in log


@pytest.mark.parametrize("lane_index", [2, 3])
def test_shared_f_presentation_cannot_substitute_for_qualified_q_source(
        tmp_path, lane_index):
    document = _retained_document(authenticated=True)
    lane = sr.load_catalog(CHIPDB).lanes[lane_index]
    driver = next(
        cell for cell in _module(document)["cells"].values()
        if (cell.get("attributes") or {}).get("NEXTPNR_BEL") == lane.source_bel
    )
    bit = driver["connections"]["Q"]
    driver["connections"]["Q"] = []
    driver["connections"]["F"] = bit
    result, log, _ = _run(tmp_path, "wrong_f_%d" % lane_index, document, "--pack-only")
    assert result.returncode != 0
    assert "requires exact %s.Q" % lane.source_bel in log
