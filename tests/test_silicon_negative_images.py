import hashlib
import json
import string
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agamemnon.engine import bitgen
from agamemnon.engine import silicon_negatives as negatives
from agamemnon.engine.registry import options_from


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


def test_logical_design_registry_is_narrow_and_covers_retained_graphs():
    assert negatives.LOGICAL_DESIGN_DIGEST_SCHEMA == 1
    assert negatives.logical_design_digest(
        {"ports": {}, "cells": {}, "netnames": {}}
    ) == "b79840e1a78c0302c679a29b65512f3e20dfafe5a76f60a0824fa03861be8d37"
    assert len(negatives.KNOWN_SILICON_NEGATIVE_DESIGNS) == 7
    assert {
        item.defect for item in negatives.KNOWN_SILICON_NEGATIVE_DESIGNS.values()
    } == {
        "VP-AGM-001", "VP-AGM-003", "VP-AGM-004", "VP-AGM-005",
        "VP-AGM-008", "VP-AGM-009",
    }
    assert all(
        len(digest) == 64 and set(digest) <= set(string.hexdigits.lower())
        for digest in negatives.KNOWN_SILICON_NEGATIVE_DESIGNS
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


def test_logical_design_digest_ignores_physical_annotations_only():
    module = {
        "settings": {"seed": "1", "router": "router2"},
        "attributes": {"src": "private/source.v:1"},
        "ports": {},
        "cells": {
            "state": {
                "hide_name": 0,
                "type": "GENERIC_SLICE",
                "parameters": {"INIT": "1010", "FF_USED": "1"},
                "attributes": {
                    "NEXTPNR_BEL": "X1Y1_SLICE0",
                    "BEL_STRENGTH": "3",
                },
                "port_directions": {"I[0]": "input", "Q": "output"},
                "connections": {"I[0]": [10], "Q": [11]},
            },
        },
        "netnames": {
            "state_q": {
                "hide_name": 0,
                "bits": [11],
                "attributes": {"ROUTING": "first physical route"},
            },
        },
    }
    rerouted = deepcopy(module)
    rerouted["settings"] = {"seed": "99", "router": "router1"}
    rerouted["attributes"]["src"] = "another/source.v:9"
    rerouted["cells"]["state"]["attributes"] = {
        "NEXTPNR_BEL": "X20Y12_SLICE15",
        "BEL_STRENGTH": "3",
        "AGRV2K_MCU_ENTRY_ROW": "9",
    }
    rerouted["netnames"]["state_q"]["attributes"]["ROUTING"] = (
        "changed physical route"
    )

    digest = negatives.logical_design_digest(module)
    assert negatives.logical_design_digest(rerouted) == digest

    changed_logic = deepcopy(rerouted)
    changed_logic["cells"]["state"]["parameters"]["INIT"] = "0101"
    assert negatives.logical_design_digest(changed_logic) != digest


def test_known_logical_design_refuses_reroute(monkeypatch):
    module = {"ports": {}, "cells": {}, "netnames": {}}
    digest = negatives.logical_design_digest(module)
    negative = negatives.SiliconNegative("VP-AGM-TEST", "test design")
    monkeypatch.setitem(
        negatives.KNOWN_SILICON_NEGATIVE_DESIGNS, digest, negative
    )

    with pytest.raises(SystemExit, match="rerouted variants") as error:
        negatives.refuse_known_silicon_negative_design(module)
    assert "VP-AGM-TEST" in str(error.value)


def test_prepare_design_checks_logical_negative(monkeypatch, tmp_path):
    module = {"attributes": {}, "ports": {}, "cells": {}, "netnames": {}}
    routed = tmp_path / "routed.json"
    routed.write_text(
        json.dumps({"modules": {"top": module}}), encoding="utf-8"
    )

    def refuse(candidate):
        assert candidate == module
        raise SystemExit("logical negative reached")

    monkeypatch.setattr(
        bitgen, "refuse_known_silicon_negative_design", refuse
    )
    with pytest.raises(SystemExit, match="logical negative reached"):
        bitgen.prepare_design(routed, options_from({}))


def test_build_removes_stale_output_before_logical_refusal(
        monkeypatch, tmp_path):
    output = tmp_path / "image.agm"
    output.write_bytes(b"stale output")

    def refuse(*_args, **_kwargs):
        assert not output.exists()
        raise SystemExit("logical negative reached")

    monkeypatch.setattr(bitgen, "prepare_design", refuse)
    with pytest.raises(SystemExit, match="logical negative reached"):
        bitgen.build(tmp_path / "routed.json", output, environ={})
    assert not output.exists()


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
