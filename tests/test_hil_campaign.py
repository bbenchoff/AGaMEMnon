import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
from types import SimpleNamespace

import pytest

from agamemnon import hil_campaign as H
from agamemnon import fcb_restream as F
from agamemnon import program as P
from agamemnon.project import find_riscv_tool


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "agamemnon" / "sdk" / "include" / "ag32_hil_campaign.h"


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


def _fcb_mailbox(record=None):
    words = [0] * F.MAILBOX_WORDS
    words[F.WORD_MAGIC] = F.MAGIC
    words[F.WORD_VERSION] = F.VERSION
    words[F.WORD_SENTINEL] = F.SENTINEL
    if record is None:
        words[F.WORD_STATE] = F.STATE_READY
    else:
        words[F.WORD_STATE] = F.STATE_DONE
        words[F.WORD_RESULT_SEQUENCE] = record.sequence
        words[F.WORD_RESULT_CODE] = F.RESULT_OK
        words[F.WORD_FCB_STATUS] = F.FCB_STAT_OK
        words[F.WORD_RESULT_TAG] = record.tag
        words[F.WORD_ATTEMPTS] = record.sequence
        words[F.WORD_SUCCESSES] = record.sequence
    return words


def _campaign_mailbox(record=None, results=()):
    words = [0] * H.CAMPAIGN_MAILBOX_WORDS
    words[H.CAMPAIGN_WORD_MAGIC] = H.CAMPAIGN_MAGIC
    words[H.CAMPAIGN_WORD_VERSION] = H.CAMPAIGN_VERSION
    words[H.CAMPAIGN_WORD_SENTINEL] = H.CAMPAIGN_SENTINEL
    if record is None:
        words[H.CAMPAIGN_WORD_STATE] = H.CAMPAIGN_STATE_READY
    else:
        words[H.CAMPAIGN_WORD_STATE] = H.CAMPAIGN_STATE_DONE
        words[H.CAMPAIGN_WORD_RESULT_SEQUENCE] = record.sequence
        words[H.CAMPAIGN_WORD_RESULT_TAG] = record.tag
        words[H.CAMPAIGN_WORD_COUNT] = len(results)
        words[H.CAMPAIGN_WORD_RESULTS:H.CAMPAIGN_WORD_RESULTS + len(results)] = results
    return words


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
    assert ready["execution"] == {
        "firmware_address": H.DEFAULT_FIRMWARE_ADDRESS,
        "stack_pointer": H.DEFAULT_STACK_POINTER,
    }
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


def test_high_sram_observer_layout_is_bounded_and_hash_planned(tmp_path):
    worklist = _worklist(tmp_path)
    worklist["jobs"][0]["execution"] = {
        "firmware_address": "0x2001b000",
        "stack_pointer": "0x20020000",
    }
    job = H.build_plan(worklist, tmp_path)["jobs"][0]
    assert job["execution"] == {
        "firmware_address": 0x2001B000,
        "stack_pointer": 0x20020000,
    }

    worklist["jobs"][0]["execution"]["firmware_address"] = "0x20002000"
    with pytest.raises(H.HilCampaignError, match="staged fabric image"):
        H.build_plan(worklist, tmp_path)
    worklist["jobs"][0]["execution"] = {
        "firmware_address": "0x2001b000",
        "stack_pointer": "0x2001fff0",
    }
    with pytest.raises(H.HilCampaignError, match="top-of-SRAM stack"):
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


def test_campaign_protocol_constants_match_the_packaged_header():
    text = HEADER.read_text(encoding="utf-8")
    expected = {
        "MAILBOX_ADDRESS": H.CAMPAIGN_MAILBOX_ADDRESS,
        "MAGIC": H.CAMPAIGN_MAGIC,
        "VERSION": H.CAMPAIGN_VERSION,
        "SENTINEL": H.CAMPAIGN_SENTINEL,
    }
    for suffix, value in expected.items():
        match = re.search(
            r"^#define AG32_HIL_CAMPAIGN_%s\s+(0x[0-9a-fA-F]+|[0-9]+)u" % suffix,
            text, re.MULTILINE,
        )
        assert match and int(match.group(1), 0) == value


def test_campaign_mailbox_requires_ready_and_exact_observer_result(tmp_path):
    ready = _campaign_mailbox()
    H.validate_campaign_ready(ready)
    image = _artifact(tmp_path, "image.bin", bytes(H.IMAGE_BYTES))
    record = F.inspect_image(tmp_path / image["path"], 7)
    decoded = H.decode_campaign_result(
        _campaign_mailbox(record, [0x12345678, 0xABCDEF01]), record, 2,
    )
    assert decoded == [0x12345678, 0xABCDEF01]
    bad = _campaign_mailbox(record, [1])
    bad[H.CAMPAIGN_WORD_ERROR] = 2
    with pytest.raises(H.HilCampaignError, match="reported an error"):
        H.decode_campaign_result(bad, record, 1)
    with pytest.raises(H.HilCampaignError, match="requires 2"):
        H.decode_campaign_result(_campaign_mailbox(record, [1]), record, 2)


