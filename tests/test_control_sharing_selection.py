import json
import os
from types import SimpleNamespace

import pytest

from agamemnon import cli
from agamemnon.engine import attempt_ladder as ladder


def _attempt(log, outcome=ladder.NOT_ROUTED):
    return ladder.AttemptRecord(1, 8, "4", 0, outcome, log)


def _routed(path, *, native_groups=(), ordinary=0):
    cells = {}
    for index, group in enumerate(native_groups):
        cells[f"native_{index}"] = {
            "type": "GENERIC_SLICE", "parameters": {"FF_USED": "1"},
            "attributes": {"AGRV2K_CLOCK_ENABLE_NET": group},
        }
    for index in range(ordinary):
        cells[f"ordinary_{index}"] = {
            "type": "GENERIC_SLICE", "parameters": {"FF_USED": "1"},
        }
    path.write_text(json.dumps({"modules": {"top": {"cells": cells}}}))


def _baseline(path, *, state=None):
    return {
        "routed_json": str(path), "occupied_tiles": 10, "slice_count": 96,
        "mapping": "legacy", "srst_recovery": "0", "mapping_options": {},
        "effective_build_state": {} if state is None else state,
    }


def _ordinary_args(**changes):
    values = dict(uarch=True, input="top.v", project=None,
                  no_native_clock_enable=False, qualified_checkpoint=None,
                  qualified_bram_write=None, research_unsafe=False,
                  _native_srst_candidate=False)
    values.update(changes)
    return SimpleNamespace(**values)


