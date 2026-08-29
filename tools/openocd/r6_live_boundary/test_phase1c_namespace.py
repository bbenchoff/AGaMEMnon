from __future__ import annotations

import hashlib
import mmap
import os
from pathlib import Path

import pytest

from tools.openocd.r6_live_boundary import phase1c
from tools.openocd.r6_live_boundary import phase1c_namespace as namespace


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows custody contract")


def identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    executable = tmp_path / "openocd.exe"
    executable.write_bytes(b"ordinary desk fixture, never executed")
    config = tmp_path / "agrv2k.cfg"
    config.write_bytes(phase1c.LIVE_CONFIG_PATH.read_bytes())
    command = tmp_path / "session.tcl"
    command.write_bytes(phase1c.LIVE_COMMAND_PATH.read_bytes())
    return tuple(Path(namespace.canonical_volume_path(path)) for path in
                 (executable, config, command)) + (
                     Path(namespace.canonical_volume_path(
                         tmp_path / "launch.log", must_exist=False)),)


def test_exact_file_custody_blocks_rewrite_replace_and_parent_rename(
        tmp_path: Path) -> None:
    executable, config, command, log = fixture(tmp_path)
    moved = tmp_path.with_name(tmp_path.name + "-moved")
    with namespace.WindowsNamespaceCustody(
            executable=executable, config=config, command=command,
            log_path=log) as custody:
        custody.verify(openocd=identity(executable), config=identity(config),
                       command=identity(command))
        with pytest.raises(OSError):
            config.write_bytes(b"same pathname, changed bytes")
        replacement = tmp_path / "replacement.cfg"
        replacement.write_bytes(config.read_bytes())
        with pytest.raises(OSError):
            os.replace(replacement, os.fspath(config))
        with pytest.raises(OSError):
            tmp_path.rename(moved)
        assert all(custody._matches(item, namespace._identity(item.handle, item.path))
                   for item in custody._held)
        for item in custody._held:
            flags = namespace.wintypes.DWORD()
            assert namespace.kernel32.GetHandleInformation(
                namespace.wintypes.HANDLE(item.handle), namespace.ctypes.byref(flags))
            assert flags.value & namespace.HANDLE_FLAG_INHERIT == 0
    assert custody.closed is True
    config.write_bytes(b"custody closed")
    assert config.read_bytes() == b"custody closed"


def test_custody_rejects_hardlinked_leaf(tmp_path: Path) -> None:
    executable, config, command, log = fixture(tmp_path)
    os.link(os.fspath(config), tmp_path / "config-alias.cfg")
    with pytest.raises(phase1c.Phase1CFailure, match="multiple hard links"):
        with namespace.WindowsNamespaceCustody(
                executable=executable, config=config, command=command,
                log_path=log):
            pass


def test_custody_detects_concurrent_log_creator(tmp_path: Path) -> None:
    executable, config, command, log = fixture(tmp_path)
    with namespace.WindowsNamespaceCustody(
            executable=executable, config=config, command=command,
            log_path=log) as custody:
        log.write_bytes(b"foreign creator")
        with pytest.raises(phase1c.Phase1CFailure, match="launch log appeared"):
            custody.verify(openocd=identity(executable), config=identity(config),
                           command=identity(command))


def test_preexisting_writable_handle_or_mapping_prevents_custody(tmp_path: Path) -> None:
    executable, config, command, log = fixture(tmp_path)
    stream = config.open("r+b")
    try:
        with pytest.raises(phase1c.Phase1CFailure, match="CreateFileW custody"):
            with namespace.WindowsNamespaceCustody(
                    executable=executable, config=config, command=command,
                    log_path=log):
                pass
        view = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_WRITE)
    finally:
        stream.close()
    try:
        with pytest.raises(phase1c.Phase1CFailure, match="CreateFileW custody"):
            with namespace.WindowsNamespaceCustody(
                    executable=executable, config=config, command=command,
                    log_path=log):
                pass
    finally:
        view.close()


def test_log_create_new_uses_exact_volume_path_and_refuses_collision(
        tmp_path: Path) -> None:
    from tools.openocd.r6_live_boundary import phase1c_win32

    _, _, _, log = fixture(tmp_path)
    handle = phase1c_win32._create_log(log)
    phase1c_win32._close(handle)
    assert log.is_file()
    with pytest.raises(phase1c.Phase1CFailure, match="CreateFileW launch log"):
        phase1c_win32._create_log(log)


def test_close_fault_is_reported_after_every_handle_is_attempted(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    executable, config, command, log = fixture(tmp_path)
    custody = namespace.WindowsNamespaceCustody(
        executable=executable, config=config, command=command, log_path=log).acquire()
    expected = len(custody._held)
    original = namespace._close_handle
    calls = []

    def injected(handle: int, path: Path) -> None:
        original(handle, path)
        calls.append(path)
        if len(calls) == 1:
            raise phase1c.Phase1CFailure("injected close fault")

    monkeypatch.setattr(namespace, "_close_handle", injected)
    with pytest.raises(phase1c.Phase1CFailure, match="namespace custody close failed"):
        custody.close()
    assert len(calls) == expected


@pytest.mark.parametrize("value", [
    "C:/drive/path/file.cfg",
    "C:/a/../file.cfg",
    "C:/a/./file.cfg",
    "C:/a//file.cfg",
    "C:/a/file.cfg::$DATA",
    "C:/a./file.cfg",
    "C:/a /file.cfg",
    "C:/CON/file.cfg",
    "//server/share/file.cfg",
    "//?/Volume{4CA5E373-7A50-4B7D-9B37-BD91A58FF133}/a/file.cfg",
])
def test_windows_path_grammar_rejects_aliases(value: str) -> None:
    with pytest.raises(phase1c.Phase1CFailure):
        phase1c._portable_absolute(value, "fixture")
