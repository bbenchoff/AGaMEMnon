"""Windows namespace custody for the R6 Phase1C exact launch files.

The accepted Phase1C child no longer admits an external scripts search tree.
Its exact self-contained config and command are ordinary files, so held file
handles plus non-delete ancestor handles close the remaining executable/config/
command/log pathname races without claiming mutable-directory-tree custody.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Mapping

from tools.openocd.r6_live_boundary.phase1c import Phase1CFailure, exact_keys, require


FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
GENERIC_READ = 0x80000000
FILE_READ_ATTRIBUTES = 0x00000080
FILE_LIST_DIRECTORY = 0x00000001
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_BEGIN = 0
VOLUME_NAME_GUID = 0x00000001
HANDLE_FLAG_INHERIT = 0x00000001
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetHandleInformation.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetHandleInformation.restype = wintypes.BOOL
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    kernel32.SetHandleInformation.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
    ]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    kernel32.SetFilePointerEx.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
else:
    kernel32 = None


def _error(label: str) -> Phase1CFailure:
    return Phase1CFailure(f"{label} failed: {ctypes.get_last_error()}")


def _open_handle(path: Path, *, directory: bool) -> int:
    require(kernel32 is not None and os.name == "nt",
            "namespace custody requires Windows")
    access = ((FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES)
              if directory else GENERIC_READ)
    # Ancestors remain usable for unrelated filesystem work, but omitting
    # FILE_SHARE_DELETE prevents any component from being renamed or removed.
    share = FILE_SHARE_READ | FILE_SHARE_WRITE if directory else FILE_SHARE_READ
    flags = ((FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
             if directory else
             (FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN |
              FILE_FLAG_OPEN_REPARSE_POINT))
    handle = kernel32.CreateFileW(
        str(path), access, share, None, OPEN_EXISTING, flags, None)
    if handle in (None, 0, INVALID_HANDLE_VALUE):
        raise _error(f"CreateFileW custody {path}")
    raw = int(handle)
    if not kernel32.SetHandleInformation(
            wintypes.HANDLE(raw), HANDLE_FLAG_INHERIT, 0):
        kernel32.CloseHandle(wintypes.HANDLE(raw))
        raise _error(f"SetHandleInformation custody {path}")
    inherited = wintypes.DWORD()
    if not kernel32.GetHandleInformation(
            wintypes.HANDLE(raw), ctypes.byref(inherited)):
        kernel32.CloseHandle(wintypes.HANDLE(raw))
        raise _error(f"GetHandleInformation custody {path}")
    if inherited.value & HANDLE_FLAG_INHERIT:
        kernel32.CloseHandle(wintypes.HANDLE(raw))
        raise Phase1CFailure(f"custody handle is inheritable: {path}")
    return raw


def _information(handle: int, path: Path) -> BY_HANDLE_FILE_INFORMATION:
    value = BY_HANDLE_FILE_INFORMATION()
    if not kernel32.GetFileInformationByHandle(
            wintypes.HANDLE(handle), ctypes.byref(value)):
        raise _error(f"GetFileInformationByHandle custody {path}")
    return value


def _identity(handle: int, path: Path) -> tuple[int, int, int]:
    value = _information(handle, path)
    index = (int(value.nFileIndexHigh) << 32) | int(value.nFileIndexLow)
    size = (int(value.nFileSizeHigh) << 32) | int(value.nFileSizeLow)
    return int(value.dwVolumeSerialNumber), index, size


def _require_kind(handle: int, path: Path, *, directory: bool) -> None:
    value = _information(handle, path)
    require(not value.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT,
            f"custody target is a reparse point: {path}")
    require(bool(value.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == directory,
            f"custody target type differs: {path}")
    if not directory:
        require(value.nNumberOfLinks == 1,
                f"custody file has multiple hard links: {path}")


def _final_path(handle: int, path: Path) -> str:
    needed = kernel32.GetFinalPathNameByHandleW(
        wintypes.HANDLE(handle), None, 0, VOLUME_NAME_GUID)
    if not needed:
        raise _error(f"GetFinalPathNameByHandleW size {path}")
    buffer = ctypes.create_unicode_buffer(needed + 1)
    written = kernel32.GetFinalPathNameByHandleW(
        wintypes.HANDLE(handle), buffer, len(buffer), VOLUME_NAME_GUID)
    if not written or written >= len(buffer):
        raise _error(f"GetFinalPathNameByHandleW {path}")
    value = buffer.value
    require(value.startswith("\\\\?\\Volume{") and "}\\" in value,
            f"custody target is not a local volume-GUID path: {path}")
    return value


def verify_open_handle_path(handle: int, path: Path, *, directory: bool) -> None:
    """Require exact kind and normalized final pathname for an already-open handle."""
    _require_kind(handle, path, directory=directory)
    final = os.path.normcase(os.path.abspath(_final_path(handle, path)))
    expected = os.path.normcase(os.path.abspath(os.fspath(path)))
    require(final == expected, f"custody final pathname differs: {path}")


def canonical_volume_path(path: Path, *, must_exist: bool = True) -> str:
    """Return canonical forward-slash volume-GUID form for a local path."""
    target = path if must_exist else path.parent
    handle = _open_handle(target, directory=not target.is_file())
    try:
        _require_kind(handle, target, directory=not target.is_file())
        value = _final_path(handle, target)
    finally:
        _close_handle(handle, target)
    if not must_exist:
        require(not os.path.lexists(path), "future custody path already exists")
        value = value.rstrip("\\") + "\\" + path.name
    return value.replace("\\", "/")


def _sha256_handle(handle: int, path: Path) -> str:
    if not kernel32.SetFilePointerEx(
            wintypes.HANDLE(handle), 0, None, FILE_BEGIN):
        raise _error(f"SetFilePointerEx custody {path}")
    digest = hashlib.sha256()
    while True:
        block = ctypes.create_string_buffer(1024 * 1024)
        consumed = wintypes.DWORD()
        if not kernel32.ReadFile(
                wintypes.HANDLE(handle), block, len(block),
                ctypes.byref(consumed), None):
            raise _error(f"ReadFile custody {path}")
        if consumed.value == 0:
            break
        digest.update(block.raw[:consumed.value])
    return digest.hexdigest()


def _close_handle(handle: int, path: Path) -> None:
    if not kernel32.CloseHandle(wintypes.HANDLE(handle)):
        raise _error(f"CloseHandle custody {path}")


@dataclass
class _Held:
    path: Path
    handle: int
    directory: bool
    identity: tuple[int, int, int]


class WindowsNamespaceCustody:
    """Hold exact launch-file and ancestor identities through backend return."""

    def __init__(self, *, executable: Path, config: Path, command: Path,
                 log_path: Path):
        require(os.name == "nt" and kernel32 is not None,
                "namespace custody requires Windows")
        self.executable = executable
        self.config = config
        self.command = command
        self.log_path = log_path
        self._held: list[_Held] = []
        self._by_key: dict[str, _Held] = {}
        self.closed = False

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _reject_reparse(path: Path) -> None:
        try:
            item = os.lstat(path)
        except OSError as exc:
            raise Phase1CFailure(f"cannot stat custody target {path}: {exc}") from exc
        attributes = getattr(item, "st_file_attributes", 0)
        require(not stat.S_ISLNK(item.st_mode) and
                not attributes & FILE_ATTRIBUTE_REPARSE_POINT,
                f"custody target is a reparse point: {path}")

    def _hold(self, path: Path, *, directory: bool) -> _Held:
        key = self._key(path)
        existing = self._by_key.get(key)
        if existing is not None:
            require(existing.directory == directory,
                    f"custody target type conflicts: {path}")
            return existing
        self._reject_reparse(path)
        handle = _open_handle(path, directory=directory)
        try:
            verify_open_handle_path(handle, path, directory=directory)
            held = _Held(path, handle, directory, _identity(handle, path))
        except BaseException:
            _close_handle(handle, path)
            raise
        self._held.append(held)
        self._by_key[key] = held
        return held

    def _hold_ancestors(self, path: Path) -> None:
        chain: list[Path] = []
        current = path.parent
        while True:
            chain.append(current)
            if current.parent == current:
                break
            current = current.parent
        for ancestor in reversed(chain):
            self._hold(ancestor, directory=True)

    def _path_identity(self, held: _Held) -> tuple[int, int, int]:
        transient = _open_handle(held.path, directory=held.directory)
        try:
            verify_open_handle_path(transient, held.path, directory=held.directory)
            return _identity(transient, held.path)
        finally:
            _close_handle(transient, held.path)

    @staticmethod
    def _matches(held: _Held, observed: tuple[int, int, int]) -> bool:
        return (observed[:2] == held.identity[:2] and
                (held.directory or observed[2] == held.identity[2]))

    def acquire(self) -> "WindowsNamespaceCustody":
        try:
            for path in (self.executable, self.config, self.command, self.log_path):
                self._hold_ancestors(path)
            for path in (self.executable, self.config, self.command):
                self._hold(path, directory=False)
            require(not os.path.lexists(self.log_path),
                    "launch log appeared while acquiring namespace custody")
            return self
        except BaseException as exc:
            failures = self.close(suppress=True)
            if failures and hasattr(exc, "add_note"):
                exc.add_note("namespace custody close failures: " + "; ".join(failures))
            raise

    def _verify_file(self, path: Path, expected: Mapping, label: str) -> None:
        exact_keys(expected, {"size", "sha256"}, f"{label} identity")
        held = self._by_key[self._key(path)]
        require(self._matches(held, _identity(held.handle, held.path)),
                f"{label} held identity changed")
        require(self._matches(held, self._path_identity(held)),
                f"{label} pathname identity changed")
        require(held.identity[2] == expected["size"],
                f"{label} size differs under custody")
        require(_sha256_handle(held.handle, held.path) == expected["sha256"],
                f"{label} SHA-256 differs under custody")

    def verify(self, *, openocd: Mapping, config: Mapping, command: Mapping) -> None:
        require(not self.closed, "namespace custody is closed")
        for held in self._held:
            require(self._matches(held, _identity(held.handle, held.path)),
                    f"held namespace identity changed: {held.path}")
            require(self._matches(held, self._path_identity(held)),
                    f"pathname identity changed under custody: {held.path}")
        self._verify_file(self.executable, openocd, "OpenOCD")
        self._verify_file(self.config, config, "config")
        self._verify_file(self.command, command, "command")
        require(not os.path.lexists(self.log_path),
                "launch log appeared under namespace custody")

    def close(self, *, suppress: bool = False) -> list[str]:
        if self.closed:
            return []
        self.closed = True
        failures = []
        for held in reversed(self._held):
            try:
                _close_handle(held.handle, held.path)
            except BaseException as exc:
                failures.append(str(exc))
        self._held.clear()
        self._by_key.clear()
        if failures and not suppress:
            raise Phase1CFailure("namespace custody close failed: " + "; ".join(failures))
        return failures

    def __enter__(self) -> "WindowsNamespaceCustody":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> bool:
        failures = self.close(suppress=True)
        if failures:
            message = "namespace custody close failed: " + "; ".join(failures)
            if exc is not None and hasattr(exc, "add_note"):
                exc.add_note(message)
            else:
                raise Phase1CFailure(message)
        return False


def acquire_namespace_custody(*, executable: Path, config: Path, command: Path,
                              log_path: Path) -> WindowsNamespaceCustody:
    return WindowsNamespaceCustody(
        executable=executable, config=config, command=command, log_path=log_path)
