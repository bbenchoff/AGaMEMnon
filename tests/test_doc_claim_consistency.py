"""User-facing docs must not drift back to a superseded claim.

Three claims in this repo have been corrected after silicon, and all are the kind
that a later edit reverts by accident because the older sentence reads more
cautious:

  * the qualified top-edge output surface grew from two pads to all ten decimal
    L48 leads PIN_10 through PIN_19 -- older exact counts are
    wrong, not conservative;
  * PACKEDMODE stopped being a bounded null. It was null in the read-only
    oracle and has measured first-order behaviour in the write-path and
    dual-port oracles, so "no behavioural measurement" is now wrong too.
  * the release status-overlay path now accepts one independently routed,
    synchronous pure-fabric scalar. The generic multi-bit/CDC/interrupt and
    arbitrary-fit cases remain open, but "no generic socket" is stale.

These tests read the docs as text and fail on the stale phrasings. They
deliberately do NOT assert the positive claims in prose -- the chipdb table and
the evidence ledgers are the source of truth for those, and are checked
elsewhere. The point here is only to stop a regression in the human-readable
surface.

They also pin the things that must stay UNCLAIMED: a PACKEDMODE mechanism, a
CLKMODE characterization, and hard-BRAM writes. Direct hard-output controls
superseded the former wrapper-visible X13Y4 x2 write claim.
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

STALE_STATUS_OVERLAY_PHRASES = [
    "a generic application-owned STATUS_SET socket",
    "a generic application-owned `STATUS_SET` socket",
    "not yet the generic socket",
]

STALE_BANK16_READ_PHRASES = [
    "Foreign reads still alias +0",
    "foreign reads still alias +0",
    "Its foreign reads deliberately alias +0",
    "16-bit read/full address decode",
    "its reads are not decoded",
]

STALE_BANK16_SUBWORD_PHRASES = [
    "Subword read-lane semantics",
    "subword read-lane semantics",
    "byte-read lane semantics remain",
    "halfword-read lane semantics remain",
]

# Current-facing pages which lagged the public32 promotion even though the
# SDK profile, silicon ledger, and primary MCU docs had moved.  These are
# scoped by page so the immutable public16 evidence can continue describing
# its own narrower boundary honestly.
STALE_PUBLIC32_BY_PAGE = [
    ("CHANGELOG.md", "complete public register-bank profile remains the 8-bit"),
    ("ROADMAP.md", "composition with the public ID/counter/W1C map are still open"),
    ("docs/PERIPHERAL_CATALOG.md", "remains isolated from the public"),
    ("docs/PERIPHERAL_CATALOG.md", "full public-bank integration"),
    ("docs/MCU_AHB_INTERFACE.md", "wider public-bank integration remain"),
    ("docs/MCU_FABRIC_ROADMAP.md", "current 8-bit writable-data boundary"),
    ("docs/DOES_EVERYTHING_ROADMAP.md", "integrate the 16-bit checkpoint into the public bank"),
    ("docs/HAL_FPGA_REFERENCE.md", "Writable state **wider than 8 bits**"),
    ("docs/HAL_FPGA_REFERENCE.md", "32-lane read, grouped write, 8-bit writable bank"),
    ("docs/ARCHITECTURE.md", "wider public-bank integration remain"),
    ("docs/MCU_AHB_REGISTER_BANK.md", "default SDK profile now strictly replays one exact L48 map\nthat composes immutable ID8"),
    ("docs/USAGE.md", "ID8/scratch16/counter3/W1C1 map and rejects any source"),
]

# Claims that must NEVER appear. The ring is not qualified, PACKEDMODE's
# mechanism is unresolved, CLKMODE is bounded rather than characterized, and the
# direct hard-output controls leave BRAM write ingress unqualified.
FORBIDDEN = [
    (r"PACKEDMODE (?:splits|repartitions|switches) the array",
     "no PACKEDMODE mechanism is claimed"),
    (r"CLKMODE is (?:fully )?characterized", "CLKMODE is a bounded null, not characterized"),
    (r"(?:generic|all|arbitrary) BRAM writes? (?:are|is) (?:now )?qualified",
     "no hard-BRAM write is qualified"),
    (r"BRAM writes? (?:are|is) fully qualified",
     "no hard-BRAM write is qualified"),
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


@pytest.mark.parametrize("phrase", STALE_STATUS_OVERLAY_PHRASES)
def test_no_page_reopens_the_qualified_scalar_status_overlay(phrase):
    hits = pages_containing(phrase)
    assert not hits, (
        "%r appears in %s. The release status-overlay qualifies one separately "
        "routed, HCLK-synchronous pure-fabric scalar. Keep multi-bit, CDC, "
        "interrupt integration, reset semantics, reservation-aware placement, "
        "and guaranteed arbitrary-overlay fit open instead."
        % (phrase, ", ".join(hits))
    )


@pytest.mark.parametrize("phrase", STALE_BANK16_READ_PHRASES)
def test_no_page_reopens_the_qualified_bank16_word_read_decode(phrase):
    hits = pages_containing(phrase)
    assert not hits, (
        "%r appears in %s. The exact L48 checkpoint now returns low-16 aligned "
        "word reads at +0/+4/+8/+c as [state,0,0,0]. Keep raw upper lanes, "
        "higher/full-window decode and public-bank "
        "integration open instead." % (phrase, ", ".join(hits))
    )


@pytest.mark.parametrize("phrase", STALE_BANK16_SUBWORD_PHRASES)
def test_no_page_reopens_the_qualified_bank16_cpu_subword_reads(phrase):
    hits = pages_containing(phrase)
    assert not hits, (
        "%r appears in %s. The exact L48 checkpoint now qualifies aligned "
        "unsigned LBU/LHU lane selection and zero extension. Keep misaligned "
        "and signed loads plus raw HRDATA[31:16] behavior open instead." %
        (phrase, ", ".join(hits))
    )


@pytest.mark.parametrize("page,phrase", STALE_PUBLIC32_BY_PAGE)
def test_current_pages_do_not_revert_to_the_public16_frontier(page, phrase):
    text = (ROOT / page).read_text(encoding="utf-8")
    assert phrase not in text, (
        "%r in %s predates the exact public32 promotion. The default pinned "
        "L48 profile now returns canonical ID32 0x4147414d and zero-extended "
        "scratch16/counter3/W1C1; keep generic generation, production "
        "status-set ingress, full-window decode, and portability open instead."
        % (phrase, page)
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


def test_current_conduction_count_is_derived_from_the_production_gate():
    """A row promotion must update every current-facing count in the same commit."""
    import csv

    dead_rows = list(csv.DictReader(
        (ROOT / "agamemnon" / "chipdb" / "dead_edges_silicon.csv")
        .open(newline="", encoding="utf-8")))
    original = 14
    blocked = len(dead_rows)
    admitted = original - blocked
    assert (admitted, blocked) == (10, 4)

    expected = ("Current production count: %d of %d admitted; %d "
                "conservatively blocked as unverified" %
                (admitted, original, blocked))
    for relative in (
        "docs/STATUS.md",
        "docs/VENDOR_PARITY.md",
        "docs/ARCHITECTURE.md",
        "docs/CONDUCTION_REFRAME_STATUS.md",
        "docs/FPGA_PARITY_LEDGER.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8").replace("\n", " ")
        assert expected in text, "%s does not reflect dead_edges_silicon.csv" % relative

    evidence = [json.loads(line) for line in
                (ROOT / "qualification" / "conduction_ungate_evidence.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
    by_edge = {record.get("edge"): record for record in evidence if record.get("edge")}
    for edge in (
        "RMUX26@15,4->RMUX09@14,4",
        "RMUX33@15,4->RMUX39@14,4",
        "RMUX80@15,7->RMUX33@15,4",
        "RMUX21@14,8->RMUX87@14,5",
    ):
        assert edge in by_edge and by_edge[edge]["result"] == "pass"
        assert edge not in {row["edge"] for row in dead_rows}


def test_pin12_input_claim_stays_bounded_to_the_measured_composition():
    records = [json.loads(line) for line in
               (ROOT / "qualification" / "left_input_evidence.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    record = next((row for row in records if row.get("trial_id") ==
                   "top-input-pin12-direct-inversion-silicon-20260816"), None)
    assert record is not None and record["result"] == "pass"
    assert record["target_bel"] == "X19Y12_SLICE2"
    assert record["target_pin"] == 2
    assert "13/13 data PIPs mapped" in record["selector_policy"]
    assert "fanout" in record["scope"] and "registered capture" in record["scope"]

    bounded = "PIN_12 is qualified only as a scalar single-consumer direct combinational input"
    for relative in ("docs/STATUS.md", "docs/FPGA_PARITY_LEDGER.md"):
        assert bounded in (ROOT / relative).read_text(encoding="utf-8")


def test_the_waited_sixteen_bit_bank_is_qualified_without_becoming_generic():
    records = [json.loads(line) for line in
               (ROOT / "qualification" / "mcu_ahb_register_bank_evidence.jsonl")
               .read_text(encoding="utf-8").splitlines() if line.strip()]
    record = next((row for row in records if row.get("trial_id") ==
                   "mcu-ahb-register-bank16-external-feedback-waited-silicon-20260815"), None)
    assert record is not None
    assert record["result"] == "pass_retained_16_bit_scratch"
    assert "arbitrary widths" in record["scope"]

    word_byte = next((row for row in
                      (json.loads(line) for line in
                       (ROOT / "qualification" /
                        "mcu_ahb_bank16_write_isolation_evidence.jsonl")
                       .read_text(encoding="utf-8").splitlines() if line.strip())
                      if row.get("trial_id") ==
                      "mcu-ahb-register-bank16-word-byte-waited-silicon-20260815"),
                     None)
    assert word_byte is not None
    assert word_byte["result"] == "pass_exact_16_bit_word_and_byte_semantics"
    assert "Halfword transfers were deliberately not tested" in word_byte["scope"]
    assert "not a generic 16-bit register-bank claim" in word_byte["consequence"]

    halfword = json.loads((ROOT / "qualification" /
                           "mcu_ahb_bank16_halfword_evidence.jsonl")
                          .read_text(encoding="utf-8").strip())
    assert halfword["result"] == \
        "pass_exact_16_bit_aligned_word_byte_halfword_semantics"
    assert "Misaligned transfers" in halfword["scope"]
    assert "foreign reads return zero" in halfword["next_experiment"]
    assert "not a generic 16-bit register-bank claim" in halfword["consequence"]

    read_records = [json.loads(line) for line in
                    (ROOT / "qualification" /
                     "mcu_ahb_bank16_read_isolation_evidence.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line.strip()]
    read_isolation = next(row for row in read_records if row["trial_id"] ==
                          "mcu-ahb-register-bank16-read-word0-isolation-silicon-20260815")
    assert read_isolation["result"] == \
        "pass_exact_16_bit_read_word_offset_isolation"
    assert "[offset +0,+4,+8,+c] = [state,0,0,0]" in \
        read_isolation["causal_controls"]
    assert "byte-read lane semantics" in read_isolation["scope"]
    assert "halfword-read lane semantics" in read_isolation["scope"]
    assert "pinned checkpoint" in read_isolation["consequence"]

    subword_read = next(row for row in read_records if row["trial_id"] ==
                        "mcu-ahb-register-bank16-cpu-subword-read-silicon-20260815")
    assert subword_read["result"] == \
        "pass_exact_16_bit_cpu_visible_aligned_subword_reads"
    assert "Three SRAM-only hardware runs" in subword_read["observed"]
    assert "raw HRDATA[31:16]" in subword_read["scope"]
    assert "misaligned halfword loads" in subword_read["scope"]

    plus4 = next(row for row in read_records if row["trial_id"] ==
                 "mcu-ahb-register-bank16-public-scratch4-silicon-20260815")
    assert plus4["result"] == \
        "pass_exact_16_bit_plus4_rebased_scratch_semantics"
    assert plus4["runs"] == 3
    assert "public ID/counter/W1C coexistence" in plus4["scope"]
    assert "not a 16-bit public bank" in plus4["consequence"]


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
        "the immutable BRAM ledger lost the historical no-write experiment")
    assert "bram_dual_ctrl" in blob, (
        "the immutable BRAM ledger lost the historical TMUX13 hypothesis")

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
    assert "emulate_read_first" in positive["root_cause"]
    assert "not arbitrary WeA" in positive["consequence"]
    correction = next((record for record in ingress
                       if record.get("trial_id") ==
                       "2026-08-16-bram-x2-direct-hard-readback-refutes-write-positive"), None)
    assert correction is not None, "the false wrapper-visible write claim is not superseded"
    assert correction["supersedes"] == positive["trial_id"]
    assert correction["result"] == "refute_wrapper_visible_write_as_hard_bram_write"
    assert "No source-built hard-BRAM write is qualified" in correction["consequence"]
