"""Plan and, only with an explicit gate, run one-firmware FCB restreams.

The default operation is desk-only: validate every full image, bind it to a
SHA-256 digest, and print the mailbox plan.  The optional execution path uses
volatile SRAM and the open DAP transport; it contains no flash command.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import tempfile


MAILBOX_ADDRESS = 0x20001000
IMAGE_ADDRESS = 0x20002000
IMAGE_BYTES = 99944
IMAGE_WORDS = 24986
MAILBOX_WORDS = 16

MAGIC = 0x46434252
VERSION = 1
SENTINEL = 0xC0FFEE46

STATE_READY = 1
STATE_BUSY = 2
STATE_DONE = 3
STATE_ERROR = 4
STATE_REJECTED = 5

COMMAND_CONFIGURE = 1

RESULT_NONE = 0
RESULT_OK = 1
RESULT_BAD_COMMAND = 2
RESULT_BAD_LENGTH = 3
RESULT_BAD_ADDRESS = 4
RESULT_FCB_STATUS = 5
RESULT_FAULT_LATCHED = 6
FCB_STAT_OK = 0x000F0002

WORD_MAGIC = 0
WORD_VERSION = 1
WORD_STATE = 2
WORD_REQUEST_SEQUENCE = 3
WORD_COMMAND = 4
WORD_IMAGE_WORDS = 5
WORD_IMAGE_TAG = 6
WORD_RESULT_SEQUENCE = 7
WORD_RESULT_CODE = 8
WORD_FCB_STATUS = 9
WORD_RESULT_TAG = 10
WORD_ATTEMPTS = 11
WORD_SUCCESSES = 12
WORD_REJECTED = 13
WORD_RESERVED = 14
WORD_SENTINEL = 15


class FcbRestreamError(RuntimeError):
    """The restream protocol or a target result failed closed."""


@dataclass(frozen=True)
class RestreamImage:
    path: str
    label: str
    sequence: int
    size: int
    sha256: str
    tag: int

    def public_record(self):
        return {
            "path": self.label,
            "sequence": self.sequence,
            "size": self.size,
            "sha256": self.sha256,
            "tag": "0x%08x" % self.tag,
        }


def _portable_label(path):
    value = Path(path)
    try:
        relative = value.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        return value.name
    return relative.as_posix()


def inspect_image(path, sequence):
    if not (1 <= sequence <= 0xFFFFFFFF):
        raise ValueError("restream sequence must be in 1..0xffffffff")
    source = Path(path)
    data = source.read_bytes()
    if len(data) != IMAGE_BYTES:
        raise ValueError(
            "%s is %d bytes; FCB restream requires exactly %d"
            % (_portable_label(source), len(data), IMAGE_BYTES)
        )
    digest = hashlib.sha256(data).hexdigest()
    return RestreamImage(
        str(source), _portable_label(source), sequence, len(data), digest,
        int(digest[:8], 16),
    )


def _build_plan(firmware_path, firmware_data, records):
    firmware_size = len(firmware_data)
    if firmware_size <= 0 or firmware_size > 0x1000:
        raise ValueError("restream firmware must be nonempty and at most 4096 bytes")
    if not records:
        raise ValueError("at least one fabric image is required")
    return {
        "schema": 1,
        "kind": "agamemnon-fcb-restream-plan",
        "qualification": "desk-built; consecutive-image silicon trial pending",
        "execution_gate": "explicit --execute-sram plus --human-approved",
        "flash_writes": 0,
        "layout": {
            "firmware": "0x20000000",
            "mailbox": "0x%08x" % MAILBOX_ADDRESS,
            "image": "0x%08x" % IMAGE_ADDRESS,
            "image_bytes": IMAGE_BYTES,
        },
        "firmware": {
            "path": _portable_label(firmware_path),
            "size": firmware_size,
            "sha256": hashlib.sha256(firmware_data).hexdigest(),
            "loads": 1,
        },
        "images": [record.public_record() for record in records],
    }


def build_plan(firmware, images):
    firmware_path = Path(firmware)
    firmware_data = firmware_path.read_bytes()
    records = tuple(inspect_image(path, index + 1) for index, path in enumerate(images))
    return _build_plan(firmware_path, firmware_data, records)


def mailbox_writes(record):
    """Return ordered mailbox writes; request_sequence is published last."""
    return (
        (MAILBOX_ADDRESS + 4 * WORD_COMMAND, COMMAND_CONFIGURE),
        (MAILBOX_ADDRESS + 4 * WORD_IMAGE_WORDS, IMAGE_WORDS),
        (MAILBOX_ADDRESS + 4 * WORD_IMAGE_TAG, record.tag),
        (MAILBOX_ADDRESS + 4 * WORD_REQUEST_SEQUENCE, record.sequence),
    )


def _tcl_require_word(address, expected, label):
    """Build an in-session OpenOCD assertion that aborts later mutations."""
    return (
        'if {[lindex [read_memory %#x 32 1] 0] != %#x} '
        '{ error "FCB restream %s mismatch" }'
        % (address, expected, label)
    )


def _unpack_mailbox(path):
    data = Path(path).read_bytes()
    if len(data) != MAILBOX_WORDS * 4:
        raise FcbRestreamError("mailbox snapshot is not exactly 64 bytes")
    return struct.unpack("<16I", data)


def validate_ready(words):
    if len(words) != MAILBOX_WORDS:
        raise FcbRestreamError("mailbox snapshot is not 16 words")
    expected = (MAGIC, VERSION, STATE_READY, SENTINEL)
    observed = (words[WORD_MAGIC], words[WORD_VERSION], words[WORD_STATE],
                words[WORD_SENTINEL])
    if observed != expected or words[WORD_RESULT_SEQUENCE] != 0:
        raise FcbRestreamError("restream firmware did not publish a clean READY mailbox")


def decode_result(words, record):
    if len(words) != MAILBOX_WORDS:
        raise FcbRestreamError("mailbox snapshot is not 16 words")
    if words[WORD_MAGIC] != MAGIC or words[WORD_VERSION] != VERSION:
        raise FcbRestreamError("restream mailbox magic/version mismatch")
    if words[WORD_SENTINEL] != SENTINEL or words[WORD_RESERVED] != 0:
        raise FcbRestreamError("restream mailbox sentinel/reserved field mismatch")
    if words[WORD_RESULT_SEQUENCE] != record.sequence:
        raise FcbRestreamError(
            "request %d did not complete (result sequence %d)"
            % (record.sequence, words[WORD_RESULT_SEQUENCE])
        )
    if words[WORD_RESULT_TAG] != record.tag:
        raise FcbRestreamError("request %d returned the wrong image tag" % record.sequence)
    passed = (
        words[WORD_STATE] == STATE_DONE
        and words[WORD_RESULT_CODE] == RESULT_OK
        and words[WORD_FCB_STATUS] == FCB_STAT_OK
    )
    return {
        "sequence": record.sequence,
        "sha256": record.sha256,
        "tag": "0x%08x" % record.tag,
        "state": words[WORD_STATE],
        "result_code": words[WORD_RESULT_CODE],
        "fcb_status": "0x%08x" % words[WORD_FCB_STATUS],
        "attempts": words[WORD_ATTEMPTS],
        "successes": words[WORD_SUCCESSES],
        "rejected": words[WORD_REJECTED],
        "passed": passed,
    }


def execute_restream(firmware, images, *, sleep_ms=500, human_approved=False):
    """Run the SRAM-only protocol once; never retry and never issue flash commands."""
    if not human_approved:
        raise FcbRestreamError("hardware execution requires explicit human approval")
    if sleep_ms < 1:
        raise ValueError("sleep_ms must be positive")

    from . import program as programmer

    firmware_path = Path(firmware)
    firmware_data = firmware_path.read_bytes()
    records = tuple(inspect_image(path, index + 1) for index, path in enumerate(images))
    plan = _build_plan(firmware_path, firmware_data, records)

    with tempfile.TemporaryDirectory(prefix="agamemnon-fcb-restream-") as temporary:
        temporary_path = Path(temporary)
        staged_firmware = temporary_path / "firmware.bin"
        current_firmware_data = firmware_path.read_bytes()
        if hashlib.sha256(current_firmware_data).hexdigest() != plan["firmware"]["sha256"]:
            raise FcbRestreamError("firmware changed after the restream plan was built")
        staged_firmware.write_bytes(current_firmware_data)
        staged_images = []
        for record in records:
            data = Path(record.path).read_bytes()
            if len(data) != record.size or hashlib.sha256(data).hexdigest() != record.sha256:
                raise FcbRestreamError(
                    "%s changed after the restream plan was built" % record.label
                )
            staged = temporary_path / ("image-%04d.bin" % record.sequence)
            staged.write_bytes(data)
            staged_images.append(staged)

        # Validate and freeze every input before the first target interaction.
        programmer._require_ag32()
        ready_path = Path(temporary) / "ready.bin"
        result_paths = [Path(temporary) / ("result-%04d.bin" % r.sequence)
                        for r in records]
        commands = [
            "reset halt",
            "mww %#x 0 %d" % (MAILBOX_ADDRESS, MAILBOX_WORDS),
            "load_image %s %#x bin" % (
                programmer._tcl_path(staged_firmware), programmer.SRAM_STUB),
            "reg pc %#x" % programmer.SRAM_STUB,
            "reg sp %#x" % programmer.SRAM_SP,
            "resume", "sleep 50", "halt",
            "dump_image %s %#x %d" % (
                programmer._tcl_path(ready_path), MAILBOX_ADDRESS, MAILBOX_WORDS * 4),
            _tcl_require_word(
                MAILBOX_ADDRESS + 4 * WORD_MAGIC, MAGIC, "READY magic"),
            _tcl_require_word(
                MAILBOX_ADDRESS + 4 * WORD_VERSION, VERSION, "READY version"),
            _tcl_require_word(
                MAILBOX_ADDRESS + 4 * WORD_STATE, STATE_READY, "READY state"),
            _tcl_require_word(
                MAILBOX_ADDRESS + 4 * WORD_RESULT_SEQUENCE, 0, "READY sequence"),
            _tcl_require_word(
                MAILBOX_ADDRESS + 4 * WORD_SENTINEL, SENTINEL, "READY sentinel"),
        ]
        for record, staged, snapshot in zip(records, staged_images, result_paths):
            commands.append(
                "load_image %s %#x bin" % (
                    programmer._tcl_path(staged), IMAGE_ADDRESS)
            )
            commands.extend("mww %#x %#x" % item for item in mailbox_writes(record))
            commands.extend((
                "resume", "sleep %d" % sleep_ms, "halt",
                "dump_image %s %#x %d" % (
                    programmer._tcl_path(snapshot), MAILBOX_ADDRESS, MAILBOX_WORDS * 4),
                _tcl_require_word(
                    MAILBOX_ADDRESS + 4 * WORD_RESULT_SEQUENCE,
                    record.sequence, "result sequence"),
                _tcl_require_word(
                    MAILBOX_ADDRESS + 4 * WORD_RESULT_TAG,
                    record.tag, "result tag"),
                _tcl_require_word(
                    MAILBOX_ADDRESS + 4 * WORD_STATE,
                    STATE_DONE, "result state"),
                _tcl_require_word(
                    MAILBOX_ADDRESS + 4 * WORD_RESULT_CODE,
                    RESULT_OK, "result code"),
                _tcl_require_word(
                    MAILBOX_ADDRESS + 4 * WORD_FCB_STATUS,
                    FCB_STAT_OK, "FCB status"),
            ))
        commands.extend(("reset", "shutdown"))

        result = programmer._oocd(
            commands, timeout=max(180, 30 + len(records) * (sleep_ms // 1000 + 10))
        )
        if result.returncode:
            raise programmer.DapProgrammingError(
                "FCB restream session failed; target state is unknown and partial results were ignored"
            )
        validate_ready(_unpack_mailbox(ready_path))
        outcomes = [decode_result(_unpack_mailbox(path), record)
                    for path, record in zip(result_paths, records)]

    failed = next((item for item in outcomes if not item["passed"]), None)
    if failed:
        raise FcbRestreamError(
            "request %d failed closed: result=%d FCB=%s"
            % (failed["sequence"], failed["result_code"], failed["fcb_status"])
        )
    return {"plan": plan, "outcomes": outcomes}


def cmd_restream(args):
    if args.execute_sram:
        result = execute_restream(
            args.firmware, args.images, sleep_ms=args.sleep,
            human_approved=args.human_approved,
        )
    else:
        if args.human_approved:
            raise FcbRestreamError("--human-approved requires --execute-sram")
        result = build_plan(args.firmware, args.images)
    print(json.dumps(result, indent=2, sort_keys=True))
