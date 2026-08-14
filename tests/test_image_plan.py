import hashlib
import json
from types import SimpleNamespace

import pytest

from agamemnon import program


def test_image_plan_records_regions_hashes_and_option_pair_without_host_roots(
    tmp_path, monkeypatch,
):
    project = tmp_path / "project"
    project.mkdir()
    mcu = project / "mcu.bin"
    fabric = project / "fabric.bin"
    mcu.write_bytes(b"mcu")
    fabric.write_bytes(b"fabric")
    monkeypatch.chdir(project)

    plan = program.build_image_plan(
        fabric.resolve(), mcu.resolve(), 0x80010000,
        flash=False, backup=False, write_options=False,
    )

    assert [region["path"] for region in plan["regions"]] == ["mcu.bin", "fabric.bin"]
    assert plan["regions"][0]["sha256"] == hashlib.sha256(b"mcu").hexdigest()
    assert plan["regions"][1]["address"] == 0x80010000
    assert plan["option_pointer"] == {
        "address": 0x81000030,
        "value": 0x80010000,
        "complement": 0x7FFEFFFF,
        "write_requested": False,
        "qualification": "unsupported",
    }
    encoded = json.dumps(plan)
    assert str(tmp_path) not in encoded
    assert plan["path_policy"]["portable"] is True
    assert plan["agamemnon_version"] == "0.3.0"


def test_image_command_writes_plan_before_any_hardware_action(tmp_path, monkeypatch):
    fabric = tmp_path / "fabric.bin"
    fabric.write_bytes(bytes(99944))
    output = tmp_path / "reports" / "boot-plan.json"
    monkeypatch.chdir(tmp_path)

    program.cmd_image(SimpleNamespace(
        fabric=str(fabric),
        mcu=None,
        logic_addr=None,
        plan_json=str(output),
        flash=False,
        backup=None,
        write_options=False,
        option_backup=None,
    ))

    plan = json.loads(output.read_text(encoding="utf-8"))
    assert plan["kind"] == "agamemnon-flash-boot-plan"
    assert plan["regions"][0]["path"] == "fabric.bin"
    assert plan["operation"] == {
        "flash_requested": False,
        "backup_requested": False,
        "option_backup_requested": False,
    }


def _image_args(fabric, **overrides):
    values = {
        "fabric": str(fabric),
        "mcu": None,
        "logic_addr": None,
        "plan_json": None,
        "flash": False,
        "backup": None,
        "option_backup": None,
        "write_options": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_image_rejects_every_persistent_write_without_complete_backups(tmp_path):
    fabric = tmp_path / "fabric.bin"
    fabric.write_bytes(bytes(99944))

    with pytest.raises(SystemExit) as missing_flash_backup:
        program.cmd_image(_image_args(fabric, flash=True))
    assert missing_flash_backup.value.code == 2

    with pytest.raises(SystemExit) as missing_option_backup:
        program.cmd_image(_image_args(
            fabric,
            flash=True,
            backup=str(tmp_path / "full.bin"),
            write_options=True,
        ))
    assert missing_option_backup.value.code == 2


def test_image_rejects_backup_paths_that_alias_inputs_or_each_other(tmp_path):
    fabric = tmp_path / "fabric.bin"
    fabric.write_bytes(bytes(99944))

    with pytest.raises(SystemExit) as input_alias:
        program.cmd_image(_image_args(fabric, flash=True, backup=str(fabric)))
    assert input_alias.value.code == 2

    same = tmp_path / "same.bin"
    with pytest.raises(SystemExit) as backup_alias:
        program.cmd_image(_image_args(
            fabric,
            flash=True,
            backup=str(same),
            option_backup=str(same),
            write_options=True,
        ))
    assert backup_alias.value.code == 2

    with pytest.raises(SystemExit) as manifest_alias:
        program.cmd_image(_image_args(fabric, plan_json=str(fabric)))
    assert manifest_alias.value.code == 2


def test_openocd_paths_are_quoted_as_one_tcl_word(tmp_path):
    path = tmp_path / 'space $ [probe] "image".bin'
    quoted = program._tcl_path(path)
    assert quoted.startswith('"') and quoted.endswith('"')
    assert " " in quoted
    assert r"\$" in quoted
    assert r"\[" in quoted and r"\]" in quoted
    assert r'\"image\"' in quoted


def test_backup_is_published_atomically_only_after_a_complete_dump(tmp_path, monkeypatch):
    output = tmp_path / "directory with spaces" / "full.bin"

    def successful(commands):
        command = next(item for item in commands if item.startswith("dump_image "))
        temporary = command.split('"', 2)[1]
        with open(temporary, "wb") as stream:
            stream.write(b"x" * 16)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(program, "_oocd", successful)
    assert program._dump_backup(output, 0x80000000, 16) is True
    assert output.read_bytes() == b"x" * 16

    def failed(commands):
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(program, "_oocd", failed)
    assert program._dump_backup(output, 0x80000000, 16) is False
    assert output.read_bytes() == b"x" * 16
