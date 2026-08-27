"""N5.1 native placement and strict emission for fixed I/O output endpoints."""

from __future__ import annotations

from collections import defaultdict, deque
import csv
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from agamemnon.engine.features.core_logic import CoreLogicFeature
from agamemnon.engine.features.native_endpoint import (
    NATIVE_ENDPOINT_MODE_TOKENS,
    validate_module_native_endpoints,
)
from agamemnon.engine.features.physical_io import (
    qualified_input_endpoint_bels,
    qualified_output_endpoint_bels,
)


ROOT = Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
DEVDB = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
SOURCE = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
OVERLAY = (
    ROOT / "third_party" / "nextpnr" / "generic" / "viaduct" /
    "agrv2k" / "agrv2k.cc"
)


def _tool():
    executable = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not executable or not Path(executable).is_file():
        pytest.skip("set AGAMEMNON_UARCH_NEXTPNR to the isolated agrv2k build")
    if not (DEVDB / "dev_pips.csv").is_file():
        pytest.skip("emit the strict agrv2k devdb before native-endpoint tests")
    return executable


def _slice(*, bel=None, mode=None, name="driver", output_bit=2):
    attrs = {"AGRV2K_REGISTER_INPUT_MODE": "NONE"}
    if bel:
        attrs.update({
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        })
    if mode is not None:
        attrs["AGRV2K_NATIVE_ENDPOINT_MODE"] = mode
    return {
        "hide_name": 0,
        "type": "GENERIC_SLICE",
        "parameters": {
            "FF_USED": format(0, "032b"),
            "INIT": format(0xAAAA, "016b"),
            "K": format(4, "032b"),
        },
        "attributes": attrs,
        "port_directions": {"I": "input", "F": "output", "Q": "output"},
        "connections": {"I": [3, "x", "x", "x"], "F": [output_bit], "Q": []},
    }


def _iob(name="pad_iob", *, bel="X19Y13_OPAD0", bit=2, port="I",
         direction="input", cell_type="GENERIC_IOB"):
    return name, {
        "hide_name": 0,
        "type": cell_type,
        "parameters": {},
        "attributes": {
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        },
        "port_directions": {"PAD": "inout", port: direction},
        "connections": {"PAD": [10], port: [bit]},
    }


def _design(*, driver_bel=None, mode=None, occupant_bel=None, endpoints=None):
    cells = {"driver": _slice(bel=driver_bel, mode=mode)}
    endpoint_cells = [_iob()] if endpoints is None else endpoints
    cells.update(dict(endpoint_cells))
    if occupant_bel:
        occupied = _slice(bel=occupant_bel, name="occupied", output_bit=30)
        occupied["parameters"]["INIT"] = format(0, "016b")
        occupied["connections"] = {"I": ["x"] * 4, "F": [], "Q": []}
        cells["occupied"] = occupied
    return {
        "creator": "N5.1 typed native-endpoint compiled fixture",
        "modules": {"top": {
            "attributes": {"top": 1},
            "ports": {"pad": {"direction": "output", "bits": [10]}},
            "cells": cells,
            "netnames": {
                "data": {"hide_name": 0, "bits": [3], "attributes": {}},
                "driver_to_pad": {"hide_name": 0, "bits": [2], "attributes": {}},
                "pad": {"hide_name": 0, "bits": [10], "attributes": {}},
            },
        }},
    }


def _input_iob(name="pad_iob", *, bel="X19Y13_IO22", bit=2, port="O",
               direction="output", cell_type="GENERIC_IOB"):
    return name, {
        "hide_name": 0,
        "type": cell_type,
        "parameters": {},
        "attributes": {
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        },
        "port_directions": {"PAD": "inout", port: direction},
        "connections": {"PAD": [10], port: [bit]},
    }


