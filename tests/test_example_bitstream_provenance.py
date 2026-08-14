"""Guards the offline ``examples/bitstream_provenance.py`` worked example.

This runs with only the Python package (no board, no Yosys/nextpnr/OpenOCD, no
Icarus), so it is never skipped. It pins the vendor-canvas provenance figures
cited across docs/FABRIC_DEFAULT_CANVAS.md, docs/CONFIG_SURFACE_MAP.md, and
docs/VENDOR_PARITY.md: if the shipped canvas or the codec drifts, both the
example's own self-check and these assertions fail.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "bitstream_provenance.py"


@pytest.fixture(scope="module")
def prov():
    spec = importlib.util.spec_from_file_location("bitstream_provenance", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_example_self_check_passes_on_shipped_canvas(prov, capsys):
    assert prov.main([]) == 0
    out = capsys.readouterr().out
    assert "matches every documented provenance invariant" in out
    assert "FAIL" not in out


def test_canvas_provenance_numbers_match_docs(prov):
    report, source_bytes, source_sha = prov.analyze(prov.CANVAS)
    summary = report["summary"]
    assert source_bytes == prov.EXPECTED["source_bytes"]
    assert source_sha == prov.EXPECTED["source_sha256"]
    assert summary["named_features"] == prov.EXPECTED["named_features"]
    assert summary["tiles"] == prov.EXPECTED["named_tiles"]
    assert summary["unknown_set_bits"] == prov.EXPECTED["unknown_set_bits"]
    assert report["crc"]["valid"] is prov.EXPECTED["crc_valid"]


def test_open_codec_roundtrip_is_byte_exact(prov):
    assert prov.roundtrip_is_byte_exact(prov.CANVAS) is True


def test_example_runs_on_a_non_canvas_image(prov, capsys):
    blinky = ROOT / "tests" / "fixtures" / "blinky.bin"
    assert prov.main([str(blinky)]) == 0
    out = capsys.readouterr().out
    assert "no documented-invariant self-check" in out
