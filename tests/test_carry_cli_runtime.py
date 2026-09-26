"""The default CLI must deliver the carry site table to the native placer."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


def test_fresh_cli_cache_loads_qualified_carry_sites(tmp_path):
    binary = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if not binary or not Path(binary).is_file() or not shutil.which("yosys"):
        pytest.skip("requires the built native architecture and yosys")
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "counter.v"
    source.write_text("""module top(input clock, input reset, output led);
reg [12:0] count;
always @(posedge clock) count <= reset ? 13'd0 : count + 13'd1;
assign led = count[12];
endmodule
""")
    pcf = tmp_path / "pins.pcf"
    pcf.write_text("set_io led PIN_17\nset_io reset PIN_15\n")
    devdb = tmp_path / "cold-devdb"
    routed = tmp_path / "routed.json"
    output = tmp_path / "counter.bin"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGAMEMNON_", "AGRV2K_"))}
    env.update(PYTHONPATH=str(root), AGAMEMNON_UARCH_NEXTPNR=binary, AGAMEMNON_DEVDB=str(devdb))
    if "AGAMEMNON_OSS" in os.environ:
        env["AGAMEMNON_OSS"] = os.environ["AGAMEMNON_OSS"]
    result = subprocess.run([sys.executable, "-m", "agamemnon.cli", "build", str(source),
                             "--uarch", "--pcf", str(pcf), "--freq", "10", "--seed", "1",
                             "--write-routed", str(routed), "-o", str(output)],
                            cwd=root, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, (result.stdout + result.stderr)[-10000:]
    assert output.stat().st_size == 99944
    # Follow actual routed metadata, including the automatic enable fallback's
    # separate cache, instead of assuming which cache the CLI will select.
    tables = list(tmp_path.glob("cold-devdb*/carry_qualified_sites.csv"))
    assert tables, "the placer received no qualified carry-site table"
    expected = (root / "agamemnon/chipdb/carry_qualified_sites.csv").read_bytes()
    assert all(table.read_bytes() == expected for table in tables)
    # Load the cache through the actual native reader. The CLI filters its
    # successful nextpnr logs, so stdout from the CLI is not this evidence.
    probe = subprocess.run([binary, "--uarch", "agrv2k", "-o", "chipdb=" + str(tables[-1].parent),
                            "--json", str(routed), "--no-place", "--no-route"],
                           cwd=root, env=env, capture_output=True, text=True, timeout=60)
    native_log = probe.stdout + probe.stderr
    assert re.search(r"loaded 117 silicon-witnessed wide-native-carry site", native_log), native_log[-6000:]
    document = json.loads(routed.read_text())
    assert any(cell["type"] == "GENERIC_SLICE" for module in document["modules"].values()
               for cell in module.get("cells", {}).values())
