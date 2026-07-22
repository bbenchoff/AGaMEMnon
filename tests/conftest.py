"""Pytest configuration for the AGaMEMnon test suite.

Exposes the bundled real-silicon fixture path. The whole suite is self-contained:
no external data files and no hardware.
"""
import os

import pytest

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