def test_explicit_ready_job_execution_is_one_sram_session(tmp_path, monkeypatch):
    worklist = _worklist(tmp_path)
    job = H.build_plan(worklist, tmp_path)["jobs"][0]
    records = [
        F.inspect_image(tmp_path / step["image"]["path"], step["sequence"])
        for step in job["steps"]
    ]
    observed = {1: [0, 2], 2: [0, 7], 3: [0, 2]}
    calls = []
    monkeypatch.setattr(P, "_require_ag32", lambda: P.EXPECTED_DEVICE_ID)

    def simulated_openocd(commands, timeout):
        calls.append(tuple(commands))
        for command in commands:
            if not command.startswith("dump_image "):
                continue
            path = Path(re.match(r'dump_image "([^"]+)"', command).group(1))
            name = path.name
            if name == "fcb-ready.bin":
                words = _fcb_mailbox()
                path.write_bytes(struct.pack("<16I", *words))
            elif name == "campaign-ready.bin":
                words = _campaign_mailbox()
                path.write_bytes(struct.pack("<41I", *words))
            elif name.startswith("fcb-"):
                sequence = int(name[4:8])
                words = _fcb_mailbox(records[sequence - 1])
                path.write_bytes(struct.pack("<16I", *words))
            elif name.startswith("campaign-"):
                sequence = int(name[9:13])
                words = _campaign_mailbox(records[sequence - 1], observed[sequence])
                path.write_bytes(struct.pack("<41I", *words))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(P, "_oocd", simulated_openocd)
    snapshot_dir = tmp_path / "snapshots"
    result = H.execute_ready_job_sram(
        worklist, tmp_path, "job-ready", sleep_ms=1,
        snapshot_dir=snapshot_dir,
    )
    assert result["status"] == "CLASSIFIED"
    assert result["control_recovered"] is True
    assert result["transport"]["firmware_loads"] == 1
    assert result["transport"]["flash_writes"] == 0
    assert result["snapshots"]["complete"] is True
    assert result["snapshots"]["expected_files"] == 8
    assert len(result["snapshots"]["files"]) == 8
    assert result["snapshots"]["missing"] == []
    manifest = result["snapshots"]["manifest"]
    manifest_path = snapshot_dir / manifest["path"]
    assert manifest_path.stat().st_size == manifest["size"]
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == manifest["sha256"]
    assert len(calls) == 1
    commands = calls[0]
    assert commands[0] == "reset halt"
    assert commands[-2:] == ("reset", "shutdown")
    assert sum("load_image" in item and "0x20000000" in item for item in commands) == 1
    assert sum("load_image" in item and "0x20002000" in item for item in commands) == 3
    assert not any(token in item.lower() for item in commands
                   for token in ("flash", "erase", "option"))

    recovered = H.execute_ready_job_sram(
        worklist, tmp_path, "job-ready", sleep_ms=1,
        initial_reset=False, final_reset=False,
    )
    assert recovered["transport"]["reset_policy"] == {
        "initial_reset": False,
        "final_reset": False,
    }
    assert calls[1][0] == "halt"
    assert calls[1][-2:] == ("halt", "shutdown")


