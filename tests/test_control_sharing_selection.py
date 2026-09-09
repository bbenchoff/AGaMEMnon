import json
import os
from types import SimpleNamespace

import pytest

from agamemnon import cli


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
    assert report["outcome"] == "classified_placement_routing_exhaustion"
    for failure in (RuntimeError("unknown"), SystemExit(2)):
        monkeypatch.setattr(cli, "_cmd_build_once",
                            lambda candidate, failure=failure: (_ for _ in ()).throw(failure))
        with pytest.raises(type(failure)):
            cli._compare_control_sharing(_ordinary_args(), baseline, str(tmp_path))
