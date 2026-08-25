import hashlib
import string
from types import SimpleNamespace

import pytest

from agamemnon.engine import bitgen
from agamemnon.engine import silicon_negatives as negatives


OPEN_DEFECTS = {
    "VP-AGM-001",
    "VP-AGM-003",
    "VP-AGM-004",
    "VP-AGM-005",
    "VP-AGM-006",
    "VP-AGM-007",
    "VP-AGM-008",
    "VP-AGM-009",
}


def test_registry_is_exact_and_covers_each_open_escape_defect():
    assert len(negatives.KNOWN_SILICON_NEGATIVE_IMAGES) == 17
    assert {
        item.defect for item in negatives.KNOWN_SILICON_NEGATIVE_IMAGES.values()
    } == OPEN_DEFECTS
    assert all(
        len(digest) == 64 and set(digest) <= set(string.hexdigits.lower())
        for digest in negatives.KNOWN_SILICON_NEGATIVE_IMAGES
    )


def test_known_digest_refuses_and_unknown_digest_passes():
    digest, negative = next(iter(negatives.KNOWN_SILICON_NEGATIVE_IMAGES.items()))
    with pytest.raises(SystemExit, match=negative.defect) as error:
        negatives.refuse_known_silicon_negative_digest(digest.upper())
    assert digest.upper() in str(error.value)

    negatives.refuse_known_silicon_negative_digest("0" * 64)


def test_image_gate_hashes_header_plus_crc_finalized_payload(monkeypatch):
    header = b"canonical-header"
    image = bytearray(b"crc-finalized-payload")
    digest = hashlib.sha256(header + image).hexdigest()
    negative = negatives.SiliconNegative("VP-AGM-TEST", "test image")
    monkeypatch.setitem(negatives.KNOWN_SILICON_NEGATIVE_IMAGES, digest, negative)

    with pytest.raises(SystemExit, match="VP-AGM-TEST"):
        negatives.refuse_known_silicon_negative_image(header, image)


def test_write_output_removes_stale_file_before_exact_image_refusal(
        tmp_path, monkeypatch):
    output_path = tmp_path / "image.agm"
    output_path.write_bytes(b"stale output")
    assembly = SimpleNamespace(
        header=b"header",
        image=bytearray(b"payload"),
        trace_path=None,
    )
    events = []

    def emit_integrity_phase(candidate):
        assert candidate is assembly
        assert not output_path.exists()
        events.append("integrity")
        return b"compressed output"

    def refuse(header, image):
        assert header == assembly.header
        assert image is assembly.image
        assert not output_path.exists()
        events.append("refusal")
        raise SystemExit("retained negative")

    monkeypatch.setattr(bitgen, "emit_integrity_phase", emit_integrity_phase)
    monkeypatch.setattr(bitgen, "refuse_known_silicon_negative_image", refuse)

    with pytest.raises(SystemExit, match="retained negative"):
        bitgen.write_output(assembly, "routed.json", output_path)

    assert events == ["integrity", "refusal"]
    assert not output_path.exists()
