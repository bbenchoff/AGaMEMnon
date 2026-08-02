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
    assert '["--uarch", "agrv2k"' in src
    assert '"--router", "router2"' in src
    assert '"--qualified-checkpoint"' in src
    assert '"--write-routed"' in src
    assert '"--freq"' in src
    assert 'env.setdefault("AGRV2K_CONDPLACE_SEED", "4")' in src
    assert 'route_seeds = [env["AGRV2K_CONDPLACE_SEED"]] if seed_locked else ["4", "2", "7"]' in src
    assert 'b.add_argument("--cap", type=int, default=5' in src
    assert "attempts = _uarch_attempts(a.cap, a.maxfo, split_first=live_portb)" in src
    cap_assignment = 'env["AGRV2K_CONDPLACE_CAP"] = str(cap)'
    assert cap_assignment in src
    # WSLENV must be refreshed after the per-attempt cap exists. Otherwise the
    # Windows log advertises a 2/4/8 sweep while Linux silently runs cap=1.
    assert src.index("_forward_wsl_uarch_environment(env)", src.index(cap_assignment)) \
        > src.index(cap_assignment)
    assert '["nextpnr-generic", "--pre-pack", os.path.join(engine, "arch.py"),\n               "--router", "router2"]' in src

    bitgen = (ENGINE / "bitgen_seq.py").read_text(encoding="utf-8")
    assert "refusing to emit a partial bitstream" in bitgen
    assert 'OPTIONS.enabled("AGAMEMNON_ALLOW_UNMAPPED")' in bitgen
    # Silicon-qualified AHB readback: route BBMUXE02 programs physical
    # CFG_BBMUXE2, not the neighboring field.  An off-by-one here made a
    # correctly running carry counter appear to have a frozen high bit.
    assert "mux_i = di" in bitgen
    assert "mux_i = di - 1" not in bitgen

    uarch = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text(encoding="utf-8")
    assert 'parse_after(name, "hwdata")' in uarch
    assert 'near = tkey(14, hwbit <= 17 ? 10 : 9)' in uarch
    assert "lock_registered_mcu_inputs()" in uarch
    assert 'name.find("hwrite")' in uarch
    assert 'name.find("htrans1")' in uarch
    assert 'bn = "X10Y5_MCU_DIN" + std::to_string(lane)' in uarch
    assert "qualified vendor-observed corridor supports one chain through 33 stages" in uarch


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
    assert attempts[:4] == [(2, 0), (4, 0), (5, 0), (8, 0)]
    assert attempts[4:6] == [(5, 16), (8, 16)]
    assert attempts[-2:] == [(5, 2), (8, 2)]
    assert len(attempts) == len(set(attempts))


def test_uarch_attempts_can_prioritize_the_qualified_portb_shape():
    from agamemnon.cli import _uarch_attempts

    attempts = _uarch_attempts(5, 2, split_first=True)
    assert attempts[0] == (5, 16)
    assert len(attempts) == len(set(attempts))
    assert (2, 0) in attempts
    assert (8, 2) in attempts


@pytest.mark.parametrize("uarch, hard_carry, expected", [
    (True, False, None), (True, True, "1"), (False, False, None),
])
def test_cli_sets_hw_carry_only_when_explicit(monkeypatch, tmp_path, uarch, hard_carry, expected):
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
        hard_carry=hard_carry,
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
    data = tmp_path / "chipdb"
    data.mkdir()
    arch.write_text("arch-v1")
    emitter.write_text("emit-v1")
    evidence = data / "evidence.csv"
    evidence.write_text("edge\nlive\n")
    first = _devdb_fingerprint(str(arch), str(emitter), str(data), ["STRICT=1"])
    evidence.write_text("edge\ndead\n")
    second = _devdb_fingerprint(str(arch), str(emitter), str(data), ["STRICT=1"])
    third = _devdb_fingerprint(str(arch), str(emitter), str(data), ["STRICT=0"])
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
        "KEEP:AGRV2K_CONDPLACE:AGRV2K_CONDPLACE_CAP:AGRV2K_REPLAY_BELS_IN_DB"


def test_silicon_dead_edges_have_absolute_precedence():
    src = (ENGINE / "arch.py").read_text()
    assert 'os.path.join(DATA, "dead_edges_silicon.csv")' in src
    assert "CONDUCT.difference_update(EDGE_BLACKLIST)" in src
    assert "if _blacklisted(r):" in src

    master = (REPO / "agamemnon" / "chipdb" / "master_conduction.csv").read_text()
    assert "RMUX07,14,11,RMUX46,14,12,ahb-write-silicon" in master
    assert "RMUX87,14,11,RMUX59,14,12,ahb-write-silicon" in master

    # The checked-in negative set is currently contradicted by legacy positive
    # campaigns.  This is intentional regression coverage: arch.py must resolve
    # those conflicts in favor of the silicon-negative evidence.
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
    assert dead
    assert dead <= positive


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


def test_regional_placer_has_stable_bfs_order():
    src = (ENGINE / "uarch" / "agrv2k" / "agrv2k.cc").read_text()
    assert "ASLR heap addresses" in src
    assert 'a->name.str(ctx) < b->name.str(ctx)' in src
