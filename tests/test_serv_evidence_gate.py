"""CI gate: shipped SERV routed artifacts must still pack strict-clean and match
their recorded evidence.

This runs ``qualification/regen_serv_evidence.py`` in its dry-run mode, which:

  * recomputes every derivable hash (sources, routed JSONs, packed bitstreams)
    and pip metric from the on-disk artifacts, and
  * re-packs each routed JSON through strict AGaMEMnon bitgen, REFUSING any
    artifact that does not pack with 0 unmapped/predicted/legacy selectors.

The dry-run exits 0 only when every derivable field already matches the shipped
files and both routes reproduce the qualified bitstreams under the recorded
pack environment. Any drift -- a re-routed JSON whose canonical hash no longer
matches, a missing pack setting, a different packed image, or a route that lost
a clean selector encoding -- makes it exit non-zero, and this test fails.

That is deliberately the same failure ``test_large_flow_helpers`` catches, but
from the *artifact* side: it stops a stale or unpackable SERV route from
silently shipping under a ``verdict: pass`` record. It needs only Python and the
in-tree engine (``pack`` runs offline -- no Yosys/nextpnr/hardware), so it runs
everywhere the rest of the hardware-free suite does.

If this fails, do NOT edit the evidence hashes by hand. Re-qualify:
  1. recover or deliberately select the exact pack environment and record it,
  2. re-route until both images pack 0-unmapped and verify them on the board,
  3. update rtl.*/hardware.*/verdict by hand from the bench run,
  4. ``python qualification/regen_serv_evidence.py --write`` to sync the hashes.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGEN = REPO / "qualification" / "regen_serv_evidence.py"


def test_serv_evidence_artifacts_pack_clean_and_match_record():
    assert REGEN.exists(), f"missing gate script: {REGEN}"
    proc = subprocess.run(
        [sys.executable, str(REGEN)],  # dry-run (no --write)
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "SERV evidence gate failed: a shipped routed artifact is stale against "
        "its recorded evidence or no longer packs strict-clean. Re-qualify (do "
        "not hand-edit the hashes); see this test's module docstring.\n\n"
        "--- regen_serv_evidence.py output ---\n"
        + (proc.stdout or "") + (proc.stderr or "")
    )


def test_serv_evidence_replay_ignores_ambient_engine_switches():
    env = dict(os.environ)
    env["AGAMEMNON_SYSCLK"] = "100"
    env["AGAMEMNON_ALLOW_UNMAPPED"] = "1"
    proc = subprocess.run(
        [sys.executable, str(REGEN)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "ambient AGAMEMNON_* settings changed the qualified SERV replay:\n\n"
        + (proc.stdout or "") + (proc.stderr or "")
    )
