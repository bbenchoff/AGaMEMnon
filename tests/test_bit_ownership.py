import json

from agamemnon.engine.bit_ownership import BitOwnershipTrace


def test_trace_covers_every_bit_and_uses_last_writer(tmp_path):
    raw = bytes((0x00, 0xA5))
    trace = BitOwnershipTrace(len(raw))
    trace.touch(0, 0x03, "PIP")
    trace.touch(0, 0x02, "LUT")
    trace.touch_bytes(1, 2, "clock")
    report = trace.report(raw, source="fixture.json", output_sha256="a" * 64)

    assert sum(report["owner_bit_counts"].values()) == 16
    assert report["owner_bit_counts"] == {"LUT": 1, "PIP": 1, "clock": 8, "baseline": 6}
    assert report["runs"][0] == [0, 1, "PIP"]
    assert report["runs"][1] == [1, 2, "LUT"]
    assert report["runs"][-1] == [8, 16, "clock"]

    output = tmp_path / "trace.json"
    trace.write_json(str(output), raw, source="fixture.json", output_sha256="a" * 64)
    assert json.loads(output.read_text(encoding="utf-8"))["payload_bytes"] == 2
