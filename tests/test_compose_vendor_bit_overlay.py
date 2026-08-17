import struct
import subprocess
import sys
from pathlib import Path

from agamemnon.engine import agasc


ROOT = Path(__file__).resolve().parents[1]
HEADER = bytes.fromhex("123456789abcdef0")


def _framed(raw):
    return HEADER + bytes(raw)


def test_overlay_reapplies_selected_vendor_bits_and_repairs_crc(tmp_path):
    old_raw = bytearray(agasc.RAW_LEN)
    vendor_raw = bytearray(old_raw)
    vendor_raw[20] = 0x03

    old_hybrid_raw = bytearray(old_raw)
    old_hybrid_raw[20] = 0x03
    subtract_raw = bytearray(old_raw)
    subtract_raw[20] = 0x01
    new_raw = bytearray(old_raw)
    new_raw[20] = 0x80

    paths = {
        "old": tmp_path / "old.bin",
        "hybrid": tmp_path / "hybrid.bin",
        "subtract": tmp_path / "subtract.bin",
        "new": tmp_path / "new.bin",
        "vendor": tmp_path / "vendor.raw",
        "output": tmp_path / "output.bin",
    }
    paths["old"].write_bytes(_framed(old_raw))
    paths["hybrid"].write_bytes(_framed(old_hybrid_raw))
    paths["subtract"].write_bytes(_framed(subtract_raw))
    paths["new"].write_bytes(_framed(new_raw))
    paths["vendor"].write_bytes(vendor_raw)

    result = subprocess.run(
        [
            sys.executable,
            "tools/compose_vendor_bit_overlay.py",
            "--new-base", str(paths["new"]),
            "--old-base", str(paths["old"]),
            "--old-hybrid", str(paths["hybrid"]),
            "--subtract-hybrid", str(paths["subtract"]),
            "--vendor-raw", str(paths["vendor"]),
            "--output", str(paths["output"]),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "selected_bits=1" in result.stdout

    output = paths["output"].read_bytes()
    assert output[:8] == HEADER
    assert output[8 + 20] == 0x82
    expected_crc = struct.pack(
        ">I", agasc.crc32_bzip2(output[:8] + output[8:8 + agasc.CRC_OFFSET])
    )
    assert output[-4:] == expected_crc
