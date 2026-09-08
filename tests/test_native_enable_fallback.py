from agamemnon import cli
from agamemnon.engine import attempt_ladder as ladder
import pytest


def record(log, outcome=ladder.NOT_ROUTED):
    return ladder.AttemptRecord(1, 16, "4", 0, outcome, log)


DOCUMENT = {"modules": {"top": {"cells": {"state": {"type": "DFFE"}}}}}
PLACEMENT = record("ERROR: clock-enable cluster has no legal same-tile slot assignment")


def test_native_placement_fallback_requires_live_native_population():
    assert cli._native_enable_fallback_allowed(True, DOCUMENT, [PLACEMENT])
    assert not cli._native_enable_fallback_allowed(False, DOCUMENT, [PLACEMENT])
    assert not cli._native_enable_fallback_allowed(True, {}, [PLACEMENT])
    assert not cli._native_enable_fallback_allowed(True, DOCUMENT, [])


@pytest.mark.parametrize("other", [
    record("timeout after 30 seconds"),
    record("Unable to place cell\nAGaMEMnon place&route time limit exceeded (30 seconds)"),
    record("unknown implementation failure"),
    record("Routing complete", ladder.SUCCESS),
    record("Routing complete", ladder.TIMING_FAILED),
    record("Unable to place cell", ladder.ABORTED),
    record("Unable to place cell", ladder.NONRETRYABLE),
])
def test_native_fallback_does_not_hide_other_failure_classes(other):
    assert not cli._native_enable_fallback_allowed(True, DOCUMENT, [PLACEMENT, other])
