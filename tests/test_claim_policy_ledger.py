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
    # Every retained artifact must pack with no permission errors under its own
    # recorded policy, and all but the pinned exceptions must be release-strict.
    # The exception set is pinned BY NAME so it cannot quietly grow: the pad pair
    # is research-unsafe because the Python-architecture PCF placer composes
    # AGAMEMNON_SOFT_PREFER, AGAMEMNON_SOFT_PENALTY and AGAMEMNON_NO_FFBRIDGE,
    # which are registered experimental. That gate is not specific to pads -- a
    # plain non-pad toggle design is rejected by release-strict identically --
    # and it was not loosened to retain this artifact.
    NOT_RELEASE_STRICT = {
        "qualification/pad_pair_pin18_pin16_routed.json": "research-unsafe",
    }
    for row in dry["artifacts"]:
        expected = NOT_RELEASE_STRICT.get(row["routed"], "release-strict")
        assert row["policy"] == expected, (
            "%s packs under %s, expected %s" % (row["routed"], row["policy"], expected)
        )
    assert {row["routed"] for row in dry["artifacts"]} >= set(NOT_RELEASE_STRICT)
