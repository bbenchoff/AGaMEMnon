from pathlib import Path
import json
import re
import struct
from types import SimpleNamespace

import pytest

from agamemnon import fcb_restream as R
from agamemnon import program as P
from agamemnon.project import find_riscv_tool


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "agamemnon" / "sdk" / "include" / "ag32_fcb_restream.h"
DEVICE_HEADER = ROOT / "agamemnon" / "sdk" / "include" / "ag32.h"


def _image(path, fill):
    path.write_bytes(bytes([fill]) * R.IMAGE_BYTES)
    return path


def _mailbox(*, state=R.STATE_READY, sequence=0, result=R.RESULT_NONE,
             status=0, tag=0, attempts=0, successes=0, rejected=0):
    words = [0] * R.MAILBOX_WORDS
    words[R.WORD_MAGIC] = R.MAGIC
    words[R.WORD_VERSION] = R.VERSION
    words[R.WORD_STATE] = state
    words[R.WORD_RESULT_SEQUENCE] = sequence
    words[R.WORD_RESULT_CODE] = result
    words[R.WORD_FCB_STATUS] = status
    words[R.WORD_RESULT_TAG] = tag
    words[R.WORD_ATTEMPTS] = attempts
    words[R.WORD_SUCCESSES] = successes
    words[R.WORD_REJECTED] = rejected
    words[R.WORD_SENTINEL] = R.SENTINEL
    return words


def test_protocol_constants_match_the_packaged_header():
    text = HEADER.read_text(encoding="utf-8")
    expected = {
        "MAILBOX_ADDRESS": R.MAILBOX_ADDRESS,
        "IMAGE_ADDRESS": R.IMAGE_ADDRESS,
        "IMAGE_BYTES": R.IMAGE_BYTES,
        "IMAGE_WORDS": R.IMAGE_WORDS,
        "MAGIC": R.MAGIC,
        "VERSION": R.VERSION,
        "SENTINEL": R.SENTINEL,
    }
    for suffix, value in expected.items():
        match = re.search(
            r"^#define AG32_FCB_RESTREAM_%s\s+(0x[0-9a-fA-F]+|[0-9]+)u" % suffix,
            text, re.MULTILINE,
        )
        assert match and int(match.group(1), 0) == value


def test_fcb_stream_resets_the_apb_endpoint_before_auto_mode():
    text = DEVICE_HEADER.read_text(encoding="utf-8")
    configure = text[text.index("static inline uint32_t ag32_fcb_config"):]
    enable = configure.index("SYSCTL_APBCLK |= APBCLK_FCB")
    reset = configure.index("ag32_apb_reset(AG32_APB_FCB0)")
    auto = configure.index("FCB_CTRL = FCB_CTRL_AUTO")
    assert enable < reset < auto


def test_plan_is_one_firmware_load_and_hash_binds_every_exact_image(tmp_path):
    firmware = tmp_path / "restream.bin"
    firmware.write_bytes(b"firmware")
    first = _image(tmp_path / "first.img", 0x11)
    second = _image(tmp_path / "second.img", 0x22)
    plan = R.build_plan(firmware, [first, second])
    assert plan["flash_writes"] == 0
    assert plan["firmware"]["loads"] == 1
    assert [row["sequence"] for row in plan["images"]] == [1, 2]
    assert len({row["sha256"] for row in plan["images"]}) == 2
    assert all(row["size"] == R.IMAGE_BYTES for row in plan["images"])


def test_plan_refuses_empty_oversized_firmware_and_wrong_image_length(tmp_path):
    firmware = tmp_path / "restream.bin"
    firmware.write_bytes(b"")
    image = _image(tmp_path / "image.img", 0x33)
    with pytest.raises(ValueError, match="nonempty"):
        R.build_plan(firmware, [image])
    firmware.write_bytes(b"x" * 0x1001)
    with pytest.raises(ValueError, match="4096"):
        R.build_plan(firmware, [image])
    firmware.write_bytes(b"ok")
    image.write_bytes(b"short")
    with pytest.raises(ValueError, match="exactly 99944"):
        R.build_plan(firmware, [image])


