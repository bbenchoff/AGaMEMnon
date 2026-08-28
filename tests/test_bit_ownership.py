import json

import pytest

from agamemnon.engine.bit_ownership import BitOwnershipError, BitOwnershipTrace


def test_trace_covers_every_bit_and_uses_last_writer(tmp_path):
    raw = bytes((0x00, 0xA5))
    trace = BitOwnershipTrace(len(raw))
    trace.touch(0, 0x03, "PIP")
    trace.touch(0, 0x02, "LUT")
    trace.touch_bytes(1, 2, "clock")
    report = trace.report(
        raw,
        source="fixture.json",
        output_sha256="a" * 64,
        routed_sha256="b" * 64,
    )

    assert sum(report["owner_bit_counts"].values()) == 16
    assert report["owner_bit_counts"] == {"LUT": 1, "PIP": 1, "clock": 8, "baseline": 6}
    assert report["runs"][0] == [0, 1, "PIP"]
    assert report["runs"][1] == [1, 2, "LUT"]
    assert report["runs"][-1] == [8, 16, "clock"]
    assert report["routed_sha256"] == "b" * 64

    output = tmp_path / "trace.json"
    trace.write_json(
        str(output),
        raw,
        source="fixture.json",
        output_sha256="a" * 64,
        routed_sha256="b" * 64,
    )
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["payload_bytes"] == 2
    assert written["routed_sha256"] == "b" * 64


def test_bound_feature_rejects_undeclared_and_cross_feature_writes():
    trace = BitOwnershipTrace(2)
    routing = trace.bind("routing", bits=[(0, 0x03)])
    clocks = trace.bind("clocks", bits=[(0, 0x02), (1, 0xFF)])

    routing.touch(0, 0x02, "PIP")
    with pytest.raises(BitOwnershipError, match="undeclared"):
        routing.touch(0, 0x04, "PIP")
    with pytest.raises(BitOwnershipError, match="collision"):
        clocks.touch(0, 0x02, "clock")
    clocks.touch_bytes(1, 2, "clock")

    initialization = BitOwnershipTrace(1)
    first = initialization.bind("first", bits=[(0, 0x01)])
    second = initialization.bind("second", bits=[(0, 0x01)])
    first.clearing().touch(0, 0x01, "default")
    second.touch(0, 0x01, "second")
    with pytest.raises(BitOwnershipError, match="undeclared"):
        first.clearing().touch(0, 0x02, "default")
