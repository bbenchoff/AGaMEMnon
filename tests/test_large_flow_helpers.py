import json
import csv
import hashlib
import os
import re
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "agamemnon" / "engine"


def _sha256(path):
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_serv_rv32i_signature_sources_match_recorded_evidence():
    qualification = REPO / "qualification"
    source = qualification / "serv_rv32i_smoke.v"
    assembly = qualification / "serv_rv32i_smoke.S"
    heartbeat = qualification / "serv_rv32i_heartbeat.v"
    pcf = qualification / "serv_rv32i_smoke_L48.pcf"

    verilog = source.read_text()
    for opcode in (
        "00500093", "00209113", "00714193", "01300213",
        "00419463", "00418663", "00002023", "ffdff06f",
        "00302023",
    ):
        assert opcode in verilog
    assert "mem_dat == 32'd19" in verilog
    assert "SERV_RV32I_HEARTBEAT" in verilog
    assert "mem_adr[5:0] == 6'h20" in verilog
    assert "`define SERV_RV32I_HEARTBEAT" in heartbeat.read_text()
    assert pcf.read_text().splitlines()[1:] == [
        "set_io pass  PIN_25", "set_io reset PIN_10"
    ]

    records = [json.loads(line) for line in
               (qualification / "serv_compliance_evidence.jsonl").read_text().splitlines()]
    record = next(r for r in records
                  if r["trial_id"] == "2026-07-15-serv-seven-form-signature-and-jal-heartbeat")
    assert record["verdict"] == "pass"
    assert record["artifact_hash_mode"] == "sha256-lf-v1"
    assert record["pack_environment"] == {
        "AGAMEMNON_HSE": "8",
        "AGAMEMNON_LEFT_PAD_OUT": "1",
        "AGAMEMNON_SYSCLK": "25",
    }
    assert record["source_sha256"] == _sha256(source)
    assert record["assembly_sha256"] == _sha256(assembly)
    assert record["signature_testbench_sha256"] == _sha256(
        qualification / "tb_serv_rv32i_smoke.v"
    )
    assert record["heartbeat_wrapper_sha256"] == _sha256(heartbeat)
    assert record["heartbeat_testbench_sha256"] == _sha256(
        qualification / "tb_serv_rv32i_heartbeat.v"
    )
    assert record["pcf_sha256"] == _sha256(pcf)
    assert record["signature_build"]["routed_sha256"] == _sha256(
        qualification / "serv_rv32i_smoke_L48_routed.json"
    )
    assert record["heartbeat_build"]["routed_sha256"] == _sha256(
        qualification / "serv_rv32i_heartbeat_L48_routed.json"
    )
    assert record["signature_build"]["predicted"] == 0
    assert record["signature_build"]["legacy"] == 0
    assert record["signature_build"]["unmapped"] == 0
    assert record["heartbeat_build"]["predicted"] == 0
    assert record["heartbeat_build"]["legacy"] == 0
    assert record["heartbeat_build"]["unmapped"] == 0


def _write_netlist(path, cells, netnames=None):
    path.write_text(json.dumps({"modules": {"top": {
        "cells": cells, "netnames": netnames or {}, "ports": {}, "attributes": {}
    }}}))


def test_uarch_single_slice_pin_sets_exact_bel_and_ignores_ground(tmp_path):
    from agamemnon.cli import _pin_uarch_single_slice

    path = tmp_path / "one.json"
    _write_netlist(path, {
        "logic": {"type": "LUT", "attributes": {}},
        "$PACKER_GND": {"type": "GENERIC_SLICE", "attributes": {}},
    })
    assert _pin_uarch_single_slice(path, "X19Y12_SLICE2") == "logic"
    cells = json.loads(path.read_text())["modules"]["top"]["cells"]
    assert cells["logic"]["attributes"]["BEL"] == "X19Y12_SLICE2"
    assert "BEL" not in cells["$PACKER_GND"]["attributes"]


def test_uarch_single_slice_pin_rejects_ambiguous_design(tmp_path):
    from agamemnon.cli import _pin_uarch_single_slice

    path = tmp_path / "two.json"
    _write_netlist(path, {
        "a": {"type": "LUT", "attributes": {}},
        "b": {"type": "LUT", "attributes": {}},
    })
    with pytest.raises(ValueError, match="exactly one non-ground"):
        _pin_uarch_single_slice(path, "X19Y12_SLICE2")


def test_live_bram_portb_detection_ignores_dangling_output_bits(tmp_path):
    from agamemnon.cli import _json_has_live_bram_portb

    bram = {"type": "ALTA_BRAM9K", "connections": {"DataOutB": [10, 11]}}
    netlist = tmp_path / "bram.json"
    _write_netlist(netlist, {"ram": bram})
    assert not _json_has_live_bram_portb(netlist)

    cells = {
        "ram": bram,
        "use": {"type": "GENERIC_SLICE", "connections": {"I": [11], "F": [12]}},
    }
    _write_netlist(netlist, cells)
    assert _json_has_live_bram_portb(netlist)


