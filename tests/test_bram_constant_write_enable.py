"""Keystone silent-degradation regression: a constant-tied BRAM write-enable.

Confirmed real (2026-08-15): an ordinary single-port inferred BRAM write
(``mem[addr] <= din;`` every cycle, i.e. ``WeA`` tied to the constant 1) used
to be silently swallowed by ``pack_bram_localize_const`` in
``agrv2k.cc``. Under ``AGRV2K_BRAM_HARDCONST`` (always on for ``--uarch``
builds), any constant-tied BRAM control pin -- including ``WeA``/``WeB`` --
was disconnected on the assumption that the generic control blob
(``bram_rom_ctrl.csv`` vs ``bram_dual_ctrl.csv``, selected in
``features/bram.py`` from ``portb_read`` + WeA-connectivity) supplies the
right default. That default is write-DISABLED (the "ROM" blob) for any
design that is not also live-reading Port B, so an unconditional write
(``WeA`` tied HIGH) silently degraded to a read-only ROM image with no error
-- exactly the class of bug this suite exists to catch.

The fix in ``agrv2k.cc`` (``pack_bram_localize_const``) refuses instead of
guessing: a constant-1 ``WeA``/``WeB`` now aborts packing with a named,
actionable diagnostic instead of either silently dropping the pin or (as
observed for some netlist shapes pre-fix) crashing nextpnr with an
unrelated-looking ``std::out_of_range``.

These tests require the ``agrv2k`` uarch build of nextpnr-generic
(``$AGAMEMNON_UARCH_NEXTPNR``, built via
``agamemnon/engine/uarch/agrv2k/build.sh``) plus yosys. They skip cleanly
when that toolchain is not available -- see ``test_build_e2e.py`` for the
same convention.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGRV2K_CC = os.path.join(
    ROOT, "agamemnon", "engine", "uarch", "agrv2k", "agrv2k.cc"
)

# An unconditional single-port BRAM write: WeA is tied to the constant 1 by
# yosys's memory_libmap/ag32_brams_map lowering (no dynamic write-enable, no
# Port-B read). This is the exact shape the keystone bug silently mishandled.
WRITE_BRAM_V = """\
module top(input clk, input [8:0] addr, input din, output reg dout);
  (* ram_style = "block" *) reg mem [0:511];
  always @(posedge clk) begin
    mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
"""

# A genuine read-only ROM: WeA is absent/tied to 0. The fix must not fire for
# this shape (it is the one case the "ROM" control blob is actually correct
# for).
ROM_V = """\
module top(input clk, input [1:0] addr, output reg dout);
  (* ram_style = "block" *) reg mem [0:3];
  initial mem[0] = 0;
  always @(posedge clk) begin
    dout <= mem[addr];
  end
endmodule
"""


def _tool(name):
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for ext in ("", ".exe"):
            candidate = os.path.join(oss, "bin", name + ext)
            if os.path.exists(candidate):
                return candidate
    return shutil.which(name)


def _uarch_nextpnr():
    """Resolve a nextpnr-generic build that actually registers the agrv2k
    uarch (a stock nextpnr-generic does not); None if unavailable."""
    candidate = os.environ.get("AGAMEMNON_UARCH_NEXTPNR") or _tool("nextpnr-generic")
    if not candidate:
        return None
    exe = shutil.which(candidate) or (candidate if os.path.exists(candidate) else None)
    if not exe:
        return None
    try:
        result = subprocess.run(
            [exe, "--uarch", "?"], capture_output=True, text=True, timeout=30,
        )
    except OSError:
        return None
    if "agrv2k" not in (result.stdout + result.stderr):
        return None
    return exe


def _build(tmp_path, source_text, name):
    yosys = _tool("yosys")
    npr = _uarch_nextpnr()
    if not yosys or not npr:
        pytest.skip("agrv2k uarch nextpnr-generic + yosys not available "
                     "(build via agamemnon/engine/uarch/agrv2k/build.sh, "
                     "point $AGAMEMNON_UARCH_NEXTPNR at it)")
    source = tmp_path / name
    source.write_text(source_text, encoding="utf-8")
    output = tmp_path / (name + ".bin")
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["AGAMEMNON_UARCH_NEXTPNR"] = npr
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "build", str(source),
         "--uarch", "-o", str(output)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=600,
    )
    return result


def test_pack_bram_localize_const_refuses_a_constant_high_write_enable():
    """Desk check: the refusal is source-present even when tools are absent."""
    text = open(AGRV2K_CC, encoding="utf-8").read()
    assert "is_write_enable" in text
    assert "hardconst && is_write_enable && pr.second" in text
    # (the runtime message itself spans a source line break via adjacent
    # string-literal concatenation, so check pieces that don't straddle it)
    assert "an unconditional " in text
    assert "ROM control blob" in text
    # The guard must run BEFORE the blanket disconnect it is protecting
    # against, in the same function.
    localize = text.index("pack_bram_localize_const")
    guard = text.index("hardconst && is_write_enable && pr.second", localize)
    disconnect = text.index(
        "hardconst && !routed_address_low &&\n"
        "                    (!pr.second || characterized_control || default_high_suffix)",
        localize,
    )
    assert localize < guard < disconnect


def test_inferred_write_bram_with_constant_high_we_fails_loud_not_silent(tmp_path):
    """The keystone regression: this used to build 'successfully' with WeA
    silently dropped (ROM control blob), or crash with an opaque
    std::out_of_range. It must now fail with a named, actionable error."""
    result = _build(tmp_path, WRITE_BRAM_V, "write_bram.v")
    log = result.stdout or ""
    assert result.returncode != 0, (
        "an unconditional constant-write-enable BRAM build must not "
        "silently succeed:\n%s" % log[-3000:]
    )
    assert "unconditional write-enable" in log, (
        "expected the named agrv2k refusal, not a different failure:\n%s"
        % log[-3000:]
    )
    assert "ROM control blob" in log
    # The old failure mode for this exact shape was an unstructured abort;
    # the fix must turn it into a controlled nextpnr ERROR/log_error exit.
    assert "std::out_of_range" not in log
    assert "terminate called" not in log


def test_genuine_readonly_bram_does_not_trip_the_write_enable_guard(tmp_path):
    """Negative control: a real ROM (WeA absent/0) must never see this
    refusal, whatever else it does or does not succeed at."""
    result = _build(tmp_path, ROM_V, "rom.v")
    log = result.stdout or ""
    assert "unconditional write-enable" not in log, (
        "the constant-high-WeA guard must not fire for a read-only BRAM:\n%s"
        % log[-3000:]
    )
