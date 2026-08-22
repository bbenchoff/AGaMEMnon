"""Unit tests for the G10 escalation-ladder attempt logging + cross-attempt summariser
(agamemnon/engine/attempt_ladder.py).

Pure-Python: no nextpnr, no yosys, no board, no real device database, no build. Every test feeds
synthetic ``AttemptRecord``s (or writes them via ``write_attempt_log``) built directly from
hand-written log strings that mimic real nextpnr/router2 output.
"""
import os

from agamemnon.engine import attempt_ladder as A


def _rec(index, cap, seed, fanout, outcome, log):
    return A.AttemptRecord(index, cap, seed, fanout, outcome, log)


def _arc_log(net, src="X15Y9_OMUX14", dst="X0Y5_SinkMUXPseudo199"):
    return ("Info: Packing constants..\nInfo: Routing..\n"
            "ERROR: Failed to route arc 1.0 of net '%s', from %s to %s.\n"
            "ERROR: place&route failed\n" % (net, src, dst))


ROUTED_OK_LOG = "Info: Routing..\nInfo: Routing complete.\nInfo: Max frequency ...\n"


# ---------------------------------------------------------------------------------------------
# attempt_filename / attempt_header / write_attempt_log
# ---------------------------------------------------------------------------------------------

def test_attempt_filename_is_predictable_and_greppable():
    r = _rec(7, 8, "7", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]"))
    assert A.attempt_filename(r) == "attempt_07_cap8_seed7_maxfooff.log"


def test_attempt_filename_encodes_a_real_fanout_value():
    r = _rec(12, 8, "4", 16, A.NOT_ROUTED, _arc_log("dut.beat[0]"))
    assert A.attempt_filename(r) == "attempt_12_cap8_seed4_maxfo16.log"


def test_attempt_header_records_cap_seed_fanout_and_outcome():
    r = _rec(1, 2, "4", 0, A.SUCCESS, ROUTED_OK_LOG)
    header = A.attempt_header(r)
    assert "attempt 1" in header
    assert "cap=2" in header
    assert "seed=4" in header
    assert "fanout=off" in header
    assert "outcome=ROUTED" in header


def test_write_attempt_log_writes_header_then_full_log(tmp_path):
    log_text = _arc_log("s_hreadyout")
    r = _rec(3, 4, "2", 0, A.NOT_ROUTED, log_text)
    path = A.write_attempt_log(str(tmp_path), r)
    assert path == os.path.join(str(tmp_path), "attempt_03_cap4_seed2_maxfooff.log")
    contents = open(path, encoding="utf-8").read()
    assert contents.startswith("# attempt 3 cap=4 seed=2 fanout=off outcome=NOT_ROUTED\n")
    assert log_text in contents


def test_write_attempt_log_creates_the_directory(tmp_path):
    target = tmp_path / "nested" / "attempts"
    r = _rec(1, 2, "4", 0, A.SUCCESS, ROUTED_OK_LOG)
    path = A.write_attempt_log(str(target), r)
    assert os.path.isfile(path)


def test_write_attempt_log_does_not_raise_when_the_path_is_unwritable(tmp_path):
    # Point the "directory" at an existing FILE so os.makedirs/open both fail -- this must
    # degrade to a warning + None, never an exception (a diagnostic aid must not break the build).
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    r = _rec(1, 2, "4", 0, A.SUCCESS, ROUTED_OK_LOG)
    result = A.write_attempt_log(str(blocker), r)
    assert result is None


# ---------------------------------------------------------------------------------------------
# summarize_ladder / format_ladder_summary -- edge cases the task explicitly calls out
# ---------------------------------------------------------------------------------------------

def test_zero_attempts_does_not_crash():
    summary = A.summarize_ladder([])
    assert summary is None
    assert A.format_ladder_summary(summary) is None


def test_single_successful_attempt_does_not_crash_and_summarises_to_nothing():
    r = _rec(1, 4, "4", 0, A.SUCCESS, ROUTED_OK_LOG)
    summary = A.summarize_ladder([r])
    assert summary is not None
    assert summary.total == 1
    assert summary.succeeded is True
    assert summary.success_index == 1
    assert summary.representative is None
    # A lone success is not a ladder failure to report on.
    assert A.format_ladder_summary(summary) is None


def test_single_failing_attempt_reports_plainly_not_as_a_distribution():
    r = _rec(1, 4, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]"))
    summary = A.summarize_ladder([r])
    assert summary.total == 1
    assert summary.succeeded is False
    assert summary.representative is r
    text = A.format_ladder_summary(summary)
    assert text is not None
    assert "1 attempt ran" in text
    # Must not claim a recurring signature from a single data point.
    assert "recur" not in text.lower() or "not enough attempts" in text.lower()
    assert "not enough attempts" in text


# ---------------------------------------------------------------------------------------------
# the core case: a recurring signature across several failing attempts
# ---------------------------------------------------------------------------------------------

