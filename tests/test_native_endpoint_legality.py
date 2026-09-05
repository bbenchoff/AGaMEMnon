"""N5 native placement and strict emission for fixed I/O endpoints."""

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
DEVDB = Path(os.environ.get("AGAMEMNON_UARCH_DEVDB", str(
    ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "devdb_strict"
)))
SOURCE = ROOT / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc"
OVERLAY = Path(os.environ.get("AGAMEMNON_UARCH_SOURCE", str(
    ROOT / "third_party" / "nextpnr" / "generic" / "viaduct" /
    "agrv2k" / "agrv2k.cc"
)))


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


def _input_iob(name="pad_iob", *, bel="X19Y13_IO22", bit=2, pad_bit=10,
               port="O", direction="output", cell_type="GENERIC_IOB"):
    return name, {
        "hide_name": 0,
        "type": cell_type,
        "parameters": {},
        "attributes": {
            "NEXTPNR_BEL": bel,
            "BEL_STRENGTH": format(5, "032b"),
        },
        "port_directions": {"PAD": "inout", port: direction},
        "connections": {"PAD": [pad_bit], port: [bit]},
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


def _identity_design(*, identity_bel="X19Y12_SLICE4", mode="IOB_INPUT",
                     fabric_bel=None, endpoint_bel="X19Y13_IO22"):
    design = _input_design(consumer_bel=identity_bel, mode=mode)
    module = design["modules"]["top"]
    identity = module["cells"]["consumer"]
    module["cells"]["pad_iob"]["attributes"]["NEXTPNR_BEL"] = endpoint_bel
    identity["attributes"]["AGRV2K_PAD_INPUT_IDENTITY"] = \
        format(1, "032b")
    identity["connections"]["F"] = [3]
    fabric = _slice(bel=fabric_bel, name="fabric", output_bit=4)
    fabric["connections"] = {"I": [3, "x", "x", "x"], "F": [], "Q": []}
    module["cells"]["fabric"] = fabric
    module["netnames"]["identity_to_fabric"] = {
        "hide_name": 0, "bits": [3], "attributes": {},
    }
    return design


def _shared_input_design(*, occupant_bels=(), congestion=False):
    consumer = _slice(name="consumer", output_bit=6)
    # Two-input XOR, independent of the two deliberately unconnected axes.
    consumer["parameters"]["INIT"] = format(0x6666, "016b")
    consumer["connections"] = {
        "I": [2, 4, "x", "x"], "F": [], "Q": [],
    }
    cells = {
        "consumer": consumer,
        "pad_a": _input_iob(
            "pad_a", bel="X19Y13_IO22", bit=2, pad_bit=10,
        )[1],
        "pad_b": _input_iob(
            "pad_b", bel="X19Y13_IO23", bit=4, pad_bit=11,
        )[1],
    }
    for index, bel in enumerate(occupant_bels):
        occupied = _slice(
            bel=bel, name="occupied_%d" % index, output_bit=30 + index,
        )
        occupied["parameters"]["INIT"] = format(0, "016b")
        occupied["connections"] = {"I": ["x"] * 4, "F": [], "Q": []}
        cells["occupied_%d" % index] = occupied
    netnames = {
        "pad_a": {"hide_name": 0, "bits": [10], "attributes": {}},
        "pad_b": {"hide_name": 0, "bits": [11], "attributes": {}},
        "pad_a_to_consumer": {
            "hide_name": 0, "bits": [2], "attributes": {},
        },
        "pad_b_to_consumer": {
            "hide_name": 0, "bits": [4], "attributes": {},
        },
    }
    if congestion:
        for index in range(4):
            bit = 40 + index
            source = _slice(name="traffic_source_%d" % index, output_bit=bit)
            source["parameters"]["INIT"] = format(0xFFFF, "016b")
            source["connections"] = {"I": ["x"] * 4, "F": [bit], "Q": []}
            sink = _slice(name="traffic_sink_%d" % index, output_bit=50 + index)
            sink["connections"] = {
                "I": [bit, "x", "x", "x"], "F": [], "Q": [],
            }
            cells["traffic_source_%d" % index] = source
            cells["traffic_sink_%d" % index] = sink
            netnames["traffic_%d" % index] = {
                "hide_name": 0, "bits": [bit], "attributes": {},
            }
    return {
        "creator": "N5.3 generated pad-isolation compiled fixture",
        "modules": {"top": {
            "attributes": {"top": 1},
            "ports": {
                "pad_a_port": {"direction": "input", "bits": [10]},
                "pad_b_port": {"direction": "input", "bits": [11]},
            },
            "cells": cells,
            "netnames": netnames,
        }},
    }


def _run(tmp_path, name, design, *extra, condplace=True, pinpack=True,
         env_overrides=None):
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
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
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


def _identities(output):
    cells = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"] \
        ["cells"]
    return {
        name: cell for name, cell in cells.items()
        if "AGRV2K_PAD_INPUT_IDENTITY" in cell.get("attributes", {})
    }


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


def _input_reaches(bel, endpoint="X19Y13_IO22", pin="I[0]", endpoint_pin="O"):
    source = None
    target = None
    with (DEVDB / "dev_belpins.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["bel"] == endpoint and row["pin"] == endpoint_pin:
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


def _input_reachable_bels(endpoint="X19Y13_IO22", pin="I[0]"):
    source = None
    targets = {}
    with (DEVDB / "dev_belpins.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["bel"] == endpoint and row["pin"] == "O":
                source = row["wire"]
            if row["pin"] == pin and re.fullmatch(r"X\d+Y\d+_SLICE\d+", row["bel"]):
                targets[row["bel"]] = row["wire"]
    assert source
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
    return {
        bel for bel, target in targets.items()
        if target in reachable
    }


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


def _assert_overlay_matches(source, overlay, *, explicitly_configured):
    if not overlay.is_file():
        if explicitly_configured:
            pytest.fail(f"configured AGAMEMNON_UARCH_SOURCE is not a file: {overlay}")
        pytest.skip("optional nextpnr source checkout absent; set AGAMEMNON_UARCH_SOURCE")
    assert source.read_bytes() == overlay.read_bytes(), "native nextpnr overlay differs from shipped source"


def test_installed_native_overlay_matches_shipped_source():
    _assert_overlay_matches(SOURCE, OVERLAY,
                            explicitly_configured="AGAMEMNON_UARCH_SOURCE" in os.environ)


@pytest.mark.parametrize("case", ("absent_optional", "absent_explicit", "matching", "different"))
def test_overlay_check_distinguishes_optional_installation_from_mismatch(tmp_path, case):
    source, overlay = tmp_path / "source.cc", tmp_path / "overlay.cc"
    source.write_bytes(b"source\n")
    if case == "absent_optional":
        with pytest.raises(pytest.skip.Exception, match="optional nextpnr source checkout absent"):
            _assert_overlay_matches(source, overlay, explicitly_configured=False)
    elif case == "absent_explicit":
        with pytest.raises(pytest.fail.Exception, match="configured AGAMEMNON_UARCH_SOURCE"):
            _assert_overlay_matches(source, overlay, explicitly_configured=True)
    elif case == "matching":
        overlay.write_bytes(source.read_bytes())
        _assert_overlay_matches(source, overlay, explicitly_configured=True)
    else:
        overlay.write_bytes(b"different\n")
        with pytest.raises(AssertionError, match="overlay differs"):
            _assert_overlay_matches(source, overlay, explicitly_configured=False)


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
    # The sole remaining BEL bind retains the exact left-pad source site. N5.5
    # moves the 36 corridor PIPs into typed router2 ownership, so the packer no
    # longer binds any PIP. The ordinary tail stamps intent and selects no BEL.
    assert output.count("ctx->bindBel(") == 1
    assert "ctx->bindBel(exact_bel, drv, STRENGTH_LOCKED)" in output
    ordinary = output[output.index("set_native_endpoint_mode(ctx, drv") :]
    assert "ctx->bindBel(" not in ordinary
    assert "bindPip" not in output
    assert "typed corridor deferred to router2" in output
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
    native_start = inputs.index("if (chosen != BelId() &&")
    native_input = inputs[
        native_start:
        inputs.index("// ABC may put a physical input", native_start)
    ]
    assert "NativeEndpointMode::IOB_INPUT" in native_input
    assert "direct_native_input || native_pad_identity" in native_input
    assert "ctx->bindBel(" not in native_input
    assert "bindPip" in inputs
    identity_creation = inputs[
        inputs.index('std::string name = "$pad_input_identity"'):
        inputs.index("int bound = 0;")
    ]
    assert "set_register_input_mode" not in identity_creation
    assert 'params[ctx->id("FF_USED")]' not in identity_creation
    identity_guard = inputs[
        inputs.index("const bool native_pad_identity"):
        inputs.index("if (sink->bel != BelId())")
    ]
    assert identity_guard.index('std::getenv("AGRV2K_INPUT_SLICE")') < \
        identity_guard.index("pad_input_identity_shape_error")
    assert identity_guard.index('std::getenv("AGRV2K_INPUT_TILE")') < \
        identity_guard.index("pad_input_identity_shape_error")

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


def test_pack_only_defers_only_exact_generated_pad_identities(tmp_path):
    result, log, output = _run(
        tmp_path, "identity_pack_only", _shared_input_design(), "--pack-only",
    )
    assert result.returncode == 0, log
    identities = _identities(output)
    assert len(identities) == 2
    for identity in identities.values():
        attrs = identity["attributes"]
        assert attrs["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_INPUT"
        assert "NEXTPNR_BEL" not in attrs
        assert "AGRV2K_IO_PINPACKED" not in attrs
        assert int(identity["parameters"]["INIT"], 2) == 0xAAAA
        assert int(identity["parameters"]["FF_USED"], 2) == 0
        assert int(identity["parameters"]["K"], 2) == 4
        assert len(identity["connections"]["I"]) == 4
        assert isinstance(identity["connections"]["I"][0], int)
        document = json.loads(output.read_text(encoding="utf-8"))
        module = document["modules"]["top"]
        live_bits = {
            bit for net in module["netnames"].values()
            for bit in net["bits"] if isinstance(bit, int)
        }
        assert not live_bits.intersection(identity["connections"]["I"][1:])
        assert len(identity["connections"]["F"]) == 1
        assert identity["connections"].get("Q", []) == []
    consumer = _consumer(output)
    assert int(consumer["parameters"]["INIT"], 2) == 0x6666
    assert "AGRV2K_PAD_INPUT_IDENTITY" not in consumer["attributes"]
    assert "AGRV2K_NATIVE_ENDPOINT_MODE" not in consumer["attributes"]
    assert "isolated 2 physical-pad inputs from shared LUT 'consumer'" in log
    assert log.count("pad-isolation consumer") == 2
    assert "retained 0 exact consumer(s) and deferred 2 native consumer(s)" in log


def test_heap_places_and_router2_routes_generated_pad_identities(tmp_path):
    result, log, output = _run(
        tmp_path, "identity_heap_route", _shared_input_design(),
        "--placer", "heap", "--router", "router2",
    )
    assert result.returncode == 0, log
    document = json.loads(output.read_text(encoding="utf-8"))
    cells = document["modules"]["top"]["cells"]
    identities = _identities(output)
    assert len(identities) == 2
    placed = set()
    for identity in identities.values():
        bel = identity["attributes"]["NEXTPNR_BEL"]
        placed.add(bel)
        z = int(bel.rsplit("SLICE", 1)[1])
        assert z != 0 and z % 2 == 0
        assert bel != "X1Y4_SLICE4"
        input_bit = identity["connections"]["I"][0]
        endpoint = next(
            cell["attributes"]["NEXTPNR_BEL"]
            for cell in cells.values()
            if cell.get("type") == "GENERIC_IOB" and
            cell.get("connections", {}).get("O") == [input_bit]
        )
        assert _input_reaches(bel, endpoint=endpoint)
    assert len(placed) == 2
    assert "HeAP Placer Time:" in log
    assert "pre-route DRC verified 2 typed native endpoint(s)" in log
    assert "Running router2" in log


def test_generated_identity_occupancy_uses_alternate_native_bels(tmp_path):
    first, first_log, first_output = _run(
        tmp_path, "identity_first", _shared_input_design(),
        "--no-route", "--placer", "heap",
    )
    assert first.returncode == 0, first_log
    first_bels = {
        cell["attributes"]["NEXTPNR_BEL"]
        for cell in _identities(first_output).values()
    }
    second, second_log, second_output = _run(
        tmp_path, "identity_occupied",
        _shared_input_design(occupant_bels=sorted(first_bels)),
        "--no-route", "--placer", "heap",
    )
    assert second.returncode == 0, second_log
    second_bels = {
        cell["attributes"]["NEXTPNR_BEL"]
        for cell in _identities(second_output).values()
    }
    assert first_bels.isdisjoint(second_bels)
    assert len(second_bels) == 2


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 7, 11, 19, 31])
def test_generated_identities_route_with_concurrent_ordinary_traffic(
        tmp_path, seed):
    result, log, output = _run(
        tmp_path, "identity_congestion_seed_%d" % seed,
        _shared_input_design(congestion=True),
        "--placer", "heap", "--router", "router2", "--seed", str(seed),
    )
    assert result.returncode == 0, log
    identities = _identities(output)
    assert len(identities) == 2
    bels = {
        cell["attributes"]["NEXTPNR_BEL"] for cell in identities.values()
    }
    assert len(bels) == 2
    for bel in bels:
        z = int(bel.rsplit("SLICE", 1)[1])
        assert z != 0 and z % 2 == 0
        assert bel != "X1Y4_SLICE4"
    assert "pre-route DRC verified 2 typed native endpoint(s)" in log
    assert "Running router2" in log


def test_typed_identity_fails_closed_when_every_admissible_bel_is_occupied(
        tmp_path):
    reachable = _input_reachable_bels()
    admissible = sorted(
        bel for bel in reachable
        if int(bel.rsplit("SLICE", 1)[1]) != 0 and
        int(bel.rsplit("SLICE", 1)[1]) % 2 == 0 and
        bel != "X1Y4_SLICE4"
    )
    assert admissible
    design = _identity_design(identity_bel=None)
    cells = design["modules"]["top"]["cells"]
    for index, bel in enumerate(admissible):
        occupied = _slice(
            bel=bel, name="no_fit_%d" % index, output_bit=1000 + index,
        )
        occupied["parameters"]["INIT"] = format(0, "016b")
        occupied["connections"] = {"I": ["x"] * 4, "F": [], "Q": []}
        cells["no_fit_%d" % index] = occupied
    result, log, output = _run(
        tmp_path, "identity_no_fit", design,
        "--no-route", "--placer", "heap", condplace=False, pinpack=False,
    )
    assert result.returncode == 125
    assert ("Unable to find legal placement for cell 'consumer' of type "
            "'GENERIC_SLICE' after 10001 attempts") in log
    assert "placer-heap-cell-placement-timeout" in log
    assert "Running router2" not in log
    assert not output.exists()


def test_generated_identity_preserves_forced_input_diagnostic_fallback(tmp_path):
    result, log, output = _run(
        tmp_path, "identity_forced_slice", _shared_input_design(),
        "--pack-only", env_overrides={"AGRV2K_INPUT_SLICE": "4"},
    )
    assert result.returncode == 0, log
    identities = _identities(output)
    assert len(identities) == 2
    retained = 0
    for identity in identities.values():
        attrs = identity["attributes"]
        assert "AGRV2K_NATIVE_ENDPOINT_MODE" not in attrs
        if "AGRV2K_IO_PINPACKED" in attrs:
            retained += 1
            assert attrs["AGRV2K_IO_PINPACKED"] == format(1, "032b")
        else:
            # This forced diagnostic has no second exact SLICE4 fit.  N5.3
            # retains that legacy no-candidate result instead of granting the
            # unbound identity native placement freedom.
            assert "AGRV2K_IO_PINPACKED" not in attrs
    assert retained == 1
    assert "deferred 0 native consumer(s)" in log
    assert "pad-isolation consumer" not in log
    assert log.count("input-pin packed pad") == 1
    assert "-> X19Y12_SLICE4" in log


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


def test_user_fixed_exact_identity_is_accepted_on_reachable_nonzero_even_bel(
        tmp_path):
    result, log, output = _run(
        tmp_path, "identity_fixed_good", _identity_design(),
        "--no-route", "--placer", "heap", pinpack=False,
    )
    assert result.returncode == 0, log
    identity = _consumer(output)
    assert identity["attributes"]["NEXTPNR_BEL"] == "X19Y12_SLICE4"
    assert identity["attributes"]["AGRV2K_NATIVE_ENDPOINT_MODE"] == "IOB_INPUT"
    assert _input_reaches("X19Y12_SLICE4")


@pytest.mark.parametrize(
    "bel, reason, endpoint_bel",
    [
        ("X19Y12_SLICE0", "requires a nonzero even slice", "X19Y13_IO22"),
        ("X19Y12_SLICE3", "requires a nonzero even slice", "X19Y13_IO22"),
        ("X1Y4_SLICE4", "other than X1Y4_SLICE4", "X19Y13_IO23"),
        ("X1Y1_SLICE2", "fixed input net", "X19Y13_IO22"),
    ],
)
def test_user_fixed_identity_rejects_forbidden_or_unreachable_bels(
        tmp_path, bel, reason, endpoint_bel):
    if bel == "X1Y4_SLICE4":
        assert _input_reaches(bel, endpoint=endpoint_bel)
    result, log, _ = _run(
        tmp_path, "identity_fixed_bad_" + bel.lower(),
        _identity_design(identity_bel=bel, endpoint_bel=endpoint_bel),
        "--no-route", "--placer", "heap", pinpack=False,
    )
    assert result.returncode != 0
    assert reason in log
    assert "post-placement validity check failed" in log


def test_no_place_accepts_fixed_exact_identity_with_same_admission(tmp_path):
    result, log, _ = _run(
        tmp_path, "identity_no_place_good",
        _identity_design(fabric_bel="X19Y12_SLICE6"),
        "--no-place", "--router", "router2", condplace=False, pinpack=False,
    )
    assert result.returncode == 0, log
    assert "pre-route DRC verified 1 typed native endpoint(s)" in log
    assert "Running router2" in log


def test_no_place_rejects_fixed_identity_forbidden_site_before_router(tmp_path):
    result, log, _ = _run(
        tmp_path, "identity_no_place_bad",
        _identity_design(
            identity_bel="X19Y12_SLICE0", fabric_bel="X19Y12_SLICE6",
        ),
        "--no-place", "--router", "router2", condplace=False, pinpack=False,
    )
    assert result.returncode != 0
    assert "pre-route DRC rejects native endpoint" in log
    assert "bound BEL fails its typed physical admission" in log
    assert "Running router2" not in log


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


def test_strict_validator_accepts_registered_output_with_q_feedback():
    design = _design(driver_bel="X19Y12_SLICE8", mode="IOB_OUTPUT")
    driver = design["modules"]["top"]["cells"]["driver"]
    driver["parameters"]["FF_USED"] = format(1, "032b")
    driver["connections"] = {"I": [2, "x", "x", "x"], "F": [], "Q": [2]}

    requirement = validate_module_native_endpoints(
        design["modules"]["top"], CHIPDB,
    )
    assert requirement["driver"].mode == "IOB_OUTPUT"
    assert requirement["driver"].fixed_endpoints == ("pad_iob",)


def test_strict_validator_does_not_infer_iob_input_from_self_driven_feedback():
    design = _design(driver_bel="X19Y12_SLICE8", mode="IOB_INPUT")
    driver = design["modules"]["top"]["cells"]["driver"]
    driver["parameters"]["FF_USED"] = format(1, "032b")
    driver["connections"] = {"I": [2, "x", "x", "x"], "F": [], "Q": [2]}

    with pytest.raises(SystemExit, match="one or more genuine fixed GENERIC_IOB.O"):
        validate_module_native_endpoints(design["modules"]["top"], CHIPDB)


@pytest.mark.parametrize(
    "malformed_directions",
    [
        {"I": "output", "F": "output", "Q": "input"},
        {"I": "input", "F": "output"},
        {"I": "input", "F": "output", "Q": None},
        {"I": "input", "F": "output", "Q": "unknown"},
        None,
    ],
)
def test_strict_validator_rejects_untrusted_feedback_port_directions(
        malformed_directions):
    design = _design(driver_bel="X19Y12_SLICE8", mode="IOB_OUTPUT")
    driver = design["modules"]["top"]["cells"]["driver"]
    driver["parameters"]["FF_USED"] = format(1, "032b")
    driver["connections"] = {"I": [2, "x", "x", "x"], "F": [], "Q": [2]}
    if malformed_directions is None:
        driver.pop("port_directions")
    else:
        driver["port_directions"] = malformed_directions

    with pytest.raises(SystemExit, match="direction"):
        validate_module_native_endpoints(design["modules"]["top"], CHIPDB)


def test_strict_validator_accepts_genuine_fixed_generic_iob_input():
    design = _input_design(
        consumer_bel="X19Y12_SLICE4", mode="IOB_INPUT",
    )
    requirement = validate_module_native_endpoints(
        design["modules"]["top"], CHIPDB,
    )
    assert requirement["consumer"].fixed_endpoints == ("pad_iob",)


def test_strict_validator_accepts_exact_pad_identity_shape():
    design = _identity_design()
    requirement = validate_module_native_endpoints(
        design["modules"]["top"], CHIPDB,
    )
    assert requirement["consumer"].mode == "IOB_INPUT"
    assert requirement["consumer"].fixed_endpoints == ("pad_iob",)


@pytest.mark.parametrize(
    "case, reason",
    [
        ("marker", "marker is not numeric 1"),
        ("init_missing", "exact INIT=0xAAAA"),
        ("init", "exact INIT=0xAAAA"),
        ("k", "exact K=4"),
        ("ff_missing", "explicit FF_USED=0"),
        ("ff", "explicit FF_USED=0"),
        ("i1", r"I\[1:3\] disconnected"),
        ("f", "one live F output"),
        ("q", "Q disconnected"),
        ("extra_port", "unexpected live port"),
        ("endpoint_count", "exactly one fixed GENERIC_IOB.O"),
        ("f_consumer", "ordinary fabric consumer"),
        ("mixed_f_consumer", "only ordinary fabric consumers"),
        ("pinpacked", "special attribute"),
        ("sync", "cannot claim a synchronizer root"),
        ("direct_d", "special attribute"),
        ("route_through", "special attribute"),
        ("carry", "dedicated carry ports"),
        ("cluster", "special attribute"),
        ("register_mode", "REGISTER_INPUT_MODE=NONE"),
    ],
)
def test_strict_validator_rejects_forged_pad_identity_shape(case, reason):
    design = _identity_design()
    module = design["modules"]["top"]
    identity = module["cells"]["consumer"]
    if case == "marker":
        identity["attributes"]["AGRV2K_PAD_INPUT_IDENTITY"] = format(2, "032b")
    elif case == "init_missing":
        del identity["parameters"]["INIT"]
    elif case == "init":
        identity["parameters"]["INIT"] = format(0x5555, "016b")
    elif case == "k":
        identity["parameters"]["K"] = format(3, "032b")
    elif case == "ff_missing":
        del identity["parameters"]["FF_USED"]
    elif case == "ff":
        identity["parameters"]["FF_USED"] = format(1, "032b")
    elif case == "i1":
        identity["connections"]["I"][1] = 3
    elif case == "f":
        identity["connections"]["F"] = []
    elif case == "q":
        identity["connections"]["Q"] = [7]
        module["netnames"]["forged_q"] = {
            "hide_name": 0, "bits": [7], "attributes": {},
        }
    elif case == "extra_port":
        identity["port_directions"]["CLK"] = "input"
        identity["connections"]["CLK"] = [8]
        module["netnames"]["forged_clk"] = {
            "hide_name": 0, "bits": [8], "attributes": {},
        }
    elif case == "endpoint_count":
        second_name, second = _input_iob(
            "second_pad", bel="X19Y13_IO23", bit=2, pad_bit=11,
        )
        module["cells"][second_name] = second
    elif case == "f_consumer":
        del module["cells"]["fabric"]
    elif case == "mixed_f_consumer":
        module["cells"]["hard_sink"] = {
            "hide_name": 0,
            "type": "MCU_DOUT",
            "parameters": {},
            "attributes": {},
            "port_directions": {"DIN": "input"},
            "connections": {"DIN": [3]},
        }
    elif case == "pinpacked":
        identity["attributes"]["AGRV2K_IO_PINPACKED"] = format(1, "032b")
    elif case == "sync":
        identity["attributes"]["agamemnon_pad_sync_stage"] = "stage1"
    elif case == "direct_d":
        identity["attributes"]["agamemnon_direct_d_feedback"] = format(1, "032b")
    elif case == "route_through":
        identity["attributes"]["AGRV2K_ROUTE_THROUGH"] = format(1, "032b")
    elif case == "carry":
        identity["port_directions"]["CIN"] = "input"
        identity["connections"]["CIN"] = []
    elif case == "cluster":
        identity["attributes"]["NEXTPNR_CLUSTER"] = "forged_cluster"
    elif case == "register_mode":
        identity["attributes"]["AGRV2K_REGISTER_INPUT_MODE"] = "DIRECT_D_I3"
    with pytest.raises(SystemExit, match=reason):
        validate_module_native_endpoints(module, CHIPDB)


@pytest.mark.parametrize(
    "case, reason",
    [
        ("marker", "marker is not numeric 1"),
        ("init", "exact INIT=0xAAAA"),
    ],
)
def test_cpp_and_python_reject_same_serialized_identity_forgery(
        tmp_path, case, reason):
    design = _identity_design()
    identity = design["modules"]["top"]["cells"]["consumer"]
    if case == "marker":
        # JSON's binary spelling is loaded as a numeric C++ Property; Python's
        # decoder intentionally accepts the same representation.
        identity["attributes"]["AGRV2K_PAD_INPUT_IDENTITY"] = format(2, "032b")
    else:
        identity["parameters"]["INIT"] = format(0x5555, "016b")
    with pytest.raises(SystemExit, match=reason):
        validate_module_native_endpoints(design["modules"]["top"], CHIPDB)
    result, log, _ = _run(
        tmp_path, "identity_forged_" + case, design,
        "--no-route", "--placer", "heap", pinpack=False,
    )
    assert result.returncode != 0
    assert reason in log
    assert "post-placement validity check failed" in log


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
         "pad identity requires one live F output"),
        ("synchronizer", None, 0, "agamemnon_pad_sync_stage",
         "cannot claim a synchronizer"),
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


@pytest.mark.parametrize("seed", [2, 4, 7])
def test_heap_places_a_consumer_of_qualified_hsize1_logic_entry(tmp_path, seed):
    # HSIZE1 previously had no reachable LUT input because first-hop
    # admission discarded its separately qualified InputMUX05 corridor.
    # Exercise actual placement and independently check the chosen input.
    consumer = _slice(name="consumer")
    consumer["connections"] = {"I": [2, "x", "x", "x"], "F": [], "Q": []}
    design = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {},
        "cells": {
            "consumer": consumer,
            "arbitrary_hard_source": {
                "type": "MCU_AHB_HSIZE1", "parameters": {}, "attributes": {},
                "port_directions": {"DIN": "output"},
                "connections": {"DIN": [2]},
            },
        },
        "netnames": {"hard_input": {"bits": [2], "attributes": {}}},
    }}}
    result, log, output = _run(
        tmp_path, "unique_mcu_%d" % seed, design,
        "--no-pack", "--no-route", "--placer", "heap", "--seed", str(seed),
        condplace=False, pinpack=False,
    )
    assert result.returncode == 0, log
    cells = json.loads(output.read_text(encoding="utf-8"))["modules"]["top"]["cells"]
    assert _input_reaches(
        cells["consumer"]["attributes"]["NEXTPNR_BEL"],
        endpoint=cells["arbitrary_hard_source"]["attributes"]["NEXTPNR_BEL"],
        endpoint_pin="DIN",
    )


