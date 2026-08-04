"""Observational last-writer tracing for AGRV2K configuration payloads.

The tracer is deliberately outside the emission data path: callers mutate
their ordinary ``bytearray`` exactly as before and only notify this object of
the physical cells a stage wrote.  Its compact run-length JSON covers every
bit, including untouched baseline bits, without embedding vendor material.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter


SCHEMA = 1


class BitOwnershipTrace:
    """Track the last named stage to write each LSB-numbered payload bit."""

    def __init__(self, byte_count: int, initial_owner: str = "baseline"):
        if byte_count <= 0:
            raise ValueError("byte_count must be positive")
        self.byte_count = byte_count
        self._owners = [initial_owner] * (byte_count * 8)

    def touch(self, byte: int, mask: int, owner: str) -> None:
        if not (0 <= byte < self.byte_count):
            raise IndexError("ownership byte is outside the payload")
        if not owner:
            raise ValueError("ownership stage must be non-empty")
        for bit in range(8):
            if mask & (1 << bit):
                self._owners[byte * 8 + bit] = owner

    def touch_bytes(self, start: int, end: int, owner: str) -> None:
        if not (0 <= start <= end <= self.byte_count):
            raise IndexError("ownership byte range is outside the payload")
        for byte in range(start, end):
            self.touch(byte, 0xFF, owner)

    def report(self, raw: bytes, *, source: str, output_sha256: str) -> dict:
        if len(raw) != self.byte_count:
            raise ValueError("payload length changed while tracing")
        runs = []
        start = 0
        owner = self._owners[0]
        for index, current in enumerate(self._owners[1:], 1):
            if current != owner:
                runs.append([start, index, owner])
                start, owner = index, current
        runs.append([start, len(self._owners), owner])
        counts = Counter(self._owners)
        return {
            "schema": SCHEMA,
            "bit_numbering": "payload byte offset * 8 + LSB bit index",
            "payload_bytes": self.byte_count,
            "payload_sha256": hashlib.sha256(raw).hexdigest(),
            "output_sha256": output_sha256,
            "source": source,
            "owner_bit_counts": dict(sorted(counts.items())),
            "runs": runs,
        }

    def write_json(self, path: str, raw: bytes, *, source: str, output_sha256: str) -> None:
        report = self.report(raw, source=source, output_sha256=output_sha256)
        with open(path, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