def test_direct_d_admission_requires_exact_distinct_qualified_bels(tmp_path):
    from agamemnon.cli import _json_admits_direct_d

    netlist = tmp_path / "directd.json"
    _write_netlist(netlist, {"comb": {"type": "LUT", "attributes": {}}})
    assert not _json_admits_direct_d(netlist)

    def tagged(bel=None):
        attributes = {"agamemnon_direct_d_feedback": "1"}
        if bel is not None:
            attributes["BEL"] = bel
        return {"type": "LUT", "attributes": attributes}

    _write_netlist(netlist, {"state": tagged("X14Y11_SLICE7")})
    assert _json_admits_direct_d(netlist)

    _write_netlist(netlist, {
        "s4": tagged("X14Y11_SLICE4"), "s5": tagged("X14Y11_SLICE5"),
        "s6": tagged("X14Y11_SLICE6"), "s7": tagged("X14Y11_SLICE7"),
    })
    assert _json_admits_direct_d(netlist)

    for cells, match in (
        ({"state": tagged()}, "unbound=state"),
        ({"a": tagged("X14Y11_SLICE4"), "b": tagged("X14Y11_SLICE4")},
         "duplicate=X14Y11_SLICE4"),
        ({"state": tagged("X15Y8_SLICE12")}, "outside-pool"),
    ):
        _write_netlist(netlist, cells)
        with pytest.raises(ValueError, match=match):
            _json_admits_direct_d(netlist)

    _write_netlist(netlist, {"state": tagged("X15Y8_SLICE12")})
    assert _json_admits_direct_d(
        netlist, {"AGAMEMNON_DIRECT_D_X15Y8_S12_EXPERIMENT": "1"}
    )


    _write_netlist(netlist, {"state": {
        "type": "GENERIC_IOB",
        "attributes": {"agamemnon_direct_d_feedback": "1",
                       "BEL": "X14Y11_SLICE7"},
    }})
    with pytest.raises(ValueError, match="wrong-cell-type"):
        _json_admits_direct_d(netlist)


def test_direct_d_admission_can_use_exact_checkpoint_placements(tmp_path):
    from agamemnon.cli import _json_admits_direct_d, _json_direct_d_bels

    netlist = tmp_path / "directd.json"
    checkpoint = tmp_path / "routed.json"
    _write_netlist(netlist, {
        "state0": {"type": "LUT", "attributes": {"agamemnon_direct_d_feedback": "1"}},
        "state1": {"type": "LUT", "attributes": {"agamemnon_direct_d_feedback": "1"}},
    })
    _write_netlist(checkpoint, {
        "state0": {"type": "GENERIC_SLICE", "attributes": {"NEXTPNR_BEL": "X14Y11_SLICE4"}},
        "state1": {"type": "GENERIC_SLICE", "attributes": {"NEXTPNR_BEL": "X14Y11_SLICE5"}},
    })
    assert _json_admits_direct_d(netlist, qualified_checkpoint=checkpoint)
    assert _json_direct_d_bels(netlist, checkpoint) == [
        "X14Y11_SLICE4", "X14Y11_SLICE5"
    ]


