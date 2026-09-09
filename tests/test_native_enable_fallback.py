from agamemnon import cli
from agamemnon.engine import attempt_ladder as ladder
import json
import os
from pathlib import Path
from types import SimpleNamespace
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


def _report(*, group_id="000000000000ab12", candidate=6, legal=0, rejected=6):
    return {
        "schema": "agamemnon.native-enable-infeasible.v1",
        "stage": "prepare_control_placements",
        "groups": [{
            "key": group_id, "native_ff_count": 6,
            "candidate_tiles": candidate,
            "legal_tiles": legal, "rejected_enable_driver": rejected,
        }],
    }


def test_selective_fallback_accepts_only_explicit_zero_reachability_report(tmp_path):
    path = tmp_path / "native-enable.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    report = cli._load_native_enable_infeasible_report(path)
    assert report == {"schema": "agamemnon.native-enable-infeasible.v1",
                      "groups": ("000000000000ab12",)}
    assert cli._native_enable_selective_fallback_allowed(
        True, DOCUMENT, [PLACEMENT], report)
    assert not cli._native_enable_selective_fallback_allowed(
        True, DOCUMENT, [PLACEMENT], report,
        ("selective_data_logic_enable",),
    )


def test_native_srst_candidate_wrapper_selects_final_route_cost_and_legacy_tie(
        tmp_path, monkeypatch):
    calls = []
    def fake_once(candidate):
        calls.append((candidate.output, os.environ["AGRV2K_SHARED_CONTROL_SRST_RECOVERY"]))
        path = Path(candidate.output)
        path.write_bytes(b"bitstream")
        Path(str(path) + ".comp").write_bytes(b"compressed")
        routed = Path(candidate.write_routed)
        routed.write_text("{}", encoding="utf-8")
        return {"output": str(path), "routed_json": str(routed),
                "slice_count": 70, "routed_sha256": candidate.output[-13:-4],
                "eligible_srst_cells": 1}
    monkeypatch.setattr(cli, "_cmd_build_once", fake_once)
    monkeypatch.delenv("AGRV2K_SHARED_CONTROL_SRST_RECOVERY", raising=False)
    output = tmp_path / "out.bin"
    routed = tmp_path / "out.json"
    args = SimpleNamespace(uarch=True, no_native_clock_enable=False,
                           qualified_checkpoint=None, qualified_bram_write=None,
                           input="design.v", output=str(output),
                           write_routed=str(routed))
    cli.cmd_build(args)
    assert [recovery for _, recovery in calls] == ["1", "0"]
    assert output.read_bytes() == b"bitstream"
    report = json.loads((tmp_path / "out.bin.native-srst-selection.json").read_text())
    assert report["selected"] == "legacy"
    assert report["selected_output"] == str(output)
    assert report["selected_image_sha256"]
    assert os.environ.get("AGRV2K_SHARED_CONTROL_SRST_RECOVERY") is None


def test_native_srst_candidate_wrapper_propagates_safety_exit(monkeypatch, tmp_path):
    def unsafe(_candidate):
        raise SystemExit(1)
    monkeypatch.setattr(cli, "_cmd_build_once", unsafe)
    monkeypatch.delenv("AGRV2K_SHARED_CONTROL_SRST_RECOVERY", raising=False)
    args = SimpleNamespace(uarch=True, no_native_clock_enable=False,
                           qualified_checkpoint=None, qualified_bram_write=None,
                           input="design.v", output=str(tmp_path / "out.bin"),
                           write_routed=None)
    with pytest.raises(SystemExit):
        cli.cmd_build(args)