def test_request_sequence_is_the_last_mailbox_write(tmp_path):
    record = R.inspect_image(_image(tmp_path / "image.img", 0x44), 7)
    writes = R.mailbox_writes(record)
    assert writes[-1] == (
        R.MAILBOX_ADDRESS + 4 * R.WORD_REQUEST_SEQUENCE, 7,
    )
    assert writes[:-1] == (
        (R.MAILBOX_ADDRESS + 4 * R.WORD_COMMAND, R.COMMAND_CONFIGURE),
        (R.MAILBOX_ADDRESS + 4 * R.WORD_IMAGE_WORDS, R.IMAGE_WORDS),
        (R.MAILBOX_ADDRESS + 4 * R.WORD_IMAGE_TAG, record.tag),
    )


def test_openocd_assertion_reads_one_word_and_raises_on_mismatch():
    command = R._tcl_require_word(R.MAILBOX_ADDRESS, R.MAGIC, "READY magic")
    assert command == (
        'if {[lindex [read_memory 0x20001000 32 1] 0] != 0x46434252} '
        '{ error "FCB restream READY magic mismatch" }'
    )


def test_mailbox_validation_requires_exact_completion_and_fcb_status(tmp_path):
    record = R.inspect_image(_image(tmp_path / "image.img", 0x55), 1)
    R.validate_ready(_mailbox())
    passed = R.decode_result(_mailbox(
        state=R.STATE_DONE, sequence=1, result=R.RESULT_OK,
        status=R.FCB_STAT_OK, tag=record.tag, attempts=1, successes=1,
    ), record)
    assert passed["passed"] is True
    refused = R.decode_result(_mailbox(
        state=R.STATE_REJECTED, sequence=1, result=R.RESULT_BAD_LENGTH,
        status=0, tag=record.tag, attempts=1, rejected=1,
    ), record)
    assert refused["passed"] is False
    with pytest.raises(R.FcbRestreamError, match="did not complete"):
        R.decode_result(_mailbox(sequence=0), record)


def test_plan_path_never_touches_identity_or_transport(tmp_path, monkeypatch):
    firmware = tmp_path / "restream.bin"
    firmware.write_bytes(b"firmware")
    image = _image(tmp_path / "image.img", 0x66)

    def forbidden(*args, **kwargs):
        raise AssertionError("hardware must not be touched")

    monkeypatch.setattr(P, "_require_ag32", forbidden)
    monkeypatch.setattr(P, "_oocd", forbidden)
    args = SimpleNamespace(
        execute_sram=False, firmware=firmware, images=[image], sleep=1,
    )
    R.cmd_restream(args)


def test_explicit_execution_is_one_session_sram_only_and_never_retries(tmp_path, monkeypatch):
    firmware = tmp_path / "restream.bin"
    firmware.write_bytes(b"firmware")
    images = [
        _image(tmp_path / "first.img", 0x77),
        _image(tmp_path / "second.img", 0x88),
    ]
    records = [R.inspect_image(path, index + 1) for index, path in enumerate(images)]
    calls = []
    monkeypatch.setattr(P, "_require_ag32", lambda: P.EXPECTED_DEVICE_ID)

    def simulated_openocd(commands, timeout):
        calls.append(tuple(commands))
        dumps = [command for command in commands if command.startswith("dump_image ")]
        snapshots = [_mailbox()]
        for record in records:
            snapshots.append(_mailbox(
                state=R.STATE_DONE, sequence=record.sequence, result=R.RESULT_OK,
                status=R.FCB_STAT_OK, tag=record.tag,
                attempts=record.sequence, successes=record.sequence,
            ))
        assert len(dumps) == len(snapshots)
        for command, words in zip(dumps, snapshots):
            path = re.match(r'dump_image "([^"]+)"', command).group(1)
            Path(path).write_bytes(struct.pack("<16I", *words))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(P, "_oocd", simulated_openocd)
    result = R.execute_restream(firmware, images, sleep_ms=1)
    assert len(calls) == 1
    commands = calls[0]
    firmware_loads = [index for index, item in enumerate(commands)
                      if "load_image" in item and "0x20000000" in item]
    image_loads = [index for index, item in enumerate(commands)
                   if "load_image" in item and "0x20002000" in item]
    assert len(firmware_loads) == 1
    assert len(image_loads) == 2
    ready_guards = [index for index, item in enumerate(commands)
                    if "FCB restream READY" in item]
    result_guards = [index for index, item in enumerate(commands)
                     if "FCB restream result" in item or
                     "FCB restream FCB status" in item]
    assert len(ready_guards) == 5 and max(ready_guards) < image_loads[0]
    assert len(result_guards) == 10
    assert max(result_guards[:5]) < image_loads[1]
    assert all(str(path).replace("\\", "/") not in "\n".join(commands)
               for path in [firmware, *images])
    assert not any(token in item.lower() for item in commands
                   for token in ("flash", "erase", "option"))
    assert [item["passed"] for item in result["outcomes"]] == [True, True]


