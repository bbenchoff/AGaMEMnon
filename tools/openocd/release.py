#!/usr/bin/env python3
"""Prepare, verify, and package the pinned AGaMEMnon OpenOCD release."""

from __future__ import annotations

import argparse
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


def _source_require(condition, message):
    if not condition:
        raise SystemExit(message)


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


def copy_source_tree(source, destination):
    source = Path(source)
    destination = Path(destination)
    for relative in tracked_files(source):
        src = source / relative
        dst = destination / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            source_stat = os.lstat(src)
            if stat.S_ISLNK(source_stat.st_mode):
                raise SystemExit(
                    "source archive tracked Git symlink is not allowed by the exact "
                    f"source inventory: {relative}"
                )
            elif stat.S_ISREG(source_stat.st_mode):
                shutil.copy2(src, dst, follow_symlinks=False)
            else:
                raise SystemExit(f"source archive input type differs: {relative}")
        except OSError as exc:
            raise SystemExit(f"cannot stage source archive input {relative}: {exc}") from exc


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


def normalized_tar_gz(root, archive, epoch):
    with Path(archive).open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as out:
                for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                    path_stat = os.lstat(path)
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
    with tempfile.TemporaryDirectory(prefix="agamemnon-openocd-") as temporary:
        temporary = Path(temporary)
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
        copy_source_tree(source, source_root)
        write_text_lf(
            source_root / PROVENANCE_NAME,
            canonical_provenance_text(source_provenance(source)),
        )
        shutil.copy2(MANIFEST_PATH, source_root / "AGAMEMNON-BUILD-MANIFEST.json")
        shutil.copy2(HERE / "README.md", source_root / "AGAMEMNON-BUILD.md")
        tool_dir = source_root / "AGAMEMNON-BUILD-TOOLS"
        tool_dir.mkdir()
        shutil.copy2(HERE / "release.py", tool_dir / "release.py")
        shutil.copy2(HERE / "build.sh", tool_dir / "build.sh")
        shutil.copy2(MANIFEST_PATH, tool_dir / "manifest.json")
        shutil.copytree(HERE / "patches", tool_dir / "patches")
        source_archive = output / "agamemnon-openocd-source.tar.gz"
        normalized_tar_gz(source_root, source_archive, epoch)

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
