"""Native/profile agreement using actual core-logic graph generation."""
import contextlib
import csv
import io
import itertools
import shutil
from types import SimpleNamespace

import pytest

from agamemnon.engine.emit_uarch_db import Loc, RecordingCtx
from agamemnon.engine.features.core_logic import CoreLogicFeature
from agamemnon.engine.registry import CONSTANTS, options_from
from agamemnon.engine import special_routes as sr
from test_uarch_special_routes import DEVDB, CHIPDB, PHYSICAL_ENV, _run, _retained_document


def _source_profile(tmp_path, sites):
    devdb = tmp_path / "source-profile"
    shutil.copytree(DEVDB, devdb)
    extra = {"AGAMEMNON_DIRECT_D": "1", "AGAMEMNON_DIRECT_D_SITES":
             ";".join("X14Y11_SLICE%d" % z for z in sites)}
    env = {**PHYSICAL_ENV, **extra}
    ctx = RecordingCtx()
    wire_name = lambda x, y, name: "X%dY%d_%s" % (x, y, name)
    wires = {wire_name(14, 11, "%s%02d" % (kind, n))
             for kind, count in (("IMUX", 64), ("OMUX", 48), ("ClkMUX", 16))
             for n in range(count)}
    with contextlib.redirect_stdout(io.StringIO()):
        CoreLogicFeature().add_architecture(SimpleNamespace(
            ctx=ctx, loc=Loc, options=options_from(env), shared={
                "wire_name": wire_name, "wires": wires,
                "tile_types": {(14, 11): "LogicTILE"}, "constants": CONSTANTS}))
    generated = {(bel, pin): (wire, direction) for bel, pin, wire, direction in ctx.belpins}
    path = devdb / "dev_belpins.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    for row in rows[1:]:
        if tuple(row[:2]) in generated:
            row[2:] = generated[tuple(row[:2])]
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    path = devdb / "dev_meta.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    for row in rows[1:]:
        if row[0] == "agamemnon_env":
            row[1] += "".join(";" + key + "=" + value.replace(";", r"\;")
                              for key, value in extra.items())
    with path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)
    assert sr.validate_devdb(devdb, CHIPDB)
    return devdb


@pytest.mark.parametrize("sites", [s for n in range(5)
                                  for s in itertools.combinations(range(4, 8), n)])
def test_native_loads_real_direct_d_graph_profiles(tmp_path, sites):
    devdb = _source_profile(tmp_path, sites)
    empty = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {}, "cells": {}, "netnames": {}}}}
    result, log, _ = _run(tmp_path, "profile", empty,
                         "--no-pack", "--no-place", "--no-route", devdb=devdb)
    assert result.returncode == 0, log


@pytest.mark.parametrize("lane", range(4))
def test_native_real_direct_d_profile_owner_compatibility(tmp_path, lane):
    devdb = _source_profile(tmp_path, (4, 5, 6, 7))
    document = _retained_document((lane,), routed=False)
    module = document["modules"]["top"]
    cells = module["cells"]
    sink = sr.load_catalog(CHIPDB).lanes[lane].sink_bel
    drivers = {}
    for name, cell in cells.items():
        for port, bits in cell.get("connections", {}).items():
            if cell.get("port_directions", {}).get(port) == "output":
                for bit in bits:
                    if isinstance(bit, int):
                        drivers.setdefault(bit, set()).add(name)
    pending = [name for name, cell in cells.items()
               if cell.get("attributes", {}).get("NEXTPNR_BEL") == sink]
    assert len(pending) == 1
    retained = set()
    while pending:
        name = pending.pop()
        if name in retained:
            continue
        retained.add(name)
        cell = cells[name]
        for port, bits in cell.get("connections", {}).items():
            if cell.get("port_directions", {}).get(port) == "input":
                for bit in bits:
                    pending.extend(drivers.get(bit, ()))
    # Test this pad's complete logic/clock/OE cone, not unrelated retained
    # counters that assumed a different Q presentation at inactive sites.
    module["cells"] = {name: cell for name, cell in cells.items() if name in retained}
    used_bits = {bit for cell in module["cells"].values()
                 for bits in cell.get("connections", {}).values() for bit in bits}
    module["netnames"] = {name: net for name, net in module["netnames"].items()
                          if set(net.get("bits", ())) & used_bits}
    result, log, output = _run(
        tmp_path, "owner", document,
        "--no-pack", "--no-place", "--router", "router2", devdb=devdb)
    if lane >= 2:
        assert result.returncode != 0
        assert "incompatible with the selected direct-D graph profile" in log
    else:
        assert result.returncode == 0, log
        assert sr.validate_routed_json(output, "post-nextpnr", CHIPDB,
                                       environ=PHYSICAL_ENV, devdb=devdb)["active_lanes"] == (lane,)
