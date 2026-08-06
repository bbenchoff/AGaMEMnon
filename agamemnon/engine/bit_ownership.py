"""Declared bit ownership enforcement and last-writer tracing.

Every feature receives a writer bound to its declared physical masks. Writes
outside those masks and active claims already owned by another feature fail
the build. Clear-phase writes are declaration-checked initialization and do
not claim the resulting bit. The optional compact run-length JSON still covers
every bit, including untouched baseline bits, without embedding vendor material.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter


SCHEMA = 1


class BitOwnershipError(RuntimeError):
    """A feature wrote outside its declaration or collided with another feature."""


class _FeatureOwnership:
    def __init__(self, trace, feature_id, claim=True):
        self._trace = trace
        self._feature_id = feature_id
        self._claim = claim

    def clearing(self):
        return _FeatureOwnership(self._trace, self._feature_id, claim=False)

    def touch(self, byte: int, mask: int, owner: str) -> None:
        self._trace._touch_feature(
            byte, mask, owner, self._feature_id, claim=self._claim
        )

    def touch_bytes(self, start: int, end: int, owner: str) -> None:
        for byte in range(start, end):
            self.touch(byte, 0xFF, owner)


class BitOwnershipTrace:
    """Enforce feature regions and track the last stage writing each payload bit."""

    def __init__(self, byte_count: int, initial_owner: str = "baseline"):
        if byte_count <= 0:
            raise ValueError("byte_count must be positive")
        self.byte_count = byte_count
        self._owners = [initial_owner] * (byte_count * 8)
        self._claimants = [None] * (byte_count * 8)
        self._allowed = {}

    def bind(self, feature_id: str, bits=(), byte_ranges=()):
        if not feature_id:
            raise ValueError("feature_id must be non-empty")
        allowed = self._allowed.setdefault(feature_id, {})
        for byte, mask in bits:
            if not (0 <= byte < self.byte_count):
                raise IndexError("declared ownership byte is outside the payload")
            allowed[byte] = allowed.get(byte, 0) | mask
        for start, end in byte_ranges:
            if not (0 <= start <= end <= self.byte_count):
                raise IndexError("declared ownership byte range is outside the payload")
            for byte in range(start, end):
                allowed[byte] = 0xFF
        return _FeatureOwnership(self, feature_id)

    def _touch_feature(
        self, byte: int, mask: int, owner: str, feature_id: str, *, claim: bool
    ) -> None:
        if not (0 <= byte < self.byte_count):
            raise IndexError("ownership byte is outside the payload")
        allowed = self._allowed.get(feature_id, {}).get(byte, 0)
        outside = mask & ~allowed
        if outside:
            raise BitOwnershipError(
                "feature %s wrote undeclared bit(s) at byte %d mask 0x%02x" %
                (feature_id, byte, outside)
            )
        for bit in range(8):
            bit_mask = 1 << bit
            if not (mask & bit_mask):
                continue
            index = byte * 8 + bit
            if claim:
                previous = self._claimants[index]
                if previous is not None and previous != feature_id:
                    raise BitOwnershipError(
                        "feature ownership collision at byte %d mask 0x%02x: %s and %s" %
                        (byte, bit_mask, previous, feature_id)
                    )
                self._claimants[index] = feature_id
        self.touch(byte, mask, owner)

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
