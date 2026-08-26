import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agamemnon import hil_campaign as H


def _artifact(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "path": name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _contract(low, high):
    return {
        "word_count": 2,
        "outcomes": [
            {"id": "low", "rules": [
                {"word": 1, "mask": "0x000000ff", "equals": low},
            ]},
            {"id": "high", "rules": [
                {"word": 1, "mask": "0x000000ff", "equals": high},
            ]},
        ],
    }


def _worklist(tmp_path):
    matrix = _artifact(tmp_path, "matrix.json", b"{}\n")
    firmware = _artifact(tmp_path, "probe.bin", b"probe")
    control = _artifact(tmp_path, "control.img", bytes([0x11]) * H.IMAGE_BYTES)
    candidate = _artifact(tmp_path, "candidate.img", bytes([0x22]) * H.IMAGE_BYTES)
    return {
        "schema": H.SCHEMA,
        "kind": H.KIND,
        "campaign_id": "unit-campaign",
        "expected_jobs": 2,
        "design_denominator": ["ready-design", "blocked-design"],
        "source_matrix": matrix,
        "jobs": [
            {
                "job_id": "job-ready",
                "design": "ready-design",
                "defect": "VP-TEST-1",
                "release_status": "RELEASE_CONTAINED",
                "state": "READY",
                "producer": "mcu-ahb",
                "transport": "fcb-restream-sram",
                "evidence": [matrix],
                "firmware": firmware,
                "control": {"image": control, "observation": _contract(2, 6)},
                "candidates": [{
                    "candidate_id": "candidate-a",
                    "hypothesis": "one bounded hypothesis",
                    "intervention": "change one bound field",
                    "discriminator": "low versus high observation",
                    "image": candidate,
                    "observation": _contract(3, 7),
                }],
                "blockers": [],
            },
            {
                "job_id": "job-blocked",
                "design": "blocked-design",
                "defect": "VP-TEST-2",
                "release_status": "RELEASE_CONTAINED",
                "state": "BLOCKED",
                "producer": "fabric-ahb-master",
                "transport": "fcb-restream-sram",
                "evidence": [matrix],
                "firmware": None,
                "control": {"image": None, "observation": _contract(1, 2)},
                "candidates": [{
                    "candidate_id": "candidate-b",
                    "hypothesis": "a second bounded hypothesis",
                    "intervention": "await a witness image",
                    "discriminator": "two frozen outcomes",
                    "image": None,
                    "observation": _contract(4, 5),
                }],
                "blockers": ["request boundary is not independently driven"],
            },
        ],
    }


def test_plan_hash_binds_artifacts_and_orders_control_candidate_recovery(tmp_path):
    worklist = _worklist(tmp_path)
    plan = H.build_plan(worklist, tmp_path)
    assert plan["job_count"] == 2
    assert plan["candidate_count"] == 2
    assert (plan["ready_jobs"], plan["blocked_jobs"]) == (1, 1)
    ready = plan["jobs"][0]
    assert [step["role"] for step in ready["steps"]] == [
        "control", "candidate", "control-recovery",
    ]
    assert [step["sequence"] for step in ready["steps"]] == [1, 2, 3]
    assert ready["steps"][0]["image"] == ready["steps"][2]["image"]
    assert [item["candidate_id"] for item in ready["candidates"]] == ["candidate-a"]
    assert plan["jobs"][1]["steps"] == []
    assert plan["jobs"][1]["candidates"][0]["image"] is None
    assert plan["source_matrix"]["path"] == "matrix.json"
    assert len(plan["worklist_sha256"]) == 64


def test_require_ready_refuses_a_partially_prepared_campaign(tmp_path):
    with pytest.raises(H.HilCampaignError, match="not READY"):
        H.build_plan(_worklist(tmp_path), tmp_path, require_ready=True)


def test_present_artifact_tamper_and_path_escape_fail_closed(tmp_path):
    worklist = _worklist(tmp_path)
    (tmp_path / "candidate.img").write_bytes(b"changed")
    with pytest.raises(H.HilCampaignError, match="size changed"):
        H.build_plan(worklist, tmp_path)
    worklist = _worklist(tmp_path)
    worklist["source_matrix"]["path"] = "../outside.json"
    with pytest.raises(H.HilCampaignError, match="escapes"):
        H.build_plan(worklist, tmp_path)


def test_denominator_candidate_count_and_release_status_are_enforced(tmp_path):
    worklist = _worklist(tmp_path)
    worklist["jobs"][0]["candidates"] *= 3
    with pytest.raises(H.HilCampaignError, match="one or two"):
        H.build_plan(worklist, tmp_path)
    worklist = _worklist(tmp_path)
    worklist["jobs"][0]["release_status"] = "ROOT_CAUSED"
    with pytest.raises(H.HilCampaignError, match="RELEASE_CONTAINED"):
        H.build_plan(worklist, tmp_path)
    worklist = _worklist(tmp_path)
    worklist["design_denominator"][0] = "wrong-design"
    with pytest.raises(H.HilCampaignError, match="exactly cover"):
        H.build_plan(worklist, tmp_path)


def test_observation_classification_is_exact_ambiguous_or_unclassified():
    contract = _contract(2, 6)
    assert H.classify_observation(contract, [0, 2])["classification"] == "low"
    assert H.classify_observation(contract, [0, 6])["classification"] == "high"
    assert H.classify_observation(contract, [0, 9])["classification"] == "UNCLASSIFIED"
    ambiguous = {
        "word_count": 1,
        "outcomes": [
            {"id": "a", "rules": [{"word": 0, "mask": 1, "equals": 1}]},
            {"id": "b", "rules": [{"word": 0, "mask": 3, "equals": 1}]},
        ],
    }
    result = H.classify_observation(ambiguous, [1])
    assert result["classification"] == "AMBIGUOUS"
    assert result["matches"] == ["a", "b"]


def test_ready_job_runner_requires_and_recovers_the_control(tmp_path):
    plan = H.build_plan(_worklist(tmp_path), tmp_path)

    def executor(job):
        assert job["firmware"]["sha256"]
        return {1: [0, 2], 2: [0, 7], 3: [0, 2]}

    result = H.run_ready_job(plan, "job-ready", executor)
    assert result["status"] == "CLASSIFIED"
    assert result["control_recovered"] is True
    assert [step["classification"] for step in result["steps"]] == [
        "low", "high", "low",
    ]


def test_ready_job_runner_keeps_a_bad_recovery_out_of_classified_status(tmp_path):
    plan = H.build_plan(_worklist(tmp_path), tmp_path)
    result = H.run_ready_job(
        plan, "job-ready", lambda job: {1: [0, 2], 2: [0, 3], 3: [0, 6]},
    )
    assert result["status"] == "CONTROL_FAILED"
    assert result["control_recovered"] is False
    with pytest.raises(H.HilCampaignError, match="not READY"):
        H.run_ready_job(plan, "job-blocked", lambda job: {})


def test_cli_command_prints_the_same_plan(tmp_path, capsys):
    worklist = _worklist(tmp_path)
    path = tmp_path / "worklist.json"
    path.write_text(json.dumps(worklist), encoding="utf-8")
    H.cmd_campaign(SimpleNamespace(
        worklist=str(path), root=str(tmp_path), require_ready=False,
    ))
    output = json.loads(capsys.readouterr().out)
    assert output["kind"] == H.PLAN_KIND
    assert output["campaign_id"] == "unit-campaign"
