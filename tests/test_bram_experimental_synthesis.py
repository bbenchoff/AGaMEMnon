"""The experimental source interface retains modes instead of lowering RAM."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_modes_require_opt_in_and_survive_full_synthesis(tmp_path):
    yosys = shutil.which("yosys")
    launcher = []
    if not yosys:
        wsl = shutil.which("wsl")
        if not wsl:
            pytest.skip("Yosys unavailable")
        probe = subprocess.run([wsl, "--exec", "yosys", "-V"], capture_output=True)
        if probe.returncode:
            pytest.skip("WSL Yosys unavailable")
        launcher = [wsl, "--exec"]
        yosys = "yosys"

    def path(value):
        value = str(value).replace("\\", "/")
        if launcher and ":/" in value:
            drive, rest = value.split(":/", 1)
            return "/mnt/" + drive.lower() + "/" + rest
        return value

    source = tmp_path / "top.v"
    source.write_text('''module top(input clk, we, input [12:0] addr,
        input [17:0] din, output [17:0] dout);
      ALTA_BRAM9K #(.INIT_VAL(9216'h12345), .CLKMODE(1),
        .PORTA_OUTREG(1), .PORTA_WRITETHRU(1), .PORTB_WRITETHRU(1),
        .PORTA_CLKIN_EN(1), .PORTA_CLKOUT_EN(1),
        .PORTB_CLKIN_EN(1), .PORTB_CLKOUT_EN(1)) memory(
        .AddressA(addr), .DataInA(din), .DataOutA(dout), .WeA(we), .ReA(1'b1),
        .ByteEnA(2'b11), .Clk0(clk), .ClkEn0(1'b1), .AsyncReset0(1'b0),
        .AddressB(13'b0), .DataInB(18'b0), .WeB(1'b0), .ReB(1'b0),
        .ByteEnB(2'b11), .Clk1(clk), .ClkEn1(1'b1), .AsyncReset1(1'b0),
        .AddressStallA(1'b0), .AddressStallB(1'b0));
    endmodule
    ''')
    for enabled in (False, True):
        output = tmp_path / ("enabled.json" if enabled else "default.json")
        settings = {"AGAMEMNON_BRAM_EXPERIMENTAL_CONFIG": "1" if enabled else "",
                    "AGAMEMNON_YOSYS_TOP": "top", "AGAMEMNON_YOSYS_JSON": path(output)}
        command = [yosys, "-q", "-c", path(ROOT / "agamemnon/synth/synth_pads.tcl"), path(source)]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AGAMEMNON_", "AGRV2K_"))}
        env.update(settings)
        if launcher:
            command = launcher + ["env"] + [f"{k}={v}" for k, v in settings.items()] + command
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        if not enabled:
            assert result.returncode != 0
            assert "does not have a port named" in result.stderr
            assert not output.exists()
            continue
        assert result.returncode == 0, result.stdout + result.stderr
        cells = json.loads(output.read_text())["modules"]["top"]["cells"]
        blocks = [c for c in cells.values() if c["type"] == "ALTA_BRAM9K"]
        assert len(blocks) == 1
        block = blocks[0]
        for field in ("PORTA_OUTREG", "PORTA_WRITETHRU", "PORTB_WRITETHRU"):
            assert int(block["parameters"][field], 2) == 1
        assert int(block["parameters"]["INIT_VAL"], 2) == 0x12345
        for port in ("AddressStallA", "AddressStallB", "AsyncReset1"):
            assert block["connections"][port] == ["0"]
