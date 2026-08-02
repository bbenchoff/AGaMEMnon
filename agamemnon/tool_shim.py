"""Narrow host compatibility shims for pinned native tools."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root):
    digest = hashlib.sha256()
    root = Path(root)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _ascii(value):
    try:
        str(value).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def stage_windows_executable(command, platform_name=None):
    """Return *command* with a non-ASCII Windows executable staged safely.

    The pinned MSYS2 nextpnr build can hang before ``main`` when its executable
    resides below a non-ASCII path. Its DLL search path does not have that
    limitation. Copy only the immutable executable into a content-addressed
    ASCII cache, leaving every runtime and data path at its bundled location.
    """
    command = list(command)
    platform_name = platform_name or os.name
    if platform_name != "nt" or not command:
        return command
    executable = Path(command[0])
    if _ascii(executable) or not executable.is_file():
        return command

    roots = [
        os.environ.get("AGAMEMNON_ASCII_TOOL_CACHE"),
        tempfile.gettempdir(),
        os.environ.get("PUBLIC"),
    ]
    digest = _sha256(executable)
    failures = []
    for root_value in roots:
        if not root_value or not _ascii(root_value):
            continue
        root = Path(root_value) / "agamemnon-ascii-tools" / digest[:16]
        target = root / executable.name
        try:
            root.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or _sha256(target) != digest:
                temporary = root / (executable.name + ".new")
                shutil.copy2(executable, temporary)
                os.replace(temporary, target)
            return [str(target), *command[1:]]
        except OSError as exc:
            failures.append(f"{root}: {exc}")
    detail = "; ".join(failures) or "no writable ASCII cache root was found"
    raise RuntimeError(
        "cannot stage the Windows nextpnr executable from a non-ASCII path: "
        + detail
        + "; set AGAMEMNON_ASCII_TOOL_CACHE to a writable ASCII-only directory"
    )


def stage_windows_directory(directory, platform_name=None):
    """Stage a non-ASCII native-tool data directory into the same safe cache."""
    source = Path(directory)
    platform_name = platform_name or os.name
    if platform_name != "nt" or _ascii(source) or not source.is_dir():
        return source
    digest = _tree_sha256(source)
    roots = [
        os.environ.get("AGAMEMNON_ASCII_TOOL_CACHE"),
        tempfile.gettempdir(),
        os.environ.get("PUBLIC"),
    ]
    failures = []
    for root_value in roots:
        if not root_value or not _ascii(root_value):
            continue
        target = (
            Path(root_value) / "agamemnon-ascii-tools" / digest[:16] / source.name
        )
        marker = target / ".source_sha256"
        try:
            if not marker.is_file() or marker.read_text(encoding="ascii").strip() != digest:
                target.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target, dirs_exist_ok=True)
                marker.write_text(digest + "\n", encoding="ascii")
            return target
        except OSError as exc:
            failures.append(f"{target}: {exc}")
    detail = "; ".join(failures) or "no writable ASCII cache root was found"
    raise RuntimeError(
        "cannot stage native-tool data from a non-ASCII path: "
        + detail
        + "; set AGAMEMNON_ASCII_TOOL_CACHE to a writable ASCII-only directory"
    )
