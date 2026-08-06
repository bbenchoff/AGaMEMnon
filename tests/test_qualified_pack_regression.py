"""A0 byte-identity gate for every retained qualification routed artifact."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION = ROOT / "qualification"
MANIFEST_PATH = QUALIFICATION / "pack_regression.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
ARTIFACTS = MANIFEST["artifacts"]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_lf(data):
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _sha256_text(path):
    return hashlib.sha256(_canonical_lf(path.read_bytes())).hexdigest()


def test_qualified_pack_manifest_covers_every_retained_routed_json():
    assert MANIFEST["schema"] == 1
    assert MANIFEST["hash_mode"] == "routed-sha256-lf-v1+bitstream-sha256-binary-v1"
    recorded = {item["routed"] for item in ARTIFACTS}
    present = {
        path.relative_to(ROOT).as_posix()
        for path in QUALIFICATION.glob("*routed*.json")
    }
    assert len(recorded) == len(ARTIFACTS)
    assert recorded == present


@pytest.mark.parametrize("artifact", ARTIFACTS, ids=lambda item: Path(item["routed"]).name)
def test_qualified_pack_is_byte_identical(artifact, tmp_path):
    routed = ROOT / artifact["routed"]
    assert _sha256_text(routed) == artifact["routed_sha256"]

    # Prove the pinned routed identity is invariant under both checkout EOL
    # forms without weakening the emitted-image check below.
    canonical = _canonical_lf(routed.read_bytes())
    assert hashlib.sha256(canonical).hexdigest() == artifact["routed_sha256"]
    crlf_checkout = canonical.replace(b"\n", b"\r\n")
    assert hashlib.sha256(_canonical_lf(crlf_checkout)).hexdigest() \
        == artifact["routed_sha256"]

    env = {key: value for key, value in os.environ.items()
           if not key.startswith("AGAMEMNON_")}
    env.update(artifact["environment"])
    output = tmp_path / (routed.stem + ".bin")
    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", str(routed), str(output)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert output.stat().st_size == 99_944
    assert _sha256(output) == artifact["bitstream_sha256"]
