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
    "VP-AGM-012",
    "VP-AGM-013",
    "VP-AGM-014",
    "VP-AGM-015",
    "VP-AGM-016",
    "VP-AGM-017",
    "VP-AGM-018",
}

# de6 shared-control lowering silicon witness (2026-08-31): five emits are
# silicon-wrong and fenced (VP-AGM-012); these three emit and are silicon-correct
# and must NEVER be fenced.
DE6_SILICON_CORRECT_NOT_FENCED = {
    # (logical_design_digest, image_sha256)
    ("becf120f66861746872270cc60bfa5f1e4cbabf6588df64bd6a1d837bfb45480",
     "99be7039cb7388d2eb89e1c8637c10f701fb84b06c94ab5e5aedcf63beee5953"),  # compare_1_2_4_user
    ("28086c97017515687075037514b24dfa31631bfe28e7223293d2cd700e3d8c76",
     "9e987cca6e1a09b6fd2831bceeaeb6028bea0d093402ddccd8eb043e35cd9892"),  # shift8_user
    ("59958ee3cdaa0a14ecc54e7785613c8d50b1373255f1d58e38c42d7c133caba8",
     "58134b2d86818cf51d300e0286e06249d318e6ed613eae3421881c9a4a556847"),  # util10_user
}


def test_registry_is_exact_and_covers_each_open_escape_defect():
    assert len(negatives.KNOWN_SILICON_NEGATIVE_IMAGES) == 43
    assert {
        item.defect for item in negatives.KNOWN_SILICON_NEGATIVE_IMAGES.values()
    } == OPEN_DEFECTS | {"VP-AGM-019", "VP-GPT6-001", "VP-GPT6-002"}
    assert all(
        len(digest) == 64 and set(digest) <= set(string.hexdigits.lower())
        for digest in negatives.KNOWN_SILICON_NEGATIVE_IMAGES
    )


def test_logical_design_registry_is_narrow_and_covers_retained_graphs():
    assert negatives.LOGICAL_DESIGN_DIGEST_SCHEMA == 1
    assert negatives.logical_design_digest(
        {"ports": {}, "cells": {}, "netnames": {}}
    ) == "b79840e1a78c0302c679a29b65512f3e20dfafe5a76f60a0824fa03861be8d37"
    assert len(negatives.KNOWN_SILICON_NEGATIVE_DESIGNS) == 31
    assert {
        item.defect for item in negatives.KNOWN_SILICON_NEGATIVE_DESIGNS.values()
    } == {
        "VP-AGM-001", "VP-AGM-003", "VP-AGM-004", "VP-AGM-005",
        "VP-AGM-008", "VP-AGM-009", "VP-AGM-012", "VP-AGM-013",
        "VP-AGM-014", "VP-AGM-015",
        "VP-AGM-016", "VP-AGM-017",
        "VP-AGM-018", "VP-AGM-019",
    }
    assert all(
        len(digest) == 64 and set(digest) <= set(string.hexdigits.lower())
        for digest in negatives.KNOWN_SILICON_NEGATIVE_DESIGNS
    )


def test_de6_shared_constant_escapes_are_fenced_both_ways():
    """The five silicon-wrong de6 emits (VP-AGM-012) are refused by both registries."""
    fenced = {
        # (logical_design_digest, image_sha256)
        ("091d55a8274b135088e4ce4013ed2a43d670ac0e303acb331ed9bcadae7a3301",
         "818ff992fea304d11fd02ca9ec09d6c1f1edb6550fc75354003bb663a40e4999"),
        ("feb8618c8d8a0aaee93d2f0ae7d753cd7a6f89ce5895037b693105e418dae6ca",
         "9ba3847c9e2170483eefaf71f287d0671a6e40ffe7ca8fea7d430c6bb7e2d02d"),
        ("536d9d0c265b577b9515b56e97bc5c50738d87238f4d56cb2107e6d999b81c8c",
         "fbd0362495b0b1589171ee8774f2e1cb6da05867c37f719767a36a3bcda57f92"),
        ("0bdc08a1dd69ef0c6a06943714918db58ed60179d35a3ccb92d91552dcc900be",
         "f82dda520a9b57b3164f61a2b1fc996c3a480d147f78ee962f0ac2112ae7ffd0"),
        ("1bddb34fd0711a1f07c0ed88670e1c5fef12f42e0e2553d43cc81f929140ba64",
         "b8ab756dba05ff4f678cf70a15ce033164144ab7266407bf380d2ff3d725226a"),
    }
    for design_digest, image_digest in fenced:
        assert negatives.KNOWN_SILICON_NEGATIVE_DESIGNS[design_digest].defect == "VP-AGM-012"
        assert negatives.KNOWN_SILICON_NEGATIVE_IMAGES[image_digest].defect == "VP-AGM-012"


def test_de6_silicon_correct_emits_are_not_fenced():
    """compare_1_2_4/shift8/util10 emit and PASS on silicon; they must not be fenced."""
    for design_digest, image_digest in DE6_SILICON_CORRECT_NOT_FENCED:
        assert design_digest not in negatives.KNOWN_SILICON_NEGATIVE_DESIGNS
        assert image_digest not in negatives.KNOWN_SILICON_NEGATIVE_IMAGES
        # And the refusal helpers stay silent (no SystemExit) for them.
        negatives.refuse_known_silicon_negative_digest(image_digest)


def test_known_digest_refuses_and_unknown_digest_passes():
    digest, negative = next(iter(negatives.KNOWN_SILICON_NEGATIVE_IMAGES.items()))
    with pytest.raises(SystemExit, match=negative.defect) as error:
        negatives.refuse_known_silicon_negative_digest(digest.upper())
    assert digest.upper() in str(error.value)

    negatives.refuse_known_silicon_negative_digest("0" * 64)


def test_waitstate_carry_negative_does_not_fence_working_lut_carry_image():
    with pytest.raises(SystemExit, match="VP-GPT6-001"):
        negatives.refuse_known_silicon_negative_digest(
            "73c9826375b7c3261e52e766f9793e457350402d143406dc8de1e66d78b3bf2c")
    negatives.refuse_known_silicon_negative_digest(
        "ca34e4abb2285d56e1d4a0d33a60bf8424ec43d0efa311cef025c38cd19dc4db")


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
    routed = tmp_path / "routed.json"
    routed.write_text(json.dumps({"modules": {"top": {
        "attributes": {"top": 1}, "cells": {}, "netnames": {},
    }}}), encoding="utf-8")

    def refuse(*_args, **_kwargs):
        assert not output.exists()
        raise SystemExit("logical negative reached")

    monkeypatch.setattr(bitgen, "prepare_design", refuse)
    with pytest.raises(SystemExit, match="logical negative reached"):
        bitgen.build(routed, output, environ={})
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
