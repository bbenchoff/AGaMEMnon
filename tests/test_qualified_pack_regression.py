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


def test_qualified_pack_manifest_covers_every_retained_routed_json():
    assert MANIFEST["schema"] == 1
    assert MANIFEST["hash_mode"] == "sha256-binary-v1"
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
    assert _sha256(routed) == artifact["routed_sha256"]

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
