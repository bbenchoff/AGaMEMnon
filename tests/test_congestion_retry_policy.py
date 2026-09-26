"""Only a completed unsafe route enables automatic avoidance costs."""
import pytest

from agamemnon import cli
from agamemnon.engine import attempt_ladder as ladder


def record(outcome):
    return ladder.AttemptRecord(1, 0, "1", 0, outcome, "")


@pytest.mark.parametrize("outcomes", [[], [ladder.SUCCESS], [ladder.NOT_ROUTED],
                                   [ladder.TIMING_FAILED], [ladder.ABORTED],
                                   [ladder.NONRETRYABLE]])
def test_ordinary_and_unrelated_failures_keep_original_costs(outcomes):
    env = {"other": "preserved"}
    assert not cli._apply_congestion_retry_penalty(env, list(map(record, outcomes)))
    assert env == {"other": "preserved"}


def test_unsafe_candidate_enables_avoidance_once_for_remaining_attempts():
    env = {}
    records = [record(ladder.NOT_ROUTED), record(ladder.ROUTED_UNSAFE)]
    assert cli._apply_congestion_retry_penalty(env, records)
    assert env == {"AGRV2K_CONGESTION_PENALTY_NS": "25"}
    assert not cli._apply_congestion_retry_penalty(env, records)


@pytest.mark.parametrize("value", ["0", "7", "25"])
def test_explicit_cost_is_preserved(value):
    env = {"AGRV2K_CONGESTION_PENALTY_NS": value}
    assert not cli._apply_congestion_retry_penalty(env, [record(ladder.ROUTED_UNSAFE)])
    assert env["AGRV2K_CONGESTION_PENALTY_NS"] == value