def test_native_srst_auto_wrapper_excludes_project_and_explicit_disable(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_cmd_build_once", lambda candidate: calls.append(candidate))
    project = SimpleNamespace(uarch=True, input=None, project="agamemnon.toml",
                              no_native_clock_enable=False,
                              qualified_checkpoint=None, qualified_bram_write=None)
    cli.cmd_build(project)
    assert calls == [project]
    calls.clear()
    plain = SimpleNamespace(uarch=True, input="design.v", project=None,
                            no_native_clock_enable=False,
                            qualified_checkpoint=None, qualified_bram_write=None)
    monkeypatch.setenv("AGRV2K_SHARED_CONTROL_ENABLE", "0")
    cli.cmd_build(plain)
    assert calls == [plain]


def test_selective_report_overrides_only_ambiguous_placement_signature(tmp_path):
    path = tmp_path / "native-enable.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    report = cli._load_native_enable_infeasible_report(path)
    # The C++ fatal occurs in placement preparation but older signature rules
    # categorize this wording as PACKING.  Its explicit report is sufficient.
    assert cli._native_enable_selective_fallback_allowed(
        True, DOCUMENT, [record("unknown implementation failure")], report)
    assert not cli._native_enable_selective_fallback_allowed(
        True, DOCUMENT,
        [record("AGaMEMnon place&route time limit exceeded (20 seconds)")], report)
    assert not cli._native_enable_selective_fallback_allowed(
        True, DOCUMENT, [record("placed", ladder.ABORTED)], report)


@pytest.mark.parametrize("patch", [
    {"candidate_tiles": 0},
    {"legal_tiles": 1},
    {"rejected_enable_driver": 5},
])
def test_selective_fallback_rejects_nonexact_or_partial_placement_failures(
        tmp_path, patch):
    report = _report()
    report["groups"][0].update(patch)
    path = tmp_path / "native-enable.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert cli._load_native_enable_infeasible_report(path) is None


def test_selective_fallback_banks_stable_ids_from_multiple_attempts(tmp_path):
    paths = []
    for index, group_id in enumerate(("000000000000000a", "00000000000000ff")):
        path = tmp_path / ("attempt%d.json" % index)
        path.write_text(json.dumps(_report(group_id=group_id)), encoding="utf-8")
        paths.append(path)
    assert cli._native_enable_infeasible_groups_from_reports(paths) == {
        "schema": "agamemnon.native-enable-infeasible.v1",
        "groups": ("000000000000000a", "00000000000000ff"),
    }


def test_selective_fallback_deduplicates_failed_chunks_of_one_enable_group(tmp_path):
    report = _report()
    report["groups"].append(dict(report["groups"][0]))
    path = tmp_path / "native-enable.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert cli._load_native_enable_infeasible_report(path)["groups"] == (
        "000000000000ab12",
    )


@pytest.mark.parametrize("field, value", [
    ("native_ff_count", 0), ("native_ff_count", True),
    ("candidate_tiles", True), ("legal_tiles", True),
    ("rejected_enable_driver", True),
])
def test_selective_fallback_rejects_invalid_report_counts(tmp_path, field, value):
    report = _report()
    report["groups"][0][field] = value
    path = tmp_path / "native-enable.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid counts"):
        cli._load_native_enable_infeasible_report(path)


def test_selective_fallback_never_uses_display_names_or_unknown_schema(tmp_path):
    path = tmp_path / "native-enable.json"
    bad = _report(group_id="$abc$auto$unstable")
    bad["schema"] = "wrong"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown schema"):
        cli._load_native_enable_infeasible_report(path)


def test_wsl_forwards_the_native_enable_report_as_a_path():
    env = {
        "AGRV2K_NATIVE_ENABLE_INFEASIBLE_REPORT": r"C:\temp\report.json",
        "AGRV2K_SHARED_CONTROL_ENABLE": "1",
    }
    cli._forward_wsl_uarch_environment(env)
    entries = env["WSLENV"].split(":")
    assert "AGRV2K_NATIVE_ENABLE_INFEASIBLE_REPORT/p" in entries
    assert "AGRV2K_NATIVE_ENABLE_INFEASIBLE_REPORT" not in entries


def test_cli_stamps_the_archived_preqin_snapshot_before_retry_selection(tmp_path):
    path = tmp_path / "synth.json"
    document = {"modules": {"top": {"cells": {
        "state": {"type": "DFFE", "attributes": {},
                  "connections": {"CLK": [1], "EN": [2], "D": [3], "Q": [4]}},
    }}}}
    path.write_text(json.dumps(document), encoding="utf-8")
    helper = cli._stamp_native_enable_groups(path)
    stamped = json.loads(path.read_text(encoding="utf-8"))
    assert stamped["modules"]["top"]["cells"]["state"]["attributes"][
        "AGRV2K_ENABLE_GROUP_ID"
    ] == helper.enable_group_id("top", 2)
