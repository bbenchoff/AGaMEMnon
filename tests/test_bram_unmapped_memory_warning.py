"""Sibling silent-degradation regression: a memory that ``memory_libmap``
declines to place on the ALTA_BRAM9K block RAM used to fall through to
``memory_map`` (one flip-flop per bit + an address-decode LUT tree) with
*zero* visible signal under the default ``-q`` build -- ``memory_libmap``
prints nothing when it never attempts a mapping, and ``-q`` suppresses the
informational ``stat`` counts that would otherwise show it.

Confirmed real (2026-08): a plain 512-deep, 1-bit memory with an
asynchronous/combinational read (a common, legitimate RTL style the block-RAM
library's clocked-only "srsw" ports cannot express) silently expanded into
512 DFFs + ~1000 LUT4s -- roughly a quarter of this device's entire flip-flop
budget and half its LUT budget -- with yosys exiting 0 and no diagnostic
anywhere in the normal build log.

The fix (``agamemnon/synth/synth_pads.tcl``) inspects the design for leftover
``$mem``/``$mem_v2`` cells right before ``memory_map`` would lower them, and
prints an always-visible ``AGAMEMNON WARNING`` (raw ``puts stderr``, so it
survives ``-q``) naming the cell. This is a warning, not a hard failure --
the existing script's own comment already documents that small/odd memories
falling through to FFs is an accepted, size-based outcome, and yosys itself
already hard-errors when an explicit ``(* ram_style = "block" *)`` truly
cannot be satisfied (verified below). Silence is the bug being fixed, not the
fallback itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNTH_TCL = os.path.join(ROOT, "agamemnon", "synth", "synth_pads.tcl")

# A plain 512x1 memory with an asynchronous (combinational) read: the
# block-RAM library only offers clocked "srsw" ports, so memory_libmap can
# never place this one -- it silently expands to 512 DFFs + ~1000 LUT4s.
ASYNC_READ_MEM_V = """\
module top(input clk, input [8:0] addr, input din, output dout);
  reg mem [0:511];
  always @(posedge clk) begin
    mem[addr] <= din;
  end
  assign dout = mem[addr];
endmodule
"""

# The same shape, but forcing block-RAM placement. yosys's own memory_libmap
# already refuses this loudly (an existing behavior this suite must not
# weaken) -- used as a negative control on the *desk* assumption above.
ASYNC_READ_MEM_FORCED_V = ASYNC_READ_MEM_V.replace(
    "  reg mem [0:511];", '  (* ram_style = "block" *) reg mem [0:511];'
)

# An ordinary synchronous-read/write memory: must map cleanly and never warn.
CLOCKED_WRITE_MEM_V = """\
module top(input clk, input [8:0] addr, input din, output reg dout);
  (* ram_style = "block" *) reg mem [0:511];
  always @(posedge clk) begin
    mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
"""


def _yosys():
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for ext in ("", ".exe"):
            candidate = os.path.join(oss, "bin", "yosys" + ext)
            if os.path.exists(candidate):
                return candidate
    return shutil.which("yosys")


def _synth(tmp_path, source_text, name):
    yosys = _yosys()
    if not yosys:
        pytest.skip("yosys absent (set AGAMEMNON_OSS or put yosys on PATH)")
    source = tmp_path / name
    source.write_text(source_text, encoding="utf-8")
    output = tmp_path / (name + ".json")
    env = dict(os.environ)
    oss = env.get("AGAMEMNON_OSS")
    if oss:
        env["YOSYSHQ_ROOT"] = oss + os.sep
        env["PATH"] = (os.path.join(oss, "bin") + os.pathsep +
                        os.path.join(oss, "lib") + os.pathsep + env.get("PATH", ""))
    env["AGAMEMNON_YOSYS_TOP"] = "top"
    env["AGAMEMNON_YOSYS_JSON"] = str(output)
    result = subprocess.run(
        [yosys, "-q", "-c", SYNTH_TCL, str(source)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=120,
    )
    return result


def test_synth_pads_source_contains_the_leftover_memory_guard():
    """Desk check: the guard is source-present even when yosys is absent."""
    text = open(SYNTH_TCL, encoding="utf-8").read()
    assert 't:\\$mem t:\\$mem_v2' in text
    assert "AGAMEMNON WARNING" in text
    assert "puts stderr" in text
    # It must run between the BRAM techmap and memory_map, or the cells it is
    # meant to catch are already gone.
    bram_techmap = text.index("ag32_brams_map.v")
    guard = text.index("AGAMEMNON WARNING")
    memory_map = text.index("yosys memory_map")
    assert bram_techmap < guard < memory_map


def test_async_read_memory_silently_expanding_to_ffs_now_warns(tmp_path):
    """The keystone-sibling regression: this used to build with rc=0 and no
    signal at all that ~1500 cells of LUT/FF replaced one BRAM."""
    result = _synth(tmp_path, ASYNC_READ_MEM_V, "async_read.v")
    assert result.returncode == 0, (
        "the fallback itself must still succeed (it is not the bug):\n%s"
        % result.stdout[-3000:]
    )
    assert "AGAMEMNON WARNING" in result.stdout, (
        "an unmapped memory falling through to memory_map must never be "
        "silent:\n%s" % result.stdout[-3000:]
    )
    assert "did NOT map to the ALTA_BRAM9K" in result.stdout


def test_forced_block_ram_still_hard_errors_on_an_unfittable_shape(tmp_path):
    """Negative control on the desk assumption the fix relies on: yosys's
    own memory_libmap must still refuse loudly when ram_style=block truly
    cannot be satisfied, so our warning-not-error choice does not paper over
    an existing hard failure."""
    result = _synth(tmp_path, ASYNC_READ_MEM_FORCED_V, "async_read_forced.v")
    assert result.returncode != 0
    assert "no valid mapping found" in result.stdout


def test_ordinary_write_bram_does_not_trip_the_leftover_memory_warning(tmp_path):
    """Negative control: a real BRAM-mapped write must never warn."""
    result = _synth(tmp_path, CLOCKED_WRITE_MEM_V, "clocked_write.v")
    assert result.returncode == 0, result.stdout[-3000:]
    assert "AGAMEMNON WARNING" not in result.stdout
