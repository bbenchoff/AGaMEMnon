"""End-to-end BUILD regression: Verilog -> yosys synth -> nextpnr place&route -> open bitgen -> .bin,
via `python -m agamemnon.cli build`. This is the one path the rest of the suite doesn't cover (test_pack /
test_cli start from a pre-routed JSON). It guards the whole front-end wiring: synth scripts, arch.py load,
place_auto, and bitgen producing a valid image.

Requires yosys + nextpnr-generic on PATH or under $AGAMEMNON_OSS/bin (the open flow's external tools). When
they're absent (e.g. bare CI) the test SKIPS cleanly rather than failing -- run it locally / in a toolchain
image to exercise the front-end. No hardware.
"""
import os
import re
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A minimal self-contained sequential design (the proven toggle-FF -> MCU_DOUT shape; cf. tff_routed.json):
# one FF q<=~q read on hrdata0. Exercises synth + the FF/MCU-edge packing + place_auto + bitgen.
TFF_V = """\
module top (input clk);
  wire hrdata0;
  (* keep *) MCU_DOUT h0(.DOUT(hrdata0));
  reg t = 0;
  always @(posedge clk) t <= ~t;
  assign hrdata0 = t;
endmodule
"""


def _tool(name):
    """Locate an open-flow tool: $AGAMEMNON_OSS/bin first, then PATH. None if absent."""
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for ext in ("", ".exe"):
            p = os.path.join(oss, "bin", name + ext)
            if os.path.exists(p):
                return p
    return shutil.which(name)


def test_build_verilog_to_bin(tmp_path):
    yosys = _tool("yosys")
    npr = _tool("nextpnr-generic")
    if not yosys or not npr:
        pytest.skip("open-flow tools absent (need yosys + nextpnr-generic on PATH or $AGAMEMNON_OSS/bin)")

    vsrc = tmp_path / "tff.v"
    vsrc.write_text(TFF_V)
    outbin = tmp_path / "tff.bin"

    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "build", str(vsrc),
         "--research-unsafe", "-o", str(outbin)],
        cwd=str(tmp_path), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=600,
    )
    log = r.stdout or ""
    assert r.returncode == 0, "build failed (rc=%d):\n%s" % (r.returncode, log[-2000:])
    assert outbin.exists(), "no output .bin produced:\n%s" % log[-2000:]
    # a valid image is the fixed 99944-byte raw (8-byte header + 99936) or a smaller LZW-compressed one
    # that decodes to 99936. Just assert it's non-trivial and, if raw-sized, the right length.
    n = outbin.stat().st_size
    assert n > 0, "empty .bin"
    assert n == 99944 or n < 99944, "unexpected .bin size %d" % n


def test_build_physical_pcf_combination(tmp_path):
    """The silicon-proven arbitrary RTL/physical-I/O path must stay routable and fully encodable."""
    if not _tool("yosys") or not _tool("nextpnr-generic"):
        pytest.skip("open-flow tools absent (need yosys + nextpnr-generic)")
    outbin = tmp_path / "comb.bin"
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "build",
         os.path.join(REPO_ROOT, "examples", "designs", "comb.v"),
         "--pcf", os.path.join(REPO_ROOT, "examples", "constraints", "comb_proven_L48.pcf"),
         "--research-unsafe",
         "-o", str(outbin)],
        cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=600,
    )
    assert r.returncode == 0, r.stdout[-3000:]
    assert outbin.stat().st_size == 99944
    assert "0 unmapped" in r.stdout


def test_build_physical_pcf_multilut_chain(tmp_path):
    """Three dependent LUTs must cluster, route both LUT-to-LUT legs, and remain fully encodable."""
    if not _tool("yosys") or not _tool("nextpnr-generic"):
        pytest.skip("open-flow tools absent (need yosys + nextpnr-generic)")
    outbin = tmp_path / "multilut.bin"
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    r = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "build",
         os.path.join(REPO_ROOT, "examples", "designs", "multilut.v"),
         "--pcf", os.path.join(REPO_ROOT, "examples", "constraints", "multilut_proven_L48.pcf"),
         "--research-unsafe",
         "-o", str(outbin)],
        cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=600,
    )
    assert r.returncode == 0, r.stdout[-3000:]
    assert outbin.stat().st_size == 99944
    mapped = re.search(r"data pips: (\d+) total, (\d+) mapped", r.stdout)
    assert mapped and int(mapped.group(1)) == int(mapped.group(2))
    assert int(mapped.group(1)) >= 2
    assert "0 unmapped" in r.stdout
