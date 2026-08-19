"""Pinned reproducer for the ``core_logic`` vs ``route_through`` BitOwnershipError
(AG32-Docs docs/TASK_QUEUE.md queue E, "B2"; scale_report.json failure_modes:
``BitOwnershipError, byte 65852 mask 0x08, core_logic and route_through``, 22
instances across the ``lfsr``, ``bram_rom`` and ``congestion_wide`` fuzz-factory
families as of the 2026-08-19 801-design campaign).

Root cause (established by rebuilding two of the preserved failing designs
fresh and inspecting their routed netlists -- see the investigation write-up
for the full chain of evidence):

  * Byte 65852 mask 0x08 is ``physmap.init_bit_pos(14, 4, 0, 1)`` -- LUT-init
    bit 1 of the physical logic slice at X14Y4_SLICE0, one of exactly four
    sites characterized in ``agamemnon/chipdb/route_through_footprints.csv``
    (the others are X14Y4_SLICE5, X14Y7_SLICE3, X14Y8_SLICE8).
  * ``agamemnon/engine/qin_pack.py``'s ``externalize_multi_selffb`` inserts a
    synthetic combinational identity-buffer LUT cell
    (``$agamemnon$feedback_buffer$N_LC``, attribute
    ``agamemnon_external_selffb_buffer=1``, INIT 0xFF00 or 0xAAAA) whenever a
    module has more than one own-Q self-feedback register -- an extremely
    common RTL shape (any counter, LFSR, shift register, or hold-register).
    These buffers carry no ``AGRV2K_ROUTE_THROUGH`` attribute and are meant
    to be placed anywhere ordinary ("device-wide", per that module's own
    docstring, not restricted to any 4-site pool).
  * ``agamemnon/engine/features/route_through.py``'s
    ``complete_footprint_for_cell()`` admits a cell into the characterized
    "complete footprint" write set whenever its INIT and an input net's
    routed edge match one of the four table entries -- with NO requirement
    that ``AGRV2K_ROUTE_THROUGH`` be set (see
    ``tests/test_route_through_footprints.py::
    test_exact_identity_and_final_edge_select_complete_footprint_automatically``,
    which pins this as *intentional*).
  * ``agamemnon/engine/features/core_logic.py``'s ``prepare()`` only excludes
    a placed slice from its own LUT-init claim when the cell carries the
    explicit ``AGRV2K_ROUTE_THROUGH`` attribute. It has no way to learn that
    ``route_through`` will *also* implicitly claim an unattributed cell's
    bits, so both features legitimately claim byte 65852 bit 3, and
    ``bit_ownership.py`` (correctly) refuses the build.

Confirmed on real placement/routing (not asserted from source alone): two
independently preserved fuzz-factory failures (``lfsr_s102``, ``bram_rom_s289``)
were rebuilt from scratch and each placed a fresh, distinctly-named
``$agamemnon$feedback_buffer$N_LC`` cell at X14Y4_SLICE0 with INIT 0xFF00 and
no ``AGRV2K_ROUTE_THROUGH`` attribute, whose routed input net's ``ROUTING``
attribute genuinely contains ``X14Y4_RMUX71.X14Y4_IMUX03`` (the site's real,
electrically-live final edge -- not a coincidental substring hit).

This module's design below is a hand-reduced version of the preserved
``lfsr_s102`` reproducer (AG32-Docs
``tools/fuzz_factory/failures/lfsr_s102__20260819T080906Z/top.v``): a 36-bit
LFSR plus a freeze-and-capture register bank feeding eight ``MCU_DOUT``
sinks. Deliberate size/shape reduction was attempted and did NOT reproduce
the collision at 8/16/24/32-bit width variants, nor with the freeze/capture
logic alone (no LFSR) at width 8 -- the failure depends on nextpnr's
deterministic placement choice for this exact netlist shape, not merely on
"has more than one self-feedback register." The full-size design is kept
here because it is the smallest *known-reproducing* instance, not because it
is believed to be irreducible.

xfail, not skip: this is a currently open defect, not an environment gap.
An unexpected XPASS is the signal to review this pin (and the root-cause
writeup) because the predicate mismatch between ``core_logic`` and
``route_through`` has been closed.
"""
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Verbatim (modulo trailing newline) copy of the preserved fuzz-factory
# reproducer. Kept self-contained in this repo rather than reaching across
# to the sibling AG32-Docs workbench checkout.
LFSR_FREEZE_V = """\
module top (input clk);
  reg [35:0] state = 36'h0;
  wire fb = ~(state[35] ^ state[33] ^ state[3]);
  always @(posedge clk) state <= {state[34:0], fb};
  wire [7:0] live_taps;
  assign live_taps[0] = state[0];
  assign live_taps[1] = state[5];
  assign live_taps[2] = state[10];
  assign live_taps[3] = state[15];
  assign live_taps[4] = state[20];
  assign live_taps[5] = state[25];
  assign live_taps[6] = state[30];
  assign live_taps[7] = state[35];
  reg [6:0] freeze_ctr = 7'h0;
  reg frozen = 1'b0;
  reg [7:0] frozen_taps = 8'h0;
  always @(posedge clk) begin
    if (!frozen) begin
      if (freeze_ctr == 7'd64) begin
        frozen_taps <= live_taps;
        frozen <= 1'b1;
      end else begin
        freeze_ctr <= freeze_ctr + 1'b1;
      end
    end
  end
  (* keep *) MCU_DOUT mcu_h0(.DOUT(frozen_taps[0]));
  (* keep *) MCU_DOUT mcu_h1(.DOUT(frozen_taps[1]));
  (* keep *) MCU_DOUT mcu_h2(.DOUT(frozen_taps[2]));
  (* keep *) MCU_DOUT mcu_h3(.DOUT(frozen_taps[3]));
  (* keep *) MCU_DOUT mcu_h4(.DOUT(frozen_taps[4]));
  (* keep *) MCU_DOUT mcu_h5(.DOUT(frozen_taps[5]));
  (* keep *) MCU_DOUT mcu_h6(.DOUT(frozen_taps[6]));
  (* keep *) MCU_DOUT mcu_h7(.DOUT(frozen_taps[7]));
endmodule
"""


