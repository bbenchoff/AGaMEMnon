"""Hash-bound work lists for repeatable silicon witness campaigns.

The public module is deliberately transport-neutral.  It validates and freezes
the firmware, control image, candidate images, and observation classifiers
before a board runner is invoked.  A runner receives an ordered
control/candidate/control-recovery plan and returns observation words; this
module classifies those words without turning FCB acceptance into a functional
verdict.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import tempfile


SCHEMA = 1
KIND = "agamemnon-hil-campaign-worklist"
PLAN_KIND = "agamemnon-hil-campaign-plan"
RESULT_KIND = "agamemnon-hil-campaign-result"
IMAGE_BYTES = 99_944
SRAM_BASE = 0x20000000
SRAM_END = 0x20020000
DEFAULT_FIRMWARE_ADDRESS = SRAM_BASE
DEFAULT_STACK_POINTER = SRAM_END
FCB_MAILBOX_ADDRESS = 0x20001000
FCB_MAILBOX_BYTES = 64
FCB_IMAGE_ADDRESS = 0x20002000

CAMPAIGN_MAILBOX_ADDRESS = 0x20001040
CAMPAIGN_MAILBOX_WORDS = 41
CAMPAIGN_MAGIC = 0x48494C43
CAMPAIGN_VERSION = 1
CAMPAIGN_SENTINEL = 0xC0FFEE48
CAMPAIGN_STATE_READY = 1
CAMPAIGN_STATE_DONE = 3
CAMPAIGN_ERROR_NONE = 0

CAMPAIGN_WORD_MAGIC = 0
CAMPAIGN_WORD_VERSION = 1
CAMPAIGN_WORD_STATE = 2
CAMPAIGN_WORD_RESULT_SEQUENCE = 3
CAMPAIGN_WORD_RESULT_TAG = 4
CAMPAIGN_WORD_COUNT = 5
CAMPAIGN_WORD_ERROR = 6
CAMPAIGN_WORD_RESERVED = 7
CAMPAIGN_WORD_RESULTS = 8
CAMPAIGN_WORD_SENTINEL = 40

JOB_STATES = {"READY", "BLOCKED"}
PRODUCERS = {"mcu-ahb", "fabric-ahb-master", "external-fixture"}
TRANSPORTS = {"fcb-restream-sram", "flash-boot"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HilCampaignError(RuntimeError):
    """The work list, artifact set, or observation failed closed."""


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _manifest_hash(worklist):
    encoded = json.dumps(
        worklist, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    return _sha256_bytes(encoded)


def _require_string(value, context):
    if not isinstance(value, str) or not value.strip():
        raise HilCampaignError("%s must be a nonempty string" % context)
    return value


def _u32(value, context):
    if isinstance(value, str):
        try:
            value = int(value, 0)
        except ValueError as exc:
            raise HilCampaignError("%s is not an integer" % context) from exc
    if not isinstance(value, int) or isinstance(value, bool) or not (0 <= value <= 0xFFFFFFFF):
        raise HilCampaignError("%s must be a 32-bit unsigned integer" % context)
    return value


def _ranges_overlap(first_start, first_end, second_start, second_end):
    return first_start < second_end and second_start < first_end


def _validate_execution(record, firmware, context):
    """Validate one volatile SRAM layout before any target interaction."""
    if record is None:
        record = {}
    if not isinstance(record, dict):
        raise HilCampaignError("%s must be an object" % context)
    unknown = set(record) - {"firmware_address", "stack_pointer"}
    if unknown:
        raise HilCampaignError("%s has unsupported field(s): %s" % (
            context, ", ".join(sorted(unknown))))
    firmware_address = _u32(
        record.get("firmware_address", DEFAULT_FIRMWARE_ADDRESS),
        "%s.firmware_address" % context,
    )
    stack_pointer = _u32(
        record.get("stack_pointer", DEFAULT_STACK_POINTER),
        "%s.stack_pointer" % context,
    )
    if firmware_address & 3:
        raise HilCampaignError("%s.firmware_address must be word-aligned" % context)
    if stack_pointer != SRAM_END:
        raise HilCampaignError(
            "%s.stack_pointer must preserve the qualified top-of-SRAM stack" % context)
    firmware_size = 0 if firmware is None else firmware["size"]
    firmware_end = firmware_address + firmware_size
    if not (SRAM_BASE <= firmware_address <= firmware_end <= SRAM_END):
        raise HilCampaignError("%s.firmware is outside the qualified SRAM" % context)
    reserved = (
        (FCB_MAILBOX_ADDRESS, FCB_MAILBOX_ADDRESS + FCB_MAILBOX_BYTES,
         "FCB mailbox"),
        (CAMPAIGN_MAILBOX_ADDRESS,
         CAMPAIGN_MAILBOX_ADDRESS + CAMPAIGN_MAILBOX_WORDS * 4,
         "campaign mailbox"),
        (FCB_IMAGE_ADDRESS, FCB_IMAGE_ADDRESS + IMAGE_BYTES,
         "staged fabric image"),
    )
    for start, end, label in reserved:
        if _ranges_overlap(firmware_address, firmware_end, start, end):
            raise HilCampaignError("%s.firmware overlaps the %s" % (context, label))
    return {
        "firmware_address": firmware_address,
        "stack_pointer": stack_pointer,
    }


def _resolve_artifact(record, root, context, expected_size=None):
    if not isinstance(record, dict):
        raise HilCampaignError("%s must be an artifact record" % context)
    label = _require_string(record.get("path"), "%s.path" % context)
    portable = Path(label)
    if portable.is_absolute() or "\\" in label:
        raise HilCampaignError("%s.path must be a portable relative path" % context)
    resolved_root = Path(root).resolve()
    resolved = (resolved_root / portable).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise HilCampaignError("%s.path escapes the artifact root" % context) from exc
    if not resolved.is_file():
        raise HilCampaignError("%s is missing: %s" % (context, label))
    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
        raise HilCampaignError("%s.sha256 must be lowercase SHA-256" % context)
    expected_record_size = record.get("size")
    if not isinstance(expected_record_size, int) or isinstance(expected_record_size, bool):
        raise HilCampaignError("%s.size must be an integer" % context)
    data = resolved.read_bytes()
    if len(data) != expected_record_size:
        raise HilCampaignError(
            "%s size changed: expected %d, observed %d"
            % (context, expected_record_size, len(data))
        )
    if expected_size is not None and len(data) != expected_size:
        raise HilCampaignError(
            "%s must be exactly %d bytes" % (context, expected_size)
        )
    observed_hash = _sha256_bytes(data)
    if observed_hash != expected_hash:
        raise HilCampaignError("%s SHA-256 changed" % context)
    return {
        "path": portable.as_posix(),
        "size": len(data),
        "sha256": observed_hash,
    }


def _validate_observation(contract, context):
    if not isinstance(contract, dict):
        raise HilCampaignError("%s must be an observation contract" % context)
    word_count = contract.get("word_count")
    if not isinstance(word_count, int) or isinstance(word_count, bool) or not (1 <= word_count <= 256):
        raise HilCampaignError("%s.word_count must be in 1..256" % context)
    outcomes = contract.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) < 2:
        raise HilCampaignError("%s requires at least two outcome classes" % context)
    outcome_ids = set()
    normalized = []
    for outcome_index, outcome in enumerate(outcomes):
        where = "%s.outcomes[%d]" % (context, outcome_index)
        if not isinstance(outcome, dict):
            raise HilCampaignError("%s must be an object" % where)
        outcome_id = _require_string(outcome.get("id"), "%s.id" % where)
        if outcome_id in outcome_ids:
            raise HilCampaignError("%s has duplicate outcome %s" % (context, outcome_id))
        outcome_ids.add(outcome_id)
        rules = outcome.get("rules")
        if not isinstance(rules, list) or not rules:
            raise HilCampaignError("%s.rules must be nonempty" % where)
        normalized_rules = []
        for rule_index, rule in enumerate(rules):
            rule_where = "%s.rules[%d]" % (where, rule_index)
            if not isinstance(rule, dict):
                raise HilCampaignError("%s must be an object" % rule_where)
            word = rule.get("word")
            if not isinstance(word, int) or isinstance(word, bool) or not (0 <= word < word_count):
                raise HilCampaignError("%s.word is outside the observation" % rule_where)
            mask = _u32(rule.get("mask"), "%s.mask" % rule_where)
            equals = _u32(rule.get("equals"), "%s.equals" % rule_where)
            if mask == 0:
                raise HilCampaignError("%s.mask must select at least one bit" % rule_where)
            normalized_rules.append({
                "word": word,
                "mask": "0x%08x" % mask,
                "equals": "0x%08x" % equals,
            })
        normalized.append({"id": outcome_id, "rules": normalized_rules})
    return {"word_count": word_count, "outcomes": normalized}


def classify_observation(contract, words):
    """Classify exact observation words as one outcome, ambiguous, or unknown."""
    normalized = _validate_observation(contract, "observation")
    if not isinstance(words, (list, tuple)) or len(words) != normalized["word_count"]:
        raise HilCampaignError(
            "observation must contain exactly %d words" % normalized["word_count"]
        )
    observed = [_u32(value, "observation[%d]" % index)
                for index, value in enumerate(words)]
    matches = []
    for outcome in normalized["outcomes"]:
        if all(
            (observed[rule["word"]] & int(rule["mask"], 0))
            == (int(rule["equals"], 0) & int(rule["mask"], 0))
            for rule in outcome["rules"]
        ):
            matches.append(outcome["id"])
    if len(matches) == 1:
        classification = matches[0]
    elif matches:
        classification = "AMBIGUOUS"
    else:
        classification = "UNCLASSIFIED"
    return {
        "classification": classification,
        "matches": matches,
        "words": ["0x%08x" % value for value in observed],
    }


def validate_worklist(worklist, root, *, require_ready=False):
    """Validate schema, denominator, classifiers, and every present artifact."""
    if not isinstance(worklist, dict):
        raise HilCampaignError("work list must be a JSON object")
    if worklist.get("schema") != SCHEMA or worklist.get("kind") != KIND:
        raise HilCampaignError("unsupported HIL campaign schema/kind")
    campaign_id = _require_string(worklist.get("campaign_id"), "campaign_id")
    expected_jobs = worklist.get("expected_jobs")
    if not isinstance(expected_jobs, int) or isinstance(expected_jobs, bool) or expected_jobs < 1:
        raise HilCampaignError("expected_jobs must be positive")
    denominator = worklist.get("design_denominator")
    if (not isinstance(denominator, list) or len(denominator) != expected_jobs
            or any(not isinstance(item, str) or not item for item in denominator)
            or len(set(denominator)) != len(denominator)):
        raise HilCampaignError("design_denominator must contain expected_jobs unique names")
    source_matrix = _resolve_artifact(
        worklist.get("source_matrix"), root, "source_matrix",
    )
    jobs = worklist.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != expected_jobs:
        raise HilCampaignError("jobs must contain exactly expected_jobs entries")

    job_ids = set()
    designs = set()
    candidate_ids = set()
    normalized_jobs = []
    for job_index, job in enumerate(jobs):
        where = "jobs[%d]" % job_index
        if not isinstance(job, dict):
            raise HilCampaignError("%s must be an object" % where)
        job_id = _require_string(job.get("job_id"), "%s.job_id" % where)
        design = _require_string(job.get("design"), "%s.design" % where)
        defect = _require_string(job.get("defect"), "%s.defect" % where)
        if job_id in job_ids or design in designs:
            raise HilCampaignError("job_id and design must be unique")
        job_ids.add(job_id)
        designs.add(design)
        state = job.get("state")
        if state not in JOB_STATES:
            raise HilCampaignError("%s.state must be READY or BLOCKED" % where)
        producer = job.get("producer")
        transport = job.get("transport")
        if producer not in PRODUCERS:
            raise HilCampaignError("%s has unsupported producer" % where)
        if transport not in TRANSPORTS:
            raise HilCampaignError("%s has unsupported transport" % where)
        if job.get("release_status") != "RELEASE_CONTAINED":
            raise HilCampaignError("%s must preserve RELEASE_CONTAINED status" % where)
        blockers = job.get("blockers", [])
        if not isinstance(blockers, list) or any(not isinstance(item, str) or not item for item in blockers):
            raise HilCampaignError("%s.blockers must be a string list" % where)
        if state == "BLOCKED" and not blockers:
            raise HilCampaignError("%s is blocked without a reason" % where)
        if state == "READY" and blockers:
            raise HilCampaignError("%s is ready but still has blockers" % where)
        if require_ready and state != "READY":
            raise HilCampaignError("%s is not READY" % job_id)

        evidence_records = job.get("evidence")
        if not isinstance(evidence_records, list) or not evidence_records:
            raise HilCampaignError("%s.evidence must bind at least one artifact" % where)
        evidence = [
            _resolve_artifact(record, root, "%s.evidence[%d]" % (where, index))
            for index, record in enumerate(evidence_records)
        ]

        firmware = None
        if job.get("firmware") is not None:
            firmware = _resolve_artifact(job["firmware"], root, "%s.firmware" % where)
            if firmware["size"] > 0x1000:
                raise HilCampaignError("%s.firmware exceeds the restream window" % where)
        elif state == "READY":
            raise HilCampaignError("%s READY job has no firmware" % job_id)
        execution = _validate_execution(
            job.get("execution"), firmware, "%s.execution" % where,
        )

        control = job.get("control")
        if not isinstance(control, dict):
            raise HilCampaignError("%s.control must be an object" % where)
        control_contract = _validate_observation(
            control.get("observation"), "%s.control.observation" % where,
        )
        control_image = None
        if control.get("image") is not None:
            control_image = _resolve_artifact(
                control["image"], root, "%s.control.image" % where, IMAGE_BYTES,
            )
        elif state == "READY":
            raise HilCampaignError("%s READY job has no control image" % job_id)

        candidates = job.get("candidates")
        if not isinstance(candidates, list) or not (1 <= len(candidates) <= 2):
            raise HilCampaignError("%s must contain one or two candidates" % where)
        normalized_candidates = []
        for candidate_index, candidate in enumerate(candidates):
            candidate_where = "%s.candidates[%d]" % (where, candidate_index)
            if not isinstance(candidate, dict):
                raise HilCampaignError("%s must be an object" % candidate_where)
            candidate_id = _require_string(
                candidate.get("candidate_id"), "%s.candidate_id" % candidate_where,
            )
            if candidate_id in candidate_ids:
                raise HilCampaignError("candidate_id must be campaign-unique")
            candidate_ids.add(candidate_id)
            hypothesis = _require_string(
                candidate.get("hypothesis"), "%s.hypothesis" % candidate_where,
            )
            intervention = _require_string(
                candidate.get("intervention"), "%s.intervention" % candidate_where,
            )
            discriminator = _require_string(
                candidate.get("discriminator"), "%s.discriminator" % candidate_where,
            )
            observation = _validate_observation(
                candidate.get("observation"), "%s.observation" % candidate_where,
            )
            image = None
            if candidate.get("image") is not None:
                image = _resolve_artifact(
                    candidate["image"], root, "%s.image" % candidate_where, IMAGE_BYTES,
                )
            elif state == "READY":
                raise HilCampaignError("%s READY candidate has no image" % candidate_id)
            normalized_candidates.append({
                "candidate_id": candidate_id,
                "hypothesis": hypothesis,
                "intervention": intervention,
                "discriminator": discriminator,
                "image": image,
                "observation": observation,
            })

        normalized_jobs.append({
            "job_id": job_id,
            "design": design,
            "defect": defect,
            "release_status": "RELEASE_CONTAINED",
            "state": state,
            "producer": producer,
            "transport": transport,
            "evidence": evidence,
            "firmware": firmware,
            "execution": execution,
            "control": {"image": control_image, "observation": control_contract},
            "candidates": normalized_candidates,
            "blockers": blockers,
        })
    if designs != set(denominator):
        raise HilCampaignError("jobs do not exactly cover design_denominator")
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "campaign_id": campaign_id,
        "worklist_sha256": _manifest_hash(worklist),
        "source_matrix": source_matrix,
        "expected_jobs": expected_jobs,
        "design_denominator": list(denominator),
        "jobs": normalized_jobs,
    }


def build_plan(worklist, root, *, require_ready=False):
    """Build ordered control/candidate/control-recovery steps for every job."""
    checked = validate_worklist(worklist, root, require_ready=require_ready)
    planned_jobs = []
    for job in checked["jobs"]:
        steps = []
        if job["state"] == "READY":
            sequence = 1
            steps.append({
                "sequence": sequence, "role": "control",
                "image": job["control"]["image"],
                "observation": job["control"]["observation"],
            })
            for candidate in job["candidates"]:
                sequence += 1
                steps.append({
                    "sequence": sequence, "role": "candidate",
                    "candidate_id": candidate["candidate_id"],
                    "image": candidate["image"],
                    "observation": candidate["observation"],
                })
            sequence += 1
            steps.append({
                "sequence": sequence, "role": "control-recovery",
                "image": job["control"]["image"],
                "observation": job["control"]["observation"],
            })
        planned_jobs.append({
            "job_id": job["job_id"],
            "design": job["design"],
            "defect": job["defect"],
            "release_status": job["release_status"],
            "state": job["state"],
            "producer": job["producer"],
            "transport": job["transport"],
            "evidence": job["evidence"],
            "firmware": job["firmware"],
            "execution": job["execution"],
            "candidates": job["candidates"],
            "steps": steps,
            "blockers": job["blockers"],
        })
    return {
        "schema": SCHEMA,
        "kind": PLAN_KIND,
        "campaign_id": checked["campaign_id"],
        "worklist_sha256": checked["worklist_sha256"],
        "source_matrix": checked["source_matrix"],
        "job_count": len(planned_jobs),
        "candidate_count": sum(len(job["candidates"]) for job in checked["jobs"]),
        "ready_jobs": sum(job["state"] == "READY" for job in planned_jobs),
        "blocked_jobs": sum(job["state"] == "BLOCKED" for job in planned_jobs),
        "jobs": planned_jobs,
        "claim_limit": (
            "FCB acceptance and classifier output are evidence records, not automatic "
            "root-cause, repair, parity, or release-surface promotion"
        ),
    }


def run_ready_job(plan, job_id, executor):
    """Run one READY job through an injected board transport and classify it.

    ``executor(job)`` must return a mapping from sequence number (integer or
    decimal string) to the exact observation-word list captured after that
    step.  The final control must classify exactly as the first control.
    """
    if plan.get("kind") != PLAN_KIND:
        raise HilCampaignError("run_ready_job requires a validated campaign plan")
    matching = [job for job in plan.get("jobs", []) if job.get("job_id") == job_id]
    if len(matching) != 1:
        raise HilCampaignError("job_id is absent or not unique")
    job = matching[0]
    if job["state"] != "READY":
        raise HilCampaignError("%s is not READY" % job_id)
    observations = executor(job)
    if not isinstance(observations, dict):
        raise HilCampaignError("executor must return a sequence-to-words mapping")
    results = []
    for step in job["steps"]:
        sequence = step["sequence"]
        words = observations.get(sequence, observations.get(str(sequence)))
        if words is None:
            raise HilCampaignError("executor omitted sequence %d" % sequence)
        result = classify_observation(step["observation"], words)
        result.update({"sequence": sequence, "role": step["role"]})
        if "candidate_id" in step:
            result["candidate_id"] = step["candidate_id"]
        results.append(result)
    controls = [result for result in results if result["role"] in
                ("control", "control-recovery")]
    control_recovered = (
        len(controls) == 2
        and controls[0]["classification"] not in ("AMBIGUOUS", "UNCLASSIFIED")
        and controls[0]["classification"] == controls[1]["classification"]
    )
    return {
        "schema": SCHEMA,
        "kind": RESULT_KIND,
        "campaign_id": plan["campaign_id"],
        "worklist_sha256": plan["worklist_sha256"],
        "job_id": job_id,
        "release_status": job["release_status"],
        "control_recovered": control_recovered,
        "status": "CLASSIFIED" if control_recovered else "CONTROL_FAILED",
        "steps": results,
        "claim_limit": plan["claim_limit"],
    }


def _unpack_campaign_mailbox(path):
    data = Path(path).read_bytes()
    if len(data) != CAMPAIGN_MAILBOX_WORDS * 4:
        raise HilCampaignError("campaign mailbox snapshot is not exactly 164 bytes")
    return struct.unpack("<41I", data)


def validate_campaign_ready(words):
    if len(words) != CAMPAIGN_MAILBOX_WORDS:
        raise HilCampaignError("campaign mailbox snapshot is not 41 words")
    if (words[CAMPAIGN_WORD_MAGIC], words[CAMPAIGN_WORD_VERSION],
            words[CAMPAIGN_WORD_STATE], words[CAMPAIGN_WORD_RESULT_SEQUENCE],
            words[CAMPAIGN_WORD_RESERVED], words[CAMPAIGN_WORD_SENTINEL]) != (
                CAMPAIGN_MAGIC, CAMPAIGN_VERSION, CAMPAIGN_STATE_READY,
                0, 0, CAMPAIGN_SENTINEL):
        raise HilCampaignError("campaign firmware did not publish a clean READY mailbox")
    if words[CAMPAIGN_WORD_COUNT] != 0 or words[CAMPAIGN_WORD_ERROR] != 0:
        raise HilCampaignError("campaign READY mailbox contains a stale result")


def decode_campaign_result(words, record, expected_count):
    if len(words) != CAMPAIGN_MAILBOX_WORDS:
        raise HilCampaignError("campaign mailbox snapshot is not 41 words")
    if words[CAMPAIGN_WORD_MAGIC] != CAMPAIGN_MAGIC or words[CAMPAIGN_WORD_VERSION] != CAMPAIGN_VERSION:
        raise HilCampaignError("campaign mailbox magic/version mismatch")
    if words[CAMPAIGN_WORD_SENTINEL] != CAMPAIGN_SENTINEL or words[CAMPAIGN_WORD_RESERVED] != 0:
        raise HilCampaignError("campaign mailbox sentinel/reserved field mismatch")
    if words[CAMPAIGN_WORD_RESULT_SEQUENCE] != record.sequence:
        raise HilCampaignError("campaign observer did not complete sequence %d" % record.sequence)
    if words[CAMPAIGN_WORD_RESULT_TAG] != record.tag:
        raise HilCampaignError("campaign observer returned the wrong image tag")
    if (words[CAMPAIGN_WORD_STATE] != CAMPAIGN_STATE_DONE
            or words[CAMPAIGN_WORD_ERROR] != CAMPAIGN_ERROR_NONE):
        raise HilCampaignError("campaign observer reported an error")
    count = words[CAMPAIGN_WORD_COUNT]
    if count != expected_count:
        raise HilCampaignError(
            "campaign observer returned %d words; contract requires %d"
            % (count, expected_count)
        )
    if any(words[CAMPAIGN_WORD_RESULTS + count:CAMPAIGN_WORD_SENTINEL]):
        raise HilCampaignError("campaign observer left nonzero words beyond its result")
    return list(words[CAMPAIGN_WORD_RESULTS:CAMPAIGN_WORD_RESULTS + count])


def execute_ready_job_sram(
        worklist, root, job_id, *, sleep_ms=500,
        initial_reset=True, final_reset=True):
    """Execute one READY FCB-restream job in one volatile DAP session.

    ``initial_reset=False`` is the fail-safe recovery form for a hart already
    halted through the debug module; it prevents an unsafe resident fabric
    image from running between reset release and the first control restream.
    ``final_reset=False`` leaves the recovered control and hart halted.
    """
    if sleep_ms < 1:
        raise ValueError("sleep_ms must be positive")
    if not isinstance(initial_reset, bool) or not isinstance(final_reset, bool):
        raise TypeError("initial_reset and final_reset must be bool")
    from . import fcb_restream as restream
    from . import program as programmer

    root = Path(root).resolve()
    plan = build_plan(worklist, root)
    matching = [job for job in plan["jobs"] if job["job_id"] == job_id]
    if len(matching) != 1:
        raise HilCampaignError("job_id is absent or not unique")
    job = matching[0]
    if job["state"] != "READY":
        raise HilCampaignError("%s is not READY" % job_id)
    if job["transport"] != "fcb-restream-sram":
        raise HilCampaignError("%s is not an SRAM-restream job" % job_id)

    def current_bytes(record, context):
        data = (root / record["path"]).read_bytes()
        if len(data) != record["size"] or _sha256_bytes(data) != record["sha256"]:
            raise HilCampaignError("%s changed after campaign planning" % context)
        return data

    with tempfile.TemporaryDirectory(prefix="agamemnon-hil-campaign-") as temporary:
        temporary_path = Path(temporary)
        firmware = temporary_path / "firmware.bin"
        firmware.write_bytes(current_bytes(job["firmware"], "firmware"))
        staged_images = []
        records = []
        for step in job["steps"]:
            staged = temporary_path / ("image-%04d.bin" % step["sequence"])
            staged.write_bytes(current_bytes(step["image"], "sequence %d image" % step["sequence"]))
            staged_images.append(staged)
            records.append(restream.inspect_image(staged, step["sequence"]))

        programmer._require_ag32()
        fcb_ready = temporary_path / "fcb-ready.bin"
        campaign_ready = temporary_path / "campaign-ready.bin"
        fcb_results = [temporary_path / ("fcb-%04d.bin" % record.sequence)
                       for record in records]
        campaign_results = [temporary_path / ("campaign-%04d.bin" % record.sequence)
                            for record in records]
        commands = [
            "reset halt" if initial_reset else "halt",
            "mww %#x 0 %d" % (restream.MAILBOX_ADDRESS, restream.MAILBOX_WORDS),
            "mww %#x 0 %d" % (CAMPAIGN_MAILBOX_ADDRESS, CAMPAIGN_MAILBOX_WORDS),
            "load_image %s %#x bin" % (
                programmer._tcl_path(firmware),
                job["execution"]["firmware_address"]),
            "reg pc %#x" % job["execution"]["firmware_address"],
            "reg sp %#x" % job["execution"]["stack_pointer"],
            "resume", "sleep 50", "halt",
            "dump_image %s %#x %d" % (
                programmer._tcl_path(fcb_ready), restream.MAILBOX_ADDRESS,
                restream.MAILBOX_WORDS * 4),
            "dump_image %s %#x %d" % (
                programmer._tcl_path(campaign_ready), CAMPAIGN_MAILBOX_ADDRESS,
                CAMPAIGN_MAILBOX_WORDS * 4),
            restream._tcl_require_word(
                restream.MAILBOX_ADDRESS + 4 * restream.WORD_MAGIC,
                restream.MAGIC, "READY magic"),
            restream._tcl_require_word(
                restream.MAILBOX_ADDRESS + 4 * restream.WORD_STATE,
                restream.STATE_READY, "READY state"),
            restream._tcl_require_word(
                CAMPAIGN_MAILBOX_ADDRESS + 4 * CAMPAIGN_WORD_MAGIC,
                CAMPAIGN_MAGIC, "campaign READY magic"),
            restream._tcl_require_word(
                CAMPAIGN_MAILBOX_ADDRESS + 4 * CAMPAIGN_WORD_STATE,
                CAMPAIGN_STATE_READY, "campaign READY state"),
        ]
        for step, record, staged, fcb_snapshot, campaign_snapshot in zip(
                job["steps"], records, staged_images, fcb_results, campaign_results):
            commands.append(
                "load_image %s %#x bin" % (
                    programmer._tcl_path(staged), restream.IMAGE_ADDRESS)
            )
            commands.extend("mww %#x %#x" % item for item in restream.mailbox_writes(record))
            commands.extend((
                "resume", "sleep %d" % sleep_ms, "halt",
                "dump_image %s %#x %d" % (
                    programmer._tcl_path(fcb_snapshot), restream.MAILBOX_ADDRESS,
                    restream.MAILBOX_WORDS * 4),
                "dump_image %s %#x %d" % (
                    programmer._tcl_path(campaign_snapshot), CAMPAIGN_MAILBOX_ADDRESS,
                    CAMPAIGN_MAILBOX_WORDS * 4),
                restream._tcl_require_word(
                    restream.MAILBOX_ADDRESS + 4 * restream.WORD_RESULT_SEQUENCE,
                    record.sequence, "result sequence"),
                restream._tcl_require_word(
                    restream.MAILBOX_ADDRESS + 4 * restream.WORD_RESULT_TAG,
                    record.tag, "result tag"),
                restream._tcl_require_word(
                    restream.MAILBOX_ADDRESS + 4 * restream.WORD_STATE,
                    restream.STATE_DONE, "result state"),
                restream._tcl_require_word(
                    restream.MAILBOX_ADDRESS + 4 * restream.WORD_FCB_STATUS,
                    restream.FCB_STAT_OK, "FCB status"),
                restream._tcl_require_word(
                    CAMPAIGN_MAILBOX_ADDRESS + 4 * CAMPAIGN_WORD_RESULT_SEQUENCE,
                    record.sequence, "campaign result sequence"),
                restream._tcl_require_word(
                    CAMPAIGN_MAILBOX_ADDRESS + 4 * CAMPAIGN_WORD_RESULT_TAG,
                    record.tag, "campaign result tag"),
                restream._tcl_require_word(
                    CAMPAIGN_MAILBOX_ADDRESS + 4 * CAMPAIGN_WORD_STATE,
                    CAMPAIGN_STATE_DONE, "campaign result state"),
                restream._tcl_require_word(
                    CAMPAIGN_MAILBOX_ADDRESS + 4 * CAMPAIGN_WORD_COUNT,
                    step["observation"]["word_count"], "campaign word count"),
                restream._tcl_require_word(
                    CAMPAIGN_MAILBOX_ADDRESS + 4 * CAMPAIGN_WORD_ERROR,
                    CAMPAIGN_ERROR_NONE, "campaign error"),
            ))
        commands.extend(("reset" if final_reset else "halt", "shutdown"))
        result = programmer._oocd(
            commands, timeout=max(180, 30 + len(records) * (sleep_ms // 1000 + 10)),
        )
        if result.returncode:
            diagnostic = (result.stdout + result.stderr)[-4000:].strip()
            raise programmer.DapProgrammingError(
                "HIL campaign session failed; target state is unknown and "
                "partial results were ignored%s" %
                (("\nOpenOCD tail:\n" + diagnostic) if diagnostic else "")
            )

        restream.validate_ready(restream._unpack_mailbox(fcb_ready))
        validate_campaign_ready(_unpack_campaign_mailbox(campaign_ready))
        transport_outcomes = []
        observations = {}
        for step, record, fcb_snapshot, campaign_snapshot in zip(
                job["steps"], records, fcb_results, campaign_results):
            transport = restream.decode_result(
                restream._unpack_mailbox(fcb_snapshot), record)
            if not transport["passed"]:
                raise HilCampaignError("FCB restream sequence %d failed" % record.sequence)
            transport_outcomes.append(transport)
            observations[record.sequence] = decode_campaign_result(
                _unpack_campaign_mailbox(campaign_snapshot), record,
                step["observation"]["word_count"],
            )

    classified = run_ready_job(plan, job_id, lambda unused: observations)
    classified["transport"] = {
        "kind": "fcb-restream-sram",
        "firmware_loads": 1,
        "flash_writes": 0,
        "execution": {
            "firmware_address": "0x%08x" % job["execution"]["firmware_address"],
            "stack_pointer": "0x%08x" % job["execution"]["stack_pointer"],
        },
        "reset_policy": {
            "initial_reset": initial_reset,
            "final_reset": final_reset,
        },
        "outcomes": transport_outcomes,
    }
    return classified


def load_worklist(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_campaign(args):
    worklist = load_worklist(args.worklist)
    root = Path(args.root) if args.root else Path(args.worklist).resolve().parent
    execute_job = getattr(args, "execute_job", None)
    if execute_job:
        result = execute_ready_job_sram(
            worklist, root, execute_job, sleep_ms=getattr(args, "sleep", 500),
        )
    else:
        result = build_plan(worklist, root, require_ready=args.require_ready)
    print(json.dumps(result, indent=2, sort_keys=True))
