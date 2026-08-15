"""User-facing docs must not drift back to a superseded claim.

Two claims in this repo have been corrected after silicon, and both are the kind
that a later edit reverts by accident because the older sentence reads more
cautious:

  * the qualified top-edge output surface grew from two pads to three (PIN_18,
    PIN_16, PIN_15) -- "exactly two" is now wrong, not conservative;
  * PACKEDMODE stopped being a bounded null. It was null in the read-only
    oracle and has measured first-order behaviour in the write-path and
    dual-port oracles, so "no behavioural measurement" is now wrong too.

These tests read the docs as text and fail on the stale phrasings. They
deliberately do NOT assert the positive claims in prose -- the chipdb table and
the evidence ledgers are the source of truth for those, and are checked
elsewhere. The point here is only to stop a regression in the human-readable
surface.

They also pin the things that must stay UNCLAIMED: the ten-pad ring, a
PACKEDMODE mechanism, a CLKMODE characterization, and a landed BRAM write.
"""

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
# Every user-facing surface. Generated pages are included on purpose: if a
# generator's source drifts, the generated page drifts with it and this catches
# it either way.
PAGES = sorted(
    [ROOT / "README.md", ROOT / "ROADMAP.md"]
    + [path for path in (ROOT / "docs").glob("*.md")]
)

# Eight of the eleven phrases below were genuinely present in the tree before the
# 2026-08-15 closure pass removed them, so those eight are proven to catch a real
# regression. Three ("exactly two TOP-edge", and the two "no behavioural
# measurement" spellings) never appeared and are forward guards only.
STALE_PAD_PHRASES = [
    "exactly two top-edge",
    "exactly two TOP-edge",
    "two top-edge pads",
    "two TOP-edge ring pads",
    "PIN_18 and PIN_16 only",
    "the other eight top pads",
]

STALE_BRAM_PHRASES = [
    "only `PORTA_OUTREG` has any behavioural measurement",
    "`PACKEDMODE`/`CLKMODE` returned a bounded null in that same read-only",
    "`PACKEDMODE`, `CLKMODE`) have only a bounded null",
    "PACKEDMODE has no behavioural measurement",
    "PACKEDMODE has no behavioral measurement",
]

# Claims that must NEVER appear. The ring is not qualified, PACKEDMODE's
# mechanism is unresolved, CLKMODE is bounded rather than characterized, and the
# fabric write did not land.
FORBIDDEN = [
    (r"ten-pad ring is (?:now )?qualified", "the ten-pad ring is not qualified"),
    (r"all ten top(?:-| )edge pads are qualified", "the ten-pad ring is not qualified"),
    (r"PACKEDMODE (?:splits|repartitions|switches) the array",
     "no PACKEDMODE mechanism is claimed"),
    (r"CLKMODE is (?:fully )?characterized", "CLKMODE is a bounded null, not characterized"),
    (r"(?:fabric |BRAM )?write (?:path )?(?:is )?(?:now )?qualified",
     "the fabric write did not land"),
]


def pages_containing(needle):
    hits = []
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        if needle in text:
            hits.append(page.relative_to(ROOT).as_posix())
    return hits


@pytest.mark.parametrize("phrase", STALE_PAD_PHRASES)
def test_no_page_says_the_top_edge_surface_is_two_pads(phrase):
    hits = pages_containing(phrase)
    assert not hits, (
        "%r appears in %s. Three top-edge pads are qualified -- PIN_18, PIN_16 "
        "and PIN_15 (silicon 2026-08-15, qualification/io_evidence.jsonl trial "
        "pad-pin15-third-top-edge-pad-silicon-20260815) -- and the other seven "
        "are unqualified." % (phrase, ", ".join(hits))
    )


@pytest.mark.parametrize("phrase", STALE_BRAM_PHRASES)
def test_no_page_says_packedmode_has_no_measurement(phrase):
    hits = pages_containing(phrase)
    assert not hits, (
        "%r appears in %s. PACKEDMODE was a bounded null in the read-only oracle "
        "but has measured first-order behaviour in the write-path and dual-port "
        "oracles (bram_evidence.jsonl trial "
        "bram-write-and-dualport-oracle-silicon-20260815). Its MECHANISM is still "
        "unclaimed -- say that instead." % (phrase, ", ".join(hits))
    )


@pytest.mark.parametrize("pattern,why", FORBIDDEN)
def test_no_page_overclaims(pattern, why):
    rule = re.compile(pattern, re.IGNORECASE)
    hits = []
    for page in PAGES:
        for lineno, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if rule.search(line):
                hits.append("%s:%d" % (page.relative_to(ROOT).as_posix(), lineno))
    assert not hits, "%s (%s)" % (", ".join(hits), why)


def test_the_qualified_pad_table_and_the_evidence_ledger_agree():
    """The table is the source of truth; the ledger must have witnessed each row."""
    import csv

    table = list(csv.DictReader(
        (ROOT / "agamemnon" / "chipdb" / "pad_output_qualified_L48.csv")
        .open(newline="", encoding="utf-8")))
    pins = {row["pin"] for row in table}
    assert pins == {"PIN_18", "PIN_16", "PIN_15"}
    ledger = (ROOT / "qualification" / "io_evidence.jsonl").read_text(encoding="utf-8")
    for pin in pins:
        assert pin in ledger, "%s is in the qualified table with no ledger record" % pin


def test_the_bram_ledger_records_both_measured_fields_and_no_write():
    records = [json.loads(line) for line in
               (ROOT / "qualification" / "bram_evidence.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    blob = json.dumps(records)
    assert "PORTA_OUTREG" in blob
    assert "PACKEDMODE" in blob
    # The write result must stay recorded as not-landed, and as unresolved
    # between silicon and emitter.
    assert any("WRITE DID NOT LAND" in json.dumps(r).upper() or
               "write did not land" in json.dumps(r) for r in records), (
        "the BRAM ledger no longer records that the fabric write did not land")
    assert "bram_dual_ctrl" in blob, (
        "the emitter-side suspect for the write failure is no longer named")