@pytest.mark.parametrize("input_pin,reachable", [(0, False), (1, True)])
def test_local_slice_output_topology_uses_actual_pins(tmp_path, input_pin, reachable):
    source_bel, sink_bel = "X14Y12_SLICE4", "X14Y12_SLICE2"
    assert _input_reaches(sink_bel, endpoint=source_bel, endpoint_pin="F",
                          pin="I[%d]" % input_pin) == reachable
    driver = _slice(bel=source_bel)
    driver["connections"]["I"] = ["x"] * 4
    driver["parameters"]["INIT"] = format(0, "016b")
    consumer = _slice(bel=sink_bel, name="consumer")
    inputs = ["x"] * 4
    inputs[input_pin] = 2
    consumer["connections"] = {"I": inputs, "F": [], "Q": []}
    consumer["parameters"]["INIT"] = format(0xAAAA if input_pin == 0 else 0xCCCC, "016b")
    design = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {},
        "cells": {"driver": driver, "consumer": consumer},
        "netnames": {"data": {"bits": [2], "attributes": {}}},
    }}}
    result, log, _ = _run(
        tmp_path, "local_output_%d" % input_pin, design,
        "--no-pack", "--no-route", "--placer", "heap",
        condplace=False, pinpack=False,
        env_overrides={"AGRV2K_LOCAL_OUTPUT_REACH": "1"},
    )
    if reachable:
        assert result.returncode == 0, log
    else:
        assert result.returncode != 0, log
        assert "local output topology cannot conduct" in log


def test_no_pack_no_place_routes_actual_slice_input_arc(tmp_path):
    """Exit zero is insufficient: imported packed cells need physical pin maps."""
    driver = _slice(bel="X14Y12_SLICE4")
    driver["connections"]["I"] = ["x"] * 4
    driver["parameters"]["INIT"] = format(0, "016b")
    consumer = _slice(bel="X14Y12_SLICE2", name="consumer")
    consumer["connections"] = {"I": ["x", 2, "x", "x"], "F": [], "Q": []}
    consumer["parameters"]["INIT"] = format(0xCCCC, "016b")
    design = {"modules": {"top": {
        "attributes": {"top": 1}, "ports": {},
        "cells": {"driver": driver, "consumer": consumer},
        "netnames": {"data": {"bits": [2], "attributes": {}}},
    }}}
    result, log, output = _run(
        tmp_path, "imported_actual_arc", design,
        "--no-pack", "--no-place", "--router", "router2",
        condplace=False, pinpack=False,
    )
    assert result.returncode == 0, log
    net = json.loads(output.read_text())["modules"]["top"]["netnames"]["data"]
    assert "X14Y12_IMUX09" in net.get("attributes", {}).get("ROUTING", ""), log