def test_failed_session_persists_hash_bound_partial_snapshots(tmp_path, monkeypatch):
    worklist = _worklist(tmp_path)
    job = H.build_plan(worklist, tmp_path)["jobs"][0]
    record = F.inspect_image(
        tmp_path / job["steps"][0]["image"]["path"], 1)
    monkeypatch.setattr(P, "_require_ag32", lambda: P.EXPECTED_DEVICE_ID)

    def simulated_partial_openocd(commands, timeout):
        for command in commands:
            if not command.startswith("dump_image "):
                continue
            path = Path(re.match(r'dump_image "([^"]+)"', command).group(1))
            if path.name == "fcb-ready.bin":
                path.write_bytes(struct.pack("<16I", *_fcb_mailbox()))
            elif path.name == "campaign-ready.bin":
                path.write_bytes(struct.pack("<41I", *_campaign_mailbox()))
            elif path.name == "fcb-0001.bin":
                path.write_bytes(struct.pack("<16I", *_fcb_mailbox(record)))
            elif path.name == "campaign-0001.bin":
                path.write_bytes(struct.pack(
                    "<41I", *_campaign_mailbox(record, [0, 2])))
        return SimpleNamespace(returncode=1, stdout="partial session", stderr="")

    monkeypatch.setattr(P, "_oocd", simulated_partial_openocd)
    snapshot_dir = tmp_path / "partial-snapshots"
    with pytest.raises(P.DapProgrammingError, match="partial results were ignored"):
        H.execute_ready_job_sram(
            worklist, tmp_path, "job-ready", sleep_ms=1,
            snapshot_dir=snapshot_dir,
        )
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(
        encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["expected_files"] == 8
    assert len(manifest["files"]) == 4
    assert manifest["missing"] == [
        "step-0002-fcb.bin", "step-0002-campaign.bin",
        "step-0003-fcb.bin", "step-0003-campaign.bin",
    ]


def test_campaign_probe_firmware_builds_and_fits_below_mailboxes(tmp_path):
    try:
        gcc = find_riscv_tool("riscv64-unknown-elf-gcc")
        objcopy = find_riscv_tool("riscv64-unknown-elf-objcopy")
    except (RuntimeError, OSError) as exc:
        pytest.skip(str(exc))
    elf = tmp_path / "hil_campaign_probe.elf"
    binary = tmp_path / "hil_campaign_probe.bin"
    subprocess.run([
        gcc, "-march=rv32imac", "-mabi=ilp32", "-Os", "-nostdlib",
        "-ffreestanding", "-fno-builtin", "-ffunction-sections",
        "-fdata-sections", "-I", str(HEADER.parent),
        "-T", str(ROOT / "agamemnon" / "sdk" / "link_sram.ld"),
        "-Wl,--gc-sections", str(ROOT / "agamemnon" / "sdk" / "startup.S"),
        str(ROOT / "qualification" / "hil_campaign_probe.c"), "-o", str(elf),
    ], check=True, capture_output=True, text=True)
    subprocess.run([objcopy, "-O", "binary", str(elf), str(binary)],
                   check=True, capture_output=True, text=True)
    assert 0 < binary.stat().st_size < 0x1000


def test_fabric_read_observer_firmware_uses_dedicated_r3_window(tmp_path):
    try:
        gcc = find_riscv_tool("riscv64-unknown-elf-gcc")
        objcopy = find_riscv_tool("riscv64-unknown-elf-objcopy")
    except (RuntimeError, OSError) as exc:
        pytest.skip(str(exc))
    elf = tmp_path / "fabric_ahb_read_observer_probe.elf"
    binary = tmp_path / "fabric_ahb_read_observer_probe.bin"
    subprocess.run([
        gcc, "-march=rv32imac", "-mabi=ilp32", "-Os", "-nostdlib",
        "-ffreestanding", "-fno-builtin", "-ffunction-sections",
        "-fdata-sections", "-I", str(HEADER.parent),
        "-T", str(ROOT / "qualification" /
                  "link_sram_fabric_observer_r3.ld"),
        "-Wl,--gc-sections", str(ROOT / "agamemnon" / "sdk" / "startup.S"),
        str(ROOT / "qualification" / "fabric_ahb_read_observer_probe.c"),
        "-o", str(elf),
    ], check=True, capture_output=True, text=True)
    subprocess.run([objcopy, "-O", "binary", str(elf), str(binary)],
                   check=True, capture_output=True, text=True)
    assert 0 < binary.stat().st_size <= 0x1000
    elf_bytes = elf.read_bytes()
    assert elf_bytes[:4] == b"\x7fELF"
    assert elf_bytes[4] == 1  # ELFCLASS32
    assert elf_bytes[5] == 1  # little-endian
    entry = int.from_bytes(elf_bytes[24:28], "little")
    assert 0x2001b000 <= entry < 0x2001c000
    source = (ROOT / "qualification" /
              "fabric_ahb_read_observer_probe.c").read_text(encoding="utf-8")
    assert "0x20000000u" in source and "0x20000004u" in source
    assert "0x20000008u" not in source


def test_control_spine_silicon_evidence_is_exact_and_narrow():
    rows = [json.loads(line) for line in (
        ROOT / "qualification" / "fcb_restream_evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    matches = [row for row in rows if row["trial_id"] ==
               "hil-campaign-control-spine-aba-20260826"]
    assert len(matches) == 1
    row = matches[0]
    assert row["result"] == "pass_classified_control_candidate_control_recovery"
    assert row["firmware"] == {
        "source": "qualification/hil_campaign_probe.c",
        "source_sha256":
            "6868a8b7f8da8013b556d06de7a65c0a7c9444f46c7ccebca32b5cc268c05c26",
        "header": "agamemnon/sdk/include/ag32_hil_campaign.h",
        "header_sha256":
            "1a104f7f4f4d3de58f6f2d52f5a95446718c50a2c0815075429977a321963333",
        "binary_size": 786,
        "binary_sha256":
            "0491ea2592c263f9552d1be1c26981f085f81fa9b1835c193a6d9de6b9e76626",
        "loads": 1,
    }
    assert [step["observation"] for step in row["sequence"]] == [
        "0x4147414d", "0x00000000", "0x4147414d",
    ]
    assert [step["classification"] for step in row["sequence"]] == [
        "control_word", "zero_word", "control_word",
    ]
    assert [step["successes"] for step in row["sequence"]] == [1, 2, 3]
    assert all(step["fcb_stat"] == "0x000f0002" for step in row["sequence"])
    assert row["safety"] == {
        "control_first": True,
        "transport": "SRAM-only",
        "flash_writes": 0,
        "por": False,
        "option_bytes": False,
        "board_lock": "released",
        "final_reset": "issued",
    }
    assert "does not qualify arbitrary observers or images" in row["scope"]
