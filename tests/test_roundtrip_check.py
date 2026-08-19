"""Round-trip equivalence regression: pack every retained routed netlist to a
bitstream, decode the bitstream back, and diff the reconstruction against
what the routed JSON asked for.

READ ``tools/roundtrip_check.py``'s module docstring FIRST. Summary: LUT-init
bits, image CRC-32/BZIP2, and the LZW compressed-sidecar round trip are
INDEPENDENT of the encoder's chipdb tables and really do catch encoder/
pipeline bugs, not just table bugs. The "mux group presence" check SHARES
the same physical-bit tables the encoder consults (``pips_full.csv``,
``pips_mcuedge.csv``, both via ``agamemnon.engine.agasc``) and therefore only
proves self-consistency, not silicon correctness -- a green result here does
NOT mean the general fabric interconnect is wired to the physically correct
pin. Only an independent oracle (silicon readback) can prove that; see the
vendor RE workbench (``../AG32-Docs``).

As of 2026-08-18 the round trip is clean across all 58 retained
``qualification/pack_regression.json`` artifacts (0 mismatches). Building
this tool surfaced -- and fixed IN THE TOOL, not the encoder -- two
false-positive classes documented in ``tools/roundtrip_check.py``'s module
docstring: pad-feed nets (an RMUX destination that feeds an IOMUX/pad
resolves through a vendor-harvested codeword table that can legitimately
land bits on a different tile) and clock-tree SeamMUX (encoded as a single
fixed-constant ``CFG_SEAMMUX`` cell by ``features/clocks.py``, decoupled from
the literal instance index a clock net's ``ROUTING`` attribute names).

This test is therefore NOT marked xfail/skip, per the "only write a failing
test if the corpus is currently clean" instruction. If it starts failing:
first work out whether the mismatch is a genuine encoder bug or a new
instance of one of the tool-level false-positive classes above (or a third
one) before concluding anything is broken in the encoder -- but do not
silence a real mismatch by reflexively widening the tool's exclusions, and
do not mark this xfail just to make a real regression go quiet.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT, ROOT / "tools"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import roundtrip_check as RTC  # noqa: E402

ARTIFACTS = RTC.load_manifest()


def test_roundtrip_manifest_is_not_empty():
    """Guard against a silently-empty corpus making every parametrized case
    below vacuously pass."""
    assert len(ARTIFACTS) >= 50


@pytest.mark.parametrize("artifact", ARTIFACTS, ids=lambda item: Path(item["routed"]).name)
def test_roundtrip_artifact_is_consistent(artifact, tmp_path):
    report = RTC.check_artifact(artifact, tmp_path)
    assert report["pack_ok"], report.get("pack_error", "pack failed")
    assert report["bitstream_sha256_match"], (
        "packed bitstream no longer matches the pinned hash in "
        "qualification/pack_regression.json for %s" % artifact["routed"]
    )
    assert report["compared"] > 0, (
        "round trip compared nothing for %s -- tool regression, not a clean pass"
        % artifact["routed"]
    )
    assert report["mismatched"] == 0, (
        "round-trip mismatch(es) for %s:\n%s"
        % (artifact["routed"], json.dumps(report["mismatches"], indent=2))
    )
