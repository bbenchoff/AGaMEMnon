"""Byte-exact bitstream regression: `agamemnon pack` on the shipped routed-JSON fixtures must
reproduce the recorded bitstreams byte-for-byte, entirely from the self-contained package engine
(no vendor binary, no reach into AG32-Docs). This is the oracle that proved the engine unification.

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


@pytest.mark.parametrize("routed", sorted(EXPECTED))
def test_pack_byte_exact(routed, tmp_path):
    out = str(tmp_path / routed.replace("_routed.json", ".bin"))
    r = subprocess.run(
        [sys.executable, "-m", "agamemnon.cli", "pack", os.path.join(FIX, routed), out],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, "pack failed:\n" + r.stdout + r.stderr
    assert os.path.getsize(out) == 99944, "expected 99944-byte uncompressed image"
    got = hashlib.sha256(open(out, "rb").read()).hexdigest()
    assert got == EXPECTED[routed], f"{routed}: {got} != {EXPECTED[routed]} (engine output changed)"
