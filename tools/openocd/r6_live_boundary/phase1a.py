#!/usr/bin/env python3
"""Read-only R6 Phase1A input, loader, and deny-gate audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
from typing import Mapping


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]
MANIFEST_PATH = HERE / "phase1a_manifest.json"
RELEASE_MANIFEST_PATH = REPOSITORY / "tools/openocd/manifest.json"
OBSERVATION_PATH = HERE / "tool_observation.json"

ACCEPTED_PHASE0_V11 = "2fee9bce38980f42bfb08ab479f89199cdf0ede3"
EXPECTED_MANIFEST_SEMANTIC_SHA256 = (
    "34f1165b0fb46781c581610caffcbb618ed77a79af6e11629fd5eafd828ab555"
)
EXPECTED_CHANGED_PATHS = {
    ".gitattributes",
    "tools/openocd/manifest.json",
    "tools/openocd/r6_live_boundary/PHASE1A.md",
    "tools/openocd/r6_live_boundary/README.md",
    "tools/openocd/r6_live_boundary/phase0_manifest.json",
    "tools/openocd/r6_live_boundary/phase1a.py",
    "tools/openocd/r6_live_boundary/phase1a_manifest.json",
    "tools/openocd/r6_live_boundary/phase1a_patches/0001-openocd-deny-live-and-disable-jim-load.patch",
    "tools/openocd/r6_live_boundary/phase1a_patches/0002-jimtcl-no-runtime-loader.patch",
    "tools/openocd/r6_live_boundary/phase1a_patches/0003-libusb-winusb-only.patch",
    "tools/openocd/r6_live_boundary/test_phase0.py",
    "tools/openocd/r6_live_boundary/test_phase1a.py",
    "tools/openocd/r6_live_boundary/tool_observation.json",
    "tools/openocd/r6_live_boundary/tool_observation.schema.json",
}


class Phase1AFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Phase1AFailure(message)


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json_strict(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise Phase1AFailure(f"cannot read strict JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"strict JSON root is not an object: {path}")
    return value


def exact_keys(value: Mapping, expected: set[str], label: str) -> None:
    require(isinstance(value, Mapping), f"{label} is not an object")
    actual = set(value)
    require(
        actual == expected,
        f"{label} keys differ: missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}",
    )


def semantic_sha256(value: Mapping) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise Phase1AFailure(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def verify_file(path: Path, size: int, digest: str, label: str) -> None:
    require(path.is_file(), f"{label} is missing: {path}")
    require(path.stat().st_size == size, f"{label} size differs")
    require(sha256(path) == digest, f"{label} SHA-256 differs")


def validate_archive_projection(archive: Path, source: Path, top_level: str) -> None:
    expected: dict[str, tuple[str, int, str | None]] = {}
    try:
        with tarfile.open(archive, "r:bz2") as bundle:
            for member in bundle.getmembers():
                member_path = PurePosixPath(member.name)
                require(not member_path.is_absolute(), "libusb archive has an absolute path")
                require(".." not in member_path.parts, "libusb archive path escapes its root")
                require(member_path.parts and member_path.parts[0] == top_level,
                        "libusb archive has a foreign top-level path")
                relative = PurePosixPath(*member_path.parts[1:]).as_posix()
                if relative == ".":
                    require(member.isdir(), "libusb top-level member is not a directory")
                    continue
                require(relative not in expected, "libusb archive has a duplicate path")
                if member.isdir():
                    expected[relative] = ("directory", 0, None)
                elif member.isfile():
                    stream = bundle.extractfile(member)
                    require(stream is not None, f"cannot read libusb archive member {relative}")
                    digest = hashlib.sha256()
                    size = 0
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
                    require(size == member.size, f"libusb archive size differs for {relative}")
                    expected[relative] = ("file", size, digest.hexdigest())
                else:
                    raise Phase1AFailure(f"libusb archive has unsupported member type: {relative}")
    except (OSError, tarfile.TarError) as exc:
        raise Phase1AFailure(f"cannot inspect libusb archive: {exc}") from exc

    actual: set[str] = set()
    for root, directories, files in os.walk(source, topdown=True, followlinks=False):
        root_path = Path(root)
        for name in [*directories, *files]:
            path = root_path / name
            relative = path.relative_to(source).as_posix()
            file_stat = os.lstat(path)
            attributes = getattr(file_stat, "st_file_attributes", 0)
            require(not (attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)),
                    f"libusb source contains a reparse point: {relative}")
            require(not stat.S_ISLNK(file_stat.st_mode),
                    f"libusb source contains a symlink: {relative}")
            actual.add(relative)
    require(actual == set(expected),
            f"libusb extracted inventory differs: missing={sorted(set(expected) - actual)}, "
            f"extra={sorted(actual - set(expected))}")
    for relative, (kind, size, digest) in expected.items():
        path = source / Path(relative)
        file_stat = os.lstat(path)
        if kind == "directory":
            require(stat.S_ISDIR(file_stat.st_mode),
                    f"libusb extracted directory differs: {relative}")
        else:
            require(stat.S_ISREG(file_stat.st_mode),
                    f"libusb extracted file type differs: {relative}")
            verify_file(path, size, digest or "", f"libusb extracted file {relative}")


def git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "")
        raise Phase1AFailure(f"git {' '.join(args)} failed in {repo}: {stderr}") from exc
    return result.stdout.strip()


def validate_manifest(manifest: dict) -> None:
    exact_keys(
        manifest,
        {
            "schema", "kind", "status", "parent_agamemnon_commit",
            "compile_authorized", "openocd_execution_authorized",
            "hardware_contact_authorized", "toolchain_decision", "openocd_source",
            "jimtcl", "libusb", "earliest_main_gate", "required_future_gates",
        },
        "Phase1A manifest",
    )
    require(manifest["schema"] == 1, "Phase1A schema differs")
    require(
        manifest["kind"] == "AGAMEMNON_R6_OPENOCD_LIVE_BOUNDARY_PHASE1A",
        "Phase1A kind differs",
    )
    require(
        manifest["status"] == "DESK_INPUT_AND_DENY_GATE_CANDIDATE_COMPILE_REFUSED",
        "Phase1A status differs",
    )
    for key in (
        "compile_authorized", "openocd_execution_authorized", "hardware_contact_authorized"
    ):
        require(manifest[key] is False, f"{key} must remain false")
    require(
        manifest["parent_agamemnon_commit"] == ACCEPTED_PHASE0_V11,
        "Phase1A accepted parent differs",
    )

    decision = manifest["toolchain_decision"]
    exact_keys(
        decision,
        {
            "policy", "distribution", "compiler", "pkgconf",
            "rolling_ci_package_resolution_allowed", "unknown_tool_or_package_disposition",
        },
        "toolchain decision",
    )
    require(
        decision["policy"] == "ACCEPT_EXACT_OBSERVED_OFFLINE_MSYS2_SNAPSHOT",
        "toolchain decision is not the frozen offline snapshot",
    )
    require(decision["rolling_ci_package_resolution_allowed"] is False,
            "rolling CI package resolution must remain refused")
    require(decision["unknown_tool_or_package_disposition"] == "REJECT",
            "unknown tool disposition is not reject")
    package_keys = {
        "package", "version", "executable_path", "executable_size", "executable_sha256",
        "package_archive", "package_archive_size", "package_archive_sha256",
        "package_signature_sha256",
    }
    exact_keys(decision["compiler"], package_keys, "compiler decision")
    exact_keys(decision["pkgconf"], package_keys, "pkgconf decision")

    openocd = manifest["openocd_source"]
    exact_keys(openocd, {
        "commit", "tree", "configure_sha256", "main_sha256", "patch", "patch_sha256"
    }, "OpenOCD source contract")
    jim = manifest["jimtcl"]
    exact_keys(jim, {
        "commit", "tree", "win32compat_sha256", "patch", "patch_sha256",
        "required_configure_token", "required_absent_final_objects", "conditional_final_object",
        "conditional_object_forbidden_imports", "final_membership_proof_complete",
    }, "JimTcl contract")
    require(jim["final_membership_proof_complete"] is False,
            "JimTcl final membership cannot be preclaimed")

    libusb = manifest["libusb"]
    exact_keys(libusb, {
        "version", "archive_name", "archive_url", "archive_size", "archive_sha256",
        "top_level_directory", "prepatch_files", "patch", "patch_sha256",
        "selected_backend", "required_system_library", "required_system_library_resolution",
        "forbidden_backend_objects", "forbidden_runtime_libraries",
        "system_or_preinstalled_libusb_link_allowed", "final_membership_proof_complete",
    }, "libusb contract")
    require(libusb["selected_backend"] == "MICROSOFT_WINUSB_SYSTEM32_ONLY",
            "libusb backend is not WinUSB-only")
    require(libusb["system_or_preinstalled_libusb_link_allowed"] is False,
            "preinstalled libusb linking must remain refused")
    require(libusb["final_membership_proof_complete"] is False,
            "libusb final membership cannot be preclaimed")

    gate = manifest["earliest_main_gate"]
    exact_keys(gate, {
        "symbol", "entry_file", "mode", "denied_exit_code", "required_order",
        "allowed_calls", "authorization_inputs", "desk_override_allowed",
        "final_disassembly_proof_complete",
    }, "earliest-main gate")
    require(gate["mode"] == "DENY_ONLY", "earliest-main gate is not deny-only")
    require(gate["denied_exit_code"] == 70, "deny-gate exit code differs")
    require(gate["allowed_calls"] == [], "deny gate gained an allowed call")
    require(gate["authorization_inputs"] == [], "deny gate gained an authorization input")
    require(gate["desk_override_allowed"] is False, "desk override became allowed")
    require(gate["final_disassembly_proof_complete"] is False,
            "final gate disassembly cannot be preclaimed")
    require(manifest["required_future_gates"], "future gate list is empty")
    require(
        semantic_sha256(manifest) == EXPECTED_MANIFEST_SEMANTIC_SHA256,
        "Phase1A manifest semantic identity differs",
    )


def verify_patch(repo: Path, record: Mapping, apply_root: Path, label: str) -> str:
    patch = repo / record["patch"]
    require(patch.is_file(), f"{label} patch is missing")
    require(sha256(patch) == record["patch_sha256"], f"{label} patch SHA-256 differs")
    try:
        result = subprocess.run(
            ["git", "-C", str(apply_root), "apply", "--check", "--whitespace=error-all", str(patch)],
            check=False,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise Phase1AFailure(f"cannot check {label} patch: {exc}") from exc
    require(result.returncode == 0, f"{label} patch does not apply exactly: {result.stderr.strip()}")
    return patch.read_text(encoding="utf-8")


def validate_toolchain(repo: Path, manifest: dict, package_cache: Path) -> None:
    release = load_json_strict(repo / "tools/openocd/manifest.json")
    observation = load_json_strict(repo / "tools/openocd/r6_live_boundary/tool_observation.json")
    decision = manifest["toolchain_decision"]
    expected = release["build_environment"]["windows"]["packages"]
    require(observation["blocking_mismatches"] == [], "tool observation still has drift")
    for key in ("compiler", "pkgconf"):
        record = decision[key]
        package = record["package"]
        require(expected[package] == record["version"], f"{key} release version differs")
        observed = observation["package_versions"][package]
        require(observed == {
            "expected": record["version"], "observed": record["version"], "status": "MATCH"
        }, f"{key} observation is not an exact match")
        executable = Path(record["executable_path"])
        verify_file(executable, record["executable_size"], record["executable_sha256"], key)
        observed_identity = observation["file_identities"][record["executable_path"]]
        require(observed_identity == {
            "size": record["executable_size"], "sha256": record["executable_sha256"]
        }, f"{key} observed identity differs")
        archive = package_cache / record["package_archive"]
        verify_file(archive, record["package_archive_size"], record["package_archive_sha256"],
                    f"{key} package archive")
        signature = package_cache / (record["package_archive"] + ".sig")
        require(signature.is_file(), f"{key} package signature is missing")
        require(sha256(signature) == record["package_signature_sha256"],
                f"{key} package signature SHA-256 differs")


def validate_openocd(repo: Path, manifest: dict, source: Path) -> None:
    record = manifest["openocd_source"]
    require(git(source, "rev-parse", "HEAD") == record["commit"], "OpenOCD commit differs")
    require(git(source, "rev-parse", "HEAD^{tree}") == record["tree"], "OpenOCD tree differs")
    verify_file(source / "configure.ac", (source / "configure.ac").stat().st_size,
                record["configure_sha256"], "OpenOCD configure.ac")
    verify_file(source / "src/main.c", (source / "src/main.c").stat().st_size,
                record["main_sha256"], "OpenOCD main.c")
    text = verify_patch(repo, record, source, "OpenOCD")
    gate = manifest["earliest_main_gate"]
    positions = [text.find(token) for token in gate["required_order"]]
    require(all(position >= 0 for position in positions), "deny-gate patch lacks an order token")
    require(positions == sorted(positions), "deny-gate patch token order differs")
    require("return R6_LIVE_BOUNDARY_DENIED;" in text, "deny gate is not unconditional")
    require("--without-ext=load" in text, "OpenOCD patch does not disable Jim load")

    jim = manifest["jimtcl"]
    jim_root = source / "jimtcl"
    require(git(jim_root, "rev-parse", "HEAD") == jim["commit"], "JimTcl commit differs")
    require(git(jim_root, "rev-parse", "HEAD^{tree}") == jim["tree"], "JimTcl tree differs")
    verify_file(jim_root / "jim-win32compat.c", (jim_root / "jim-win32compat.c").stat().st_size,
                jim["win32compat_sha256"], "JimTcl win32compat")
    jim_patch = verify_patch(repo, jim, jim_root, "JimTcl")
    require("defined(HAVE_DLOPEN_COMPAT) && defined(jim_ext_load)" in jim_patch,
            "JimTcl patch does not condition the loader shim on the load extension")


def validate_libusb(repo: Path, manifest: dict, archive: Path, source: Path) -> None:
    record = manifest["libusb"]
    verify_file(archive, record["archive_size"], record["archive_sha256"], "libusb archive")
    require(source.name == record["top_level_directory"], "libusb top-level directory differs")
    validate_archive_projection(archive, source, record["top_level_directory"])
    for relative, identity in record["prepatch_files"].items():
        exact_keys(identity, {"size", "sha256"}, f"libusb identity {relative}")
        verify_file(source / relative, identity["size"], identity["sha256"],
                    f"libusb prepatch file {relative}")
    text = verify_patch(repo, record, source, "libusb")
    required = (
        "-\t\t os/windows_usbdk.h os/windows_usbdk.c",
        "+static const char * const winusbx_driver_names[] = {NULL, NULL, \"WinUSB\"};",
        "+\t\tif (sub_api != SUB_API_WINUSB)",
        "-\thlibusbK = load_system_library(ctx, \"libusbK\");",
        "+\tif (hWinUSB == NULL)",
    )
    require(all(marker in text for marker in required), "libusb patch lacks a WinUSB-only marker")
    require("load_system_library(ctx, \"WinUSB\")" in text,
            "libusb patch lost the System32 WinUSB loader")


def validate_candidate_parent(repo: Path, parent: str) -> None:
    require(parent == ACCEPTED_PHASE0_V11, "Phase1A candidate parent contract differs")
    ancestry = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    require(len(ancestry) == 2, "Phase1A candidate must have exactly one parent")
    require(ancestry[1] == parent,
            "Phase1A candidate is not an exact child of accepted v11")
    changed = {
        path for path in git(repo, "diff", "--name-only", parent, "HEAD").splitlines()
        if path
    }
    require(
        changed == EXPECTED_CHANGED_PATHS,
        f"Phase1A candidate path inventory differs: "
        f"missing={sorted(EXPECTED_CHANGED_PATHS - changed)}, "
        f"extra={sorted(changed - EXPECTED_CHANGED_PATHS)}",
    )
    require(
        git(repo, "status", "--porcelain=v1", "--untracked-files=all") == "",
        "Phase1A candidate worktree is not clean",
    )


def audit(repo: Path, source: Path, libusb_archive: Path, libusb_source: Path,
          package_cache: Path) -> None:
    manifest = load_json_strict(repo / "tools/openocd/r6_live_boundary/phase1a_manifest.json")
    validate_manifest(manifest)
    validate_candidate_parent(repo, manifest["parent_agamemnon_commit"])
    validate_toolchain(repo, manifest, package_cache)
    validate_openocd(repo, manifest, source)
    validate_libusb(repo, manifest, libusb_archive, libusb_source)
    print("PASS_PHASE1A_DESK_CONTRACT_COMPILE_REFUSED")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--libusb-archive", required=True, type=Path)
    parser.add_argument("--libusb-source", required=True, type=Path)
    parser.add_argument(
        "--package-cache", type=Path,
        default=Path("C:/msys64/var/cache/pacman/pkg"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        audit(REPOSITORY, args.source.resolve(), args.libusb_archive.resolve(),
              args.libusb_source.resolve(), args.package_cache.resolve())
    except Phase1AFailure as exc:
        raise SystemExit(f"R6 Phase1A audit failed: {exc}") from exc


if __name__ == "__main__":
    main()