def test_fanout_split_is_linear_and_single_driver(tmp_path):
    cells = {
        "src": {"type": "LUT", "parameters": {"INIT": "1010101010101010", "K": "00000000000000000000000000000100"},
                "attributes": {}, "port_directions": {"I": "input", "Q": "output"},
                "connections": {"I": ["0", "0", "0", "0"], "Q": [2]}},
    }
    for i in range(40):
        cells[f"sink{i}"] = {
            "type": "LUT", "parameters": {"INIT": "1010101010101010", "K": "00000000000000000000000000000100"},
            "attributes": {}, "port_directions": {"I": "input", "Q": "output"},
            "connections": {"I": [2, "0", "0", "0"], "Q": [100 + i]},
        }
    netlist = tmp_path / "fanout.json"
    _write_netlist(netlist, cells, {"wide": {"hide_name": 0, "bits": [2], "attributes": {}}})
    r = subprocess.run([sys.executable, str(ENGINE / "fanout_split.py"), str(netlist), "8"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(netlist.read_text())["modules"]["top"]["cells"]
    buffers = [c for c in out.values() if c.get("attributes", {}).get("agamemnon_fanout_buffer") == "1"]
    assert 0 < len(buffers) <= 40
    drivers = {}
    for c in out.values():
        for port, direction in c.get("port_directions", {}).items():
            if direction == "output":
                for bit in c.get("connections", {}).get(port, []):
                    if isinstance(bit, int):
                        drivers[bit] = drivers.get(bit, 0) + 1
    assert max(drivers.values()) == 1


def test_pcf_bind_json_binds_physical_iobs(tmp_path):
    cells = {
        "$iopadmap$top.reset": {"type": "GENERIC_IOB", "attributes": {},
            "port_directions": {"PAD": "inout", "O": "output"}, "connections": {"PAD": [], "O": [2]}},
        "$iopadmap$top.q": {"type": "GENERIC_IOB", "attributes": {},
            "port_directions": {"PAD": "inout", "I": "input"}, "connections": {"PAD": [], "I": [3]}},
    }
    netlist = tmp_path / "pcf.json"
    _write_netlist(netlist, cells)
    pcf = tmp_path / "pins.pcf"
    pcf.write_text("set_io reset PIN_10\nset_io q PIN_16\n")
    r = subprocess.run([sys.executable, "-I", str(ENGINE / "pcf_bind_json.py"), str(netlist), str(pcf),
                        str(REPO / "agamemnon" / "chipdb")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(netlist.read_text())["modules"]["top"]["cells"]
    assert out["$iopadmap$top.reset"]["attributes"]["NEXTPNR_BEL"] == "X20Y13_IPAD1"
    assert out["$iopadmap$top.q"]["attributes"]["NEXTPNR_BEL"] == "X19Y13_OPAD0"

    env = dict(os.environ)
    env["AGAMEMNON_DEVICE"] = "AGRV2KL64"
    recovered = subprocess.run([sys.executable, "-I", str(ENGINE / "pcf_bind_json.py"), str(netlist), str(pcf),
                                str(REPO / "agamemnon" / "chipdb")],
                               capture_output=True, text=True, env=env)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert "recovered-unqualified" in recovered.stderr
    out = json.loads(netlist.read_text())["modules"]["top"]["cells"]
    assert out["$iopadmap$top.reset"]["attributes"]["NEXTPNR_BEL"] == "X22Y3_IPAD1"
    assert out["$iopadmap$top.q"]["attributes"]["NEXTPNR_BEL"] == "X20Y13_OPAD3"


def test_pcf_bind_json_resolves_vector_port_bits_by_pad_connection(tmp_path):
    cells = {
        "$iopadmap$top.sel": {"type": "GENERIC_IOB", "attributes": {},
            "port_directions": {"PAD": "inout", "O": "output"},
            "connections": {"PAD": [10], "O": [20]}},
        "$iopadmap$top.sel_1": {"type": "GENERIC_IOB", "attributes": {},
            "port_directions": {"PAD": "inout", "O": "output"},
            "connections": {"PAD": [11], "O": [21]}},
        "$iopadmap$top.sel_2": {"type": "GENERIC_IOB", "attributes": {},
            "port_directions": {"PAD": "inout", "O": "output"},
            "connections": {"PAD": [12], "O": [22]}},
    }
    netlist = tmp_path / "pcf_vector.json"
    netlist.write_text(json.dumps({"modules": {"top": {
        "cells": cells, "netnames": {}, "attributes": {},
        "ports": {"sel": {"direction": "input", "bits": [10, 11, 12]}},
    }}}))
    pcf = tmp_path / "vector.pcf"
    pcf.write_text("set_io sel[0] PIN_19\nset_io sel[1] PIN_15\nset_io sel[2] PIN_11\n")
    result = subprocess.run(
        [sys.executable, "-I", str(ENGINE / "pcf_bind_json.py"), str(netlist), str(pcf),
         str(REPO / "agamemnon" / "chipdb")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(netlist.read_text())["modules"]["top"]["cells"]
    assert out["$iopadmap$top.sel"]["attributes"]["NEXTPNR_BEL"] == "X17Y13_IPAD3"
    assert out["$iopadmap$top.sel_1"]["attributes"]["NEXTPNR_BEL"] == "X19Y13_IPAD1"
    assert out["$iopadmap$top.sel_2"]["attributes"]["NEXTPNR_BEL"] == "X20Y13_IPAD2"


def test_cli_large_uarch_defaults_are_strict_router2():
    src = (REPO / "agamemnon" / "cli.py").read_text()
    assert 'default_devdb = "devdb_strict_pcf"' in src
    assert '"AGAMEMNON_STRICT_GATE=1"' in src
    assert '"AGAMEMNON_XBAR_CONDUCT=1"' in src
    assert '"AGAMEMNON_CLEAN_SEL_GATE=1"' in src
    assert 'env["AGAMEMNON_CLEAN_SEL_GATE"] = "1"' in src
    assert 'env["AGAMEMNON_MESH_TEMPLATE"]' not in src
    assert '["--uarch", "agrv2k"' in src
    assert '"--router", "router2"' in src
    assert '"--qualified-checkpoint"' in src
    assert 'run("exact-route-replay"' in src
    assert 'os.path.join(engine, "route_replay.py")' in src
    assert 'a.qualified_checkpoint and getattr(a, "research_unsafe", False)' in src
    assert '"--write-routed"' in src
    assert '"--freq"' in src
    assert 'npr += ["--top", top]' in src
    assert 'env.setdefault("AGRV2K_CONDPLACE_SEED", "4")' in src
    assert 'env.setdefault("NEXTPNR_ROUTER2_STAGNATION_LIMIT", "100")' in src
    assert 'route_seeds = [env["AGRV2K_CONDPLACE_SEED"]] if seed_locked else ["4", "2", "7"]' in src
    assert 'b.add_argument("--cap", type=int, default=5' in src
    assert "heap_first = _uarch_prefers_heap(synth_json)" in src
    assert "heap_first=heap_first" in src
    assert 'attempts.append((0, 0))' in src
    assert 'env.pop("AGRV2K_CONDPLACE", None)' in src
    assert 'placement_seeds = ["1", "2", "3", "4"]' in src
    assert '["--placer", "heap", "--seed", seed]' in src
    assert '"command": attempt_npr' in src
    assert 'dedicated-carry route ladder exhausted' in src
    assert 'a.no_hard_carry = True' in src
    assert 'return cmd_build(a)' in src
    agrv = (REPO / "agamemnon" / "engine" / "uarch" / "agrv2k" / "agrv2k.cc").read_text()
    assert 'if (std::getenv("AGRV2K_CONDPLACE") != nullptr)\n            lock_mcu_dout_corridors()' in agrv
    cap_assignment = 'env["AGRV2K_CONDPLACE_CAP"] = str(cap)'
    assert cap_assignment in src
    # WSLENV must be refreshed after the per-attempt cap exists. Otherwise the
    # Windows log advertises a 2/4/8 sweep while Linux silently runs cap=1.
    assert src.index("_forward_wsl_uarch_environment(env)", src.index(cap_assignment)) \
        > src.index(cap_assignment)


    assert '["nextpnr-generic", "--pre-pack", os.path.join(engine, "arch.py"),\n               "--router", "router2"]' in src

    routing = (ENGINE / "features" / "routing.py").read_text(encoding="utf-8")
    assert "refusing to emit a partial bitstream" in routing
    assert 'options.enabled("AGAMEMNON_ALLOW_UNMAPPED")' in routing
    # Silicon-qualified AHB readback: route BBMUXE02 programs physical
    # CFG_BBMUXE2, not the neighboring field.  An off-by-one here made a
    # correctly running carry counter appear to have a frozen high bit.
    assert 'mux_name = "%s%d" % (df, di)' in routing
    assert "di - 1" not in routing

    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    assert 'parse_after(name, "hwdata")' in uarch
    assert 'near = tkey(14, hwbit <= 17 ? 10 : 9)' in uarch
    assert "lock_registered_mcu_inputs()" in uarch
    assert 'name.find("hwrite")' in uarch
    assert 'name.find("htrans1")' in uarch
    assert 'bn = "X10Y5_MCU_DIN" + std::to_string(lane)' in uarch
    assert "qualified vendor-observed corridor supports one chain through 33 stages" in uarch


def test_default_carry_fallback_is_implicit_uarch_only():
    from agamemnon import cli

    def allowed(**overrides):
        values = dict(uarch=True, hard_carry=False, no_hard_carry=False,
                      qualified_checkpoint=None, qualified_bram_write=None)
        values.update(overrides)
        return cli._default_carry_fallback_allowed(SimpleNamespace(**values))

    assert allowed()
    assert not allowed(uarch=False)
    assert not allowed(hard_carry=True)
    assert not allowed(no_hard_carry=True)
    assert not allowed(qualified_checkpoint="qualified.json")
    assert not allowed(qualified_bram_write="registered")


def test_pack_research_unsafe_sets_explicit_policy_and_removes_strict_gate(monkeypatch):
    from agamemnon import cli

    captured = {}

    def fake_run_child(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cli, "_run_child", fake_run_child)
    monkeypatch.setenv("AGAMEMNON_CLEAN_SEL_GATE", "1")
    monkeypatch.setenv("AGAMEMNON_ALLOW_UNMAPPED", "1")
    cli.cmd_pack(SimpleNamespace(
        input="routed.json", output="image.bin", baseline=None,
        research_unsafe=True,
    ))
    assert captured["env"]["AGAMEMNON_STRICT_POLICY"] == "research-unsafe"
    assert captured["env"]["AGAMEMNON_RESEARCH_UNSAFE"] == "1"
    assert captured["env"]["AGAMEMNON_MESH_TEMPLATE"] == "1"
    assert "AGAMEMNON_CLEAN_SEL_GATE" not in captured["env"]
    assert "AGAMEMNON_ALLOW_UNMAPPED" not in captured["env"]


def test_cli_parses_frequency_target_and_rejects_nonpositive(monkeypatch):
    from agamemnon import cli

    real_cmd_build = cli.cmd_build
    captured = {}
    monkeypatch.setattr(cli, "cmd_build", lambda args: captured.update(vars(args)))
    cli.main(["build", "top.v", "--uarch", "--freq", "48.5"])
    assert captured["freq"] == 48.5

    with pytest.raises(SystemExit) as exc:
        real_cmd_build(SimpleNamespace(freq=0))
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        real_cmd_build(SimpleNamespace(freq=None, hard_carry=True, uarch=False))
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        real_cmd_build(SimpleNamespace(freq=None, hard_carry=False,
                                       no_hard_carry=True, uarch=False))
    assert exc.value.code == 2


def test_build_frequency_selects_the_same_qualified_pll():
    from agamemnon.cli import DEFAULT_FABRIC_FREQUENCY_MHZ, _synchronize_build_frequency

    env = {"AGAMEMNON_HSE": "8", "AGAMEMNON_SYSCLK": "100"}
    assert _synchronize_build_frequency(env, 10) == 10
    assert env["AGAMEMNON_SYSCLK"] == "10"

    default_env = {}
    assert _synchronize_build_frequency(default_env, None) == DEFAULT_FABRIC_FREQUENCY_MHZ == 10
    assert default_env["AGAMEMNON_SYSCLK"] == "10"

    override_env = {"AGAMEMNON_SYSCLK": "25"}
    assert _synchronize_build_frequency(override_env, None) == 25

    with pytest.raises(ValueError, match="integer MHz"):
        _synchronize_build_frequency(env, 48.5)

    with pytest.raises(ValueError, match="unsupported PLL ratio"):
        _synchronize_build_frequency({"AGAMEMNON_HSE": "16"}, 25)


def test_cli_frequency_reaches_the_build_child_environment(monkeypatch, tmp_path):
    from agamemnon import cli

    seen = {}

    def stop_after_yosys(command, *, env, capture_output, text):
        seen.update(env)
        raise RuntimeError("captured synchronized clock")

    monkeypatch.setenv("AGAMEMNON_HSE", "8")
    monkeypatch.setenv("AGAMEMNON_SYSCLK", "100")
    monkeypatch.setattr(cli, "_run_child", stop_after_yosys)
    source = tmp_path / "top.v"
    source.write_text("module top(input clock); endmodule\n")
    args = SimpleNamespace(
        input=str(source), output=str(tmp_path / "top.bin"), uarch=True,
        hard_carry=False, qualified_checkpoint=None, leds=False, mcu=False,
        true_topo=False, no_intra_rmux=False, pin=None, baseline=None,
        pcf=None, freq=10,
    )

    with pytest.raises(RuntimeError, match="captured synchronized clock"):
        cli.cmd_build(args)

    assert seen["AGAMEMNON_SYSCLK"] == "10"


def test_timing_failure_is_not_accepted_as_route_success():
    from agamemnon.cli import _nonretryable_uarch_failure, _route_and_timing_succeeded

    routed = "Info: Routing complete.\nInfo: Max frequency 24.0 MHz (FAIL at 48.0 MHz)"
    assert _route_and_timing_succeeded(routed, 0)
    assert not _route_and_timing_succeeded(routed, 1)
    assert not _route_and_timing_succeeded("route failed", 0)
    no_paths = "Info: Routing complete.\nInfo: No Fmax available; no interior timing paths found in design."
    assert _route_and_timing_succeeded(no_paths, 0)
    assert not _route_and_timing_succeeded(no_paths, 0, require_fmax=True)
    assert _nonretryable_uarch_failure(
        "ERROR: agrv2k: dedicated carry requires 25 slices from slot 0"
    )
    assert _nonretryable_uarch_failure("agrv2k: malformed or branched carry graph")
    assert not _nonretryable_uarch_failure("ERROR: Failed to route arc 3.0")


def test_external_tool_environments_do_not_cross_contaminate(tmp_path):
    from agamemnon.cli import _build_tool_env

    oss = tmp_path / "oss"
    runtime = tmp_path / "runtime"
    original = tmp_path / "original"
    oss_bin = oss / "bin"
    oss_lib = oss / "lib"
    base = {"PATH": os.pathsep.join(
        [str(original), str(oss_bin), str(oss_lib), str(original)]
    )}

    yosys = _build_tool_env(base, oss=str(oss), use_oss=True)
    assert yosys["PATH"].split(os.pathsep)[:2] == [str(oss_bin), str(oss_lib)]

    nextpnr = _build_tool_env(base, oss=str(oss), runtime=str(runtime))
    parts = nextpnr["PATH"].split(os.pathsep)
    assert parts[0] == str(runtime)
    assert str(oss_bin) not in parts and str(oss_lib) not in parts
    assert parts.count(str(original)) == 2


@pytest.mark.parametrize("status, phrase", [
    (-1073741515, "required DLL"),       # 0xC0000135
    (-1073741511, "ABI-incompatible"),  # 0xC0000139
    (-1073741701, "wrong architecture"),# 0xC000007B
    (127, "not found"),
])
def test_nextpnr_loader_status_is_actionable(status, phrase):
    from agamemnon.cli import _loader_failure_hint

    assert phrase in _loader_failure_hint(status)


def test_nextpnr_preflight_runs_version_and_rejects_loader_failure(monkeypatch):
    from agamemnon import cli

    calls = []

    def fake_run(command, *, env, capture_output, text):
        calls.append((command, env))
        return SimpleNamespace(returncode=0, stdout="", stderr="nextpnr 1.0\n")

    monkeypatch.setattr(cli, "_run_child", fake_run)
    assert "nextpnr" in cli._preflight_nextpnr(["custom-nextpnr"], {"PATH": ""})
    assert calls[0][0][-1] == "--version"

    monkeypatch.setattr(
        cli, "_run_child",
        lambda *args, **kwargs: SimpleNamespace(returncode=-1073741511, stdout="", stderr=""),
    )
    with pytest.raises(RuntimeError, match="ABI-incompatible"):
        cli._preflight_nextpnr(["custom-nextpnr"], {"PATH": ""})


def test_uarch_devdb_preflight_and_abort_detection(tmp_path):
    from agamemnon.cli import _nextpnr_aborted, _validate_uarch_devdb

    for name in ("dev_meta.csv", "dev_wires.csv", "dev_belpins.csv", "dev_pips.csv"):
        (tmp_path / name).write_text("header\n")
    (tmp_path / "dev_bels.csv").write_text("name,type,x,y,z\n")
    with pytest.raises(RuntimeError, match="no CLKIN bel"):
        _validate_uarch_devdb(tmp_path)
    (tmp_path / "dev_bels.csv").write_text("name,type,x,y,z\nCLKIN,GENERIC_IOB,1,4,0\n")
    _validate_uarch_devdb(tmp_path)

    assert _nextpnr_aborted("terminate called after throwing an instance", 3)
    assert _nextpnr_aborted("", 0x40000015)
    assert not _nextpnr_aborted("ERROR: Failed to route arc", 1)


def test_uarch_attempts_honor_requested_cap_after_fanout_split():
    from agamemnon.cli import _uarch_attempts

    attempts = _uarch_attempts(5, 2)
    assert attempts[:5] == [(2, 0), (4, 0), (5, 0), (8, 0), (0, 0)]
    assert attempts[5:7] == [(5, 16), (8, 16)]
    assert attempts[-2:] == [(5, 2), (8, 2)]
    assert len(attempts) == len(set(attempts))


def test_uarch_attempts_can_prioritize_the_qualified_portb_shape():
    from agamemnon.cli import _uarch_attempts

    attempts = _uarch_attempts(5, 2, split_first=True)
    assert attempts[0] == (5, 16)
    assert len(attempts) == len(set(attempts))
    assert (2, 0) in attempts
    assert (8, 2) in attempts


def test_wsl_forwarding_includes_router2_stagnation_control():
    from agamemnon.cli import _forward_wsl_uarch_environment

    env = {"NEXTPNR_ROUTER2_STAGNATION_LIMIT": "100"}
    _forward_wsl_uarch_environment(env)
    assert env["WSLENV"] == "NEXTPNR_ROUTER2_STAGNATION_LIMIT"


def test_cli_compact_radius_is_explicit_uarch_only(monkeypatch, tmp_path):
    from agamemnon import cli

    with pytest.raises(SystemExit) as exc:
        cli.cmd_build(SimpleNamespace(
            freq=None, compact_maxd=4, hard_carry=False,
            no_hard_carry=False, uarch=False,
        ))
    assert exc.value.code == 2

    seen = {}
    monkeypatch.setenv("AGRV2K_COMPACT_MAXD", "99")
    monkeypatch.setattr(
        cli, "_run_child",
        lambda command, *, env, capture_output, text:
            (seen.update(env), (_ for _ in ()).throw(RuntimeError("captured")))[1],
    )
    source = tmp_path / "top.v"
    source.write_text("module top; endmodule\n")
    args = SimpleNamespace(
        input=str(source), output=str(tmp_path / "top.bin"), uarch=True,
        compact_maxd=4, hard_carry=False, no_hard_carry=False,
        qualified_checkpoint=None, leds=False, mcu=False, true_topo=False,
        no_intra_rmux=False, pin=None, baseline=None, pcf=None,
    )
    with pytest.raises(RuntimeError, match="captured"):
        cli.cmd_build(args)
    assert seen["AGRV2K_COMPACT_MAXD"] == "4"

    seen.clear()
    args.compact_maxd = None
    with pytest.raises(RuntimeError, match="captured"):
        cli.cmd_build(args)
    assert "AGRV2K_COMPACT_MAXD" not in seen


def test_regional_placer_applies_compact_radius_before_forced_tiles():
    source = (REPO / "agamemnon" / "engine" / "uarch" / "agrv2k" /
              "agrv2k.cc").read_text(encoding="utf-8")
    filter_at = source.index("REGIONAL compact radius")
    forced_at = source.index("std::set<int> forced;", filter_at)
    assert filter_at < forced_at
    assert "compact_maxd > 0 ? region : cand" in source


@pytest.mark.parametrize("uarch, hard_carry, no_hard_carry, expected", [
    (True, False, False, "1"), (True, True, False, "1"),
    (True, False, True, None), (False, False, False, None),
])
def test_cli_allocates_hw_carry_by_default_for_uarch(
        monkeypatch, tmp_path, uarch, hard_carry, no_hard_carry, expected):
    """The first build child is Yosys, so inspect its real subprocess environment."""
    from agamemnon import cli

    seen = {}

    def stop_after_yosys(command, *, env, capture_output, text):
        seen.update(env)
        raise RuntimeError("captured yosys environment")

    # Ambient state must not silently enable an unqualified primitive.
    monkeypatch.setenv("AGAMEMNON_HW_CARRY", "ambient")
    monkeypatch.setattr(cli, "_run_child", stop_after_yosys)
    source = tmp_path / "top.v"
    source.write_text("module top; endmodule\n")
    args = SimpleNamespace(
        input=str(source), output=str(tmp_path / "top.bin"), uarch=uarch,
        hard_carry=hard_carry, no_hard_carry=no_hard_carry,
        qualified_checkpoint=None, leds=False, mcu=False, true_topo=False,
        no_intra_rmux=False, pin=None, baseline=None, pcf=None,
    )

    with pytest.raises(RuntimeError, match="captured yosys environment"):
        cli.cmd_build(args)

    assert seen.get("AGAMEMNON_HW_CARRY") == expected


def test_devdb_fingerprint_tracks_generator_data_and_environment(tmp_path):
    from agamemnon.cli import _devdb_fingerprint

    arch = tmp_path / "arch.py"
    emitter = tmp_path / "emit.py"
    features = tmp_path / "features"
    features.mkdir()
    routing = features / "routing.py"
    data = tmp_path / "chipdb"
    data.mkdir()
    arch.write_text("arch-v1")
    emitter.write_text("emit-v1")
    routing.write_text("routing-v1")
    evidence = data / "evidence.csv"
    evidence.write_text("edge\nlive\n")
    first = _devdb_fingerprint(str(arch), str(emitter), str(data), ["STRICT=1"])
    routing.write_text("routing-v2")
    source_changed = _devdb_fingerprint(
        str(arch), str(emitter), str(data), ["STRICT=1"])
    evidence.write_text("edge\ndead\n")
    second = _devdb_fingerprint(str(arch), str(emitter), str(data), ["STRICT=1"])
    third = _devdb_fingerprint(str(arch), str(emitter), str(data), ["STRICT=0"])
    assert first != source_changed
    assert source_changed != second
    assert first != second
    assert second != third


def test_wsl_uarch_command_translates_only_artifact_paths(tmp_path):
    from agamemnon.cli import _forward_wsl_uarch_environment, _translate_wsl_nextpnr_args

    command = ["wsl", "/root/nextpnr", "--uarch", "agrv2k", "-o",
               r"chipdb=C:\repo\devdb", "--json", r"C:\tmp\design.json",
               "--write", r"C:\tmp\routed.json", "--router", "router2"]
    translated = _translate_wsl_nextpnr_args(command)
    assert "chipdb=/mnt/c/repo/devdb" in translated
    assert "/mnt/c/tmp/design.json" in translated
    assert "/mnt/c/tmp/routed.json" in translated
    assert translated[-2:] == ["--router", "router2"]

    env = {"WSLENV": "KEEP", "AGRV2K_CONDPLACE": "1", "AGRV2K_CONDPLACE_CAP": "8",
           "AGRV2K_REPLAY_BELS_IN_DB": "1", "AGAMEMNON_DATA": r"C:\chipdb"}
    _forward_wsl_uarch_environment(env)
    assert env["WSLENV"] == \
        "KEEP:AGRV2K_CONDPLACE:AGRV2K_CONDPLACE_CAP:AGRV2K_REPLAY_BELS_IN_DB:" \
        "AGAMEMNON_DATA/p"


def test_silicon_dead_edges_have_absolute_precedence():
    src = (ENGINE / "features" / "routing.py").read_text()
    assert 'os.path.join(DATA, "dead_edges_silicon.csv")' in src
    assert "CONDUCT.difference_update(" in src
    assert "if _blacklisted(r):" in src
    # The removal has to compare on the NORMALISED key.  EDGE_BLACKLIST is
    # normalised (RMUX9) while the conduction corpora spell the same wire
    # zero-padded (RMUX09), so the raw set intersection this assertion used to
    # pin silently kept every single-digit dead edge in the positive-evidence
    # set.  The data assertion below proves that spelling gap is real, so this
    # is not a vacuous requirement.
    assert "_conduct_by_norm" in src

    master = (REPO / "agamemnon" / "chipdb" / "master_conduction.csv").read_text()
    assert "RMUX07,14,11,RMUX46,14,12,ahb-write-silicon" in master
    assert "RMUX87,14,11,RMUX59,14,12,ahb-write-silicon" in master

    # The historical fourteen-edge ungating set is empty after direct positive
    # evidence.  A separate, twice-observed X14Y8 IMUX turnaround is retained
    # as a position-specific negative and must override vendor route occupancy.
    data = REPO / "agamemnon" / "chipdb"
    pat = re.compile(r"(\w+)@(-?\d+),(-?\d+)->(\w+)@(-?\d+),(-?\d+)")
    with (data / "dead_edges_silicon.csv").open(newline="") as f:
        dead = {pat.fullmatch(row["edge"]).groups() for row in csv.DictReader(f)}
    positive = set()
    for name in ("master_conduction.csv", "ff2_conduction.csv",
                 "harvest_conduction.csv", "corpus_conduction.csv"):
        with (data / name).open(newline="") as f:
            positive.update((row["src_res"], row["src_x"], row["src_y"],
                             row["dst_res"], row["dst_x"], row["dst_y"])
                            for row in csv.DictReader(f))
    assert dead == {("IMUX17", "14", "8", "RMUX69", "14", "8")}
    assert positive

    # The retained positive corpora still exercise zero-padded resource names
    # (RMUX09 versus normalized RMUX9), so the normalized-key implementation
    # remains load-bearing for any future blacklist row.
    padded = {edge for edge in positive
              if any(re.fullmatch(r"[A-Za-z]+0\d+", part) for part in (edge[0], edge[3]))}
    assert padded, ("no positive edge is zero-padded, so the normalised conflict "
                    "check can no longer be exercised by this data")


def test_qualified_checkpoint_helpers(tmp_path):
    checkpoint = tmp_path / "routed.json"
    _write_netlist(checkpoint, {
        "logic_LC": {"type": "GENERIC_SLICE", "attributes": {"NEXTPNR_BEL": "X2Y3_SLICE4"}},
    }, {
        "n": {"bits": [2], "attributes": {"ROUTING": "W0;PIP_GOOD;1;W1;;1"}},
    })
    placement = tmp_path / "placement.csv"
    r = subprocess.run([sys.executable, str(ENGINE / "placement_replay.py"), "--map",
                        str(checkpoint), str(placement)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert placement.read_text().strip() == "logic_LC,X2Y3_SLICE4"

    pips = tmp_path / "dev_pips.csv"
    pips.write_text("name,type,src,dst,delay_ns,x,y,z\n"
                    "PIP_GOOD,ROUTE,W0,W1,0.05,2,3,0\n"
                    "PIP_DEAD,ROUTE,W0,W2,0.05,2,3,0\n")
    filtered = tmp_path / "filtered.csv"
    r = subprocess.run([sys.executable, str(ENGINE / "qualify_route_db.py"), str(checkpoint),
                        str(pips), str(filtered), "--filter"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    text = filtered.read_text()
    assert "PIP_GOOD" in text and "PIP_DEAD" not in text
    assert "0.001" in text


def test_qualified_checkpoint_filter_fails_closed_on_missing_route_pip(tmp_path):
    checkpoint = tmp_path / "routed.json"
    _write_netlist(checkpoint, {}, {
        "n": {"bits": [2], "attributes": {"ROUTING": "W0;PIP_MISSING;1;W1;;1"}},
    })
    pips = tmp_path / "dev_pips.csv"
    pips.write_text("name,type,src,dst,delay_ns,x,y,z\n"
                    "PIP_GOOD,ROUTE,W0,W1,0.05,2,3,0\n")
    filtered = tmp_path / "filtered.csv"
    r = subprocess.run([sys.executable, str(ENGINE / "qualify_route_db.py"),
                        str(checkpoint), str(pips), str(filtered), "--filter"],
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "missing 1 PIP(s): PIP_MISSING" in r.stdout + r.stderr
    assert not filtered.exists()


def test_regional_placer_has_stable_bfs_order():
    src = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text()
    assert "ASLR heap addresses" in src
    assert 'a->name.str(ctx) < b->name.str(ctx)' in src