def test_baseline_srst_selector_uses_tiles_then_legacy_tie(tmp_path, monkeypatch):
    """A sharing comparison must receive the best measured isolated candidate."""
    monkeypatch.setattr(cli, "_native_srst_auto_enabled", lambda a: True)
    monkeypatch.setattr(cli, "_validate_native_srst_final_products", lambda *args: None)
    monkeypatch.setattr(cli, "_copy_candidate_products", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_sha256_file", lambda path: "selected")
    selected = []
    monkeypatch.setattr(cli, "_compare_control_sharing",
                        lambda a, baseline, root: (selected.append(baseline) or baseline,
                                                   {"selected": "isolated"}))

    def build(candidate):
        # Recovered has fewer tiles at equal slices, so it must beat legacy.
        recovered = os.environ["AGRV2K_SHARED_CONTROL_SRST_RECOVERY"] == "1"
        return {"output": candidate.output, "routed_json": candidate.write_routed,
                "slice_count": 100, "occupied_tiles": 9 if recovered else 10,
                "routed_sha256": "r" if recovered else "l",
                "eligible_srst_cells": 1, "effective_build_state": {}}
    monkeypatch.setattr(cli, "_cmd_build_once", build)
    result = cli.cmd_build(_ordinary_args(output=str(tmp_path / "out.bin"), write_routed=None))
    assert selected[0]["mapping"] == "recovered"
    assert result["mapping"] == "recovered"


def test_baseline_srst_selector_preserves_legacy_exact_tie(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_native_srst_auto_enabled", lambda a: True)
    monkeypatch.setattr(cli, "_validate_native_srst_final_products", lambda *args: None)
    monkeypatch.setattr(cli, "_copy_candidate_products", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_sha256_file", lambda path: "selected")
    selected = []
    monkeypatch.setattr(cli, "_compare_control_sharing",
                        lambda a, baseline, root: (selected.append(baseline) or baseline, {}))
    monkeypatch.setattr(cli, "_cmd_build_once", lambda candidate: {
        "output": candidate.output, "routed_json": candidate.write_routed,
        "slice_count": 100, "occupied_tiles": 10, "routed_sha256": "same",
        "eligible_srst_cells": 1, "effective_build_state": {}})
    cli.cmd_build(_ordinary_args(output=str(tmp_path / "out.bin"), write_routed=None))
    assert selected[0]["mapping"] == "legacy"


def test_sharing_candidate_copies_effective_mapping_state(tmp_path, monkeypatch):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a",), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    observed = {}
    def build(candidate):
        observed.update({key: getattr(candidate, key) for key in (
            "no_hard_carry", "_tile_compaction_disabled",
            "_native_enable_excluded_group_ids", "_fallback_stages")})
        assert candidate._control_sharing_options == {
            "AGRV2K_MIXED_NATIVE_CONTROL": "1", "AGRV2K_DUAL_NATIVE_CONTROL": "0"}
        return {"slice_count": 96, "occupied_tiles": 10, "routed_sha256": "sharing"}
    monkeypatch.setattr(cli, "_cmd_build_once", build)
    state = {"no_hard_carry": True, "_tile_compaction_disabled": True,
             "_native_enable_excluded_group_ids": ("0123456789abcdef",),
             "_fallback_stages": ("uncompacted", "selective_data_logic_enable")}
    baseline = _baseline(routed, state=state)
    chosen, report = cli._compare_control_sharing(_ordinary_args(), baseline, str(tmp_path))
    assert observed == state
    assert chosen is baseline and report["selected"] == "isolated"
    assert report["baseline_build_state"] == state


def test_sharing_budget_is_candidate_private_and_respects_tighter_user_limit(tmp_path, monkeypatch):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a",), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    args = _ordinary_args(attempt_timeout=7.0)
    baseline = _baseline(routed, state={"no_hard_carry": True})
    observed = []
    def build(candidate):
        observed.append((candidate.attempt_timeout,
                         candidate._control_sharing_max_route_attempts,
                         candidate.no_hard_carry))
        return {"slice_count": 96, "occupied_tiles": 10, "routed_sha256": "sharing"}
    monkeypatch.setattr(cli, "_cmd_build_once", build)
    chosen, report = cli._compare_control_sharing(args, baseline, str(tmp_path))
    assert chosen is baseline
    assert observed == [(7.0, 3, True)]
    assert args.attempt_timeout == 7.0
    assert baseline["effective_build_state"] == {"no_hard_carry": True}
    assert report["profiles"][0]["route_attempt_budget"] == {
        "max_route_attempts": 3, "attempt_timeout_seconds": 7.0}


def test_control_sharing_stop_helper_requires_known_records_individually():
    placement = _attempt("Unable to place cell")
    arc = _attempt("ERROR: Failed to route arc 1.0 of net 's', from A to B.")
    deadline = _attempt("AGaMEMnon place&route time limit exceeded (60 seconds)")
    unknown = _attempt("unclassified implementation result")
    assert cli._control_sharing_budget_outcome([placement, arc], 3) is None
    assert cli._control_sharing_budget_outcome([placement, arc, placement], 3) == (
        "classified_placement_routing_exhaustion")
    assert cli._control_sharing_budget_outcome([placement, deadline, arc], 3) == (
        "optional_route_budget_expired")
    # One deadline cannot turn a different unknown record into a safe skip.
    assert cli._control_sharing_budget_outcome([placement, deadline, unknown], 3) is None
    assert cli._control_sharing_budget_outcome(
        [placement, arc, _attempt("Routing complete", ladder.TIMING_FAILED)], 3) is None


@pytest.mark.parametrize(("groups", "ordinary", "expected"), [
    (("a",), 1, {"AGRV2K_MIXED_NATIVE_CONTROL": "1", "AGRV2K_DUAL_NATIVE_CONTROL": "0"}),
    (("a", "b"), 0, {"AGRV2K_MIXED_NATIVE_CONTROL": "0", "AGRV2K_DUAL_NATIVE_CONTROL": "1"}),
])
def test_composition_profiles_are_exclusive(tmp_path, monkeypatch, groups, ordinary, expected):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=groups, ordinary=ordinary)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    observed = []
    def build(candidate):
        observed.append(candidate._control_sharing_options)
        return {"slice_count": 96, "occupied_tiles": 10, "routed_sha256": "sharing"}
    monkeypatch.setattr(cli, "_cmd_build_once", build)
    cli._compare_control_sharing(_ordinary_args(), _baseline(routed), str(tmp_path))
    assert observed == [expected]
    assert set(observed[0].values()) == {"0", "1"}


def test_both_opportunities_compare_separate_profiles_and_choose_lower_tiles(tmp_path, monkeypatch):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a", "b"), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    observed, states = [], []
    state = {"no_hard_carry": True, "_tile_compaction_disabled": True,
             "_native_enable_excluded_group_ids": (), "_fallback_stages": ("uncompacted",)}
    def build(candidate):
        options = candidate._control_sharing_options
        observed.append(options)
        states.append((candidate.no_hard_carry, candidate._tile_compaction_disabled,
                       candidate._fallback_stages))
        tiles = 9 if options["AGRV2K_DUAL_NATIVE_CONTROL"] == "1" else 10
        return {"slice_count": 96, "occupied_tiles": tiles,
                "routed_sha256": "dual" if tiles == 9 else "mixed"}
    monkeypatch.setattr(cli, "_cmd_build_once", build)
    chosen, report = cli._compare_control_sharing(
        _ordinary_args(), _baseline(routed, state=state), str(tmp_path))
    assert observed == [
        {"AGRV2K_MIXED_NATIVE_CONTROL": "1", "AGRV2K_DUAL_NATIVE_CONTROL": "0"},
        {"AGRV2K_MIXED_NATIVE_CONTROL": "0", "AGRV2K_DUAL_NATIVE_CONTROL": "1"},
    ]
    assert all(set(options.values()) == {"0", "1"} for options in observed)
    assert states == [(True, True, ("uncompacted",))] * 2
    assert chosen["routed_sha256"] == "dual"
    assert report["selected"] == "dual"
    assert [row["profile"] for row in report["profiles"]] == ["mixed", "dual"]
    assert [row["selected"] for row in report["profiles"]] == [False, True]


def test_isolated_wins_ties_and_mixed_wins_equal_improved_profiles(tmp_path, monkeypatch):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a", "b"), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    baseline = _baseline(routed)
    # Equal-to-baseline metrics preserve isolated.
    monkeypatch.setattr(cli, "_cmd_build_once", lambda candidate: {
        "slice_count": 96, "occupied_tiles": 10, "routed_sha256": "tie"})
    chosen, report = cli._compare_control_sharing(_ordinary_args(), baseline, str(tmp_path))
    assert chosen is baseline and report["selected"] == "isolated"
    # Equal improvements are deterministic: mixed appears first and stays selected.
    monkeypatch.setattr(cli, "_cmd_build_once", lambda candidate: {
        "slice_count": 96, "occupied_tiles": 9,
        "routed_sha256": "mixed" if candidate._control_sharing_options[
            "AGRV2K_MIXED_NATIVE_CONTROL"] == "1" else "dual"})
    chosen, report = cli._compare_control_sharing(_ordinary_args(), baseline, str(tmp_path))
    assert chosen["routed_sha256"] == "mixed"
    assert report["selected"] == "mixed"


@pytest.mark.parametrize("change", [
    {"qualified_checkpoint": "checkpoint"},
    {"qualified_bram_write": "source"},
    {"research_unsafe": True},
    {"no_native_clock_enable": True},
])
def test_automatic_sharing_excludes_nonordinary_modes(monkeypatch, change):
    monkeypatch.delenv("AGRV2K_SHARED_CONTROL_ENABLE", raising=False)
    monkeypatch.delenv("AGRV2K_SHARED_CONTROL_SRST_RECOVERY", raising=False)
    monkeypatch.delenv("AGRV2K_MIXED_NATIVE_CONTROL", raising=False)
    monkeypatch.delenv("AGRV2K_DUAL_NATIVE_CONTROL", raising=False)
    assert not cli._control_sharing_auto_enabled(_ordinary_args(**change))


@pytest.mark.parametrize("key", ["AGRV2K_MIXED_NATIVE_CONTROL", "AGRV2K_DUAL_NATIVE_CONTROL",
                                  "AGRV2K_REPLAY_BELS_top"])
def test_automatic_sharing_excludes_explicit_or_replay_controls(monkeypatch, key):
    monkeypatch.delenv("AGRV2K_SHARED_CONTROL_ENABLE", raising=False)
    monkeypatch.delenv("AGRV2K_SHARED_CONTROL_SRST_RECOVERY", raising=False)
    monkeypatch.setenv(key, "1")
    assert not cli._control_sharing_auto_enabled(_ordinary_args())


def test_classified_exhaustion_keeps_baseline_and_other_failures_propagate(tmp_path, monkeypatch):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a",), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    baseline = _baseline(routed)
    monkeypatch.setattr(cli, "_cmd_build_once",
                        lambda candidate: (_ for _ in ()).throw(cli._ControlSharingCandidateExhausted()))
    chosen, report = cli._compare_control_sharing(_ordinary_args(), baseline, str(tmp_path))
    assert chosen is baseline
    assert report["profiles"] == [{
        "profile": "mixed",
        "options": {"AGRV2K_MIXED_NATIVE_CONTROL": "1", "AGRV2K_DUAL_NATIVE_CONTROL": "0"},
        "route_attempt_budget": {
            "max_route_attempts": 3, "attempt_timeout_seconds": 60.0},
        "outcome": "classified_placement_routing_exhaustion"}]
    assert report["outcome"] == "classified_placement_routing_exhaustion"
    for failure in (RuntimeError("unknown"), SystemExit(2)):
        monkeypatch.setattr(cli, "_cmd_build_once",
                            lambda candidate, failure=failure: (_ for _ in ()).throw(failure))
        with pytest.raises(type(failure)):
            cli._compare_control_sharing(_ordinary_args(), baseline, str(tmp_path))


def test_classified_mixed_exhaustion_continues_to_dual(tmp_path, monkeypatch):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a", "b"), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    calls = []
    def build(candidate):
        profile = "mixed" if candidate._control_sharing_options[
            "AGRV2K_MIXED_NATIVE_CONTROL"] == "1" else "dual"
        calls.append(profile)
        if profile == "mixed":
            raise cli._ControlSharingCandidateExhausted()
        return {"slice_count": 96, "occupied_tiles": 9, "routed_sha256": "dual"}
    monkeypatch.setattr(cli, "_cmd_build_once", build)
    chosen, report = cli._compare_control_sharing(_ordinary_args(), _baseline(routed), str(tmp_path))
    assert calls == ["mixed", "dual"]
    assert chosen["routed_sha256"] == "dual"
    assert report["profiles"][0]["outcome"] == "classified_placement_routing_exhaustion"


@pytest.mark.parametrize("outcome", [
    "optional_route_budget_expired", "optional_carry_graph_infeasible",
])
def test_optional_budget_outcomes_are_recorded_without_selecting_candidate(
        tmp_path, monkeypatch, outcome):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a",), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    monkeypatch.setattr(
        cli, "_cmd_build_once",
        lambda candidate: (_ for _ in ()).throw(cli._ControlSharingCandidateExhausted(
            outcome, attempts_run=1, max_route_attempts=3, attempt_timeout_seconds=60.0)))
    baseline = _baseline(routed)
    chosen, report = cli._compare_control_sharing(_ordinary_args(), baseline, str(tmp_path))
    assert chosen is baseline
    assert report["profiles"][0].items() >= {
        "outcome": outcome, "attempts_run": 1,
        "max_route_attempts": 3, "attempt_timeout_seconds": 60.0}.items()
    assert report["outcome"] == outcome


def test_unknown_or_timing_mixed_failure_does_not_run_dual(tmp_path, monkeypatch):
    routed = tmp_path / "baseline.json"
    _routed(routed, native_groups=("a", "b"), ordinary=1)
    monkeypatch.setattr(cli, "_control_sharing_auto_enabled", lambda a: True)
    for failure in (RuntimeError("unknown"), RuntimeError("timing")):
        calls = []
        def build(candidate, failure=failure):
            calls.append(candidate._control_sharing_options)
            raise failure
        monkeypatch.setattr(cli, "_cmd_build_once", build)
        with pytest.raises(RuntimeError, match=str(failure)):
            cli._compare_control_sharing(_ordinary_args(), _baseline(routed), str(tmp_path))
        assert len(calls) == 1