def _tool(name):
    """Locate an open-flow tool: $AGAMEMNON_OSS/bin first, then PATH.

    Mirrors tests/test_build_e2e.py's ``_tool`` helper.
    """
    oss = os.environ.get("AGAMEMNON_OSS")
    if oss:
        for ext in ("", ".exe"):
            candidate = os.path.join(oss, "bin", name + ext)
            if os.path.exists(candidate):
                return candidate
    return shutil.which(name)


def _uarch_nextpnr():
    """Locate the agrv2k uarch nextpnr-generic build the real CLI would use.

    Mirrors tests/test_route_from_source_invariance.py's helper: this bug
    only reproduces through the C++ uarch flow (qin_pack's feedback-buffer
    rewrite plus the agrv2k placer), not the legacy Python architecture.
    """
    configured = os.environ.get("AGAMEMNON_UARCH_NEXTPNR")
    if configured:
        first = configured.split()[0]
        if shutil.which(first) or os.path.isfile(first):
            return configured
        return None
    return shutil.which("nextpnr-generic")


@pytest.mark.xfail(
    reason=(
        "known open defect: core_logic/route_through ownership-predicate "
        "mismatch at the four route_through_footprints.csv sites -- see "
        "AG32-Docs docs/TASK_QUEUE.md queue E ('B2') and the 2026-08-19 "
        "root-cause investigation. Fix is proposed, not landed."
    ),
    strict=False,
)
def test_lfsr_freeze_capture_hits_the_core_logic_route_through_collision(tmp_path):
    yosys = _tool("yosys")
    npr = _uarch_nextpnr()
    if not yosys:
        pytest.skip("open-flow tools absent (need yosys on PATH or $AGAMEMNON_OSS/bin)")
    if not npr:
        pytest.skip(
            "agrv2k uarch nextpnr-generic absent (need $AGAMEMNON_UARCH_NEXTPNR "
            "or nextpnr-generic on PATH built via "
            "agamemnon/engine/uarch/agrv2k/build.sh)"
        )

    vsrc = tmp_path / "top.v"
    vsrc.write_text(LFSR_FREEZE_V)
    outbin = tmp_path / "top.bin"

    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "build", str(vsrc),
         "--uarch", "-o", str(outbin)],
        cwd=str(tmp_path), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=300,
    )
    log = result.stdout or ""
    assert result.returncode != 0, (
        "expected the known-open BitOwnershipError; build unexpectedly "
        "succeeded -- if the ownership predicate mismatch has been fixed, "
        "update/remove this xfail:\n%s" % log[-2000:]
    )
    assert "BitOwnershipError" in log, (
        "expected a BitOwnershipError; got a different failure -- "
        "investigate before assuming this is the same known defect:\n%s"
        % log[-3000:]
    )
    assert (
        "feature ownership collision at byte 65852 mask 0x08: "
        "core_logic and route_through" in log
    ), (
        "BitOwnershipError raised, but not at the pinned byte/mask/owner "
        "signature -- the defect may have moved or changed shape:\n%s"
        % log[-3000:]
    )