def test_counts_an_identical_recurring_signature_across_attempts():
    records = [
        _rec(1, 2, "4", 0, A.NOT_ROUTED, _arc_log("s_hreadyout")),
        _rec(2, 4, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(3, 8, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(4, 8, "2", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
    ]
    summary = A.summarize_ladder(records)
    assert summary.total == 4
    assert summary.succeeded is False
    assert summary.all_distinct is False
    # most common first
    top_sig, top_count = summary.signature_counts[0]
    assert top_sig.kind == "ARC_FAILURE"
    assert top_sig.key == "s_hwdata[2]"
    assert top_count == 3
    assert summary.signature_attempts[top_sig] == [2, 3, 4]
    other_sig, other_count = summary.signature_counts[1]
    assert other_sig.key == "s_hreadyout"
    assert other_count == 1


def test_representative_is_the_last_attempt_bearing_the_recurring_signature():
    records = [
        _rec(1, 2, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(2, 4, "4", 0, A.NOT_ROUTED, _arc_log("dut.beat[0]")),
        _rec(3, 8, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
    ]
    summary = A.summarize_ladder(records)
    assert summary.representative.index == 3
    assert summary.representative.cap == 8


def test_format_ladder_summary_names_the_recurring_arc_and_attempt_counts(tmp_path):
    records = [
        _rec(1, 2, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(2, 4, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(3, 8, "4", 0, A.NOT_ROUTED, _arc_log("dut.beat[0]")),
    ]
    summary = A.summarize_ladder(records)
    text = A.format_ladder_summary(summary, attempts_dir=str(tmp_path))
    assert "3 attempts" in text
    assert "s_hwdata[2]" in text
    assert "2x" in text
    assert "attempts 1, 2" in text
    assert str(tmp_path) in text


def test_every_attempt_disagreeing_is_reported_as_the_finding_not_papered_over():
    records = [
        _rec(1, 2, "4", 0, A.NOT_ROUTED, _arc_log("s_hreadyout")),
        _rec(2, 4, "4", 0, A.NOT_ROUTED, _arc_log("dut.beat[0]")),
        _rec(3, 8, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
    ]
    summary = A.summarize_ladder(records)
    assert summary.all_distinct is True
    assert all(count == 1 for _, count in summary.signature_counts)
    # Falls back to the last attempt, preserving the old "last attempt" contract when nothing
    # recurs -- but the printed text must say plainly that nothing recurred.
    assert summary.representative.index == 3
    text = A.format_ladder_summary(summary)
    assert "DIFFERENT terminal signature" in text
    assert "no single arc recurs" in text


def test_representative_description_matches_the_representative_own_signature_not_the_mode():
    # Regression pin: when every attempt disagrees, signature_counts[0] is whichever signature was
    # first SEEN (attempt 1's, here 's_hreadyout'), but the representative is the LAST attempt
    # (attempt 3, 's_hwdata[2]'). An earlier version of this module described the representative
    # attempt using signature_counts[0]'s text, printing attempt 3 under the WRONG net name. The
    # printed description must always describe the representative attempt's own signature.
    records = [
        _rec(1, 2, "4", 0, A.NOT_ROUTED, _arc_log("s_hreadyout")),
        _rec(2, 4, "4", 0, A.NOT_ROUTED, _arc_log("dut.beat[0]")),
        _rec(3, 8, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
    ]
    summary = A.summarize_ladder(records)
    assert summary.representative.index == 3
    assert summary.representative_signature.key == "s_hwdata[2]"
    text = A.format_ladder_summary(summary)
    tail = text.split("most representative")[1]
    assert "s_hwdata[2]" in tail
    assert "s_hreadyout" not in tail
    assert "dut.beat[0]" not in tail


def test_recurs_fraction_counts_only_failing_attempts_not_the_whole_ladder():
    records = [
        _rec(1, 2, "4", 0, A.NOT_ROUTED, _arc_log("s_hreadyout")),
        _rec(2, 4, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(3, 8, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(4, 8, "2", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
    ]
    summary = A.summarize_ladder(records)
    text = A.format_ladder_summary(summary)
    assert "recurs 3/4 failing attempts" in text


def test_a_successful_final_attempt_is_excluded_from_failure_signatures():
    # cli.py only calls the summariser when the WHOLE ladder failed, but the summariser itself
    # must not crash or miscount if a success record is present in the list it is handed.
    records = [
        _rec(1, 2, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(2, 4, "4", 0, A.NOT_ROUTED, _arc_log("s_hwdata[2]")),
        _rec(3, 8, "4", 0, A.SUCCESS, ROUTED_OK_LOG),
    ]
    summary = A.summarize_ladder(records)
    assert summary.total == 3
    assert summary.succeeded is True
    assert summary.success_index == 3
    assert summary.signature_counts[0][1] == 2  # only the two failing attempts are counted


def test_aborted_and_nonretryable_get_their_own_stable_signatures():
    records = [
        _rec(1, 2, "4", 0, A.ABORTED, "terminate called after throwing an exception\n"),
        _rec(2, 4, "4", 0, A.ABORTED, "Assertion failure: bogus\n"),
        _rec(3, 8, "4", 0, A.NONRETRYABLE, "dedicated carry requires ...\n"),
    ]
    summary = A.summarize_ladder(records)
    top_sig, top_count = summary.signature_counts[0]
    assert top_sig.kind == "ABORTED"
    assert top_count == 2


def test_timing_failure_without_a_parsable_arc_gets_a_timing_signature():
    log = "Info: Routing complete.\nInfo: No Fmax available.\n"
    r = _rec(1, 4, "4", 0, A.TIMING_FAILED, log)
    summary = A.summarize_ladder([r])
    assert summary.representative.outcome == A.TIMING_FAILED
    sig = A._signature_for(r)
    assert sig.kind == "TIMING"


def test_garbage_log_with_no_recognisable_marker_falls_back_to_other_and_never_raises():
    r = _rec(1, 4, "4", 0, A.NOT_ROUTED, "")
    summary = A.summarize_ladder([r])
    assert summary is not None
    sig = summary.representative and A._signature_for(summary.representative)
    assert sig.kind == "OTHER"
    # Must still format without raising.
    assert A.format_ladder_summary(summary) is not None
