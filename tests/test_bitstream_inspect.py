import json
import struct
from pathlib import Path

from agamemnon import cli
from agamemnon.engine import agasc, bitstream_inspect


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "agamemnon" / "chipdb"


def _valid(raw):
    raw[agasc.CRC_OFFSET:] = struct.pack(
        ">I", agasc.crc32_bzip2(cli.HDR + bytes(raw[:agasc.CRC_OFFSET]))
    )
    return bytes(raw)


def test_describe_reports_named_unknown_and_crc():
    by_bit, _ = agasc.load_feature_map(str(DATA))
    (byte, mask), (x, y, feature) = next(iter(by_bit.items()))
    raw = bytearray(agasc.RAW_LEN)
    raw[byte] |= mask
    # Locate an unmapped physical bit outside the CRC.
    mapped = agasc._mapped_masks(by_bit)
    unknown_byte = next(i for i, value in enumerate(mapped[:agasc.CRC_OFFSET]) if value != 0xFF)
    unknown_mask = next(1 << bit for bit in range(8) if not mapped[unknown_byte] & (1 << bit))
    raw[unknown_byte] |= unknown_mask
    report = bitstream_inspect.describe(cli.HDR, _valid(raw), str(DATA), include_raw=True)
    assert report["crc"]["valid"]
    assert {"x": x, "y": y, "features": [feature]} in report["tiles"]
    assert report["summary"]["named_features"] == 1
    assert report["summary"]["unknown_set_bits"] == 1
    assert {"offset": unknown_byte, "value": unknown_mask} in report["raw"]


def test_compare_separates_features_from_residual_and_ignores_crc():
    by_bit, _ = agasc.load_feature_map(str(DATA))
    (byte, mask), (x, y, feature) = next(iter(by_bit.items()))
    mapped = agasc._mapped_masks(by_bit)
    unknown_byte = next(i for i, value in enumerate(mapped[:agasc.CRC_OFFSET]) if value != 0xFF)
    unknown_mask = next(1 << bit for bit in range(8) if not mapped[unknown_byte] & (1 << bit))
    before = _valid(bytearray(agasc.RAW_LEN))
    changed = bytearray(before)
    changed[byte] |= mask
    changed[unknown_byte] |= unknown_mask
    after = _valid(changed)
    report = bitstream_inspect.compare(cli.HDR, before, cli.HDR, after, str(DATA))
    assert report["summary"] == {
        "added_features": 1, "removed_features": 0, "raw_bytes_changed": 1
    }
    assert report["added"][0]["feature"] == feature
    assert report["raw"] == [{"offset": unknown_byte, "before": 0, "after": unknown_mask}]


def test_cli_explain_and_diff_json(tmp_path):
    fixture = ROOT / "tests" / "fixtures" / "blinky.bin"
    explain = cli.main(["explain", str(fixture), "--json", "-o", str(tmp_path / "explain.json")])
    assert explain is None
    report = json.loads((tmp_path / "explain.json").read_text())
    assert report["schema"] == 1 and report["crc"]["valid"]
    diff = tmp_path / "diff.json"
    cli.main(["diff", str(fixture), str(fixture), "--json", "-o", str(diff)])
    assert json.loads(diff.read_text())["summary"] == {
        "added_features": 0, "raw_bytes_changed": 0, "removed_features": 0
    }
