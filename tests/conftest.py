"""Pytest configuration for the AGaMEMnon test suite.

Puts the repo root on sys.path so `import agamemnon` / `import agamemnon.cli` resolve to the
in-tree package (cli.py does `from . import program`, so it must be imported as a package, not as a
bare module). Also exposes the bundled real-silicon fixture path. The whole suite is
self-contained: no external data files, no hardware.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BLINKY_BIN = os.path.join(FIXTURES, "blinky.bin")


@pytest.fixture
def blinky_bin_path():
    """Absolute path to the 2921-byte real fabric .bin fixture (cpld_native/blinky.bin)."""
    assert os.path.exists(BLINKY_BIN), f"missing fixture: {BLINKY_BIN}"
    return BLINKY_BIN


@pytest.fixture
def blinky_bin_bytes(blinky_bin_path):
    """Raw bytes of the fixture .bin."""
    with open(blinky_bin_path, "rb") as f:
        return f.read()