def test_probe_firmware_builds_and_fits_below_the_mailbox(tmp_path):
    try:
        gcc = find_riscv_tool("riscv64-unknown-elf-gcc")
        objcopy = find_riscv_tool("riscv64-unknown-elf-objcopy")
    except (RuntimeError, OSError) as exc:
        pytest.skip(str(exc))
    elf = tmp_path / "fcb_restream_probe.elf"
    binary = tmp_path / "fcb_restream_probe.bin"
    subprocess_args = [
        gcc, "-march=rv32imac", "-mabi=ilp32", "-Os", "-nostdlib",
        "-ffreestanding", "-fno-builtin", "-ffunction-sections",
        "-fdata-sections", "-I", str(HEADER.parent),
        "-T", str(ROOT / "agamemnon" / "sdk" / "link_sram.ld"),
        "-Wl,--gc-sections", str(ROOT / "agamemnon" / "sdk" / "startup.S"),
        str(ROOT / "qualification" / "fcb_restream_probe.c"), "-o", str(elf),
    ]
    import subprocess
    subprocess.run(subprocess_args, check=True, capture_output=True, text=True)
    subprocess.run([objcopy, "-O", "binary", elf, binary],
                   check=True, capture_output=True, text=True)
    assert 0 < binary.stat().st_size < 0x1000


def test_silicon_evidence_is_hash_bound_and_narrowly_scoped():
    rows = [json.loads(line) for line in (
        ROOT / "qualification" / "fcb_restream_evidence.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    matches = [row for row in rows if row["trial_id"] ==
               "fcb-restream-constant-endpoint-aba-20260825"]
    assert len(matches) == 1
    row = matches[0]
    assert row["trial_id"] == "fcb-restream-constant-endpoint-aba-20260825"
    assert row["result"] == "pass_exact_live_consecutive_replacement_aba"
    assert row["firmware"] == {
        "source": "qualification/fcb_restream_probe.c",
        "binary_size": 568,
        "binary_sha256":
            "7c54351e27ccef14e3043aa778f161bc3f69149b1b990f905829444aa331e058",
        "loads": 1,
    }
    assert [item["observed_ahb"] for item in row["sequence"]] == [
        "0x4147414d", "0x00000000", "0x4147414d",
    ]
    assert [item["fcb_stat"] for item in row["sequence"]] == [
        "0x000f0002", "0x000f0002", "0x000f0002",
    ]
    assert [item["successes"] for item in row["sequence"]] == [1, 2, 3]
    assert [item["rejected"] for item in row["sequence"]] == [0, 0, 0]
    assert row["safety"] == {
        "control_first": True,
        "transport": "SRAM-only",
        "flash_writes": 0,
        "por": False,
        "option_bytes": False,
        "rewiring": False,
        "board_lock": "released",
        "final_reset": "issued",
    }
    assert "does not qualify arbitrary images" in row["scope"]