def _input_design(*, consumer_bel=None, mode=None, occupant_bel=None,
                  ff_used=0, endpoint=None, special_attr=None):
    consumer = _slice(bel=consumer_bel, mode=mode, output_bit=3)
    consumer["parameters"]["FF_USED"] = format(ff_used, "032b")
    consumer["connections"] = {"I": [2, "x", "x", "x"], "F": [], "Q": []}
    if special_attr:
        consumer["attributes"][special_attr] = "stage1" if \
            special_attr == "agamemnon_pad_sync_stage" else "1"
    cells = {"consumer": consumer}
    if endpoint is None:
        cells.update(dict([_input_iob()]))
    elif endpoint is not False:
        cells.update(dict([endpoint]))
    if occupant_bel:
        occupied = _slice(bel=occupant_bel, name="occupied", output_bit=30)
        occupied["parameters"]["INIT"] = format(0, "016b")
        occupied["connections"] = {"I": ["x"] * 4, "F": [], "Q": []}
        cells["occupied"] = occupied
    return {
        "creator": "N5.2 typed native-input endpoint compiled fixture",
        "modules": {"top": {
            "attributes": {"top": 1},
            "ports": {"pad": {"direction": "input", "bits": [10]}},
            "cells": cells,
            "netnames": {
                "pad": {"hide_name": 0, "bits": [10], "attributes": {}},
                "pad_to_consumer": {
                    "hide_name": 0, "bits": [2], "attributes": {},
                },
            },
        }},
    }


def _run(tmp_path, name, design, *extra, condplace=True, pinpack=True):
    source = tmp_path / (name + ".json")
    output = tmp_path / (name + "_out.json")
    source.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    runtime = env.get("AGAMEMNON_UARCH_NEXTPNR_RUNTIME")
    if runtime:
        env["PATH"] = runtime + os.pathsep + env.get("PATH", "")
    if pinpack:
        env["AGRV2K_IO_PINPACK"] = "1"
    else:
        env.pop("AGRV2K_IO_PINPACK", None)
    for variable in (
        "AGRV2K_DENSE_TILE", "AGRV2K_REPLAY_BELS",
        "AGRV2K_REPLAY_BELS_IN_DB", "AGRV2K_REPLAY_BELS_HARD",
    ):
        env.pop(variable, None)
    if condplace:
        env["AGRV2K_CONDPLACE"] = "1"
    else:
        env.pop("AGRV2K_CONDPLACE", None)
    result = subprocess.run(
        [_tool(), "--uarch", "agrv2k", "-o", "chipdb=" + str(DEVDB),
         "--json", str(source), "--write", str(output), *extra],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=120,
    )
    return result, result.stdout + result.stderr, output


def _driver(output):
    return json.loads(output.read_text(encoding="utf-8"))["modules"]["top"] \
        ["cells"]["driver"]


def _consumer(output):
    return json.loads(output.read_text(encoding="utf-8"))["modules"]["top"] \
        ["cells"]["consumer"]


def _function(source, signature, next_signature):
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


