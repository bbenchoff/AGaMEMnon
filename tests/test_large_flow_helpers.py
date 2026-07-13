import json
import csv
import re
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "agamemnon" / "engine"


def _write_netlist(path, cells, netnames=None):
    path.write_text(json.dumps({"modules": {"top": {
        "cells": cells, "netnames": netnames or {}, "ports": {}, "attributes": {}
    }}}))


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
    r = subprocess.run([sys.executable, str(ENGINE / "pcf_bind_json.py"), str(netlist), str(pcf),
                        str(REPO / "agamemnon" / "chipdb")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(netlist.read_text())["modules"]["top"]["cells"]
    assert out["$iopadmap$top.reset"]["attributes"]["NEXTPNR_BEL"] == "X20Y13_IPAD1"
    assert out["$iopadmap$top.q"]["attributes"]["NEXTPNR_BEL"] == "X19Y13_OPAD0"


def test_cli_large_uarch_defaults_are_strict_router2():
    src = (REPO / "agamemnon" / "cli.py").read_text()
    assert 'default_devdb = "devdb_strict_pcf"' in src
    assert '"AGAMEMNON_STRICT_GATE=1"' in src
    assert '"AGAMEMNON_XBAR_CONDUCT=1"' in src
    assert '["--uarch", "agrv2k"' in src
    assert '"--router", "router2"' in src
    assert '"--qualified-checkpoint"' in src
    assert '"--write-routed"' in src
    assert '"--freq"' in src


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


def test_timing_failure_is_not_accepted_as_route_success():
    from agamemnon.cli import _route_and_timing_succeeded

    routed = "Info: Routing complete.\nInfo: Max frequency 24.0 MHz (FAIL at 48.0 MHz)"
    assert _route_and_timing_succeeded(routed, 0)
    assert not _route_and_timing_succeeded(routed, 1)
    assert not _route_and_timing_succeeded("route failed", 0)
    no_paths = "Info: Routing complete.\nInfo: No Fmax available; no interior timing paths found in design."
    assert _route_and_timing_succeeded(no_paths, 0)
    assert not _route_and_timing_succeeded(no_paths, 0, require_fmax=True)


@pytest.mark.parametrize("uarch, expected", [(True, "1"), (False, None)])
def test_cli_sets_hw_carry_for_yosys_only_in_uarch_flow(monkeypatch, tmp_path, uarch, expected):
    """The first build child is Yosys, so inspect its real subprocess environment."""
    from agamemnon import cli

    seen = {}

    def stop_after_yosys(command, *, env, capture_output, text):
        seen.update(env)
        raise RuntimeError("captured yosys environment")

    monkeypatch.delenv("AGAMEMNON_HW_CARRY", raising=False)
    monkeypatch.setattr(cli.subprocess, "run", stop_after_yosys)
    source = tmp_path / "top.v"
    source.write_text("module top; endmodule\n")
    args = SimpleNamespace(
        input=str(source), output=str(tmp_path / "top.bin"), uarch=uarch,
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

    env = {"WSLENV": "KEEP", "AGRV2K_CONDPLACE": "1",
           "AGRV2K_REPLAY_BELS_IN_DB": "1", "AGAMEMNON_DATA": r"C:\chipdb"}
    _forward_wsl_uarch_environment(env)
    assert env["WSLENV"] == "KEEP:AGRV2K_CONDPLACE:AGRV2K_REPLAY_BELS_IN_DB"


def test_silicon_dead_edges_have_absolute_precedence():
    src = (ENGINE / "arch.py").read_text()
    assert 'os.path.join(DATA, "dead_edges_silicon.csv")' in src
    assert "CONDUCT.difference_update(EDGE_BLACKLIST)" in src
    assert "if _blacklisted(r):" in src

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
