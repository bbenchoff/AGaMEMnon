"""Byte-exact archival bitstream regression for shipped routed-JSON fixtures.

Two old fixtures intentionally contain unresolved PIPs and therefore fail
under the normal, qualification-safe CLI. D0 also rejects the old archival
override before emission; their historic hashes remain retained as evidence.

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
LEGACY_UNTYPED_CLOCK = {"tff_routed.json"}


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
        diagnostic = rejected.stdout + rejected.stderr
        if routed in LEGACY_UNTYPED_CLOCK:
            assert "typed clock direct-pack validation failed" in diagnostic
        else:
            assert "refusing to emit a partial bitstream" in diagnostic
        assert not os.path.exists(out)
        env["AGAMEMNON_ALLOW_UNMAPPED"] = "1"
        archival = subprocess.run(
            [sys.executable, "-m", "agamemnon.cli", "pack", os.path.join(FIX, routed), out],
            cwd=ROOT, capture_output=True, text=True, env=env,
        )
        assert archival.returncode != 0
        diagnostic = archival.stdout + archival.stderr
        if routed in LEGACY_UNTYPED_CLOCK:
            assert "typed clock direct-pack validation failed" in diagnostic
        else:
            assert "archival/unmapped emission is incompatible" in diagnostic
        assert not os.path.exists(out)
        return
    r = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", os.path.join(FIX, routed), out],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, "pack failed:\n" + r.stdout + r.stderr
    assert os.path.getsize(out) == 99944, "expected 99944-byte uncompressed image"
    got = hashlib.sha256(open(out, "rb").read()).hexdigest()
    assert got == EXPECTED[routed], f"{routed}: {got} != {EXPECTED[routed]} (engine output changed)"


def test_pack_explicit_100_mhz_cannot_bypass_archival_policy(tmp_path):
    out = str(tmp_path / "comb-100mhz.bin")
    env = os.environ.copy()
    env["AGAMEMNON_ALLOW_UNMAPPED"] = "1"
    env["AGAMEMNON_SYSCLK"] = "100"

    result = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack",
         os.path.join(FIX, "comb_routed.json"), out],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )

    assert result.returncode != 0
    assert "archival/unmapped emission is incompatible" in result.stdout + result.stderr
    assert not os.path.exists(out)