def _output_reaches(bel, endpoint="X19Y13_OPAD0"):
    target = None
    source = None
    with (DEVDB / "dev_belpins.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["bel"] == endpoint and row["pin"] == "I":
                target = row["wire"]
            if row["bel"] == bel and row["pin"] == "F":
                source = row["wire"]
    assert target and source
    uphill = defaultdict(list)
    with (DEVDB / "dev_pips.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            uphill[row["dst"]].append(row["src"])
    reaching = {target}
    queue = deque([target])
    while queue:
        wire = queue.popleft()
        for prior in uphill[wire]:
            if prior not in reaching:
                reaching.add(prior)
                queue.append(prior)
    return source in reaching


def _input_reaches(bel, endpoint="X19Y13_IO22", pin="I[0]"):
    source = None
    target = None
    with (DEVDB / "dev_belpins.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["bel"] == endpoint and row["pin"] == "O":
                source = row["wire"]
            if row["bel"] == bel and row["pin"] == pin:
                target = row["wire"]
    assert source and target
    downhill = defaultdict(list)
    with (DEVDB / "dev_pips.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            downhill[row["src"]].append(row["dst"])
    reachable = {source}
    queue = deque([source])
    while queue:
        wire = queue.popleft()
        for following in downhill[wire]:
            if following not in reachable:
                reachable.add(following)
                queue.append(following)
    return target in reachable


def test_cpp_and_python_native_endpoint_tokens_are_identical():
    source = SOURCE.read_text(encoding="utf-8")
    table = re.search(
        r"NATIVE_ENDPOINT_MODE_TOKENS\[\]\s*=\s*\{(?P<body>.*?)\};",
        source, re.DOTALL,
    )
    assert table
    assert tuple(re.findall(r'"([A-Z_]+)"', table.group("body"))) == \
        NATIVE_ENDPOINT_MODE_TOKENS
    requirement = _function(
        source,
        "static NativeEndpointRequirement native_endpoint_requirement(Context *ctx",
        "static bool native_endpoint_cell_admitted(Context *ctx",
    )
    output_count = requirement.index("++result.fixed_output_endpoints")
    input_count = requirement.index("++result.fixed_input_endpoints")
    explicit_none = requirement.index(
        "result.mode == NativeEndpointMode::NONE", input_count,
    )
    assert output_count < input_count < explicit_none
    assert "result.fixed_output_endpoints != 0" in requirement[explicit_none:]
    assert "result.fixed_input_endpoints != 0" in requirement[explicit_none:]
    assert "endpoint_port->second.type != PORT_IN" in requirement
    assert "allows_odd_slice() const { return mode == NativeEndpointMode::IOB_OUTPUT; }" \
        in source
    assert "xbar-conduction-even-slot-shape" in source
    pre_route = _function(source, "    void preRoute() override",
                          "    bool checkPipAvail(PipId pip) const override")
    requirement_at = pre_route.index("native_endpoint_requirement(ctx, cell)")
    malformed_at = pre_route.index("if (endpoint.malformed())", requirement_at)
    unbound_at = pre_route.index("if (cell->bel == BelId())", requirement_at)
    admission_at = pre_route.index("native_endpoint_cell_admitted", unbound_at)
    assert requirement_at < malformed_at < unbound_at < admission_at
    assert "if (endpoint.active())" in pre_route[unbound_at:admission_at]
    assert SOURCE.read_bytes() == OVERLAY.read_bytes()


def test_strict_preflight_runs_before_core_or_physical_io_claims():
    core = (ROOT / "agamemnon" / "engine" / "features" /
            "core_logic.py").read_text(encoding="utf-8")
    prepare = core[core.index("    def prepare(") :]
    assert prepare.index("validate_module_native_endpoints") < \
        prepare.index("CoreLogicState(")
    bitgen = (ROOT / "agamemnon" / "engine" /
              "bitgen.py").read_text(encoding="utf-8")
    assert bitgen.index("CORE_LOGIC_FEATURE.prepare(") < \
        bitgen.index("PHYSICAL_IO_FEATURE.prepare(")


def test_generic_io_qualifiers_match_add_architecture_pairing_exactly():
    inputs = set()
    outputs = set()
    with (CHIPDB / "rrg_edges_full.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["src_res"].startswith("InputMUX"):
                inputs.add(((row["src_x"], row["src_y"]), row["src_res"]))
            if row["dst_res"].startswith("IOMUX"):
                outputs.add(((row["dst_x"], row["dst_y"]), row["dst_res"]))
    ordered_inputs = sorted(inputs)
    ordered_outputs = sorted(outputs)
    expected = {
        "X%sY%s_IO%d" % (*ordered_inputs[z][0], z)
        for z in range(min(len(ordered_inputs), len(ordered_outputs)))
    }
    generic = re.compile(r"X\d+Y\d+_IO\d+")
    for actual in (
            qualified_input_endpoint_bels(CHIPDB),
            qualified_output_endpoint_bels(CHIPDB),
    ):
        assert {bel for bel in actual if generic.fullmatch(bel)} == expected


def test_wave1_retires_only_the_generic_output_bind_and_retains_exact_families():
    source = SOURCE.read_text(encoding="utf-8")
    output = _function(
        source, "static void pack_output_pin_drivers(Context *ctx)",
        "static void lock_uart_tx_corridors(Context *ctx)",
    )
    # The sole remaining BEL bind and every pip bind are in the retained exact
    # left-pad branch. The ordinary tail stamps intent and never selects a BEL.
    assert output.count("ctx->bindBel(") == 1
    assert "ctx->bindBel(exact_bel, drv, STRENGTH_LOCKED)" in output
    ordinary = output[output.index("set_native_endpoint_mode(ctx, drv") :]
    assert "ctx->bindBel(" not in ordinary
    assert "bindPip" in output
    assert ordinary.startswith(
        "set_native_endpoint_mode(ctx, drv, NativeEndpointMode::IOB_OUTPUT)"
    )
    assert "bestd" not in ordinary and "chosen" not in ordinary

    inputs = _function(
        source, "static void pack_input_pin_consumers(Context *ctx)",
        "static void pack_net_cluster(",
    )
    assert inputs.count("ctx->bindBel(") == 2
    assert "input-pin permuted" in inputs
    assert "ctx->bindBel(chosen, sink, STRENGTH_LOCKED)" in inputs
    native_input = inputs[
        inputs.index("if (chosen != BelId() && direct_native_input)"):
        inputs.index("// ABC may put a physical input", inputs.index(
            "if (chosen != BelId() && direct_native_input)"))
    ]
    assert "NativeEndpointMode::IOB_INPUT" in native_input
    assert "ctx->bindBel(" not in native_input
    assert "bindPip" in inputs

    dense = _function(source, "static void pack_dense(Context *ctx)",
                      "static void hint_replay_bels(Context *ctx")
    condplace = _function(source, "static void pack_condplace(Context *ctx",
                          "struct AgrvImpl : ViaductAPI")
    exit_anchor = _function(source, "    void pack_exit_anchor()",
                            "    void pack_entry_anchor()")
    for block in (dense, condplace, exit_anchor):
        assert "endpoint.active()" in block
        assert "continue;" in block[block.index("endpoint.active()") :]
    # Replay remains an explicit diagnostic/exact path and is absent unless a
    # caller opts into one of its two environment variables.
    replay = _function(source, "static void hint_replay_bels(Context *ctx",
                       "static void pack_route_through_bels(Context *ctx)")
    assert 'std::getenv("AGRV2K_REPLAY_BELS")' in replay
    assert 'std::getenv("AGRV2K_REPLAY_BELS_IN_DB")' in replay


def test_pack_only_leaves_ordinary_output_driver_unbound_and_typed(tmp_path):
    result, log, output = _run(tmp_path, "pack_only", _design(), "--pack-only")
    assert result.returncode == 0, log
    driver = _driver(output)
    assert driver["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_OUTPUT"
    assert "NEXTPNR_BEL" not in driver["attributes"]
    assert "AGRV2K_IO_PINPACKED" not in driver["attributes"]
    assert "for ordinary-placement legality" in log
    assert "CONDPLACE embedded 0 cells" in log
    assert "output-pin packed 'driver'" not in log


def test_heap_owns_native_endpoint_and_occupancy_admits_an_alternate_legal_bel(tmp_path):
    first, first_log, first_output = _run(
        tmp_path, "heap_first", _design(), "--no-route", "--placer", "heap",
    )
    assert first.returncode == 0, first_log
    first_bel = _driver(first_output)["attributes"]["NEXTPNR_BEL"]

    second, second_log, second_output = _run(
        tmp_path, "heap_occupied", _design(occupant_bel=first_bel),
        "--no-route", "--placer", "heap",
    )
    assert second.returncode == 0, second_log
    second_bel = _driver(second_output)["attributes"]["NEXTPNR_BEL"]

    assert first_bel != second_bel
    assert _output_reaches(first_bel)
    assert _output_reaches(second_bel)
    for log in (first_log, second_log):
        assert "CONDPLACE embedded 0 cells" in log
        assert "HeAP Placer Time:" in log
        assert "output-pin packed 'driver'" not in log
        assert "DENSE-placed" not in log
        assert "replay-bound" not in log


def test_normal_heap_and_router_path_reaches_mandatory_preroute_check(tmp_path):
    result, log, output = _run(
        tmp_path, "heap_route", _design(), "--placer", "heap", "--router", "router2",
    )
    assert result.returncode == 0, log
    assert "HeAP Placer Time:" in log
    assert "pre-route DRC verified 1 typed native endpoint(s)" in log
    assert "Running router2" in log
    assert _driver(output)["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_OUTPUT"


def test_user_fixed_reachable_bel_is_typed_and_accepted(tmp_path):
    result, log, output = _run(
        tmp_path, "fixed_good", _design(driver_bel="X1Y1_SLICE0"),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log
    driver = _driver(output)
    assert driver["attributes"]["NEXTPNR_BEL"] == "X1Y1_SLICE0"
    assert driver["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_OUTPUT"
    assert "for user-fixed legality" in log
    assert _output_reaches("X1Y1_SLICE0")


def test_user_fixed_unreachable_bel_is_rejected_by_placer_legality(tmp_path):
    result, log, _ = _run(
        tmp_path, "fixed_bad", _design(driver_bel="X1Y1_SLICE8"),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode != 0
    assert "cannot conduct fixed output net 'driver_to_pad' to 'pad_iob'" in log
    assert "post-placement validity check failed" in log
    assert not _output_reaches("X1Y1_SLICE8")


def test_no_place_cannot_bypass_native_endpoint_preroute_drc(tmp_path):
    result, log, _ = _run(
        tmp_path, "no_place_bad", _design(driver_bel="X1Y1_SLICE8"),
        "--no-place", "--router", "router2", condplace=False,
    )
    assert result.returncode != 0
    assert "pre-route DRC rejects native endpoint" in log
    assert "fixed endpoint pins are unreachable" in log
    assert "Running router2" not in log


@pytest.mark.parametrize("mode", ["IOB_INPUT", "IOB_OUTPUT"])
def test_no_place_rejects_unbound_active_native_endpoint_before_router(
        tmp_path, mode):
    if mode == "IOB_INPUT":
        design = _input_design(mode=mode)
        cell_name = "consumer"
    else:
        design = _design(mode=mode)
        cell_name = "driver"
    result, log, _ = _run(
        tmp_path, "unbound_no_place_" + mode.lower(), design,
        "--no-place", "--router", "router2", condplace=False, pinpack=False,
    )
    assert result.returncode != 0
    assert "pre-route DRC rejects active native endpoint on '%s'" % cell_name in log
    assert "no BEL is bound before routing" in log
    assert "Running router2" not in log


def test_pack_only_leaves_direct_combinational_input_consumer_unbound_and_typed(
        tmp_path):
    result, log, output = _run(
        tmp_path, "input_pack_only", _input_design(), "--pack-only",
    )
    assert result.returncode == 0, log
    consumer = _consumer(output)
    assert consumer["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_INPUT"
    assert "NEXTPNR_BEL" not in consumer["attributes"]
    assert "AGRV2K_IO_PINPACKED" not in consumer["attributes"]
    assert "for ordinary-placement legality" in log
    assert "retained 0 exact consumer(s) and deferred 1 native consumer(s)" in log
    assert "input-pin packed pad 'pad_iob' consumer 'consumer'" not in log


def test_heap_owns_native_input_and_occupancy_admits_alternate_reachable_bel(
        tmp_path):
    first, first_log, first_output = _run(
        tmp_path, "input_heap_first", _input_design(),
        "--no-route", "--placer", "heap",
    )
    assert first.returncode == 0, first_log
    first_bel = _consumer(first_output)["attributes"]["NEXTPNR_BEL"]

    second, second_log, second_output = _run(
        tmp_path, "input_heap_occupied",
        _input_design(occupant_bel=first_bel),
        "--no-route", "--placer", "heap",
    )
    assert second.returncode == 0, second_log
    second_bel = _consumer(second_output)["attributes"]["NEXTPNR_BEL"]

    assert first_bel != second_bel
    assert _input_reaches(first_bel)
    assert _input_reaches(second_bel)
    for bel in (first_bel, second_bel):
        z = int(bel.rsplit("SLICE", 1)[1])
        assert z != 0 and z % 2 == 0
    for log in (first_log, second_log):
        assert "CONDPLACE embedded 0 cells" in log
        assert "HeAP Placer Time:" in log
        assert "input-pin packed pad 'pad_iob' consumer 'consumer'" not in log


def test_normal_heap_routes_native_input_through_mandatory_preroute_check(tmp_path):
    result, log, output = _run(
        tmp_path, "input_heap_route", _input_design(),
        "--placer", "heap", "--router", "router2",
    )
    assert result.returncode == 0, log
    assert "HeAP Placer Time:" in log
    assert "pre-route DRC verified 1 typed native endpoint(s)" in log
    assert "Running router2" in log
    assert _consumer(output)["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == \
        "IOB_INPUT"


def test_mixed_input_output_slice_retains_exact_input_family(tmp_path):
    design = _input_design()
    module = design["modules"]["top"]
    module["cells"]["consumer"]["connections"]["F"] = [3]
    output_name, output_iob = _iob("mixed_output_iob", bit=3)
    output_iob["connections"]["PAD"] = [11]
    module["cells"][output_name] = output_iob
    module["ports"]["output_pad"] = {"direction": "output", "bits": [11]}
    module["netnames"]["output_pad"] = {
        "hide_name": 0, "bits": [11], "attributes": {},
    }

    result, log, output = _run(
        tmp_path, "input_output_mixed", design, "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log
    consumer = _consumer(output)
    assert consumer["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_OUTPUT"
    assert consumer["attributes"]["AGRV2K_IO_PINPACKED"] == \
        format(1, "032b")
    assert "NEXTPNR_BEL" in consumer["attributes"]
    assert "input-pin packed pad 'pad_iob' consumer 'consumer'" in log
    assert "deferred 0 native consumer(s)" in log


def test_user_fixed_reachable_native_input_is_typed_and_accepted(tmp_path):
    result, log, output = _run(
        tmp_path, "input_fixed_good",
        _input_design(consumer_bel="X19Y12_SLICE4"),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode == 0, log
    consumer = _consumer(output)
    assert consumer["attributes"]["NEXTPNR_BEL"] == "X19Y12_SLICE4"
    assert consumer["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_INPUT"
    assert "for user-fixed legality" in log
    assert _input_reaches("X19Y12_SLICE4")


def test_user_fixed_graph_reachable_odd_input_bel_retains_live_even_slot_reject(
        tmp_path):
    assert _input_reaches("X19Y12_SLICE3")
    result, log, _ = _run(
        tmp_path, "input_fixed_odd",
        _input_design(consumer_bel="X19Y12_SLICE3"),
        "--no-route", "--placer", "heap",
    )
    assert result.returncode != 0
    assert "ordinary cell 'consumer' at X19Y12_SLICE3 uses an unqualified odd slice" in log
    assert "post-placement validity check failed" in log


def test_no_place_cannot_bypass_native_input_reachability(tmp_path):
    assert not _input_reaches("X1Y1_SLICE2")
    result, log, _ = _run(
        tmp_path, "input_no_place_bad",
        _input_design(consumer_bel="X1Y1_SLICE2", mode="IOB_INPUT"),
        "--no-place", "--router", "router2", condplace=False, pinpack=False,
    )
    assert result.returncode != 0
    assert "pre-route DRC rejects native endpoint" in log
    assert "fixed endpoint pins are unreachable" in log
    assert "Running router2" not in log


def test_explicit_none_with_fixed_input_shape_fails_cpp_preplacement(tmp_path):
    result, log, _ = _run(
        tmp_path, "input_none_shape_cpp", _input_design(mode="NONE"),
        "--pack-only", condplace=False, pinpack=False,
    )
    assert result.returncode != 0
    assert "pre-placement native-endpoint DRC rejects 'consumer'" in log
    assert "NONE attribute disagrees with a fixed GENERIC_IOB endpoint shape" in log
    assert "Placing design" not in log


def test_explicit_none_with_fixed_output_shape_fails_cpp_preplacement(tmp_path):
    result, log, _ = _run(
        tmp_path, "none_shape_cpp", _design(mode="NONE"),
        "--pack-only", condplace=False, pinpack=False,
    )
    assert result.returncode != 0
    assert "pre-placement native-endpoint DRC rejects 'driver'" in log
    assert "NONE attribute disagrees with a fixed GENERIC_IOB endpoint shape" in log
    assert "Placing design" not in log


def test_strict_validator_accepts_one_or_more_genuine_fixed_iob_outputs():
    one = _design(driver_bel="X19Y12_SLICE8", mode="IOB_OUTPUT")
    requirement = validate_module_native_endpoints(one["modules"]["top"], CHIPDB)
    assert requirement["driver"].fixed_endpoints == ("pad_iob",)

    endpoints = [
        _iob("pad_iob", bel="X19Y13_OPAD0", bit=2),
        _iob("second_pad", bel="X18Y13_OPAD0", bit=2),
    ]
    many = _design(
        driver_bel="X19Y12_SLICE8", mode="IOB_OUTPUT", endpoints=endpoints,
    )
    requirement = validate_module_native_endpoints(many["modules"]["top"], CHIPDB)
    assert requirement["driver"].fixed_endpoints == ("pad_iob", "second_pad")


def test_strict_validator_accepts_genuine_fixed_generic_iob_input():
    design = _input_design(
        consumer_bel="X19Y12_SLICE4", mode="IOB_INPUT",
    )
    requirement = validate_module_native_endpoints(
        design["modules"]["top"], CHIPDB,
    )
    assert requirement["consumer"].fixed_endpoints == ("pad_iob",)


@pytest.mark.parametrize(
    "name, endpoint, ff_used, special_attr, reason",
    [
        ("zero", False, 0, None, "one or more genuine fixed GENERIC_IOB.O"),
        ("registered", None, 1, None, "requires explicit FF_USED=0"),
        ("bad_bel", _input_iob(bel="X99Y99_IO999"), 0, None,
         "malformed or unqualified fixed input NEXTPNR_BEL"),
        ("wrong_port", _input_iob(port="I", direction="input"), 0, None,
         "malformed mixed input endpoint claim"),
        ("wrong_direction", _input_iob(direction="input"), 0, None,
         "port O is not declared output"),
        ("wrong_type", _input_iob(cell_type="FORGED_IO"), 0, None,
         "not GENERIC_IOB"),
        ("identity", None, 0, "AGRV2K_PAD_INPUT_IDENTITY",
         "cannot claim an exact identity"),
        ("synchronizer", None, 0, "agamemnon_pad_sync_stage",
         "cannot claim an exact identity or synchronizer"),
    ],
)
def test_strict_validator_rejects_forged_native_input_shapes(
        name, endpoint, ff_used, special_attr, reason):
    design = _input_design(
        consumer_bel="X19Y12_SLICE4", mode="IOB_INPUT",
        endpoint=endpoint, ff_used=ff_used, special_attr=special_attr,
    )
    module = design["modules"]["top"]
    with pytest.raises(SystemExit, match=reason):
        validate_module_native_endpoints(module, CHIPDB)
    if name == "registered":
        with pytest.raises(SystemExit, match=reason):
            CoreLogicFeature().prepare(
                module, {}, None, {}, chipdb_root=CHIPDB,
            )


def test_strict_native_input_rejects_mixed_fixed_output_endpoint():
    design = _input_design(
        consumer_bel="X19Y12_SLICE4", mode="IOB_INPUT",
    )
    module = design["modules"]["top"]
    module["cells"]["consumer"]["connections"]["F"] = [3]
    module["cells"].update(dict([_iob("output_pad", bit=3)]))
    with pytest.raises(SystemExit, match="cannot also claim a GENERIC_IOB.I"):
        validate_module_native_endpoints(module, CHIPDB)


@pytest.mark.parametrize(
    "name, mode, endpoints, driver_bel, reason",
    [
        ("unknown", "FORGED", [_iob()], "X19Y12_SLICE8", "unknown protocol token"),
        ("malformed", "MALFORMED", [_iob()], "X19Y12_SLICE8", "fail-closed"),
        ("none_shape", "NONE", [_iob()], "X19Y12_SLICE8", "inactive attribute"),
        ("zero", "IOB_OUTPUT", [], "X19Y12_SLICE8", "one or more genuine"),
        ("bad_slice_bel", "IOB_OUTPUT", [_iob()], "FORGED", "placed slice NEXTPNR_BEL"),
        ("bad_iob_bel", "IOB_OUTPUT", [_iob(bel="X99Y99_OPAD0")],
         "X19Y12_SLICE8", "malformed or unqualified fixed output NEXTPNR_BEL"),
        ("wrong_port", "IOB_OUTPUT", [_iob(port="O", direction="output")],
         "X19Y12_SLICE8", "malformed mixed output endpoint claim"),
        ("wrong_direction", "IOB_OUTPUT", [_iob(direction="output")],
         "X19Y12_SLICE8", "port I is not declared input"),
        ("wrong_type", "IOB_OUTPUT", [_iob(cell_type="FORGED_IO")],
         "X19Y12_SLICE8", "not GENERIC_IOB"),
    ],
)
def test_strict_validator_rejects_forged_direct_emission_shapes(
        name, mode, endpoints, driver_bel, reason):
    design = _design(
        driver_bel=driver_bel, mode=mode, endpoints=endpoints,
    )
    module = design["modules"]["top"]
    with pytest.raises(SystemExit, match=reason):
        validate_module_native_endpoints(module, CHIPDB)
    # The actual core-logic entry point performs this check before consulting
    # options, selector cells, or any bit-claim state.
    if name == "unknown":
        with pytest.raises(SystemExit, match=reason):
            CoreLogicFeature().prepare(
                module, {}, None, {}, chipdb_root=CHIPDB,
            )


def test_legacy_attr_absent_routed_corpus_remains_accepted():
    paths = sorted((ROOT / "qualification").glob("*_routed.json"))
    paths += sorted((ROOT / "agamemnon" / "templates").glob("**/*_routed.json"))
    assert len(paths) >= 30
    for path in paths:
        module = json.loads(path.read_text(encoding="utf-8"))["modules"]["top"]
        assert validate_module_native_endpoints(module, CHIPDB) == {}, path
