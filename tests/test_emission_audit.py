"""Emission audit: does the image contain the route the router produced?

Validated in the workbench against three real artifacts -- two faithfully
emitted images (both 0 MISSING, 0 MALFORMED) and one deliberately corrupted
image (6 MISSING, naming the hijacked node). Those are 100 KB binaries and do not
belong in this repo, so the properties they established are pinned here against
synthetic images built from the real chipdb.
"""
import json
import os
import pathlib

import pytest

from agamemnon.engine import emission_audit

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHIPDB = ROOT / "agamemnon" / "chipdb"
IMAGE_BYTES = 99944


@pytest.fixture(scope="module")
def nodes():
    return emission_audit.node_bits(CHIPDB)


def _blank():
    return bytearray(IMAGE_BYTES)


def _write(image, nodes, key, codeword):
    for sel, (byte, mask) in nodes[key].items():
        if sel in codeword:
            image[byte] |= mask
        else:
            image[byte] &= ~mask


def test_node_bits_cover_the_fabric(nodes):
    assert len(nodes) > 10000
    sizes = {len(v) for k, v in nodes.items() if k[2] == "RMUX"}
    # Not every RMUX node populates all ten slots -- border and edge tiles carry
    # 6 or 8. The invariant that matters is that none EXCEEDS the codeword space,
    # because a node with more than ten slots would mean the grouping is wrong.
    assert sizes <= {6, 8, 10}, sizes
    counts = [len(v) for k, v in nodes.items() if k[2] == "RMUX"]
    assert counts.count(10) > len(counts) // 2, "most RMUX nodes should be full"


def test_faithful_image_passes_with_zero_findings(nodes):
    """The property that makes this shippable: blast radius zero on a faithful image."""
    key = (15, 7, "RMUX", 27)
    src = (15, 8, "RMUX", 80)
    image = _blank()
    _write(image, nodes, key, (3, 9))
    clean = {(15, 7, "RMUX", 27, "RMUX", 15, 8, 80): (3, 9)}
    missing, unresolvable, malformed = emission_audit.audit(
        image, {(src, key)}, nodes, clean, {}, tiles={(15, 7)})
    assert missing == []
    assert malformed == []
    assert unresolvable == []


def test_wrong_codeword_is_reported_missing(nodes):
    key = (15, 7, "RMUX", 27)
    src = (15, 8, "RMUX", 80)
    image = _blank()
    _write(image, nodes, key, (4, 9))          # router asked for (3, 9)
    clean = {(15, 7, "RMUX", 27, "RMUX", 15, 8, 80): (3, 9)}
    missing, _, _ = emission_audit.audit(
        image, {(src, key)}, nodes, clean, {}, tiles={(15, 7)})
    assert len(missing) == 1
    assert missing[0][2] == (4, 9) and missing[0][3] == [(3, 9)]


def test_hijacked_node_is_reported(nodes):
    """The real negative control: a wire re-pointed away from the net that owns it.

    This is the silently-wrong-image class -- well-formed, CRC-valid, and every
    structural check passes. The audit must name the VICTIM net.
    """
    key = (15, 4, "RMUX", 43)
    owner = (15, 3, "RMUX", 32)
    image = _blank()
    _write(image, nodes, key, (6, 9))          # hijacker's codeword
    clean = {(15, 4, "RMUX", 43, "RMUX", 15, 3, 32): (6, 8)}
    missing, _, _ = emission_audit.audit(
        image, {(owner, key)}, nodes, clean, {}, tiles={(15, 4)})
    assert len(missing) == 1
    assert missing[0][0] == key and missing[0][2] == (6, 9)


def test_relative_key_sign_is_dst_minus_src():
    """A sign inversion here returns a PLAUSIBLE WRONG codeword, not a miss.

    The tile-relative table holds both signs for symmetric displacements, so
    `src - dst` silently resolves to a different real codeword. That single error
    made ~2% of routed pips read as emission defects in faithful images.
    """
    dst = (12, 4, "RMUX", 33)
    src = (11, 4, "RMUX", 8)
    relative = {("RMUX", 33, "RMUX", 8, 1, 0): (2, 8),    # dst - src
                ("RMUX", 33, "RMUX", 8, -1, 0): (1, 8)}   # the inverted trap
    assert emission_audit.expected_codeword(src, dst, {}, relative) == (2, 8)


def test_unresolvable_edges_are_not_counted_as_failures(nodes):
    """Refusing over an edge the tables cannot adjudicate would be inferring."""
    key = (15, 7, "RMUX", 27)
    src = (15, 8, "RMUX", 80)
    missing, unresolvable, _ = emission_audit.audit(
        _blank(), {(src, key)}, nodes, {}, {}, tiles={(15, 7)})
    assert missing == []
    assert len(unresolvable) == 1


def test_malformed_codeword_is_reported(nodes):
    key = (15, 7, "RMUX", 27)
    image = _blank()
    _write(image, nodes, key, (1, 3, 5))       # 3-hot: selects something undefined
    _, _, malformed = emission_audit.audit(
        image, set(), nodes, {}, {}, tiles={(15, 7)})
    assert len(malformed) == 1
    assert malformed[0][0] == key


def test_audit_is_off_by_default(monkeypatch):
    monkeypatch.delenv("AGAMEMNON_VERIFY_EMISSION", raising=False)
    assert not emission_audit.enabled()
    monkeypatch.setenv("AGAMEMNON_VERIFY_EMISSION", "1")
    assert emission_audit.enabled()


def test_logic_tiles_closed_form_is_the_132():
    """The scope is derived, not a magic list.

    Scoping by slot-count instead gives 17 MISSING and 32 MALFORMED on a
    faithfully-emitted image where this scope gives 0 and 0 -- nearly every node
    has the full slot count, so it does not discriminate.
    """
    tiles = emission_audit.logic_tiles()
    assert len(tiles) == 132
    # rows 1-4 are full width minus the BRAM column; rows 5-12 are the right block
    assert (13, 2) not in tiles, "x=13 is the BRAM column, not a LogicTile"
    assert (0, 2) not in tiles and (22, 2) not in tiles, "IO borders are not LogicTiles"
    assert (1, 4) in tiles and (20, 12) in tiles
    assert (1, 5) not in tiles, "rows 5-12 do not extend to the left block"


def test_routed_pips_parses_node_pairs(tmp_path):
    routed = tmp_path / "r.json"
    routed.write_text(json.dumps({"nets": [
        "X15Y8_RMUX80;X15Y8_RMUX80.X15Y7_RMUX27;1;X15Y7_RMUX27;padding-to-length"]}),
        encoding="utf-8")
    pips = emission_audit.routed_pips(routed)
    assert ((15, 8, "RMUX", 80), (15, 7, "RMUX", 27)) in pips


def test_audit_is_off_unless_requested(monkeypatch):
    """A gate that runs by surprise is not opt-in."""
    monkeypatch.delenv("AGAMEMNON_VERIFY_EMISSION", raising=False)
    assert not emission_audit.enabled()
