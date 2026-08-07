import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generated_claim_policy_outputs_are_current():
    subprocess.run(
        [sys.executable, "tools/generate_claim_policy_ledger.py", "--check"],
        cwd=ROOT,
        check=True,
    )


def test_retained_artifact_policy_dry_run_is_clean_and_complete():
    dry = json.loads((ROOT / "qualification" / "claim_policy_dry_run.json").read_text(encoding="utf-8"))
    pack = json.loads((ROOT / "qualification" / "pack_regression.json").read_text(encoding="utf-8"))
    assert dry["summary"] == {
        "artifact_count": len(pack["artifacts"]),
        "permission_error_count": 0,
    }
    assert [row["routed"] for row in dry["artifacts"]] == [row["routed"] for row in pack["artifacts"]]
    assert all(not row["permission_errors"] for row in dry["artifacts"])
    assert all(row["policy"] == "release-strict" for row in dry["artifacts"])
