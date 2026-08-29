#!/usr/bin/env python3
"""Frozen, fail-closed classifier for N58-HWDATA25-HIL-S01 captures."""

from __future__ import annotations

from typing import Any


EXPECTED_SAMPLES = 32768
LOGICAL_MASK = 0x01
RUN_LENGTH_MIN = 32
RUN_LENGTH_MAX = 16384
COMPLETE_HIGH_RUNS_MIN = 4
COMPLETE_LOW_RUNS_MIN = 4
TRANSITIONS_MIN = 8
HIGH_FRACTION_MIN = 0.1
HIGH_FRACTION_MAX = 0.9

REJECT_INVALID_CONTROL = "REJECT_INVALID_CONTROL"
NEGATIVE_NO_CONDUCTION = "NEGATIVE_NO_CONDUCTION"
POSITIVE_EXACT_CONDUCTION = "POSITIVE_EXACT_CONDUCTION"
UNCLASSIFIED = "UNCLASSIFIED"


class CaptureContractError(ValueError):
    """The raw capture cannot be admitted to the preregistered classifier."""


def _logical(raw: bytes | bytearray | memoryview, role: str) -> tuple[int, ...]:
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise CaptureContractError(f"{role}: capture must be bytes-like")
    data = bytes(raw)
    if len(data) != EXPECTED_SAMPLES:
        raise CaptureContractError(
            f"{role}: expected {EXPECTED_SAMPLES} samples, got {len(data)}"
        )
    return tuple(1 if sample & LOGICAL_MASK else 0 for sample in data)


def _runs(logical: tuple[int, ...]) -> list[dict[str, int]]:
    runs: list[dict[str, int]] = []
    start = 0
    state = logical[0]
    for index, value in enumerate(logical[1:], 1):
        if value == state:
            continue
        runs.append(
            {"state": state, "start": start, "end": index, "length": index - start}
        )
        start = index
        state = value
    runs.append(
        {
            "state": state,
            "start": start,
            "end": len(logical),
            "length": len(logical) - start,
        }
    )
    return runs


def _metrics(logical: tuple[int, ...]) -> dict[str, Any]:
    runs = _runs(logical)
    complete = runs[1:-1]
    high_lengths = [run["length"] for run in complete if run["state"] == 1]
    low_lengths = [run["length"] for run in complete if run["state"] == 0]
    high_samples = sum(logical)
    return {
        "samples": len(logical),
        "logical_high_samples": high_samples,
        "logical_low_samples": len(logical) - high_samples,
        "high_fraction": high_samples / len(logical),
        "transitions": len(runs) - 1,
        "all_run_count": len(runs),
        "complete_run_count": len(complete),
        "complete_high_run_lengths": high_lengths,
        "complete_low_run_lengths": low_lengths,
    }

def classify(
    control: bytes | bytearray | memoryview,
    candidate: bytes | bytearray | memoryview,
    control_recovery: bytes | bytearray | memoryview,
) -> dict[str, Any]:
    """Classify exactly three full CAP8 captures in preregistered decision order."""

    control_metrics = _metrics(_logical(control, "control"))
    candidate_metrics = _metrics(_logical(candidate, "candidate"))
    recovery_metrics = _metrics(_logical(control_recovery, "control-recovery"))

    reasons: list[str] = []
    if (
        control_metrics["logical_high_samples"]
        or recovery_metrics["logical_high_samples"]
    ):
        decision = REJECT_INVALID_CONTROL
        reasons.append("at least one bracketing control has a logical high sample")
    elif candidate_metrics["logical_high_samples"] == 0:
        decision = NEGATIVE_NO_CONDUCTION
        reasons.append("both controls are idle and the candidate has no logical high sample")
    else:
        high_lengths = candidate_metrics["complete_high_run_lengths"]
        low_lengths = candidate_metrics["complete_low_run_lengths"]
        requirements = {
            "complete_high_runs_minimum": len(high_lengths) >= COMPLETE_HIGH_RUNS_MIN,
            "complete_low_runs_minimum": len(low_lengths) >= COMPLETE_LOW_RUNS_MIN,
            "all_complete_high_run_lengths_in_range": bool(high_lengths)
            and all(RUN_LENGTH_MIN <= length <= RUN_LENGTH_MAX for length in high_lengths),
            "all_complete_low_run_lengths_in_range": bool(low_lengths)
            and all(RUN_LENGTH_MIN <= length <= RUN_LENGTH_MAX for length in low_lengths),
            "high_fraction_in_open_interval": HIGH_FRACTION_MIN
            < candidate_metrics["high_fraction"]
            < HIGH_FRACTION_MAX,
            "transitions_minimum": candidate_metrics["transitions"] >= TRANSITIONS_MIN,
        }
        candidate_metrics["positive_requirements"] = requirements
        failed = [name for name, passed in requirements.items() if not passed]
        if failed:
            decision = UNCLASSIFIED
            reasons.extend(f"failed {name}" for name in failed)
        else:
            decision = POSITIVE_EXACT_CONDUCTION
            reasons.append("all preregistered exact-conduction requirements pass")

    return {
        "classifier": "N58-HWDATA25-HIL-S01-CLASSIFIER-V1",
        "decision": decision,
        "reasons": reasons,
        "roles": {
            "control": control_metrics,
            "candidate": candidate_metrics,
            "control-recovery": recovery_metrics,
        },
    }
