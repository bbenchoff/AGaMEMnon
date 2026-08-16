"""User-facing docs must not drift back to a superseded claim.

Two claims in this repo have been corrected after silicon, and both are the kind
that a later edit reverts by accident because the older sentence reads more
cautious:

  * the qualified top-edge output surface grew from two pads to all ten decimal
    L48 leads PIN_10 through PIN_19 -- older exact counts are
    wrong, not conservative;
  * PACKEDMODE stopped being a bounded null. It was null in the read-only
    oracle and has measured first-order behaviour in the write-path and
    dual-port oracles, so "no behavioural measurement" is now wrong too.

These tests read the docs as text and fail on the stale phrasings. They
deliberately do NOT assert the positive claims in prose -- the chipdb table and
the evidence ledgers are the source of truth for those, and are checked
elsewhere. The point here is only to stop a regression in the human-readable
surface.

They also pin the things that must stay UNCLAIMED: the ten-pad ring, a
PACKEDMODE mechanism, a CLKMODE characterization, and generic BRAM writes.
The exact X13Y4 x2 OLD-mode write composition is now silicon-qualified; that
bounded result must not be widened to other widths, sites, modes, clocks,
byte enables, or collision behaviour.
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
    "exactly three top-edge",
    "exactly three TOP-edge",
    "three top-edge pads",
    "three TOP-edge ring pads",
    "the other seven top pads",
    "exactly four top-edge",
    "exactly four TOP-edge",
    "four top-edge pads",
    "four TOP-edge ring pads",
    "the other six top pads",
    "exactly five top-edge",
    "exactly five TOP-edge",
    "five top-edge pads",
    "five TOP-edge ring pads",
    "the other five top pads",
    "exactly six top-edge",
    "exactly six TOP-edge",
    "six top-edge pads",
    "six TOP-edge ring pads",
    "the other four top pads",
    "exactly seven top-edge",
    "exactly seven TOP-edge",
    "seven top-edge pads",
    "seven TOP-edge ring pads",
    "the other three top pads",
    "exactly eight top-edge",
    "exactly eight TOP-edge",
    "eight top-edge pads",
    "eight TOP-edge ring pads",
    "the other two top pads",
    "exactly nine top-edge",
    "exactly nine TOP-edge",
    "nine top-edge pads",
    "nine TOP-edge ring pads",
    "the other top pad",
]

STALE_BRAM_PHRASES = [
    "only `PORTA_OUTREG` has any behavioural measurement",
    "Port-B output-register behaviour is still open",
    "`PORTB_OUTREG` is not validated",
    "`PACKEDMODE`/`CLKMODE` returned a bounded null in that same read-only",
    "`PACKEDMODE`, `CLKMODE`) have only a bounded null",
    "PACKEDMODE has no behavioural measurement",
    "PACKEDMODE has no behavioral measurement",
]

# Claims that must NEVER appear. The ring is not qualified, PACKEDMODE's
# mechanism is unresolved, CLKMODE is bounded rather than characterized, and the
# only one exact BRAM write composition is qualified.
FORBIDDEN = [
    (r"PACKEDMODE (?:splits|repartitions|switches) the array",
     "no PACKEDMODE mechanism is claimed"),
    (r"CLKMODE is (?:fully )?characterized", "CLKMODE is a bounded null, not characterized"),
    (r"(?:generic|all|arbitrary) BRAM writes? (?:are|is) (?:now )?qualified",
     "only the exact X13Y4 x2 OLD-mode write composition is qualified"),
    (r"BRAM writes? (?:are|is) fully qualified",
     "only the exact X13Y4 x2 OLD-mode write composition is qualified"),
    (r"(?:arbitrary|general|fully qualified) 16-bit (?:AHB )?register bank",
     "only one exact waited 16-bit scratch composition is qualified"),
]


def pages_containing(needle):
    hits = []
    for page in PAGES:
        text = page.read_text(encoding="utf-8")
        if needle in text:
            hits.append(page.relative_to(ROOT).as_posix())
    return hits


@pytest.mark.parametrize("phrase", STALE_PAD_PHRASES)
def test_no_page_uses_a_superseded_top_edge_pad_count(phrase):
    hits = pages_containing(phrase)
    assert not hits, (
        "%r appears in %s. All ten decimal L48 top-edge package leads PIN_10 through "
        "PIN_19 are qualified (silicon 2026-08-15, qualification/io_evidence.jsonl "
        "trial pad-pin10-pin11-complete-top-edge-ring-silicon-20260815). "
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
    assert pins == {"PIN_%d" % lead for lead in range(10, 20)}
    ledger = (ROOT / "qualification" / "io_evidence.jsonl").read_text(encoding="utf-8")
    for pin in pins:
        assert pin in ledger, "%s is in the qualified table with no ledger record" % pin
    assert "pad-pin14-fourth-top-edge-pad-silicon-20260815" in ledger
    assert "pad-pin13-fifth-top-edge-pad-silicon-20260815" in ledger
    assert "pad-pin17-sixth-top-edge-pad-silicon-20260815" in ledger
    assert "pad-pin19-seventh-top-edge-pad-silicon-20260815" in ledger
    assert "pad-pin12-eighth-top-edge-pad-silicon-20260815" in ledger
    assert "pad-pin10-pin11-complete-top-edge-ring-silicon-20260815" in ledger


def test_the_waited_sixteen_bit_bank_is_qualified_without_becoming_generic():
    records = [json.loads(line) for line in
               (ROOT / "qualification" / "mcu_ahb_register_bank_evidence.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    record = next((row for row in records if row.get("trial_id") ==
                   "mcu-ahb-register-bank16-external-feedback-waited-silicon-20260815"), None)
    assert record is not None
    assert record["result"] == "pass_retained_16_bit_scratch"
    assert "arbitrary widths" in record["scope"]


def test_the_bram_ledgers_record_the_historical_negative_and_bounded_write_positive():
    records = [json.loads(line) for line in
               (ROOT / "qualification" / "bram_evidence.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    blob = json.dumps(records)
    assert "PORTA_OUTREG" in blob
    assert "PACKEDMODE" in blob
    # The earlier negative remains immutable history.
    assert any("WRITE DID NOT LAND" in json.dumps(r).upper() or
               "write did not land" in json.dumps(r) for r in records), (
        "the BRAM ledger no longer records that the fabric write did not land")
    assert "bram_dual_ctrl" in blob, (
        "the emitter-side suspect for the write failure is no longer named")

    portb = next((record for record in records
                  if record.get("trial_id") ==
                  "2026-08-15-bram-portb-outreg-one-clock"), None)
    assert portb is not None, "the bounded Port-B output-register result is missing"
    assert portb["result"] == "pass_portb_outreg_one_clock"
    assert "does not qualify" in portb["consequence"].lower()

    ingress = [json.loads(line) for line in
               (ROOT / "qualification" / "bram_write_ingress_evidence.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    positive = next((record for record in ingress
                     if record.get("trial_id") ==
                     "2026-08-15-bram-x2-old-mode-source-built-write-positive"), None)
    assert positive is not None, "the source-built BRAM write positive is missing"
    assert positive["result"] == "pass_causal_x2_old_mode_write"
    assert "not arbitrary WeA" in positive["consequence"]
