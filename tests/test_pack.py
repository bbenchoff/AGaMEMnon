"""Byte-exact archival bitstream regression for shipped routed-JSON fixtures.

Two old fixtures intentionally contain unresolved PIPs and therefore must fail
under the normal, qualification-safe CLI.  The explicit archival override still
reproduces their historic bytes so old reverse-engineering evidence is not lost.

Fixtures live in tests/fixtures/ (routed nextpnr JSONs + expected_sha256.txt); regenerate the hashes
after any intentional engine change with:  agamemnon pack tests/fixtures/<x>_routed.json out.bin
"""
import hashlib
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")


def _expected():
    exp = {}
    with open(os.path.join(FIX, "expected_sha256.txt")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                name, sha = line.split()
                exp[name] = sha
    return exp


EXPECTED = _expected()
LEGACY_PARTIAL = {"comb_routed.json": 1, "tff_routed.json": 3}


@pytest.mark.parametrize("routed", sorted(EXPECTED))
def test_pack_byte_exact(routed, tmp_path):
    out = str(tmp_path / routed.replace("_routed.json", ".bin"))
    env = os.environ.copy()
    env.pop("AGAMEMNON_SYSCLK", None)
    if routed in LEGACY_PARTIAL:
        rejected = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "pack", os.path.join(FIX, routed), out],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
        assert rejected.returncode != 0
        assert "refusing to emit a partial bitstream" in rejected.stdout + rejected.stderr
        assert not os.path.exists(out)
        env["AGAMEMNON_ALLOW_UNMAPPED"] = "1"
    r = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", os.path.join(FIX, routed), out],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, "pack failed:\n" + r.stdout + r.stderr
    assert os.path.getsize(out) == 99944, "expected 99944-byte uncompressed image"
    got = hashlib.sha256(open(out, "rb").read()).hexdigest()
    assert got == EXPECTED[routed], f"{routed}: {got} != {EXPECTED[routed]} (engine output changed)"


def test_pack_explicit_100_mhz_override_reproduces_reference_clock_image(tmp_path):
    out = str(tmp_path / "tff-100mhz.bin")
    env = os.environ.copy()
    env["AGAMEMNON_ALLOW_UNMAPPED"] = "1"
    env["AGAMEMNON_SYSCLK"] = "100"

    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack",
         os.path.join(FIX, "tff_routed.json"), out],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert hashlib.sha256(open(out, "rb").read()).hexdigest() == (
        "33318d354f09567ac786d3ae27543b52ce456b2d72addef9570f79dcc5256061"
    )
