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
import json
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


def test_serv_replay_preserves_pre_option_direct_d_policy():
    source = REGEN.read_text(encoding="utf-8")
    assert 'LEGACY_REPLAY_ENV = {"AGAMEMNON_DIRECT_D": "1"}' in source
    assert "env.update(LEGACY_REPLAY_ENV)" in source


def test_current_serv_record_binds_fresh_silicon_without_rewriting_history():
    records = [json.loads(line) for line in
               (REPO / "qualification/serv_compliance_evidence.jsonl").read_text().splitlines()]
    current = next(r for r in records if r["trial_id"] ==
                   "2026-09-05-serv-f-output-requalification-20260905")
    previous = next(r for r in records if r["trial_id"] == current["supersedes"])
    migration = json.loads((REPO / "qualification/serv_f_output_requalification_20260905.json").read_text())
    manifest = json.loads((REPO / "qualification/pack_regression.json").read_text())
    assert "silicon fields are inherited" not in current["replay_scope"]
    assert "timing was not remeasured" in current["replay_scope"]
    assert current["scope"] == previous["scope"]
    assert current["pack_environment"] == previous["pack_environment"]
    assert current["rtl"] == previous["rtl"]
    for name, build in (("smoke", "signature_build"), ("heartbeat", "heartbeat_build")):
        reference = current["hardware"]["evidence"][name]
        path, trial = reference.split("#")
        assert path == "qualification/serv_f_output_requalification_20260905.json"
        witness = next(r for r in migration["records"] if r["trial_id"] == trial)
        artifact = next(r for r in manifest["artifacts"] if r["routed"] == witness["routed"])
        assert current[build]["bitstream_sha256"] == witness["bitstream_sha256"] == artifact["bitstream_sha256"]
        assert previous[build]["bitstream_sha256"] == witness["previous_bitstream_sha256"]
        assert current[build]["routed_sha256"] == previous[build]["routed_sha256"] == witness["routed_sha256"]
        assert current["hardware"]["report_sha256_lf"] == witness["report_sha256_lf"]
        runs = [r for r in current["hardware"]["runs"] if r["name"] == name]
        assert len(runs) == 3 and {r["repeat"] for r in runs} == {1, 2, 3}
        for run in runs:
            assert run["status"] == "PASS"
            assert run["reset_high"]["ones"] == run["reset_reasserted"]["ones"] == 0
            if name == "smoke":
                assert all(sample["ones"] == sample["n"] for sample in run["released"])
            else:
                assert all(0 < sample["ones"] < sample["n"] for sample in run["released"])
                assert run["edges"] > 0
