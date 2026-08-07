import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from generate_claim_policy_ledger import canonical_lf_sha


def test_generated_claim_policy_outputs_are_current():
    subprocess.run(
        [sys.executable, "tools/generate_claim_policy_ledger.py", "--check"],
        cwd=ROOT,
        check=True,
    )


def test_dry_run_source_hash_uses_canonical_lf(tmp_path):
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{"schema":1}\n')
    crlf.write_bytes(b'{"schema":1}\r\n')
    assert canonical_lf_sha(lf) == canonical_lf_sha(crlf)


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
