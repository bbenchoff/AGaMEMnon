#!/usr/bin/env python3
"""Prepare, verify, and package the pinned AGaMEMnon OpenOCD release."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from typing import Iterable, Mapping
import uuid
import zipfile


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "manifest.json"
PROVENANCE_NAME = "AGAMEMNON-PROVENANCE.json"
PROVENANCE_TOP_LEVEL_KEYS = (
    "schema",
    "release",
    "official_repository",
    "official_base_commit",
    "agamemnon_patched_commit",
    "gerrit",
    "patch_sha256",
    "submodules",
    "source_date_epoch",
    "oracle",
)
PROVENANCE_GERRIT_KEYS = ("change", "patchset", "commit", "ref")
PROVENANCE_ORACLE_KEYS = (
    "repository",
    "commit",
    "openocd_exe_sha256",
    "redistribute",
    "purpose",
)
GENERATED_SOURCE_PATHS = (
    PROVENANCE_NAME,
    "AGAMEMNON-PATCHES/0001-target-riscv-DM-access-on-a-DAP.patch",
    "AGAMEMNON-PATCHES/0002-target-riscv-fix-nested-ADIv5-config.patch",
)
SOURCE_ARCHIVE_PACKAGE_PATHS = (
    "AGAMEMNON-BUILD-MANIFEST.json",
    "AGAMEMNON-BUILD.md",
    "AGAMEMNON-BUILD-TOOLS/release.py",
    "AGAMEMNON-BUILD-TOOLS/build.sh",
    "AGAMEMNON-BUILD-TOOLS/manifest.json",
    "AGAMEMNON-BUILD-TOOLS/patches/0001-target-riscv-DM-access-on-a-DAP.patch",
    "AGAMEMNON-BUILD-TOOLS/patches/0002-target-riscv-fix-nested-ADIv5-config.patch",
)


def _reject_duplicate_json_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json_strict(path):
    try:
        return json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"cannot read strict JSON {path}: {exc}") from exc


def _require_exact_keys(value, expected, label):
    if not isinstance(value, Mapping):
        raise SystemExit(f"{label} must be a JSON object")
    expected_set = set(expected)
    actual_set = set(value)
    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        raise SystemExit(f"{label} keys differ: missing={missing}, extra={extra}")


def canonical_provenance_text(value):
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def manifest():
    return load_json_strict(MANIFEST_PATH)


def run(args, cwd=None, capture=False, env=None):
    result = subprocess.run(
        [str(item) for item in args],
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=capture,
        env=env,
    )
    return result.stdout.strip() if capture else result


def run_bytes(args, cwd=None):
    result = subprocess.run(
        [str(item) for item in args],
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        command = " ".join(str(item) for item in args)
        raise SystemExit(
            f"{command} failed: {result.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return result.stdout


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha1(path):
    digest = hashlib.sha1()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_hash_stream(stream):
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _release_copy_verified_stream(source_stream, destination_stream, relative):
    del relative
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
        destination_stream.write(chunk)
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _source_require(condition, message):
    if not condition:
        raise SystemExit(message)


def _release_stat_identity(file_stat):
    return (file_stat.st_dev, file_stat.st_ino)


def _release_stat_change_state(file_stat):
    return (
        file_stat.st_size,
        getattr(file_stat, "st_mtime_ns", int(file_stat.st_mtime * 1_000_000_000)),
        getattr(file_stat, "st_ctime_ns", int(file_stat.st_ctime * 1_000_000_000)),
        file_stat.st_nlink,
    )


class _ReleaseHashingReader:
    """Hash the exact bytes a consumer reads from an already verified handle."""

    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        self.size += len(data)
        return data

    def result(self):
        return self.digest.hexdigest(), self.size


def _release_decode_path(raw, label):
    try:
        path = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise SystemExit(f"{label} contains a non-UTF-8 path") from exc
    _source_require(path != "", f"{label} contains an empty path")
    return path


def _release_nul_records(data, label):
    _source_require(data == b"" or data.endswith(b"\0"), f"{label} is not NUL terminated")
    return [] if data == b"" else data[:-1].split(b"\0")


def _release_head_entries(data):
    entries = {}
    for record in _release_nul_records(data, "release HEAD tree inventory"):
        match = re.fullmatch(
            rb"([0-7]{6}) (blob|commit) ([0-9a-f]+)\t([^\0]+)", record
        )
        _source_require(match is not None, f"cannot parse release HEAD tree entry: {record!r}")
        path = _release_decode_path(match.group(4), "release HEAD tree inventory")
        _source_require(path not in entries, f"duplicate release HEAD tree path: {path}")
        entries[path] = (
            match.group(1).decode("ascii"),
            match.group(2).decode("ascii"),
            match.group(3).decode("ascii"),
        )
    _source_require(entries, "release HEAD tree inventory is empty")
    return entries


def _release_index_entries(data):
    entries = {}
    for record in _release_nul_records(data, "release index stage inventory"):
        match = re.fullmatch(rb"([0-7]{6}) ([0-9a-f]+) ([0-3])\t([^\0]+)", record)
        _source_require(match is not None, f"cannot parse release index entry: {record!r}")
        path = _release_decode_path(match.group(4), "release index stage inventory")
        _source_require(
            path not in entries,
            f"multiple release index stages or duplicate path: {path}",
        )
        entries[path] = (
            match.group(1).decode("ascii"),
            match.group(2).decode("ascii"),
            int(match.group(3)),
        )
    return entries


def _release_tagged_entries(data, label):
    entries = {}
    for record in _release_nul_records(data, label):
        _source_require(
            len(record) >= 3 and record[1:2] == b" ",
            f"cannot parse {label} entry",
        )
        try:
            tag = record[:1].decode("ascii", errors="strict")
        except UnicodeError as exc:
            raise SystemExit(f"cannot parse {label} tag") from exc
        path = _release_decode_path(record[2:], label)
        _source_require(path not in entries, f"duplicate {label} path: {path}")
        entries[path] = tag
    return entries


_RELEASE_INDEX_DEBUG_RE = re.compile(
    rb"  ctime: [^\n]*\n"
    rb"  mtime: [^\n]*\n"
    rb"  dev: [^\n]*\n"
    rb"  uid: [^\n]*\n"
    rb"  size: [^\n]*\tflags: ([0-9a-fA-F]+)\n"
)


def _release_debug_entries(data):
    entries = {}
    cursor = 0
    while cursor < len(data):
        separator = data.find(b"\0", cursor)
        _source_require(separator >= 0, "release index debug path is not NUL terminated")
        path = _release_decode_path(
            data[cursor:separator], "release index debug inventory"
        )
        _source_require(path not in entries, f"duplicate release index debug path: {path}")
        metadata = _RELEASE_INDEX_DEBUG_RE.match(data, separator + 1)
        _source_require(metadata is not None, f"cannot parse release index debug metadata: {path}")
        entries[path] = int(metadata.group(1), 16)
        cursor = metadata.end()
    return entries


def _release_blob_id(data, object_format):
    _source_require(
        object_format in {"sha1", "sha256"},
        f"unsupported release Git object format: {object_format}",
    )
    digest = hashlib.new(object_format)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _release_symlink_bytes(path):
    target = os.readlink(path)
    if os.name == "nt":
        if target.startswith("\\\\?\\UNC\\"):
            target = "//" + target[8:]
        elif target.startswith("\\\\?\\"):
            target = target[4:]
        target = target.replace("\\", "/")
    return os.fsencode(target)


def _release_path_key(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(path))))


def _release_is_reparse_point(file_stat):
    attributes = getattr(file_stat, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_attribute)


def _release_open_readonly_nofollow(path, label):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    if os.name != "nt":
        flags |= os.O_NOFOLLOW
        try:
            return os.open(path, flags)
        except OSError as exc:
            raise SystemExit(f"cannot open {label} without following links: {exc}") from exc

    # Python does not expose O_NOFOLLOW on Windows.  Open the filesystem object
    # itself with FILE_FLAG_OPEN_REPARSE_POINT, then transfer ownership of that
    # handle to a binary CRT file descriptor.
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        os.fspath(path),
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002 | 0x00000004,  # FILE_SHARE_READ/WRITE/DELETE
        None,
        3,  # OPEN_EXISTING
        0x00200000 | 0x08000000,  # OPEN_REPARSE_POINT | SEQUENTIAL_SCAN
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error = ctypes.WinError(ctypes.get_last_error())
        raise SystemExit(f"cannot open {label} without following links: {error}") from error
    try:
        return msvcrt.open_osfhandle(
            handle, os.O_RDONLY | os.O_BINARY | getattr(os, "O_NOINHERIT", 0)
        )
    except OSError as exc:
        close_handle(handle)
        raise SystemExit(f"cannot bind no-follow handle for {label}: {exc}") from exc


def _release_open_directory_custody(
    path, label, expected_identity=None, parent_custody=None, leaf_name=None
):
    """Hold a real directory so Windows cannot redirect it before child I/O.

    POSIX child opens use the returned directory descriptor directly.  Windows
    lacks Python dir_fd support, so its handle has DELETE access while
    deliberately omitting FILE_SHARE_DELETE.  That pins the pathname and lets
    rollback mark this exact held object for deletion without reopening it.
    """
    path = Path(path)
    before_stat = os.lstat(path)
    _source_require(
        stat.S_ISDIR(before_stat.st_mode)
        and not stat.S_ISLNK(before_stat.st_mode)
        and not _release_is_reparse_point(before_stat),
        f"{label} is not a real directory",
    )
    if expected_identity is not None:
        _source_require(
            _release_stat_identity(before_stat) == tuple(expected_identity),
            f"{label} identity differs before custody",
        )

    if os.name != "nt":
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            if parent_custody is None:
                descriptor = os.open(path, flags)
            else:
                descriptor = os.open(
                    leaf_name, flags, dir_fd=parent_custody["descriptor"]
                )
        except OSError as exc:
            raise SystemExit(f"cannot acquire directory custody for {label}: {exc}") from exc
        custody = {"descriptor": descriptor, "handle": None}
        try:
            opened_stat = os.fstat(descriptor)
            _source_require(
                _release_stat_identity(opened_stat)
                == _release_stat_identity(before_stat),
                f"{label} identity changed while acquiring custody",
            )
        except BaseException:
            os.close(descriptor)
            raise
    else:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        handle = create_file(
            os.fspath(path),
            0x80000000 | 0x00010000,  # GENERIC_READ | DELETE.
            0x00000001 | 0x00000002,  # Share read/write, deliberately not delete.
            None,
            3,  # OPEN_EXISTING
            0x00200000 | 0x02000000,  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            error = ctypes.WinError(ctypes.get_last_error())
            raise SystemExit(f"cannot acquire directory custody for {label}: {error}") from error
        custody = {"descriptor": None, "handle": handle, "close_handle": close_handle}

    try:
        after_stat = os.lstat(path)
        _source_require(
            _release_stat_identity(after_stat) == _release_stat_identity(before_stat)
            and stat.S_ISDIR(after_stat.st_mode)
            and not stat.S_ISLNK(after_stat.st_mode)
            and not _release_is_reparse_point(after_stat),
            f"{label} identity changed while acquiring custody",
        )
    except BaseException:
        _release_close_directory_custody(custody)
        raise
    custody.update(
        {"path": path, "identity": _release_stat_identity(after_stat), "closed": False}
    )
    return custody


def _release_close_directory_custody(custody):
    if custody is None or custody.get("closed"):
        return
    custody["closed"] = True
    if custody.get("descriptor") is not None:
        os.close(custody["descriptor"])
    elif custody.get("handle") is not None:
        custody["close_handle"](custody["handle"])


def _release_open_windows_delete_custody(path, label, expected_identity, kind):
    """Open one exact Windows object without allowing delete/rename sharing."""
    _source_require(os.name == "nt", f"exact Windows cleanup is unavailable: {label}")
    path = Path(path)
    before_stat = os.lstat(path)
    expected_mode = stat.S_ISREG if kind == "file" else stat.S_ISDIR
    _source_require(
        expected_mode(before_stat.st_mode)
        and not stat.S_ISLNK(before_stat.st_mode)
        and not _release_is_reparse_point(before_stat)
        and _release_stat_identity(before_stat) == tuple(expected_identity),
        f"transaction-created {kind} identity differs before exact cleanup: {path}",
    )

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    flags = 0x00200000  # FILE_FLAG_OPEN_REPARSE_POINT
    if kind == "directory":
        flags |= 0x02000000  # FILE_FLAG_BACKUP_SEMANTICS
    handle = create_file(
        os.fspath(path),
        0x00010000 | 0x00000080,  # DELETE | FILE_READ_ATTRIBUTES
        0x00000001 | 0x00000002,  # Share read/write, deliberately not delete.
        None,
        3,  # OPEN_EXISTING
        flags,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        error = ctypes.WinError(ctypes.get_last_error())
        raise SystemExit(f"cannot acquire exact cleanup custody for {label}: {error}") from error
    custody = {
        "descriptor": None,
        "handle": handle,
        "close_handle": close_handle,
        "path": path,
        "identity": tuple(expected_identity),
        "closed": False,
    }
    try:
        after_stat = os.lstat(path)
        _source_require(
            expected_mode(after_stat.st_mode)
            and not stat.S_ISLNK(after_stat.st_mode)
            and not _release_is_reparse_point(after_stat)
            and _release_stat_identity(after_stat) == tuple(expected_identity),
            f"transaction-created {kind} identity changed while acquiring exact cleanup custody: {path}",
        )
    except BaseException:
        _release_close_directory_custody(custody)
        raise
    return custody


def _release_mark_windows_handle_for_deletion(custody, path, kind):
    """Mark the object named by an already-held Windows handle delete-pending."""
    _source_require(os.name == "nt", f"exact Windows cleanup is unavailable: {path}")
    _source_require(
        custody is not None
        and not custody.get("closed")
        and custody.get("handle") is not None,
        f"exact cleanup lacks live {kind} custody: {path}",
    )

    import ctypes
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = (("delete_file", wintypes.BOOL),)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    disposition = FileDispositionInfo(True)
    if not set_information(
        custody["handle"],
        4,  # FileDispositionInfo
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        error = ctypes.WinError(ctypes.get_last_error())
        raise SystemExit(
            f"cannot mark exact transaction-created {kind} for deletion: {path}: {error}"
        ) from error


def _release_require_exact_cleanup_result(path, identity, kind):
    """Prove our object disappeared; a later replacement is preserved."""
    try:
        remaining_stat = os.lstat(path)
    except FileNotFoundError:
        return
    _source_require(
        _release_stat_identity(remaining_stat) != tuple(identity),
        f"exact transaction-created {kind} remains after cleanup: {path}",
    )


@contextmanager
def _release_private_package_workspace():
    """Create a unique package root without unsafe generic recursive cleanup."""
    temporary = Path(tempfile.mkdtemp(prefix="agamemnon-openocd-"))
    temporary_stat = os.lstat(temporary)
    _source_require(
        stat.S_ISDIR(temporary_stat.st_mode)
        and not stat.S_ISLNK(temporary_stat.st_mode)
        and not _release_is_reparse_point(temporary_stat),
        "private package workspace is not a real directory",
    )
    try:
        yield temporary
    finally:
        try:
            final_stat = os.lstat(temporary)
        except FileNotFoundError:
            raise SystemExit("private package workspace disappeared during packaging")
        _source_require(
            _release_stat_identity(final_stat) == _release_stat_identity(temporary_stat)
            and stat.S_ISDIR(final_stat.st_mode)
            and not stat.S_ISLNK(final_stat.st_mode)
            and not _release_is_reparse_point(final_stat),
            "private package workspace identity changed during packaging",
        )


def _release_open_readonly_in_directory(custody, path, leaf_name, label):
    if os.name == "nt":
        return _release_open_readonly_nofollow(path, label)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        return os.open(leaf_name, flags, dir_fd=custody["descriptor"])
    except OSError as exc:
        raise SystemExit(f"cannot open {label} without following links: {exc}") from exc


def _release_create_file_in_directory(custody, path, leaf_name, flags, mode):
    if os.name == "nt":
        return os.open(path, flags, mode)
    return os.open(leaf_name, flags, mode, dir_fd=custody["descriptor"])


def _release_mkdir_in_directory(custody, path, leaf_name):
    if os.name == "nt":
        os.mkdir(path)
    else:
        os.mkdir(leaf_name, dir_fd=custody["descriptor"])


def _release_require_exact_real_path(path, label):
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"cannot resolve {label}: {exc}") from exc
    _source_require(
        _release_path_key(resolved) == _release_path_key(path),
        f"{label} traverses a symlink, junction, mount alias, or reparse point",
    )
    return resolved


def _release_require_inside_repository(repository, path, label):
    try:
        common = os.path.commonpath(
            (_release_path_key(repository), _release_path_key(path))
        )
    except ValueError as exc:
        raise SystemExit(f"{label} is outside the exact repository root") from exc
    _source_require(
        common == _release_path_key(repository),
        f"{label} is outside the exact repository root",
    )


def _release_require_git_repository_identity(repository, label):
    try:
        reported_text = run_bytes(
            ["git", "rev-parse", "--show-toplevel"], cwd=repository
        ).decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise SystemExit(f"{label} Git repository identity is not UTF-8") from exc
    _source_require(reported_text != "", f"{label} has an empty Git repository identity")
    reported = Path(os.path.abspath(reported_text))
    _source_require(
        _release_path_key(reported) == _release_path_key(repository),
        f"{label} Git repository identity differs from its exact path",
    )
    try:
        _source_require(
            os.path.samefile(reported, repository),
            f"{label} Git repository identity differs from its filesystem object",
        )
    except OSError as exc:
        raise SystemExit(f"cannot prove {label} Git repository identity: {exc}") from exc


def _release_validate_repository_root(repository):
    repository = Path(os.path.abspath(os.fspath(repository)))
    try:
        root_stat = os.lstat(repository)
    except OSError as exc:
        raise SystemExit(f"cannot inspect release repository root: {exc}") from exc
    _source_require(
        stat.S_ISDIR(root_stat.st_mode), "release repository root is not a real directory"
    )
    _source_require(
        not stat.S_ISLNK(root_stat.st_mode), "release repository root is a symlink"
    )
    _source_require(
        not _release_is_reparse_point(root_stat),
        "release repository root is a reparse point",
    )
    _source_require(
        not os.path.ismount(repository), "release repository root is a mount point"
    )
    repository = _release_require_exact_real_path(repository, "release repository root")
    _release_require_git_repository_identity(repository, "release repository root")
    return repository


def _release_tracked_native_path(relative):
    pure = PurePosixPath(relative)
    _source_require(
        relative == pure.as_posix()
        and not pure.is_absolute()
        and bool(pure.parts)
        and all(part not in {"", ".", ".."} for part in pure.parts)
        and "\\" not in relative,
        f"unsafe release tracked path: {relative}",
    )
    native = Path(*pure.parts)
    _source_require(
        not native.is_absolute() and native.drive == "",
        f"unsafe release tracked native path: {relative}",
    )
    return native


def _release_validate_tracked_path_topology(repository, relative, mode):
    native = _release_tracked_native_path(relative)
    current = repository
    for index, part in enumerate(native.parts):
        current = current / part
        label = f"release tracked path topology for {relative}"
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise SystemExit(f"cannot inspect {label}: {exc}") from exc
        is_leaf = index == len(native.parts) - 1
        if is_leaf and mode == "120000":
            _source_require(
                stat.S_ISLNK(current_stat.st_mode),
                f"release tracked symlink type differs: {relative}",
            )
            # The frozen OpenOCD, JimTcl, and libjaylink trees contain no
            # mode-120000 entries, so any tracked link is an unreviewed input.
            raise SystemExit(
                "release tracked Git symlink is not allowed by the exact source "
                f"inventory: {relative}"
            )
        if is_leaf and mode in {"100644", "100755"}:
            _source_require(
                stat.S_ISREG(current_stat.st_mode),
                f"release tracked regular file type differs: {relative}",
            )
        else:
            _source_require(
                stat.S_ISDIR(current_stat.st_mode),
                f"{label} is not a real directory",
            )
        _source_require(
            not stat.S_ISLNK(current_stat.st_mode),
            f"{label} traverses a symlink",
        )
        _source_require(
            not _release_is_reparse_point(current_stat),
            f"{label} traverses a junction or reparse point",
        )
        _source_require(
            not os.path.ismount(current), f"{label} traverses a mount point"
        )
        resolved = _release_require_exact_real_path(current, label)
        _release_require_inside_repository(repository, resolved, label)
        if is_leaf and mode in {"100644", "100755"}:
            _source_require(
                current_stat.st_nlink == 1,
                f"release tracked regular file must have exactly one hard link: {relative}",
            )
        if is_leaf and mode == "160000":
            _release_require_git_repository_identity(resolved, f"release gitlink {relative}")
        if is_leaf:
            return current, current_stat
    raise SystemExit(f"empty release tracked path topology: {relative}")


def _release_validate_generated_regular_path_topology(repository, relative):
    native = _release_tracked_native_path(relative)
    current = repository
    for index, part in enumerate(native.parts):
        current = current / part
        label = f"release generated source path topology for {relative}"
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise SystemExit(f"cannot inspect {label}: {exc}") from exc
        is_leaf = index == len(native.parts) - 1
        if is_leaf:
            _source_require(
                stat.S_ISREG(current_stat.st_mode),
                f"release generated source input is not an ordinary file: {relative}",
            )
        else:
            _source_require(
                stat.S_ISDIR(current_stat.st_mode),
                f"{label} is not a real directory",
            )
        _source_require(
            not stat.S_ISLNK(current_stat.st_mode),
            f"{label} traverses a symlink",
        )
        _source_require(
            not _release_is_reparse_point(current_stat),
            f"{label} traverses a junction or reparse point",
        )
        _source_require(
            not os.path.ismount(current), f"{label} traverses a mount point"
        )
        resolved = _release_require_exact_real_path(current, label)
        _release_require_inside_repository(repository, resolved, label)
        if is_leaf:
            _source_require(
                current_stat.st_nlink == 1,
                f"release generated source input must have exactly one hard link: {relative}",
            )
            return current, current_stat
    raise SystemExit(f"empty release generated source path topology: {relative}")


def validate_generated_source_topology(repository, relative_paths):
    repository = _release_validate_repository_root(Path(repository))
    paths = tuple(relative_paths)
    _source_require(
        paths == GENERATED_SOURCE_PATHS,
        "release generated source path inventory differs from the frozen exact paths",
    )
    _source_require(
        len(paths) == len(set(paths)),
        "release generated source path inventory has duplicates",
    )
    for relative in paths:
        _release_validate_generated_regular_path_topology(repository, relative)
    return {"ordinary_files": len(paths), "paths": list(paths)}


def _release_worktree_bytes(path, mode, relative):
    try:
        if mode == "120000":
            raise SystemExit(
                "release tracked Git symlink is not allowed by the exact source "
                f"inventory: {relative}"
            )
        _source_require(
            mode in {"100644", "100755"},
            f"unsupported release tracked blob mode {mode}: {relative}",
        )
        file_stat = os.lstat(path)
        _source_require(
            stat.S_ISREG(file_stat.st_mode),
            f"release tracked regular file type differs: {relative}",
        )
        _source_require(
            file_stat.st_nlink == 1,
            f"release tracked regular file must have exactly one hard link: {relative}",
        )
        if os.name != "nt":
            executable = bool(file_stat.st_mode & stat.S_IXUSR)
            _source_require(
                executable == (mode == "100755"),
                f"release tracked executable mode differs: {relative}",
            )
        return path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read release tracked worktree path {relative}: {exc}") from exc


def _release_untracked(repository):
    visible = {
        _release_decode_path(item, "release visible untracked inventory")
        for item in _release_nul_records(
            run_bytes(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=repository,
            ),
            "release visible untracked inventory",
        )
    }
    ignored = {
        _release_decode_path(item, "release ignored untracked inventory")
        for item in _release_nul_records(
            run_bytes(
                [
                    "git",
                    "ls-files",
                    "--others",
                    "--ignored",
                    "--exclude-standard",
                    "-z",
                ],
                cwd=repository,
            ),
            "release ignored untracked inventory",
        )
    }
    _source_require(
        visible.isdisjoint(ignored),
        "release visible and ignored untracked inventories overlap",
    )
    return visible, ignored


def verify_repository_source_state(repository, allowed_untracked_paths: Iterable[str]):
    repository = _release_validate_repository_root(Path(repository))
    head = _release_head_entries(
        run_bytes(["git", "ls-tree", "-r", "-z", "--full-tree", "HEAD"], cwd=repository)
    )
    index = _release_index_entries(
        run_bytes(["git", "ls-files", "--stage", "-z"], cwd=repository)
    )
    _source_require(set(index) == set(head), "release index path inventory differs from HEAD")
    for path, (head_mode, _kind, head_object) in head.items():
        index_mode, index_object, stage = index[path]
        _source_require(stage == 0, f"release non-stage-0 index entry: {path}")
        _source_require(
            (index_mode, index_object) == (head_mode, head_object),
            f"release index entry differs from HEAD: {path}",
        )

    assume_view = _release_tagged_entries(
        run_bytes(["git", "ls-files", "-v", "-z"], cwd=repository),
        "release assume-unchanged index view",
    )
    fsmonitor_view = _release_tagged_entries(
        run_bytes(["git", "ls-files", "-f", "-z"], cwd=repository),
        "release fsmonitor-valid index view",
    )
    debug_view = _release_debug_entries(
        run_bytes(["git", "ls-files", "--debug", "-z"], cwd=repository)
    )
    for label, view in (
        ("assume-unchanged", assume_view),
        ("fsmonitor-valid", fsmonitor_view),
        ("debug", debug_view),
    ):
        _source_require(
            set(view) == set(head),
            f"release {label} index inventory differs from HEAD",
        )
    for path in head:
        _source_require(
            assume_view[path] == "H",
            f"release nonordinary/assume-unchanged index flag: {path}",
        )
        _source_require(
            fsmonitor_view[path] == "H",
            f"release nonordinary/fsmonitor-valid index flag: {path}",
        )
        _source_require(debug_view[path] == 0, f"release nonzero extended index flags: {path}")

    object_format = run(
        ["git", "rev-parse", "--show-object-format"], cwd=repository, capture=True
    )
    verified_blobs = 0
    gitlinks = 0
    for relative, (mode, kind, expected_object) in head.items():
        worktree_path, _worktree_stat = _release_validate_tracked_path_topology(
            repository, relative, mode
        )
        if mode == "160000":
            _source_require(kind == "commit", f"release gitlink object type differs: {relative}")
            actual_gitlink_head = run_bytes(
                ["git", "rev-parse", "HEAD"], cwd=worktree_path
            ).decode("ascii", errors="strict").strip()
            _source_require(
                actual_gitlink_head == expected_object,
                f"release gitlink HEAD differs from the recorded commit: {relative}",
            )
            gitlinks += 1
            continue
        _source_require(kind == "blob", f"release tracked object type differs: {relative}")
        actual_object = _release_blob_id(
            _release_worktree_bytes(worktree_path, mode, relative), object_format
        )
        _source_require(
            actual_object == expected_object,
            f"release tracked worktree bytes differ from HEAD: {relative}",
        )
        verified_blobs += 1

    _source_require(
        run_bytes(["git", "diff-files", "--raw", "-z"], cwd=repository) == b"",
        "release Git worktree mode/content view differs from the index",
    )
    visible, ignored = _release_untracked(repository)
    actual_untracked = visible | ignored
    expected_untracked = set(allowed_untracked_paths)
    _source_require(
        actual_untracked == expected_untracked,
        f"release untracked path inventory differs: actual={sorted(actual_untracked)} "
        f"expected={sorted(expected_untracked)}",
    )
    return {
        "tracked_paths": len(head),
        "verified_blobs": verified_blobs,
        "gitlinks": gitlinks,
        "ordinary_index_flags": len(debug_view),
        "visible_untracked": sorted(visible),
        "ignored_untracked": sorted(ignored),
        "object_format": object_format,
    }


def write_text_lf(path, text, encoding="utf-8"):
    """Write text with deterministic LF endings on every supported Python."""
    with Path(path).open("w", encoding=encoding, newline="\n") as stream:
        stream.write(text)


def patch_hashes(data=None):
    data = data or manifest()
    return {
        item: sha256(HERE / item)
        for item in data["openocd"]["patches"]
    }


def verify_environment(platform_name):
    environment = manifest()["build_environment"][platform_name]
    expected = environment["packages"]
    reference_packages = set(environment.get("reference_packages", ()))
    # Windows (pacman) and Linux (dpkg) build on declared CI runner families, so
    # a version mismatch in a compiler or linked dependency is fatal. Source-fetch helpers
    # such as Git are references because GitHub's hosted images may carry a newer
    # package than the distribution repository; they do not enter the binary.
    # macOS builds against Homebrew, which has no pinnable distribution snapshot,
    # so its build-tool versions are also references. Missing packages always
    # fail, and bundled macOS runtime libraries remain hard locks.
    lenient = platform_name == "macos"
    strict_macos_runtime = {"hidapi", "libusb"}
    mismatches = []
    warnings = []
    for package, version in expected.items():
        try:
            if platform_name == "windows":
                actual = run(["pacman", "-Q", package], capture=True).rsplit(" ", 1)[-1]
            elif platform_name == "macos":
                actual = run(["brew", "list", "--versions", package], capture=True).split()[-1]
            else:
                actual = run(
                    ["dpkg-query", "-W", "-f=${Version}", package],
                    capture=True,
                )
        except (OSError, subprocess.CalledProcessError, IndexError):
            actual = "not installed"
        if actual != version:
            reference_only = (
                package in reference_packages
                or (lenient and package not in strict_macos_runtime)
            )
            if reference_only and actual != "not installed":
                warnings.append(f"{package}: {actual} (reference {version})")
            else:
                mismatches.append(f"{package}: {actual} (expected {version})")
    for line in warnings:
        print(f"warning: build tool version differs from reference: {line}")
    if mismatches:
        raise SystemExit("build environment does not match manifest:\n  " +
                         "\n  ".join(mismatches))
    locked = len(expected) - len(reference_packages)
    if lenient:
        print(f"{platform_name} build environment has all {len(expected)} required packages")
    else:
        print(f"{platform_name} build environment matches {locked} locked packages; "
              f"{len(reference_packages)} fetch-tool versions are references")


def source_submodules(source):
    status = run(["git", "submodule", "status", "--recursive"], cwd=source, capture=True)
    actual = {}
    for line in status.splitlines():
        fields = line.lstrip(" +-U").split()
        if len(fields) >= 2:
            actual[fields[1]] = fields[0]
    return actual


def source_provenance(source, data=None, identity=None):
    data = data or manifest()
    _require_exact_keys(data["oracle"], PROVENANCE_ORACLE_KEYS, "release manifest oracle")
    if data["oracle"]["redistribute"] is not False:
        raise SystemExit("release manifest oracle redistribute must be false")
    identity = identity or {
        "head": run(["git", "rev-parse", "HEAD"], cwd=source, capture=True),
        "submodules": source_submodules(source),
    }
    return {
        "schema": 1,
        "release": data["release"],
        "official_repository": data["openocd"]["repository"],
        "official_base_commit": data["openocd"]["base_commit"],
        "agamemnon_patched_commit": identity["head"],
        "gerrit": {
            "change": data["openocd"]["gerrit_change"],
            "patchset": data["openocd"]["gerrit_patchset"],
            "commit": data["openocd"]["gerrit_commit"],
            "ref": data["openocd"]["gerrit_ref"],
        },
        "patch_sha256": patch_hashes(data),
        "submodules": identity["submodules"],
        "source_date_epoch": data["source_date_epoch"],
        "oracle": data["oracle"],
    }


def validate_source_provenance_document(path, expected):
    path = Path(path)
    provenance = load_json_strict(path)
    _require_exact_keys(provenance, PROVENANCE_TOP_LEVEL_KEYS, "prepared-source provenance")
    _require_exact_keys(provenance["gerrit"], PROVENANCE_GERRIT_KEYS, "provenance Gerrit")
    _require_exact_keys(
        provenance["patch_sha256"], expected["patch_sha256"], "provenance patch hashes"
    )
    _require_exact_keys(provenance["submodules"], expected["submodules"], "provenance submodules")
    _require_exact_keys(provenance["oracle"], PROVENANCE_ORACLE_KEYS, "provenance oracle")
    if provenance["oracle"]["redistribute"] is not False:
        raise SystemExit("prepared-source provenance oracle redistribute must be false")
    if provenance != expected:
        raise SystemExit("prepared-source provenance values differ from derived inputs")
    expected_bytes = canonical_provenance_text(expected).encode("utf-8")
    try:
        actual_bytes = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read prepared-source provenance bytes: {exc}") from exc
    if actual_bytes != expected_bytes:
        raise SystemExit("prepared-source provenance is not exact canonical JSON bytes")
    return provenance


def validate_source_provenance(source, data, identity):
    expected = source_provenance(source, data=data, identity=identity)
    for relative, expected_hash in expected["patch_sha256"].items():
        copied_patch = Path(source) / "AGAMEMNON-PATCHES" / Path(relative).name
        if not copied_patch.is_file():
            raise SystemExit(f"prepared source patch copy is missing: {copied_patch.name}")
        actual_hash = sha256(copied_patch)
        if actual_hash != expected_hash:
            raise SystemExit(
                f"prepared source patch copy differs: {copied_patch.name} "
                f"is {actual_hash}; expected {expected_hash}"
            )
    return validate_source_provenance_document(Path(source) / PROVENANCE_NAME, expected)


def prepare(source):
    source = Path(source).resolve()
    data = manifest()
    if source.exists() and any(source.iterdir()):
        raise SystemExit(f"refusing to prepare into non-empty directory: {source}")
    source.parent.mkdir(parents=True, exist_ok=True)
    git_env = dict(os.environ)
    git_env.update({
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.autocrlf",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.filemode",
        "GIT_CONFIG_VALUE_1": "false",
    })
    run(["git", "clone", "-c", "core.autocrlf=false", "-c", "core.filemode=false", "--no-checkout",
         data["openocd"]["repository"], source], env=git_env)
    run(["git", "fetch", "--no-tags", "origin", data["openocd"]["gerrit_ref"]],
        cwd=source, env=git_env)
    fetched = run(["git", "rev-parse", "FETCH_HEAD"], cwd=source, capture=True)
    if fetched != data["openocd"]["gerrit_commit"]:
        raise SystemExit(f"Gerrit ref resolved to {fetched}; expected {data['openocd']['gerrit_commit']}")
    parent = run(["git", "rev-parse", "FETCH_HEAD^"], cwd=source, capture=True)
    if parent != data["openocd"]["base_commit"]:
        raise SystemExit(f"Gerrit parent is {parent}; expected {data['openocd']['base_commit']}")
    run(["git", "checkout", "--detach", data["openocd"]["base_commit"]],
        cwd=source, env=git_env)
    run(["git", "submodule", "sync", "--recursive"], cwd=source, env=git_env)
    run(["git", "submodule", "update", "--init", "--recursive"], cwd=source, env=git_env)
    run(["git", "submodule", "foreach", "--recursive",
         "git config core.autocrlf false && git config core.filemode false"], cwd=source)
    for relative in data["openocd"]["patches"]:
        run(["git", "apply", "--index", "--whitespace=error-all", HERE / relative], cwd=source)
    commit_env = dict(os.environ)
    timestamp = f"@{data['source_date_epoch']} +0000"
    commit_env.update({
        "GIT_AUTHOR_NAME": "AGaMEMnon release builder",
        "GIT_AUTHOR_EMAIL": "release@agamemnon.invalid",
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_NAME": "AGaMEMnon release builder",
        "GIT_COMMITTER_EMAIL": "release@agamemnon.invalid",
        "GIT_COMMITTER_DATE": timestamp,
    })
    run(["git", "commit", "--no-gpg-sign", "-m",
         "target/riscv: apply Gerrit 9590 and AGaMEMnon config fix"],
        cwd=source, env=commit_env)
    identity = _verify_source_before_provenance(source, data=data)
    patch_dir = source / "AGAMEMNON-PATCHES"
    patch_dir.mkdir(exist_ok=True)
    for relative in data["openocd"]["patches"]:
        shutil.copy2(HERE / relative, patch_dir / Path(relative).name)
    provenance = source_provenance(source, data=data, identity=identity)
    write_text_lf(source / PROVENANCE_NAME, canonical_provenance_text(provenance))
    verify_source(source)
    print(f"prepared verified source: {source}")


def _verify_source_identity(source, data):
    head = run(["git", "rev-parse", "HEAD"], cwd=source, capture=True)
    parent = run(["git", "rev-parse", "HEAD^"], cwd=source, capture=True)
    if parent != data["openocd"]["base_commit"]:
        raise SystemExit(f"patched source parent is {parent}; expected {data['openocd']['base_commit']}")
    expected_head = data["openocd"].get("patched_commit")
    if expected_head and head != expected_head:
        raise SystemExit(f"patched source HEAD is {head}; expected {expected_head}")
    actual = source_submodules(source)
    if set(actual) != set(data["submodules"]):
        raise SystemExit(
            "submodule path inventory differs: "
            f"actual={sorted(actual)}, expected={sorted(data['submodules'])}"
        )
    for path, expected in data["submodules"].items():
        if actual.get(path) != expected:
            raise SystemExit(f"submodule {path} is {actual.get(path)}; expected {expected}")
    run(["git", "diff", "--check", "HEAD"], cwd=source)
    diff = run(["git", "diff", "HEAD^", "HEAD", "--", "src/target/riscv"],
               cwd=source, capture=True)
    required = (
        "adiv5_jim_configure_ext",
        "alternative_dmi",
        "struct adiv5_private_config *pc = &config->adi_pc",
    )
    missing = [marker for marker in required if marker not in diff and marker not in
               (source / "src/target/riscv/riscv.c").read_text(encoding="utf-8")]
    if missing:
        raise SystemExit(f"patched source is missing markers: {', '.join(missing)}")
    return {"head": head, "parent": parent, "submodules": actual}


def _verify_all_repository_source_state(source, data, root_untracked):
    source_state = {".": verify_repository_source_state(source, root_untracked)}
    for relative in data["submodules"]:
        source_state[relative] = verify_repository_source_state(source / relative, ())
    return source_state


def _verify_source_before_provenance(source, data=None):
    """Prepare-only identity check used before generated artifacts exist."""
    source = _release_validate_repository_root(Path(source))
    data = data or manifest()
    identity = _verify_source_identity(source, data)
    identity["source_state"] = _verify_all_repository_source_state(source, data, ())
    print(f"source identity verified before provenance: patched {identity['head']}, "
          f"official parent {identity['parent']}, "
          f"{len(data['openocd']['patches'])} patches")
    return identity


def verify_source(source):
    source = _release_validate_repository_root(Path(source))
    data = manifest()
    identity = _verify_source_identity(source, data)
    generated_paths = (
        PROVENANCE_NAME,
        *(
            f"AGAMEMNON-PATCHES/{Path(relative).name}"
            for relative in data["openocd"]["patches"]
        ),
    )
    _source_require(
        generated_paths == GENERATED_SOURCE_PATHS,
        "release generated source path inventory differs from the frozen exact paths",
    )
    identity["source_state"] = _verify_all_repository_source_state(
        source, data, generated_paths
    )
    identity["generated_source_topology"] = validate_generated_source_topology(
        source, generated_paths
    )
    validate_source_provenance(source, data, identity)
    print(f"source verified: patched {identity['head']}, official parent {identity['parent']}, "
          f"{len(data['openocd']['patches'])} patches")
    return identity


def tracked_files(source):
    output = run(
        ["git", "-c", "core.quotepath=false", "ls-files", "--cached",
         "--recurse-submodules"],
        cwd=source,
        capture=True,
    )
    files = [Path(line) for line in output.splitlines() if line]
    extras = [
        Path("AGAMEMNON-PROVENANCE.json"),
        *[Path("AGAMEMNON-PATCHES") / Path(item).name
          for item in manifest()["openocd"]["patches"]],
    ]
    return sorted(set(files + extras), key=lambda item: item.as_posix())


def _release_validate_staging_root(destination):
    destination = Path(os.path.abspath(os.fspath(destination)))
    try:
        root_stat = os.lstat(destination)
    except OSError as exc:
        raise SystemExit(f"cannot inspect source archive staging root: {exc}") from exc
    _source_require(
        stat.S_ISDIR(root_stat.st_mode),
        "source archive staging root is not a real directory",
    )
    _source_require(
        not stat.S_ISLNK(root_stat.st_mode),
        "source archive staging root is a symlink",
    )
    _source_require(
        not _release_is_reparse_point(root_stat),
        "source archive staging root is a reparse point",
    )
    _source_require(
        not os.path.ismount(destination),
        "source archive staging root is a mount point",
    )
    return _release_require_exact_real_path(destination, "source archive staging root")


def copy_source_tree(source, destination):
    source = _release_validate_repository_root(Path(source))
    destination = _release_validate_staging_root(destination)
    destination_root_stat = os.lstat(destination)
    destination_root_identity = _release_stat_identity(destination_root_stat)
    with os.scandir(destination) as entries:
        _source_require(
            next(entries, None) is None,
            "source archive staging root must be empty before the transaction",
        )
    relative_paths = tuple(tracked_files(source))
    normalized_paths = tuple(relative.as_posix() for relative in relative_paths)
    _source_require(
        len(normalized_paths) == len(set(normalized_paths)),
        "source archive input inventory has duplicates",
    )
    _source_require(
        set(GENERATED_SOURCE_PATHS).issubset(normalized_paths),
        "source archive input inventory omits a frozen generated source path",
    )
    validate_generated_source_topology(source, GENERATED_SOURCE_PATHS)
    created_outputs = []
    created_identities = {}
    directory_custodies = {}

    def require_staging_root_custody():
        current_stat = os.lstat(destination)
        _source_require(
            stat.S_ISDIR(current_stat.st_mode)
            and not stat.S_ISLNK(current_stat.st_mode)
            and not _release_is_reparse_point(current_stat)
            and _release_stat_identity(current_stat) == destination_root_identity,
            "source archive staging root identity changed during the transaction",
        )
        _source_require(
            not os.path.ismount(destination),
            "source archive staging root became a mount point during the transaction",
        )
        _release_require_exact_real_path(destination, "source archive staging root")

    def create_staging_parents(relative):
        require_staging_root_custody()
        native = _release_tracked_native_path(relative.as_posix())
        current = destination
        parent_custody = directory_custodies[_release_path_key(destination)]
        for part in native.parts[:-1]:
            current = current / part
            try:
                current_stat = os.lstat(current)
            except FileNotFoundError:
                _release_mkdir_in_directory(parent_custody, current, part)
                current_stat = os.lstat(current)
                identity = _release_stat_identity(current_stat)
                created_outputs.append((current, identity, "directory"))
                created_identities[_release_path_key(current)] = identity
            _source_require(
                stat.S_ISDIR(current_stat.st_mode)
                and not stat.S_ISLNK(current_stat.st_mode)
                and not _release_is_reparse_point(current_stat),
                f"source archive staging parent is not a real directory: {relative}",
            )
            expected_identity = created_identities.get(_release_path_key(current))
            if expected_identity is not None:
                _source_require(
                    _release_stat_identity(current_stat) == expected_identity,
                    f"source archive staging parent identity changed: {relative}",
                )
            _release_require_inside_repository(
                destination,
                _release_require_exact_real_path(
                    current, f"source archive staging parent for {relative}"
                ),
                f"source archive staging parent for {relative}",
            )
            custody_key = _release_path_key(current)
            if custody_key not in directory_custodies:
                directory_custodies[custody_key] = _release_open_directory_custody(
                    current,
                    f"source archive staging parent for {relative}",
                    _release_stat_identity(current_stat),
                    parent_custody,
                    part,
                )
            parent_custody = directory_custodies[custody_key]
        require_staging_root_custody()
        return destination / native, parent_custody

    def close_staging_parent_custodies(include_root):
        root_key = _release_path_key(destination)
        for key, custody in reversed(tuple(directory_custodies.items())):
            if not include_root and key == root_key:
                continue
            _release_close_directory_custody(custody)
            del directory_custodies[key]

    def rollback_staging_transaction():
        # Windows removal is applied to exact held handles while delete sharing
        # is denied.  A pathname identity comparison alone never licenses a
        # destructive operation.  POSIX open handles do not pin directory
        # entries, so preserve partial output there until an equivalent
        # exact-object primitive is implemented.
        cleanup_failures = []
        for path, identity, kind in reversed(created_outputs):
            if os.name != "nt":
                cleanup_failures.append(f"exact cleanup unavailable for {path}")
                continue
            custody = None
            custody_key = _release_path_key(path)
            try:
                if kind == "directory":
                    custody = directory_custodies.get(custody_key)
                    _source_require(
                        custody is not None
                        and not custody.get("closed")
                        and custody.get("identity") == tuple(identity),
                        f"exact cleanup lacks original directory custody: {path}",
                    )
                    current_stat = os.lstat(path)
                    _source_require(
                        stat.S_ISDIR(current_stat.st_mode)
                        and not stat.S_ISLNK(current_stat.st_mode)
                        and not _release_is_reparse_point(current_stat)
                        and _release_stat_identity(current_stat) == tuple(identity),
                        f"transaction-created directory identity differs before exact cleanup: {path}",
                    )
                else:
                    custody = _release_open_windows_delete_custody(
                        path,
                        f"transaction-created staged file {path}",
                        identity,
                        kind,
                    )
                _release_mark_windows_handle_for_deletion(custody, path, kind)
                _release_close_directory_custody(custody)
                if kind == "directory":
                    del directory_custodies[custody_key]
                _release_require_exact_cleanup_result(path, identity, kind)
            except (FileNotFoundError, OSError, SystemExit) as cleanup_exc:
                # Preserve anything whose exact disposition cannot be proved.
                # The original staging failure remains primary.
                cleanup_failures.append(str(cleanup_exc))
                if custody is not None and kind == "file":
                    _release_close_directory_custody(custody)
                continue
        return tuple(cleanup_failures)

    def validate_archive_input(relative):
        normalized = relative.as_posix()
        native = _release_tracked_native_path(normalized)
        current = source
        for index, part in enumerate(native.parts):
            current = current / part
            label = f"source archive input topology for {normalized}"
            try:
                current_stat = os.lstat(current)
            except OSError as exc:
                raise SystemExit(f"cannot inspect {label}: {exc}") from exc
            is_leaf = index == len(native.parts) - 1
            if is_leaf and stat.S_ISLNK(current_stat.st_mode):
                raise SystemExit(
                    "source archive tracked Git symlink is not allowed by the exact "
                    f"source inventory: {normalized}"
                )
            if is_leaf:
                _source_require(
                    stat.S_ISREG(current_stat.st_mode),
                    f"source archive input is not an ordinary file: {normalized}",
                )
            else:
                _source_require(
                    stat.S_ISDIR(current_stat.st_mode),
                    f"{label} is not a real directory",
                )
            _source_require(
                not stat.S_ISLNK(current_stat.st_mode),
                f"{label} traverses a symlink",
            )
            _source_require(
                not _release_is_reparse_point(current_stat),
                f"{label} traverses a junction or reparse point",
            )
            _source_require(
                not os.path.ismount(current), f"{label} traverses a mount point"
            )
            resolved = _release_require_exact_real_path(current, label)
            _release_require_inside_repository(source, resolved, label)
            if is_leaf:
                _source_require(
                    current_stat.st_nlink == 1,
                    f"source archive input must have exactly one hard link: {normalized}",
                )
                return current, current_stat
        raise SystemExit(f"empty source archive input topology: {normalized}")

    def require_opened_input(relative, before_stat, opened_stat):
        normalized = relative.as_posix()
        _source_require(
            stat.S_ISREG(opened_stat.st_mode),
            f"opened source archive input is not an ordinary file: {normalized}",
        )
        _source_require(
            not stat.S_ISLNK(opened_stat.st_mode),
            f"opened source archive input is a link: {normalized}",
        )
        _source_require(
            not _release_is_reparse_point(opened_stat),
            f"opened source archive input is a reparse point: {normalized}",
        )
        _source_require(
            opened_stat.st_nlink == 1,
            f"opened source archive input must have exactly one hard link: {normalized}",
        )
        _source_require(
            (opened_stat.st_dev, opened_stat.st_ino)
            == (before_stat.st_dev, before_stat.st_ino),
            f"source archive input identity changed while opening: {normalized}",
        )

    def open_archive_input(relative, frozen=None):
        normalized = relative.as_posix()
        src, before_stat = validate_archive_input(relative)
        if frozen is not None:
            _source_require(
                (before_stat.st_dev, before_stat.st_ino) == frozen["identity"],
                f"source archive input identity changed after preflight: {normalized}",
            )
        descriptor = _release_open_readonly_nofollow(
            src, f"source archive input {normalized}"
        )
        try:
            opened_stat = os.fstat(descriptor)
            require_opened_input(relative, before_stat, opened_stat)
            _after_path, after_open_stat = validate_archive_input(relative)
            _source_require(
                (after_open_stat.st_dev, after_open_stat.st_ino)
                == (opened_stat.st_dev, opened_stat.st_ino),
                f"source archive input identity changed while opening: {normalized}",
            )
            return src, descriptor, opened_stat
        except BaseException:
            os.close(descriptor)
            raise

    def validate_staged_output(relative, expected_hash, expected_size):
        normalized = relative.as_posix()
        native = _release_tracked_native_path(normalized)
        current = destination
        leaf_stat = None
        ancestors = []
        require_staging_root_custody()
        for index, part in enumerate(native.parts):
            current = current / part
            label = f"staged source archive output topology for {normalized}"
            try:
                current_stat = os.lstat(current)
            except OSError as exc:
                raise SystemExit(f"cannot inspect {label}: {exc}") from exc
            is_leaf = index == len(native.parts) - 1
            _source_require(
                stat.S_ISREG(current_stat.st_mode)
                if is_leaf
                else stat.S_ISDIR(current_stat.st_mode),
                f"{label} is not an ordinary file" if is_leaf else f"{label} is not a real directory",
            )
            _source_require(
                not stat.S_ISLNK(current_stat.st_mode),
                f"{label} traverses a symlink",
            )
            _source_require(
                not _release_is_reparse_point(current_stat),
                f"{label} traverses a junction or reparse point",
            )
            _source_require(
                not os.path.ismount(current), f"{label} traverses a mount point"
            )
            resolved = _release_require_exact_real_path(current, label)
            _release_require_inside_repository(destination, resolved, label)
            if is_leaf:
                _source_require(
                    current_stat.st_nlink == 1,
                    f"staged source archive output must have exactly one hard link: {normalized}",
                )
                leaf_stat = current_stat
            else:
                ancestors.append(
                    {
                        "path": Path(*native.parts[: index + 1]).as_posix(),
                        "identity": _release_stat_identity(current_stat),
                        "change_state": _release_stat_change_state(current_stat),
                    }
                )
        _source_require(leaf_stat is not None, f"empty staged source archive output: {normalized}")
        _source_require(
            leaf_stat.st_size == expected_size,
            f"staged source archive output size differs before hashing: {normalized}",
        )

        parent_custody = directory_custodies[_release_path_key(current.parent)]
        descriptor = _release_open_readonly_in_directory(
            parent_custody,
            current,
            current.name,
            f"staged source archive output {normalized}",
        )
        try:
            opened_stat = os.fstat(descriptor)
            require_opened_input(relative, leaf_stat, opened_stat)
            _source_require(
                opened_stat.st_size == expected_size,
                f"staged source archive output size differs while opening: {normalized}",
            )
            owned_descriptor = descriptor
            descriptor = -1
            with os.fdopen(owned_descriptor, "rb", closefd=True) as stream:
                actual_hash, actual_size = _release_hash_stream(stream)
                after_hash_stat = os.fstat(stream.fileno())
                _after_path, after_path_stat = (current, os.lstat(current))
                _source_require(
                    stat.S_ISREG(after_path_stat.st_mode)
                    and not stat.S_ISLNK(after_path_stat.st_mode)
                    and not _release_is_reparse_point(after_path_stat)
                    and after_path_stat.st_nlink == 1,
                    "staged source archive output topology changed while hashing: "
                    f"{normalized}",
                )
                identity = (opened_stat.st_dev, opened_stat.st_ino)
                _source_require(
                    _release_stat_identity(after_hash_stat) == identity
                    and _release_stat_identity(after_path_stat) == identity,
                    "staged source archive output identity changed while hashing: "
                    f"{normalized}",
                )
                _source_require(
                    after_hash_stat.st_size == expected_size
                    and after_path_stat.st_size == expected_size,
                    "staged source archive output size changed while hashing: "
                    f"{normalized}",
                )
        finally:
            if descriptor != -1:
                os.close(descriptor)
        _source_require(
            actual_hash == expected_hash and actual_size == expected_size,
            f"staged source archive output bytes differ: {normalized}",
        )
        final_path_stat = os.lstat(current)
        _source_require(
            _release_stat_identity(final_path_stat)
            == _release_stat_identity(after_hash_stat)
            and final_path_stat.st_size == expected_size
            and final_path_stat.st_nlink == 1,
            f"staged source archive output changed after hashing: {normalized}",
        )
        return {
            "identity": _release_stat_identity(final_path_stat),
            "sha256": expected_hash,
            "size": expected_size,
            "mode": stat.S_IMODE(final_path_stat.st_mode),
            "change_state": _release_stat_change_state(final_path_stat),
            "ancestors": tuple(ancestors),
        }

    # Refuse every bad member before creating a partial staging tree.  Each
    # member is frozen through a no-follow handle before staging.  Each copy is
    # then bound to that identity and content, and the independently reopened
    # destination must be an exact ordinary single-link file.
    frozen_inputs = {}
    for relative in relative_paths:
        normalized = relative.as_posix()
        _src, descriptor, opened_stat = open_archive_input(relative)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            frozen_hash, frozen_size = _release_hash_stream(stream)
            after_hash_stat = os.fstat(stream.fileno())
            _after_path, after_path_stat = validate_archive_input(relative)
            identity = (opened_stat.st_dev, opened_stat.st_ino)
            _source_require(
                (after_hash_stat.st_dev, after_hash_stat.st_ino) == identity
                and (after_path_stat.st_dev, after_path_stat.st_ino) == identity,
                f"source archive input identity changed during preflight: {normalized}",
            )
            _source_require(
                after_hash_stat.st_size == frozen_size,
                f"source archive input size changed during preflight: {normalized}",
            )
        frozen_inputs[normalized] = {
            "identity": identity,
            "sha256": frozen_hash,
            "size": frozen_size,
        }

    root_custody = _release_open_directory_custody(
        destination,
        "source archive staging root",
        destination_root_identity,
    )
    directory_custodies[_release_path_key(destination)] = root_custody
    frozen_outputs = {}
    try:
        for relative in relative_paths:
            normalized = relative.as_posix()
            frozen = frozen_inputs[normalized]
            descriptor = -1
            destination_descriptor = -1
            try:
                _src, descriptor, opened_stat = open_archive_input(relative, frozen)
                dst, parent_custody = create_staging_parents(relative)
                owned_source_descriptor = descriptor
                descriptor = -1
                with os.fdopen(
                    owned_source_descriptor, "rb", closefd=True
                ) as source_stream:
                    verified_hash, verified_size = _release_hash_stream(source_stream)
                    after_verification_stat = os.fstat(source_stream.fileno())
                    _after_path, after_verification_path_stat = validate_archive_input(
                        relative
                    )
                    identity = _release_stat_identity(opened_stat)
                    _source_require(
                        _release_stat_identity(after_verification_stat) == identity
                        and _release_stat_identity(after_verification_path_stat)
                        == identity,
                        f"source archive input identity changed while verifying: {normalized}",
                    )
                    _source_require(
                        verified_hash == frozen["sha256"]
                        and verified_size == frozen["size"]
                        and after_verification_stat.st_size == frozen["size"]
                        and after_verification_path_stat.st_size == frozen["size"],
                        f"source archive input bytes changed before staging: {normalized}",
                    )
                    source_stream.seek(0)

                    destination_flags = (
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_BINARY", 0)
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_NOFOLLOW", 0)
                    )
                    destination_descriptor = _release_create_file_in_directory(
                        parent_custody,
                        dst,
                        dst.name,
                        destination_flags,
                        stat.S_IMODE(opened_stat.st_mode),
                    )
                    created_stat = os.fstat(destination_descriptor)
                    _source_require(
                        stat.S_ISREG(created_stat.st_mode)
                        and not _release_is_reparse_point(created_stat)
                        and created_stat.st_nlink == 1,
                        f"created staged source archive output is not an ordinary single-link file: {normalized}",
                    )
                    created_identity = _release_stat_identity(created_stat)
                    created_outputs.append((dst, created_identity, "file"))
                    created_identities[_release_path_key(dst)] = created_identity
                    owned_destination_descriptor = destination_descriptor
                    destination_descriptor = -1
                    with os.fdopen(
                        owned_destination_descriptor, "wb", closefd=True
                    ) as destination_stream:
                        copied_hash, copied_size = _release_copy_verified_stream(
                            source_stream, destination_stream, normalized
                        )
                        destination_stream.flush()
                        if hasattr(os, "fchmod"):
                            os.fchmod(
                                destination_stream.fileno(),
                                stat.S_IMODE(opened_stat.st_mode),
                            )
                        after_copy_stat = os.fstat(source_stream.fileno())
                    _after_path, after_path_stat = validate_archive_input(relative)
                    _source_require(
                        _release_stat_identity(after_copy_stat) == identity
                        and _release_stat_identity(after_path_stat) == identity,
                        f"source archive input identity changed during staging: {normalized}",
                    )
                    _source_require(
                        after_copy_stat.st_size == frozen["size"]
                        and after_path_stat.st_size == frozen["size"],
                        f"source archive input size changed during staging: {normalized}",
                    )
                    _source_require(
                        copied_hash == frozen["sha256"]
                        and copied_size == frozen["size"],
                        f"source archive input bytes changed during staging: {normalized}",
                    )
                frozen_outputs[normalized] = validate_staged_output(
                    relative, frozen["sha256"], frozen["size"]
                )
            finally:
                if descriptor != -1:
                    os.close(descriptor)
                if destination_descriptor != -1:
                    os.close(destination_descriptor)
        # Revalidate every member after the complete tree exists.  This both
        # closes the interval after an early member's first validation and
        # freezes parent state after all natural-order child creation while
        # directory custody is still held.
        for relative in relative_paths:
            normalized = relative.as_posix()
            frozen = frozen_inputs[normalized]
            frozen_outputs[normalized] = validate_staged_output(
                relative, frozen["sha256"], frozen["size"]
            )
        require_staging_root_custody()
        expected_directories = {
            parent.as_posix()
            for normalized in normalized_paths
            for parent in PurePosixPath(normalized).parents
            if parent.as_posix() != "."
        }
        observed_files = set()
        observed_directories = set()
        for path in destination.rglob("*"):
            relative = path.relative_to(destination).as_posix()
            path_stat = os.lstat(path)
            if stat.S_ISREG(path_stat.st_mode):
                observed_files.add(relative)
            elif stat.S_ISDIR(path_stat.st_mode):
                observed_directories.add(relative)
            else:
                raise SystemExit(
                    f"source archive staging transaction contains an unsupported object: {relative}"
                )
        _source_require(
            observed_files == set(normalized_paths),
            "source archive staging file inventory differs after the transaction: "
            f"missing={sorted(set(normalized_paths) - observed_files)}, "
            f"extra={sorted(observed_files - set(normalized_paths))}",
        )
        _source_require(
            observed_directories == expected_directories,
            "source archive staging directory inventory differs after the transaction: "
            f"missing={sorted(expected_directories - observed_directories)}, "
            f"extra={sorted(observed_directories - expected_directories)}",
        )
        require_staging_root_custody()
    except BaseException as exc:
        cleanup_failures = rollback_staging_transaction()
        if cleanup_failures and hasattr(exc, "add_note"):
            exc.add_note(
                "source archive staging cleanup preserved output: "
                + "; ".join(cleanup_failures)
            )
        if isinstance(exc, OSError):
            raise SystemExit(f"cannot stage source archive transaction: {exc}") from exc
        raise
    finally:
        close_staging_parent_custodies(include_root=True)

    require_staging_root_custody()
    return {
        "schema": 1,
        "root_identity": destination_root_identity,
        "members": frozen_outputs,
    }


def normalized_zip(root, archive, epoch):
    stamp = dt.datetime.fromtimestamp(max(epoch, 315532800), tz=dt.timezone.utc)
    date_time = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute,
                 stamp.second - stamp.second % 2)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            relative = path.relative_to(root.parent).as_posix()
            info = zipfile.ZipInfo(relative, date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            out.writestr(info, path.read_bytes(), compresslevel=9)


def _release_validate_bound_archive_member(root, relative, root_identity, binding):
    root = Path(root)
    root_stat = os.lstat(root)
    _source_require(
        stat.S_ISDIR(root_stat.st_mode)
        and not stat.S_ISLNK(root_stat.st_mode)
        and not _release_is_reparse_point(root_stat)
        and _release_stat_identity(root_stat) == tuple(root_identity),
        "bound source archive root identity changed during archive consumption",
    )
    _release_require_exact_real_path(root, "bound source archive root")
    expected_ancestors = {item["path"]: item for item in binding["ancestors"]}
    native = _release_tracked_native_path(relative)
    current = root
    leaf_stat = None
    for index, part in enumerate(native.parts):
        current = current / part
        label = f"bound source archive member topology for {relative}"
        try:
            current_stat = os.lstat(current)
        except OSError as exc:
            raise SystemExit(f"cannot inspect {label}: {exc}") from exc
        is_leaf = index == len(native.parts) - 1
        _source_require(
            stat.S_ISREG(current_stat.st_mode)
            if is_leaf
            else stat.S_ISDIR(current_stat.st_mode),
            f"{label} is not an ordinary file"
            if is_leaf
            else f"{label} is not a real directory",
        )
        _source_require(
            not stat.S_ISLNK(current_stat.st_mode)
            and not _release_is_reparse_point(current_stat),
            f"{label} traverses a link or reparse point",
        )
        _source_require(
            not os.path.ismount(current), f"{label} traverses a mount point"
        )
        resolved = _release_require_exact_real_path(current, label)
        _release_require_inside_repository(root, resolved, label)
        if is_leaf:
            _source_require(
                current_stat.st_nlink == 1,
                f"bound source archive member must have exactly one hard link: {relative}",
            )
            _source_require(
                _release_stat_identity(current_stat) == tuple(binding["identity"]),
                f"bound source archive member identity changed: {relative}",
            )
            _source_require(
                current_stat.st_size == binding["size"],
                f"bound source archive member size changed: {relative}",
            )
            _source_require(
                stat.S_IMODE(current_stat.st_mode) == binding["mode"],
                f"bound source archive member mode changed: {relative}",
            )
            leaf_stat = current_stat
        else:
            ancestor = Path(*native.parts[: index + 1]).as_posix()
            _source_require(
                ancestor in expected_ancestors
                and _release_stat_identity(current_stat)
                == tuple(expected_ancestors[ancestor]["identity"])
                and _release_stat_change_state(current_stat)
                == tuple(expected_ancestors[ancestor]["change_state"]),
                f"bound source archive member parent identity changed: {relative}",
            )
    _source_require(leaf_stat is not None, f"empty bound source archive member: {relative}")
    return current, leaf_stat


def _release_consume_bound_tar_stream(out, info, stream, relative):
    del relative
    reader = _ReleaseHashingReader(stream)
    out.addfile(info, reader)
    return reader.result()


def _release_acquire_bound_archive_custodies(
    root, relative, root_identity, binding
):
    root = Path(root)
    custodies = []
    try:
        root_custody = _release_open_directory_custody(
            root, "bound source archive root", root_identity
        )
        custodies.append(root_custody)
        expected_ancestors = {item["path"]: item for item in binding["ancestors"]}
        native = _release_tracked_native_path(relative)
        current = root
        parent_custody = root_custody
        for index, part in enumerate(native.parts[:-1]):
            current = current / part
            ancestor = Path(*native.parts[: index + 1]).as_posix()
            _source_require(
                ancestor in expected_ancestors,
                f"bound source archive member lacks parent binding: {relative}",
            )
            parent_custody = _release_open_directory_custody(
                current,
                f"bound source archive parent for {relative}",
                expected_ancestors[ancestor]["identity"],
                parent_custody,
                part,
            )
            custodies.append(parent_custody)
        return custodies, parent_custody
    except BaseException:
        for custody in reversed(custodies):
            _release_close_directory_custody(custody)
        raise


def _release_add_bound_tar_member(out, root, relative, epoch, root_identity, binding):
    custodies = []
    descriptor = -1
    try:
        custodies, parent_custody = _release_acquire_bound_archive_custodies(
            root, relative, root_identity, binding
        )
        path, before_path_stat = _release_validate_bound_archive_member(
            root, relative, root_identity, binding
        )
        _source_require(
            _release_stat_change_state(before_path_stat)
            == tuple(binding["change_state"]),
            f"bound source archive member changed after staging: {relative}",
        )
        descriptor = _release_open_readonly_in_directory(
            parent_custody,
            path,
            path.name,
            f"bound source archive member {relative}",
        )
        opened_stat = os.fstat(descriptor)
        identity = tuple(binding["identity"])
        _source_require(
            stat.S_ISREG(opened_stat.st_mode)
            and not _release_is_reparse_point(opened_stat)
            and opened_stat.st_nlink == 1
            and _release_stat_identity(opened_stat) == identity,
            f"bound source archive member identity changed while opening: {relative}",
        )
        _source_require(
            opened_stat.st_size == binding["size"]
            and stat.S_IMODE(opened_stat.st_mode) == binding["mode"],
            f"bound source archive member changed while opening: {relative}",
        )
        opened_change_state = _release_stat_change_state(opened_stat)
        _after_open_path, after_open_path_stat = _release_validate_bound_archive_member(
            root, relative, root_identity, binding
        )
        _source_require(
            _release_stat_identity(after_open_path_stat) == identity
            and _release_stat_change_state(after_open_path_stat)
            == tuple(binding["change_state"]),
            f"bound source archive member changed while opening: {relative}",
        )

        archive_name = (Path(root.name) / Path(*PurePosixPath(relative).parts)).as_posix()
        info = tarfile.TarInfo(archive_name)
        info.type = tarfile.REGTYPE
        info.size = binding["size"]
        info.mode = 0o755 if binding["mode"] & stat.S_IXUSR else 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = epoch
        owned_descriptor = descriptor
        descriptor = -1
        with os.fdopen(owned_descriptor, "rb", closefd=True) as stream:
            actual_hash, actual_size = _release_consume_bound_tar_stream(
                out, info, stream, relative
            )
            after_stream_stat = os.fstat(stream.fileno())
            _source_require(
                actual_hash == binding["sha256"]
                and actual_size == binding["size"],
                f"bound source archive bytes consumed by tar differ: {relative}",
            )
            _source_require(
                _release_stat_identity(after_stream_stat) == identity
                and _release_stat_change_state(after_stream_stat)
                == opened_change_state,
                f"bound source archive member changed during tar consumption: {relative}",
            )
        _after_path, after_path_stat = _release_validate_bound_archive_member(
            root, relative, root_identity, binding
        )
        _source_require(
            _release_stat_identity(after_path_stat) == identity
            and _release_stat_change_state(after_path_stat)
            == tuple(binding["change_state"]),
            f"bound source archive member changed during tar consumption: {relative}",
        )
    finally:
        if descriptor != -1:
            os.close(descriptor)
        for custody in reversed(custodies):
            _release_close_directory_custody(custody)


def normalized_tar_gz(root, archive, epoch, source_binding=None):
    root = Path(root)
    bound_members = {}
    root_identity = None
    additional_members = set()
    expected_directories = set()
    if source_binding is not None:
        _source_require(
            source_binding.get("schema") == 1,
            "source archive binding schema differs",
        )
        root_identity = tuple(source_binding["root_identity"])
        bound_members = dict(source_binding["members"])
        additional_paths = tuple(source_binding.get("additional_members", ()))
        additional_members = set(additional_paths)
        _source_require(
            len(additional_paths) == len(additional_members)
            and additional_members.isdisjoint(bound_members),
            "source archive additional member inventory has duplicates or overlaps",
        )
        for relative in additional_paths:
            _release_tracked_native_path(relative)
        _source_require(
            set(GENERATED_SOURCE_PATHS).issubset(bound_members),
            "source archive binding omits a frozen generated source path",
        )
        expected_directories = {
            parent.as_posix()
            for relative in (*bound_members, *additional_paths)
            for parent in PurePosixPath(relative).parents
            if parent.as_posix() != "."
        }
    consumed_bound_members = set()
    consumed_additional_members = set()
    with Path(archive).open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as out:
                for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                    path_stat = os.lstat(path)
                    normalized = path.relative_to(root).as_posix()
                    if source_binding is not None and stat.S_ISDIR(path_stat.st_mode):
                        _source_require(
                            normalized in expected_directories
                            and not stat.S_ISLNK(path_stat.st_mode)
                            and not _release_is_reparse_point(path_stat),
                            f"source archive contains an unexpected directory: {normalized}",
                        )
                        continue
                    if normalized in bound_members:
                        _release_add_bound_tar_member(
                            out,
                            root,
                            normalized,
                            epoch,
                            root_identity,
                            bound_members[normalized],
                        )
                        consumed_bound_members.add(normalized)
                        continue
                    if source_binding is not None:
                        _source_require(
                            normalized in additional_members
                            and stat.S_ISREG(path_stat.st_mode)
                            and not stat.S_ISLNK(path_stat.st_mode)
                            and not _release_is_reparse_point(path_stat)
                            and path_stat.st_nlink == 1,
                            f"source archive contains an unexpected or unsafe member: {normalized}",
                        )
                        consumed_additional_members.add(normalized)
                    if not (stat.S_ISREG(path_stat.st_mode) or stat.S_ISLNK(path_stat.st_mode)):
                        continue
                    relative = Path(root.name) / path.relative_to(root)
                    info = out.gettarinfo(str(path), arcname=relative.as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = epoch
                    if info.issym():
                        info.linkname = os.fsdecode(_release_symlink_bytes(path))
                    if info.isreg():
                        info.mode = 0o755 if path_stat.st_mode & stat.S_IXUSR else 0o644
                        with path.open("rb") as stream:
                            out.addfile(info, stream)
                    else:
                        out.addfile(info)
    _source_require(
        consumed_bound_members == set(bound_members),
        "source archive did not consume every frozen bound member: "
        f"missing={sorted(set(bound_members) - consumed_bound_members)}",
    )
    _source_require(
        consumed_additional_members == additional_members,
        "source archive did not consume every expected package member: "
        f"missing={sorted(additional_members - consumed_additional_members)}",
    )


def make_sbom(root, platform_name):
    data = manifest()
    files = []
    relationships = []
    analyzed_packages = set()
    package_file_sha1 = {}
    for index, path in enumerate(sorted(root.rglob("*"), key=lambda item: item.as_posix())):
        if not path.is_file() or path.name == "openocd.spdx.json":
            continue
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()
        if (
            "libusb" in path.name.lower()
            or lowered.startswith("share/licenses/libusb/")
            or lowered.startswith("share/sources/libusb-")
        ):
            package_id = "SPDXRef-Package-libusb"
        elif (
            "hidapi" in path.name.lower()
            or lowered.startswith("share/licenses/hidapi/")
            or lowered.startswith("share/sources/hidapi-")
        ):
            package_id = "SPDXRef-Package-hidapi"
        else:
            package_id = "SPDXRef-Package-OpenOCD"
        analyzed_packages.add(package_id)
        package_file_sha1.setdefault(package_id, []).append(sha1(path))
        spdx_id = f"SPDXRef-File-{index}"
        files.append({
            "SPDXID": spdx_id,
            "fileName": "./" + relative,
            "checksums": [{"algorithm": "SHA256", "checksumValue": sha256(path)}],
            "licenseConcluded": "NOASSERTION",
            "licenseInfoInFiles": ["NOASSERTION"],
            "copyrightText": "NOASSERTION",
        })
        relationships.append({
            "spdxElementId": package_id,
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": spdx_id,
        })
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{data['release']}-{platform_name}",
        "documentNamespace": f"https://github.com/bbenchoff/AGaMEMnon/sbom/{uuid.uuid5(uuid.NAMESPACE_URL, data['release'] + platform_name)}",
        "creationInfo": {
            "created": dt.datetime.fromtimestamp(
                data["source_date_epoch"], tz=dt.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "creators": ["Tool: AGaMEMnon tools/openocd/release.py"],
        },
        "packages": [{
            "name": "OpenOCD",
            "SPDXID": "SPDXRef-Package-OpenOCD",
            "versionInfo": data["openocd"]["gerrit_commit"][:12],
            "downloadLocation": data["openocd"]["repository"],
            "filesAnalyzed": True,
            "licenseConcluded": "GPL-2.0-only",
            "licenseDeclared": "GPL-2.0-only",
            "copyrightText": "NOASSERTION",
            "externalRefs": [{
                "referenceCategory": "VCS",
                "referenceType": "vcs",
                "referenceLocator": data["openocd"]["repository"] + "@" +
                                    data["openocd"]["base_commit"],
            }],
        }, {
            "name": "Jim Tcl",
            "SPDXID": "SPDXRef-Package-JimTcl",
            "versionInfo": data["submodules"]["jimtcl"][:12],
            "downloadLocation": "https://github.com/msteveb/jimtcl",
            "filesAnalyzed": False,
            "licenseConcluded": "BSD-2-Clause",
            "licenseDeclared": "BSD-2-Clause",
            "copyrightText": "NOASSERTION",
        }, {
            "name": "libjaylink",
            "SPDXID": "SPDXRef-Package-libjaylink",
            "versionInfo": data["submodules"]["src/jtag/drivers/libjaylink"][:12],
            "downloadLocation": "https://gitlab.zapb.de/libjaylink/libjaylink",
            "filesAnalyzed": False,
            "licenseConcluded": "GPL-2.0-or-later",
            "licenseDeclared": "GPL-2.0-or-later",
            "copyrightText": "NOASSERTION",
        }, {
            "name": "libusb",
            "SPDXID": "SPDXRef-Package-libusb",
            "downloadLocation": "https://github.com/libusb/libusb",
            "filesAnalyzed": "SPDXRef-Package-libusb" in analyzed_packages,
            "licenseConcluded": "LGPL-2.1-or-later",
            "licenseDeclared": "LGPL-2.1-or-later",
            "copyrightText": "NOASSERTION",
        }, {
            "name": "hidapi",
            "SPDXID": "SPDXRef-Package-hidapi",
            "downloadLocation": "https://github.com/libusb/hidapi",
            "filesAnalyzed": "SPDXRef-Package-hidapi" in analyzed_packages,
            "licenseConcluded": "BSD-3-Clause",
            "licenseDeclared": "BSD-3-Clause",
            "copyrightText": "NOASSERTION",
        }],
        "files": files,
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package-OpenOCD",
            },
            {
                "spdxElementId": "SPDXRef-Package-OpenOCD",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": "SPDXRef-Package-libusb",
            },
            {
                "spdxElementId": "SPDXRef-Package-OpenOCD",
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": "SPDXRef-Package-hidapi",
            },
            *relationships,
        ],
    }
    for package in document["packages"]:
        package_id = package["SPDXID"]
        if package.get("filesAnalyzed"):
            concatenated = "".join(sorted(package_file_sha1[package_id])).encode("ascii")
            package["packageVerificationCode"] = {
                "packageVerificationCodeValue": hashlib.sha1(concatenated).hexdigest()
            }
    write_text_lf(
        root / "openocd.spdx.json",
        json.dumps(document, indent=2) + "\n",
    )


def write_file_manifest(root):
    entries = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    write_text_lf(root / "SHA256SUMS", "\n".join(entries) + "\n")


def package(platform_name, source, prefix, output):
    source = Path(os.path.abspath(os.fspath(source)))
    prefix = Path(prefix).resolve()
    output = Path(output).resolve()
    verify_source(source)
    executable = prefix / "bin" / ("openocd.exe" if platform_name.startswith("windows") else "openocd")
    if not executable.is_file():
        raise SystemExit(f"built OpenOCD not found: {executable}")
    output.mkdir(parents=True, exist_ok=True)
    data = manifest()
    epoch = data["source_date_epoch"]
    with _release_private_package_workspace() as temporary:
        binary_root = temporary / f"agamemnon-openocd-{platform_name}"
        shutil.copytree(prefix, binary_root)
        shutil.copy2(source / "COPYING", binary_root / "COPYING")
        shutil.copy2(MANIFEST_PATH, binary_root / "AGAMEMNON-BUILD-MANIFEST.json")
        shutil.copy2(HERE / "README.md", binary_root / "BUILD.md")
        shutil.copytree(HERE / "patches", binary_root / "patches")
        tool_dir = binary_root / "build-tools"
        tool_dir.mkdir()
        shutil.copy2(HERE / "release.py", tool_dir / "release.py")
        shutil.copy2(HERE / "build.sh", tool_dir / "build.sh")
        shutil.copy2(MANIFEST_PATH, tool_dir / "manifest.json")
        shutil.copytree(HERE / "patches", tool_dir / "patches")
        provenance = source_provenance(source)
        provenance["platform"] = platform_name
        provenance["openocd_sha256"] = sha256(executable)
        write_text_lf(
            binary_root / PROVENANCE_NAME,
            json.dumps(provenance, indent=2) + "\n",
        )
        make_sbom(binary_root, platform_name)
        write_file_manifest(binary_root)
        if platform_name.startswith("windows"):
            archive = output / f"agamemnon-openocd-{platform_name}.zip"
            normalized_zip(binary_root, archive, epoch)
        else:
            archive = output / f"agamemnon-openocd-{platform_name}.tar.gz"
            normalized_tar_gz(binary_root, archive, epoch)

        source_root = temporary / "agamemnon-openocd-source"
        source_root.mkdir()
        source_binding = copy_source_tree(source, source_root)
        shutil.copy2(MANIFEST_PATH, source_root / "AGAMEMNON-BUILD-MANIFEST.json")
        shutil.copy2(HERE / "README.md", source_root / "AGAMEMNON-BUILD.md")
        tool_dir = source_root / "AGAMEMNON-BUILD-TOOLS"
        tool_dir.mkdir()
        shutil.copy2(HERE / "release.py", tool_dir / "release.py")
        shutil.copy2(HERE / "build.sh", tool_dir / "build.sh")
        shutil.copy2(MANIFEST_PATH, tool_dir / "manifest.json")
        shutil.copytree(HERE / "patches", tool_dir / "patches")
        source_binding["additional_members"] = SOURCE_ARCHIVE_PACKAGE_PATHS
        source_archive = output / "agamemnon-openocd-source.tar.gz"
        normalized_tar_gz(source_root, source_archive, epoch, source_binding)

    for item in (archive, source_archive):
        write_text_lf(
            Path(str(item) + ".sha256"),
            f"{sha256(item)}  {item.name}\n",
            encoding="ascii",
        )
        print(f"{item.name}: {sha256(item)}")


def parse_args():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", required=True)
    verify = sub.add_parser("verify-source")
    verify.add_argument("--source", required=True)
    environment = sub.add_parser("verify-environment")
    environment.add_argument("--platform", required=True, choices=("windows", "linux", "macos"))
    pack = sub.add_parser("package")
    pack.add_argument("--platform", required=True,
                      choices=("windows-x64", "linux-x64", "macos-arm64", "macos-x64"))
    pack.add_argument("--source", required=True)
    pack.add_argument("--prefix", required=True)
    pack.add_argument("--output", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "prepare":
        prepare(args.source)
    elif args.command == "verify-source":
        verify_source(args.source)
    elif args.command == "verify-environment":
        verify_environment(args.platform)
    else:
        package(args.platform, args.source, args.prefix, args.output)


if __name__ == "__main__":
    main()
